"""Private HTTPS voice/text adapter for a single Hermes profile.

Run from the checkout using a dedicated virtual environment. Hermes's full API stays bound to localhost.
Only this adapter's narrow device endpoints are reachable on the LAN.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hmac
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import ssl
import tempfile
import time
import wave
from urllib.parse import urlsplit, quote
import yaml

from aiohttp import ClientSession, ClientTimeout, web
try:
    from .message_queue import MessageQueue
except ImportError:
    from message_queue import MessageQueue
try:
    from device.ascii_text import display_ascii
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "device"))
    from ascii_text import display_ascii

ROOT = Path(__file__).resolve().parent
MAX_AUDIO = 30 * 16000 * 2 + 44
log = logging.getLogger("pocket-hermes")


@contextmanager
def runtime_lock(root):
    """One production process per runtime, before touching persisted requests."""
    import fcntl
    with (root / '.bridge.lock').open('a') as lock:
        os.chmod(root / '.bridge.lock', 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another bridge process is using this runtime') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def validate_wav(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("Expected mono 16 kHz 16-bit PCM WAV")
            if not 4000 <= wav.getnframes() <= 480000:
                raise ValueError("Record between 0.25 and 30 seconds")
            if len(wav.readframes(wav.getnframes())) != wav.getnframes() * 2:
                raise ValueError("Incomplete recording")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV recording") from exc


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Bridge configuration must be an object")
    for key in ('hermes_key', 'device_key'):
        value = config.get(key)
        if not isinstance(value, str) or not 32 <= len(value) <= 256 or not all(33 <= ord(c) <= 126 for c in value):
            raise ValueError(key + " must contain 32-256 printable non-space ASCII characters")
        if value.startswith('REPLACE_'):
            raise ValueError("Replace example credentials before starting")
    if config['device_key'] == config['hermes_key']:
        raise ValueError("Device and upstream credentials must be different")
    url = urlsplit(config.get('hermes_url', ''))
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', '::1') or
            url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
        raise ValueError("Hermes API must use an explicit loopback HTTP URL")
    if not url.port:
        raise ValueError("Hermes API URL requires a port")
    for key, default, minimum, maximum in (
        ('port', 8643, 1, 65535), ('retention_days', 7, 1, 365),
        ('max_turns', 10000, 1, 1000000), ('max_reply_chars', 4000, 100, 4000),
        ('queue_capacity', 32, 1, 100),
    ):
        value = config.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Invalid " + key)
    if type(config.get('message_queue', False)) is not bool:
        raise ValueError('message_queue must be boolean')
    return config


class Bridge:
    def __init__(self, root=ROOT):
        self.root = root
        self.config = validate_config(json.loads((root / "config.json").read_text()))
        os.chmod(root, 0o700)
        os.chmod(root / "config.json", 0o600)
        self.audio_tmp = root / 'audio-tmp'
        self.audio_tmp.mkdir(mode=0o700, exist_ok=True)
        self.audio_tmp.chmod(0o700)
        self.db = sqlite3.connect(root / "state.sqlite3")
        os.chmod(root / "state.sqlite3", 0o600)
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=EXTRA')
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, status TEXT, transcript TEXT, text TEXT, created REAL)")
        self.queue_enabled = self.config.get('message_queue', False)
        self.queue = MessageQueue(self.db)
        # Only durable jobs which have never started may run after a restart.
        interrupted = "status NOT IN ('done','error')"
        if self.queue_enabled:
            interrupted += " AND NOT (status='queued' AND id IN (SELECT turn_id FROM queue_jobs))"
        with self.db:
            self.db.execute('UPDATE messages SET unread=1 WHERE turn_id IN (SELECT id FROM turns WHERE ' + interrupted + ')')
            self.db.execute("UPDATE turns SET status='error', text='Connection restarted. Previous action may have run; check its status before retrying.' WHERE " + interrupted)
            self.db.execute("DELETE FROM queue_jobs WHERE turn_id IN (SELECT id FROM turns WHERE status IN ('done','error'))")
            if self.queue_enabled:
                self.queue.current()
        self.db.commit()
        self.expire_content()
        self.request_slots = 0
        self.task = None
        self.client = None
        self.model = None
        self.model_error = False
        self.delegation = {}

    async def startup(self, app):
        self.client = ClientSession(timeout=ClientTimeout(total=600), headers={
            "Authorization": "Bearer " + self.config["hermes_key"],
            "X-Hermes-Session-Key": self.config.get("session_key", "pocket"),
        })
        self.warmup_task = asyncio.create_task(self.warmup())
        if self.queue_enabled:
            self.start_queue()

    def start_queue(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_queue())

    async def run_queue(self):
        while True:
            self.expire_content()
            job = self.queue.next_job()
            if job is None:
                return
            await self.run_turn(*job)

    def load_model(self):
        from faster_whisper import WhisperModel
        return WhisperModel(self.config.get("whisper_model", "tiny.en"), device="cpu", compute_type="int8", cpu_threads=4)

    async def warmup(self):
        try:
            self.model = await asyncio.to_thread(self.load_model)
            log.info("Local transcription ready")
        except Exception:
            self.model_error = True
            log.error("Local transcription initialization failed (details suppressed)")

    async def cleanup(self, app):
        for task in (self.task, self.warmup_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await self.client.close()
        self.db.close()

    async def hermes(self, method, path, **kwargs):
        async with self.client.request(method, self.config["hermes_url"].rstrip("/") + path, allow_redirects=False, **kwargs) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("Hermes HTTP " + str(response.status))
            return await response.json()

    async def session(self, conversation=None):
        row = ((self.queue.session(conversation),) if conversation else
               self.db.execute("SELECT value FROM state WHERE key='session_id'").fetchone())
        if row and row[0]:
            return row[0]
        # Hermes titles are unique across saved sessions. New-chat keeps the old
        # session, so a constant title makes every later creation fail.
        title = "M5StickS3 Pocket " + os.urandom(8).hex()
        data = await self.hermes("POST", "/api/sessions", json={"title": title})
        sid = data.get("id") or data.get("session_id") or data.get("session", {}).get("id")
        if not isinstance(sid, str) or not sid:
            raise RuntimeError("Hermes did not return a session ID")
        if conversation:
            self.queue.save_session(conversation, sid)
        else:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('session_id',?)", (sid,))
        self.db.commit()
        return sid

    def expire_content(self):
        # Keep request tombstones: deleting IDs would allow old actions to replay.
        cutoff = time.time() - self.config.get('retention_days', 7) * 86400
        with self.db:
            # Do not execute stale work after a long outage, even if never started.
            self.db.execute("UPDATE turns SET status='error',text='Queued message expired before processing.' WHERE status='queued' AND created < ? AND id IN (SELECT turn_id FROM queue_jobs)", (cutoff,))
            self.db.execute("DELETE FROM queue_jobs WHERE turn_id IN (SELECT id FROM turns WHERE status IN ('done','error'))")
            self.queue.expire(cutoff)
            self.db.execute("UPDATE turns SET transcript='', text='Result expired.' WHERE created < ? AND status IN ('done','error') AND (transcript != '' OR text != 'Result expired.')", (cutoff,))

    def update(self, tid, status, transcript=None, text=None):
        if text is not None:
            limit = self.config.get('max_reply_chars', 4000)
            text = text[:limit] + (' [truncated]' if len(text) > limit else '')
        self.db.execute("UPDATE turns SET status=?, transcript=COALESCE(?,transcript), text=COALESCE(?,text) WHERE id=?", (status, transcript, text, tid))
        if status in ('done', 'error'):
            self.queue.complete(tid)
        self.db.commit()

    def result(self, tid):
        self.expire_content()
        row = self.db.execute("SELECT id,status,transcript,text,created FROM turns WHERE id=?", (tid,)).fetchone()
        if not row:
            return None
        result = dict(zip(("id", "status", "transcript", "text"), row[:4]))
        for field in ('status', 'transcript', 'text'):
            result[field] = display_ascii(result[field])[:16000]
        result['delegation'] = self.delegation.get(tid, 'idle')
        result['elapsed_s'] = max(0, int(time.time() - row[4]))
        if self.queue_enabled:
            result.update(self.queue.metadata(tid))
        return result

    async def chat(self, sid, text, tid):
        """Expose public assistant text/tool names; never forward reasoning or args."""
        path = self.config['hermes_url'].rstrip('/') + '/api/sessions/' + quote(sid, safe='') + '/chat/stream'
        reply = ''
        final = None
        event = ''
        data_lines = []
        updated = 0.0
        async with self.client.post(path, json=self.chat_body(text), allow_redirects=False) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError('Hermes HTTP ' + str(response.status))
            async for raw in response.content:
                line = raw.decode('utf-8').rstrip('\r\n')
                if line.startswith('event:'):
                    event = line[6:].strip()
                elif line.startswith('data:'):
                    data_lines.append(line[5:].lstrip())
                    if sum(map(len, data_lines)) > 65536:
                        raise RuntimeError('Upstream event too large')
                elif not line and data_lines:
                    data = json.loads('\n'.join(data_lines))
                    data_lines = []
                    if event == 'assistant.delta':
                        reply = (reply + data.get('delta', ''))[:self.config.get('max_reply_chars', 4000)]
                        if time.monotonic() - updated > .35:
                            self.update(tid, 'replying', text=reply)
                            updated = time.monotonic()
                    elif event == 'tool.started':
                        if data.get('tool_name') == 'delegate_task':
                            self.delegation[tid] = 'active'
                        name = re.sub(r'[^a-zA-Z0-9_]', '', data.get('tool_name') or 'tool')[:24]
                        self.update(tid, 'tool:' + name, text=reply)
                    elif event in ('tool.completed', 'tool.failed'):
                        if data.get('tool_name') == 'delegate_task':
                            self.delegation[tid] = 'failed' if event == 'tool.failed' else 'returned'
                        self.update(tid, 'working', text=reply)
                    elif event == 'assistant.completed':
                        final = {'session_id': data.get('session_id', sid), 'message': {'content': data.get('content', '')}}
                    elif event == 'error':
                        raise RuntimeError('Hermes streaming run failed')
        if final is None:
            raise RuntimeError('Hermes stream ended before final response')
        return final

    def chat_body(self, text):
        """Follow only this profile's selection; never write its configuration.

        Hermes otherwise reuses the conversation's historical model label even
        after a profile model change. The lock applies to this device session.
        """
        body = {'input': text}
        profile_config = Path(self.config['profile_config']) if self.config.get('profile_config') else self.root.parent / 'config.yaml'
        if profile_config.exists():
            config = yaml.safe_load(profile_config.read_text()) or {}
            model = config.get('model') or {}
            if isinstance(model, dict):
                name, provider = model.get('default'), model.get('provider')
                if isinstance(name, str) and name and isinstance(provider, str) and provider:
                    body.update(model=name, provider=provider, require_model_lock=True)
        return body

    def transcribe(self, data):
        # Audio is deleted after transcription, including failure paths.
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=self.audio_tmp) as audio:
            audio.write(data)
            audio.flush()
            segments, _ = self.model.transcribe(audio.name, language=self.config.get("language", "en"), beam_size=3, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()

    async def run_turn(self, tid, audio=None, text=None):
        self.delegation = {tid: 'idle'}
        started_hermes = False
        try:
            if audio is not None:
                self.update(tid, "transcribing")
                await asyncio.shield(self.warmup_task)
                if self.model is None:
                    raise RuntimeError("Local speech recognition is unavailable")
                text = await asyncio.to_thread(self.transcribe, audio)
                if not text:
                    self.update(tid, "error", text="No speech detected. Hold A and speak, then release.")
                    return
            text = text[:4000]
            self.update(tid, "working", transcript=text)
            # Persist the running state before any upstream call. Never replay it.
            with self.db:
                self.db.execute('DELETE FROM queue_jobs WHERE turn_id=?', (tid,))
            conversation = self.queue.conversation(tid) if self.queue_enabled else None
            sid = await self.session(conversation)
            started_hermes = True
            data = await self.chat(sid, text, tid)
            reply = data.get("message", {}).get("content")
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("Hermes returned no text")
            if data.get("session_id"):
                if conversation:
                    self.queue.save_session(conversation, data['session_id'])
                else:
                    self.db.execute("INSERT OR REPLACE INTO state VALUES ('session_id',?)", (data["session_id"],))
            self.update(tid, "done", text=reply)
        except Exception:
            if self.delegation.get(tid) == "active":
                self.delegation[tid] = "unknown"
            log.error("Device turn failed (details suppressed)")
            message = "Hermes connection failed. An action may have run; check its status before retrying." if started_hermes else "Could not process the request. Check the bridge service."
            self.update(tid, "error", text=message)

    async def health(self, request):
        self.expire_content()
        return web.json_response({"profile": "pocket", "status": "ready", "speech": "ready" if self.model else ("error" if self.model_error else "loading"),
            'message_queue': self.queue_enabled, 'unread': self.queue.unread_count() if self.queue_enabled else 0,
            'pending': self.queue.pending_count() if self.queue_enabled else 0})

    def require_queue(self):
        if not self.queue_enabled:
            raise web.HTTPNotFound(text='Message queue is disabled')

    @staticmethod
    def request_id(ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise web.HTTPBadRequest(text='Invalid request ID')
        return ident

    def check_action_capacity(self):
        count = self.db.execute("SELECT count(*) FROM state WHERE key LIKE 'new_chat:%' OR key LIKE 'resume:%'").fetchone()[0]
        if count >= self.config.get('max_turns', 10000):
            raise web.HTTPInsufficientStorage(text='Chat ID capacity reached; maintenance required')

    async def inbox(self, request):
        self.require_queue()
        before = request.query.get('before', '0')
        unread = request.query.get('unread', '0')
        if not re.fullmatch(r'[0-9]{1,18}', before) or unread not in ('0', '1'):
            raise web.HTTPBadRequest(text='Invalid inbox cursor or filter')
        self.expire_content()
        ids, cursor = self.queue.page(int(before), unread == '1')
        items = []
        for tid in ids:
            result = self.result(tid)
            result['preview'] = (result.pop('transcript') or 'Voice message').replace('\n', ' ')[:80]
            result.pop('text')
            items.append(result)
        return web.json_response(dict(items=items, next_before=cursor, unread=self.queue.unread_count(),
            pending=self.queue.pending_count(), conversation=self.queue.current()))

    async def mark_read(self, request):
        self.require_queue()
        tid = self.request_id(request.match_info['id'])
        result = self.result(tid)
        if not result or not result.get('durable'):
            raise web.HTTPNotFound()
        if result['status'] not in ('done', 'error'):
            raise web.HTTPConflict(text='Reply is not finished')
        with self.db:
            self.queue.read(tid)
        return web.json_response(dict(status='read', unread=self.queue.unread_count()))

    async def resume_chat(self, request):
        self.require_queue()
        ident = self.request_id(request.match_info['id'])
        key = 'resume:' + ident
        if self.db.execute('SELECT 1 FROM state WHERE key=?', (key,)).fetchone():
            return web.json_response({'status': 'ready'})
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest(text='Invalid JSON')
        tid = self.request_id(body.get('turn_id') if isinstance(body, dict) else None)
        # Recheck after reading a potentially slow body to preserve idempotency.
        if self.db.execute('SELECT 1 FROM state WHERE key=?', (key,)).fetchone():
            return web.json_response({'status': 'ready'})
        result = self.result(tid)
        if not result or not result.get('durable'):
            raise web.HTTPNotFound()
        if result.get('expired'):
            raise web.HTTPGone(text='Message expired')
        if result['status'] not in ('done', 'error'):
            raise web.HTTPConflict(text='Reply is not finished')
        self.check_action_capacity()
        with self.db:
            self.queue.select(result['conversation'])
            self.queue.read(tid)
            self.db.execute('INSERT INTO state VALUES (?,?)', (key, str(time.time())))
        return web.json_response({'status': 'ready'})

    async def new_chat(self, request):
        ident = request.match_info['id']
        if not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise web.HTTPBadRequest(text='Invalid request ID')
        key = 'new_chat:' + ident
        if self.db.execute('SELECT 1 FROM state WHERE key=?', (key,)).fetchone():
            return web.json_response({'status': 'ready'})
        if not self.queue_enabled and self.task and not self.task.done():
            raise web.HTTPConflict(text='Finish current request first')
        self.check_action_capacity()
        # Lazy session creation on the next turn; keep the old conversation intact.
        with self.db:
            self.db.execute("DELETE FROM state WHERE key='session_id'")
            if self.queue_enabled:
                self.queue.select()
            else:
                self.db.execute("DELETE FROM state WHERE key='conversation_id'")
            self.db.execute('INSERT INTO state VALUES (?,?)', (key, str(time.time())))
        return web.json_response({'status': 'ready'})

    async def submit(self, request):
        tid = request.match_info["id"]
        if not re.fullmatch(r"[a-f0-9]{32}", tid):
            raise web.HTTPBadRequest(text="Invalid request ID")
        previous = self.result(tid)
        if previous:
            return web.json_response(previous)
        if not self.queue_enabled and self.task and not self.task.done():
            raise web.HTTPConflict(text="Another turn is running")
        if self.queue_enabled and self.queue.pending_count() >= self.config.get('queue_capacity', 32):
            raise web.HTTPTooManyRequests(text='Message queue is full')
        if self.db.execute("SELECT count(*) FROM turns").fetchone()[0] >= self.config.get("max_turns", 10000):
            raise web.HTTPInsufficientStorage(text="Request capacity reached; maintenance required")
        audio = text = None
        conversation = self.queue.current() if self.queue_enabled else None
        if request.content_type == "audio/wav":
            audio = await request.read()
            try:
                validate_wav(audio)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc))
        elif request.content_type == "application/json":
            try:
                body = await request.json()
            except (ValueError, UnicodeError):
                raise web.HTTPBadRequest(text="Invalid JSON")
            text = body.get("text") if isinstance(body, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise web.HTTPBadRequest(text="Expected 1-4000 characters")
        else:
            raise web.HTTPUnsupportedMediaType()
        # Recheck after reading the body: another upload may have finished first.
        previous = self.result(tid)
        if previous:
            return web.json_response(previous)
        if not self.queue_enabled and self.task and not self.task.done():
            raise web.HTTPConflict(text="Another turn is running")
        if self.queue_enabled and self.queue.pending_count() >= self.config.get('queue_capacity', 32):
            raise web.HTTPTooManyRequests(text='Message queue is full')
        if self.db.execute("SELECT count(*) FROM turns").fetchone()[0] >= self.config.get("max_turns", 10000):
            raise web.HTTPInsufficientStorage(text="Request capacity reached; maintenance required")
        with self.db:
            self.db.execute("INSERT INTO turns VALUES (?,?,?,?,?)", (tid, "queued", "", "", time.time()))
            if self.queue_enabled:
                self.queue.add(tid, audio, text, conversation)
        if self.queue_enabled:
            self.start_queue()
        else:
            self.task = asyncio.create_task(self.run_turn(tid, audio, text))
        return web.json_response(self.result(tid), status=202)

    async def poll(self, request):
        if not re.fullmatch(r"[a-f0-9]{32}", request.match_info["id"]):
            raise web.HTTPBadRequest(text="Invalid request ID")
        result = self.result(request.match_info["id"])
        if result is None:
            raise web.HTTPNotFound()
        return web.json_response(result)

    def app(self):
        @web.middleware
        async def auth(request, handler):
            supplied = request.headers.get("Authorization", "")
            expected = "Bearer " + self.config["device_key"]
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                raise web.HTTPUnauthorized()
            if self.request_slots >= 4:
                raise web.HTTPTooManyRequests()
            self.request_slots += 1
            try:
                response = await asyncio.wait_for(handler(request), timeout=15)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except asyncio.TimeoutError:
                raise web.HTTPRequestTimeout()
            finally:
                self.request_slots -= 1
        app = web.Application(middlewares=[auth], client_max_size=MAX_AUDIO)
        app.router.add_get("/health", self.health)
        app.router.add_get('/inbox', self.inbox)
        app.router.add_post('/inbox/{id}/read', self.mark_read)
        app.router.add_post('/resume/{id}', self.resume_chat)
        app.router.add_post("/chat/{id}", self.new_chat)
        app.router.add_post("/turn/{id}", self.submit)
        app.router.add_get("/turn/{id}", self.poll)
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
        return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Private bridge runtime directory')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    root = args.root.expanduser().resolve()
    with runtime_lock(root):
        bridge = Bridge(root)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(root / "tls/server.pem", root / "tls/server.key")
        web.run_app(bridge.app(), host=bridge.config.get("bind", "127.0.0.1"),
                    port=bridge.config.get("port", 8643), ssl_context=tls, access_log=None)


if __name__ == "__main__":
    main()

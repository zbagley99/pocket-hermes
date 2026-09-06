import asyncio
import binascii
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'device'), str(Path(__file__).resolve().parents[1] / 'bridge')]
from text_view import TextView
from ascii_text import display_ascii
from server import Bridge, validate_wav


class Display:
    class FONTS:
        DejaVu12 = 12
        DejaVu9 = 9
        ASCII7 = 7

    def __init__(self):
        self.pushes = []

    def newCanvas(self, **kwargs):
        return self

    def push(self, x, y):
        self.pushes.append((x, y))

    def __getattr__(self, name):
        return lambda *args: None

    def textWidth(self, s):
        return sum(10 if c == 'W' else 6 for c in s)


class LayoutTests(unittest.TestCase):
    def test_wrong_certificate_is_rejected_before_token_is_written(self):
        sys.modules['ubinascii'] = binascii
        from pocket_net import PocketClient
        with patch('pocket_net.ssl.SSLContext') as context, patch('pocket_net.socket.socket') as socket:
            stream = context.return_value.wrap_socket.return_value
            stream.getpeercert.return_value = b'wrong-certificate'
            config = {'server_sha256': hashlib.sha256(b'trusted-certificate').hexdigest(), 'host': '127.0.0.1', 'port': 8643, 'tls_name': 'pocket.example.invalid', 'device_key': 'must-not-be-sent' * 3}
            client = PocketClient(config)
            with self.assertRaisesRegex(OSError, 'pin mismatch'):
                client.request('GET', '/health')
            stream.write.assert_not_called()
            stream.close.assert_called_once()

    def test_word_wrap_and_long_identifiers_preserve_content(self):
        view = TextView(Display())
        text = 'Wide WWWWWW cafe ' + 'long_identifier_' * 30
        lines = view.wrap(text)
        self.assertTrue(all(view.display.textWidth(line) <= 228 for line in lines))
        self.assertEqual(''.join(''.join(lines).split()), ''.join(text.split()))

    def test_unicode_is_safe_on_every_display_path(self):
        raw = '\u201cReady\u201d\u2014yes\u2026 \U0001f44b\U0001f3fd\n\u2705 23\u00b0C\r\nPath: caf\u00e9\t\U0001f469\u200d\U0001f4bb\x00'
        expected = '"Ready"-yes... \n[OK] 23 degreesC\nPath: caf\\u00e9 '
        self.assertEqual(display_ascii(raw), expected)
        self.assertEqual(display_ascii(expected), expected)
        self.assertEqual(display_ascii('\U0001f44b'), '[Non-ASCII content omitted]')
        drawn = []
        class Screen(Display):
            def drawString(self, text, *args):
                drawn.append(text)
            def __getattr__(self, name):
                return lambda *args: None
        view = TextView(Screen())
        view.append(raw)
        view.status = '\u26a0\ufe0f Reconnecting\u2026'
        view.draw()
        self.assertTrue(drawn)
        self.assertTrue(all(all(32 <= ord(c) <= 126 for c in line) for line in drawn))

    def test_scroll_does_not_jump_when_new_text_arrives(self):
        view = TextView(Display(), max_lines=12)
        view.append('\n'.join(str(n) for n in range(10)))
        view.scroll(-2)
        top = view.top
        view.append('new')
        self.assertEqual(view.top, top)
        view.append('another\nand another')
        self.assertEqual(len(view.lines), 12)
        self.assertEqual(view.lines[view.top], str(top))
        view.scroll(100)
        self.assertTrue(view.follow)

    def test_region_redraws_and_request_navigation(self):
        display = Display()
        view = TextView(display)
        view.draw()
        self.assertEqual(len(display.pushes), 3)
        view.draw()
        self.assertEqual(len(display.pushes), 3)
        self.assertEqual(view.height-view.footer_y, 14)
        self.assertEqual(view.line_height, 16)
        view.status = 'Working 2s'
        view.draw()
        self.assertEqual(display.pushes[3:], [(0, view.footer_y)])
        view.delegation = 'active'
        view.draw()
        self.assertEqual(display.pushes[4:], [(0, view.footer_y)])
        for i in range(3):
            view.add_request('request %d' % i)
            view.append('answer\n' * 8)
        view.previous_request()
        self.assertEqual(view.base + view.top, view.request_starts[-1])
        view.previous_request()
        self.assertEqual(view.base + view.top, view.request_starts[-2])
        anchor = view.lines[view.top]
        view.update_reply('long streamed response\n' * 20)
        self.assertEqual(view.lines[view.top], anchor)
        view.bottom()
        self.assertTrue(view.follow)
        self.assertEqual(view.top, len(view.lines)-view.visible)

    def test_wifi_form_preserves_secrets_and_saved_home(self):
        from wifi_setup import provision
        config = {'ssid': 'home', 'wifi_password': 'home-pass', 'device_key': 'secret', 'server_sha256': 'pin'}
        result = provision(config, b'token=ok&ssid=Phone+Hotspot&password=ab%2Bc%23def', 'ok')
        self.assertEqual(result['networks'][0], {'ssid': 'Phone Hotspot', 'password': 'ab+c#def'})
        self.assertEqual(result['networks'][1]['ssid'], 'home')
        self.assertEqual(result['device_key'], 'secret')
        self.assertEqual(result['server_sha256'], 'pin')
        self.assertNotIn('networks', config)
        with self.assertRaises(ValueError):
            provision(config, b'token=wrong&ssid=phone&password=abcdefgh', 'ok')

    def test_chord_suppresses_individual_controls_until_release(self):
        from controls import Controls
        class Button:
            pressed = False
            def isPressed(self): return self.pressed
            def pressedFor(self, duration): return self.pressed
            def wasDoubleClicked(self): return False
            def wasSingleClicked(self): return False
        a, b = Button(), Button()
        c = Controls()
        diff = lambda x, y: x-y
        a.pressed = b.pressed = True
        self.assertEqual(c.update(a, b, 0, diff), 'chord')
        self.assertEqual(c.update(a, b, 900, diff), 'new_chat')
        self.assertEqual(c.update(a, b, 1000, diff), 'chord')
        b.pressed = False
        self.assertEqual(c.update(a, b, 1100, diff), 'chord')
        a.pressed = False
        self.assertEqual(c.update(a, b, 1200, diff), 'chord')
        self.assertIsNone(c.update(a, b, 1300, diff))

    def test_audio_validation_rejects_wrong_rate_and_truncation(self):
        def wav(rate):
            out = io.BytesIO()
            with wave.open(out, 'wb') as f:
                f.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                f.writeframes(bytes(16000))
            return out.getvalue()
        validate_wav(wav(16000))
        with self.assertRaises(ValueError):
            validate_wav(wav(8000))
        with self.assertRaises(ValueError):
            validate_wav(wav(16000)[:-100])


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'device-bridge'
        self.root.mkdir()
        (self.root / 'config.json').write_text(json.dumps({'hermes_url': 'http://127.0.0.1:1', 'hermes_key': 's' * 43, 'device_key': 'd' * 43}))
        self.bridge = Bridge(self.root)
        self.bridge.load_model = lambda: object()
        self.calls = []
        async def hermes(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if path == '/api/sessions':
                return {'id': 'persisted-session'}
            await asyncio.sleep(.02)
            return {'session_id': 'persisted-session', 'message': {'content': 'Done.'}}
        self.bridge.hermes = hermes
        async def chat(sid, text, tid):
            return await hermes('POST', '/api/sessions/' + sid + '/chat', json={'input': text})
        self.bridge.chat = chat
        self.client = TestClient(TestServer(self.bridge.app()))
        await self.client.start_server()
        self.headers = {'Authorization': 'Bearer ' + 'd' * 43}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_expiry_keeps_idempotency_tombstone(self):
        tid = '9' * 32
        self.bridge.db.execute('INSERT INTO turns VALUES (?,?,?,?,?)', (tid, 'done', 'sensitive input', 'sensitive reply', 0))
        self.bridge.db.commit()
        response = await self.client.post('/turn/' + tid, json={'text': 'repeat action'}, headers=self.headers)
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(result['transcript'], '')
        self.assertEqual(result['text'], 'Result expired.')
        self.assertEqual(self.calls, [])

    async def test_limits_and_bad_requests(self):
        for path in ('/health', '/turn/' + 'a' * 32, '/chat/' + 'a' * 32):
            response = await self.client.get(path)
            self.assertEqual(response.status, 401)
        response = await self.client.get('/turn/invalid', headers=self.headers)
        self.assertEqual(response.status, 400)
        response = await self.client.post('/turn/' + 'a' * 32, data=b'x' * 970000,
            headers={**self.headers, 'Content-Type': 'audio/wav'})
        self.assertEqual(response.status, 413)
        response = await self.client.post('/turn/' + 'a' * 32, json=[], headers=self.headers)
        self.assertEqual(response.status, 400)
        self.bridge.request_slots = 4
        response = await self.client.get('/health', headers=self.headers)
        self.assertEqual(response.status, 429)
        self.bridge.request_slots = 0
        self.bridge.config['max_turns'] = 1
        self.bridge.db.execute('INSERT INTO turns VALUES (?,?,?,?,?)', ('b' * 32, 'done', '', '', time.time()))
        self.bridge.db.commit()
        response = await self.client.post('/turn/' + 'a' * 32, json={'text': 'hello'}, headers=self.headers)
        self.assertEqual(response.status, 507)
        response = await self.client.get('/health', headers=self.headers)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_upstream_redirect_is_not_followed(self):
        async def redirect(request):
            raise web.HTTPTemporaryRedirect('/destination')
        received = []
        async def destination(request):
            received.append(request.headers.get('Authorization'))
            return web.json_response({})
        app = web.Application()
        app.router.add_get('/redirect', redirect)
        app.router.add_get('/destination', destination)
        upstream = TestServer(app)
        await upstream.start_server()
        try:
            self.bridge.config['hermes_url'] = str(upstream.make_url('')).rstrip('/')
            with self.assertRaises(RuntimeError):
                await Bridge.hermes(self.bridge, 'GET', '/redirect')
            self.assertEqual(received, [])
        finally:
            await upstream.close()

    async def test_auth_and_invalid_audio_never_reach_hermes(self):
        r = await self.client.post('/turn/' + 'a' * 32, json={'text': 'hello'})
        self.assertEqual(r.status, 401)
        r = await self.client.post('/turn/' + 'a' * 32, data=b'invalid', headers={**self.headers, 'Content-Type': 'audio/wav'})
        self.assertEqual(r.status, 400)
        self.assertEqual(self.calls, [])

    async def test_new_chat_can_create_session_without_title_collision(self):
        titles = {'M5StickS3 Pocket'}
        async def create(method, path, **kwargs):
            self.assertEqual((method, path), ('POST', '/api/sessions'))
            title = kwargs['json']['title']
            if title in titles:
                raise RuntimeError('Hermes HTTP 400: title already in use')
            titles.add(title)
            return {'object': 'hermes.session', 'session': {'id': 'session-' + str(len(titles))}}
        self.bridge.hermes = create
        first = await self.bridge.session()
        self.assertEqual(await self.bridge.session(), first)
        response = await self.client.post('/chat/' + 'b' * 32, headers=self.headers)
        self.assertEqual(response.status, 200)
        second = await self.bridge.session()
        self.assertNotEqual(first, second)
        self.assertEqual(len(titles), 3)

    async def test_new_chat_is_authenticated_and_idempotent(self):
        self.bridge.db.execute("INSERT INTO state VALUES ('session_id','old')")
        self.bridge.db.commit()
        path = '/chat/' + 'f' * 32
        r = await self.client.post(path)
        self.assertEqual(r.status, 401)
        r = await self.client.post(path, headers=self.headers)
        self.assertEqual(r.status, 200)
        self.assertIsNone(self.bridge.db.execute("SELECT value FROM state WHERE key='session_id'").fetchone())
        self.bridge.db.execute("INSERT INTO state VALUES ('session_id','new')")
        self.bridge.db.commit()
        r = await self.client.post(path, headers=self.headers)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.bridge.db.execute("SELECT value FROM state WHERE key='session_id'").fetchone()[0], 'new')
        self.bridge.task = asyncio.create_task(asyncio.sleep(60))
        r = await self.client.post('/chat/' + 'e' * 32, headers=self.headers)
        self.assertEqual(r.status, 409)

    async def test_retry_is_idempotent_and_session_is_reused(self):
        for tid in ('a' * 32, 'b' * 32):
            r = await self.client.post('/turn/' + tid, json={'text': 'hello'}, headers=self.headers)
            self.assertEqual(r.status, 202)
            await self.bridge.task
            r = await self.client.post('/turn/' + tid, json={'text': 'hello'}, headers=self.headers)
            self.assertEqual((await r.json())['status'], 'done')
        self.assertEqual(sum(path == '/api/sessions' for _, path, _ in self.calls), 1)
        self.assertEqual(sum(path.endswith('/chat') for _, path, _ in self.calls), 2)

    async def test_restart_marks_uncertain_action_without_replaying_it(self):
        self.bridge.db.execute('INSERT INTO turns VALUES (?,?,?,?,?)', ('c' * 32, 'working', 'hello', '', time.time()))
        self.bridge.db.commit()
        reopened = Bridge(self.root)
        self.assertEqual(reopened.result('c' * 32)['status'], 'error')
        self.assertIn('may have run', reopened.result('c' * 32)['text'])
        reopened.db.close()

    async def test_poll_sanitizes_old_unicode_without_rewriting_history(self):
        text = 'Hello! \U0001f44b \u201cReady\u201d'
        self.bridge.db.execute('INSERT INTO turns VALUES (?,?,?,?,?)', ('e' * 32, 'done', 'caf\u00e9', text, time.time()))
        self.bridge.db.commit()
        response = await self.client.get('/turn/' + 'e' * 32, headers=self.headers)
        data = await response.json()
        self.assertTrue(data['text'].isascii())
        self.assertEqual(data['transcript'], 'caf\\u00e9')
        stored = self.bridge.db.execute('SELECT text FROM turns WHERE id=?', ('e' * 32,)).fetchone()[0]
        self.assertEqual(stored, text)

    async def test_model_follows_profile_changes_without_modifying_config(self):
        config = self.root.parent / 'config.yaml'
        for name in ('old-model', 'new-model'):
            contents = 'model:\n  provider: custom\n  default: ' + name + '\n'
            config.write_text(contents)
            body = self.bridge.chat_body('hello')
            self.assertEqual(body, {'input': 'hello', 'provider': 'custom', 'model': name, 'require_model_lock': True})
            self.assertEqual(config.read_text(), contents)

    async def test_stream_forwards_public_text_and_uses_authoritative_final(self):
        async def stream(request):
            self.assertEqual((await request.json())['input'], 'hello')
            r = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await r.prepare(request)
            events = [
                ('tool.progress', {'delta': 'private reasoning must not appear'}),
                ('tool.started', {'tool_name': 'delegate_task', 'args': {'prompt': 'private child instructions'}}),
                ('tool.completed', {'tool_name': 'delegate_task', 'preview': 'private child output'}),
                ('assistant.delta', {'delta': 'Hello'}),
                ('assistant.delta', {'delta': ', world.'}),
                ('assistant.completed', {'session_id': 'stream-session', 'content': 'Hello, world.'}),
                ('done', {}),
            ]
            for name, data in events:
                await r.write(('event: ' + name + '\ndata: ' + json.dumps(data) + '\n\n').encode())
            return r
        upstream = web.Application()
        upstream.router.add_post('/api/sessions/stream-session/chat/stream', stream)
        server = TestServer(upstream)
        await server.start_server()
        try:
            self.bridge.config['hermes_url'] = str(server.make_url('')).rstrip('/')
            self.bridge.db.execute('INSERT INTO turns VALUES (?,?,?,?,?)', ('d' * 32, 'working', 'hello', '', time.time()))
            self.bridge.db.commit()
            observed = []
            original_update = self.bridge.update
            def record_update(*args, **kwargs):
                original_update(*args, **kwargs)
                observed.append(self.bridge.result('d' * 32)['delegation'])
            self.bridge.update = record_update
            result = await Bridge.chat(self.bridge, 'stream-session', 'hello', 'd' * 32)
            self.assertIn('active', observed)
            self.assertEqual(self.bridge.result('d' * 32)['delegation'], 'returned')
            self.assertNotIn('private child', json.dumps(self.bridge.result('d' * 32)))
            self.assertEqual(result['message']['content'], 'Hello, world.')
            self.assertNotIn('private reasoning', self.bridge.result('d' * 32)['text'])
        finally:
            await server.close()


if __name__ == '__main__':
    unittest.main()

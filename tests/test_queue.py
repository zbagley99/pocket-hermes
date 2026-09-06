import asyncio
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
import wave

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ('bridge', 'device')]
from server import Bridge, validate_config
from inbox import Inbox
from text_view import TextView
from test_pocket import Display


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = dict(hermes_url='http://127.0.0.1:1', hermes_key='h' * 43,
                           device_key='d' * 43, message_queue=True, queue_capacity=3)
        (self.root / 'config.json').write_text(json.dumps(self.config))
        self.headers = {'Authorization': 'Bearer ' + self.config['device_key']}
        self.calls = []
        self.sessions = []
        self.gate = asyncio.Event()
        self.started = asyncio.Event()
        self.gate.set()
        await self.start()

    async def start(self):
        self.bridge = Bridge(self.root)
        self.bridge.load_model = lambda: object()
        async def hermes(method, path, **kwargs):
            self.sessions.append('session-' + str(len(self.sessions) + 1))
            return {'id': self.sessions[-1]}
        async def chat(sid, text, tid):
            self.calls.append((sid, text, tid))
            self.started.set()
            await self.gate.wait()
            return {'session_id': sid, 'message': {'content': 'Reply to ' + text}}
        self.bridge.hermes = hermes
        self.bridge.chat = chat
        self.client = TestClient(TestServer(self.bridge.app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def send(self, number, text='hello'):
        tid = '%032x' % number
        response = await self.client.post('/turn/' + tid, json={'text': text}, headers=self.headers)
        return response.status, await response.json() if response.content_type == 'application/json' else None

    async def drain(self):
        await asyncio.wait_for(asyncio.shield(self.bridge.task), 3)

    async def test_fifo_accepts_multiple_messages_without_waiting_for_model(self):
        self.gate.clear()
        for number in range(1, 4):
            status, result = await self.send(number, 'message ' + str(number))
            self.assertEqual(status, 202)
            self.assertTrue(result['durable'])
        self.assertEqual((await self.send(4))[0], 429)
        self.assertEqual((await self.send(2))[0], 200)  # Retry still works at capacity.
        self.gate.set()
        await self.drain()
        self.assertEqual([call[1] for call in self.calls], ['message 1', 'message 2', 'message 3'])
        self.assertEqual(self.bridge.queue.unread_count(), 3)
        self.assertEqual(self.bridge.db.execute('SELECT count(*) FROM queue_jobs').fetchone()[0], 0)

    async def test_reply_survives_client_disconnect_and_bridge_restart_until_explicit_read(self):
        self.gate.clear()
        _, sent = await self.send(1)
        await self.started.wait()
        # Close only the HTTP client, leaving the bridge running while the Stick is off.
        await self.client.session.close()
        self.gate.set()
        await self.drain()
        await self.client.close()
        await self.start()
        response = await self.client.get('/inbox?unread=1', headers=self.headers)
        page = await response.json()
        self.assertEqual(page['unread'], 1)
        self.assertEqual(page['items'][0]['id'], sent['id'])
        for _ in range(2):
            await self.client.get('/turn/' + sent['id'], headers=self.headers)
            self.assertEqual(self.bridge.queue.unread_count(), 1)
        for _ in range(2):
            response = await self.client.post('/inbox/' + sent['id'] + '/read', headers=self.headers)
            self.assertEqual(response.status, 200)
        self.assertEqual(self.bridge.queue.unread_count(), 0)
        self.assertEqual(len(self.calls), 1)

    async def test_restart_resumes_only_unstarted_jobs_and_preserves_conversation(self):
        self.gate.clear()
        await self.send(1, 'started')
        await self.started.wait()
        await self.send(2, 'not started')
        await self.client.close()
        self.gate.set()
        await self.start()
        await self.drain()
        first = self.bridge.result('%032x' % 1)
        self.assertEqual(first['status'], 'error')
        self.assertIn('may have run', first['text'])
        self.assertEqual(self.bridge.result('%032x' % 2)['status'], 'done')
        self.assertEqual([call[1] for call in self.calls], ['started', 'not started'])
        self.assertEqual(len(self.sessions), 1)

    async def test_audio_is_committed_before_ack_and_deleted_after_transcription(self):
        self.gate.clear()
        await self.send(1)
        await self.started.wait()
        out = io.BytesIO()
        with wave.open(out, 'wb') as f:
            f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            f.writeframes(bytes(16000))
        audio = out.getvalue()
        tid = '%032x' % 2
        response = await self.client.post('/turn/' + tid, data=audio,
            headers={**self.headers, 'Content-Type': 'audio/wav'})
        self.assertEqual(response.status, 202)
        with sqlite3.connect(self.root / 'state.sqlite3') as independent:
            self.assertEqual(independent.execute('SELECT audio FROM queue_jobs WHERE turn_id=?', (tid,)).fetchone()[0], audio)
        # Restart before transcription; the bytes must survive and be processed once.
        await self.client.close()
        self.gate.set()
        await self.start()
        self.bridge.transcribe = lambda data: 'recovered audio' if data == audio else ''
        await self.drain()
        self.assertEqual(self.bridge.result(tid)['transcript'], 'recovered audio')
        self.assertIsNone(self.bridge.db.execute('SELECT 1 FROM queue_jobs WHERE turn_id=?', (tid,)).fetchone())
        self.assertEqual((self.root / 'state.sqlite3').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.bridge.db.execute('PRAGMA synchronous').fetchone()[0], 3)

    async def test_new_chat_during_work_and_resume_route_each_message_to_its_own_session(self):
        self.gate.clear()
        _, first = await self.send(1, 'first conversation')
        await self.started.wait()
        response = await self.client.post('/chat/' + 'c' * 32, headers=self.headers)
        self.assertEqual(response.status, 200)
        _, second = await self.send(2, 'second conversation')
        self.assertNotEqual(first['conversation'], second['conversation'])
        self.gate.set()
        await self.drain()
        self.assertNotEqual(self.calls[0][0], self.calls[1][0])
        action = '/resume/' + 'd' * 32
        response = await self.client.post(action, json={'turn_id': first['id']}, headers=self.headers)
        self.assertEqual(response.status, 200)
        self.assertFalse(self.bridge.result(first['id'])['unread'])
        await self.send(3, 'continue first')
        await self.drain()
        self.assertEqual(self.calls[0][0], self.calls[2][0])
        await self.client.post('/chat/' + 'e' * 32, headers=self.headers)
        current = self.bridge.queue.current()
        await self.client.post(action, json={'turn_id': first['id']}, headers=self.headers)
        self.assertEqual(self.bridge.queue.current(), current)  # Lost response must not reapply old selection.

    async def test_unread_pagination_is_bounded_and_does_not_expose_full_content(self):
        for number in range(1, 19):
            await self.send(number, 'private body ' * 50)
            await self.drain()
        before = 0
        seen = []
        while True:
            response = await self.client.get('/inbox?unread=1&before=' + str(before), headers=self.headers)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            page = await response.json()
            self.assertLessEqual(len(page['items']), 8)
            for item in page['items']:
                self.assertNotIn('text', item)
                self.assertNotIn('transcript', item)
                self.assertLessEqual(len(item['preview']), 80)
                seen.append(item['id'])
            before = page['next_before']
            if before is None:
                break
        self.assertEqual(len(set(seen)), 18)

    async def test_expired_replies_leave_tombstones_but_no_unread_content(self):
        _, message = await self.send(1)
        await self.drain()
        with self.bridge.db:
            self.bridge.db.execute('UPDATE turns SET created=0')
        response = await self.client.get('/inbox', headers=self.headers)
        page = await response.json()
        self.assertEqual((page['unread'], page['items']), (0, []))
        response = await self.client.post('/resume/' + 'e' * 32, json={'turn_id': message['id']}, headers=self.headers)
        self.assertEqual(response.status, 410)
        status, result = await self.send(1, 'must not replay')
        self.assertEqual(status, 200)
        self.assertTrue(result['expired'])
        self.assertEqual(len(self.calls), 1)

    async def test_stale_queued_work_is_not_executed_after_long_outage(self):
        self.gate.clear()
        await self.send(1, 'already running')
        await self.started.wait()
        await self.send(2, 'stale job')
        with self.bridge.db:
            self.bridge.db.execute('UPDATE turns SET created=0 WHERE id=?', ('%032x' % 2,))
        await self.client.close()
        self.gate.set()
        await self.start()
        await self.drain()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.bridge.result('%032x' % 2)['expired'])
        self.assertIsNone(self.bridge.queue.next_job())

    async def test_queue_endpoints_require_auth_and_reject_bad_identifiers(self):
        for method, path in [('get', '/inbox'), ('post', '/inbox/' + 'a' * 32 + '/read'), ('post', '/resume/' + 'a' * 32)]:
            response = await getattr(self.client, method)(path)
            self.assertEqual(response.status, 401)
        for path in ('/inbox?before=-1', '/inbox?before=' + '9' * 30, '/inbox?unread=yes'):
            self.assertEqual((await self.client.get(path, headers=self.headers)).status, 400)
        for body in ([], {'turn_id': '../../config.json'}, {'turn_id': 42}):
            response = await self.client.post('/resume/' + 'b' * 32, json=body, headers=self.headers)
            self.assertEqual(response.status, 400)
        self.gate.clear()
        _, message = await self.send(1)
        for path in ('/inbox/' + message['id'] + '/read', '/resume/' + 'c' * 32):
            response = await self.client.post(path, json={'turn_id': message['id']}, headers=self.headers)
            self.assertEqual(response.status, 409)

    async def test_disabled_queue_retains_original_single_request_behavior(self):
        await self.client.close()
        self.config['message_queue'] = False
        (self.root / 'config.json').write_text(json.dumps(self.config))
        await self.start()
        response = await self.client.get('/inbox', headers=self.headers)
        self.assertEqual(response.status, 404)
        self.gate.clear()
        _, result = await self.send(1)
        self.assertNotIn('durable', result)
        self.assertEqual((await self.send(2))[0], 409)

    def test_queue_config_is_opt_in_and_strictly_bounded(self):
        for override in ({'message_queue': 'true'}, {'queue_capacity': True}, {'queue_capacity': 0}, {'queue_capacity': 101}):
            with self.assertRaises(ValueError):
                validate_config(dict(self.config, **override))


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.view = TextView(Display())
        self.view.append('Current chat')
        self.inbox = Inbox(self.view)
        self.message = dict(id='a' * 32, status='done', unread=True, preview='Test question',
                            transcript='Test question', text='Long reply\n' * 20, conversation='b' * 32)

    def open_message(self):
        self.inbox.open()
        self.inbox.job = None
        self.inbox.complete('list', dict(items=[self.message], unread=1, next_before=None), None)
        self.inbox.handle('record')
        self.assertEqual(self.inbox.job, ('detail', 'GET', '/turn/' + self.message['id']))
        self.inbox.job = None
        self.inbox.complete('detail', self.message, None)

    def test_open_scroll_and_return_do_not_acknowledge_or_change_conversation(self):
        self.open_message()
        self.assertIsNone(self.inbox.job)
        self.assertEqual(self.view.top, 0)
        self.inbox.handle('down')
        self.assertEqual(self.view.top, 1)
        self.inbox.handle('wifi')
        self.assertEqual(self.inbox.job[1], 'GET')
        self.inbox.complete('list', dict(items=[self.message], unread=1), None)
        self.inbox.handle('wifi')
        self.assertFalse(self.inbox.active)
        self.assertEqual(self.view.lines, ['Current chat'])

    def test_continue_and_mark_read_are_explicit_menu_choices(self):
        self.open_message()
        self.inbox.handle('record')
        self.assertEqual(self.inbox.handle('record'), ('resume', self.message['id']))
        self.inbox.handle('down')
        self.inbox.handle('record')
        self.assertEqual(self.inbox.job, ('read', 'POST', '/inbox/' + self.message['id'] + '/read'))

    def test_pending_reply_cannot_be_resumed_or_marked_read(self):
        self.message['status'] = 'queued'
        self.open_message()
        self.inbox.handle('record')
        actions = [action for _, (action, _) in self.inbox.options]
        self.assertNotIn('read', actions)
        self.assertNotIn('resume', actions)

    def test_inbox_failure_is_recoverable_without_dismissing_unread_reply(self):
        self.inbox.open()
        self.inbox.job = None
        self.inbox.complete('list', None, OSError())
        self.inbox.handle('wifi')
        self.assertFalse(self.inbox.active)

    def test_next_page_and_filters_use_server_cursors(self):
        self.inbox.open()
        self.inbox.complete('list', dict(items=[self.message], next_before=20, unread=9), None)
        self.inbox.handle('down')
        self.inbox.handle('record')
        self.assertIn('before=20&unread=1', self.inbox.job[2])

    def test_back_cancels_a_slow_inbox_load_and_invalidates_its_response(self):
        self.inbox.open()
        generation = self.inbox.generation
        self.inbox.handle('wifi')
        self.assertFalse(self.inbox.active)
        self.assertIsNone(self.inbox.job)
        self.assertGreater(self.inbox.generation, generation)
        self.inbox.open()
        self.assertGreater(self.inbox.generation, generation)


if __name__ == '__main__':
    unittest.main()

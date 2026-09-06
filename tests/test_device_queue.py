"""Exercise the real device application loop with synthetic hardware and transport."""
import binascii
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from test_pocket import Display

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))


class StopApp(Exception):
    pass


class DeviceQueueTests(unittest.TestCase):
    def exercise(self, pending=False, navigate=False, enabled=True):
        hardware = Mock()
        hardware.Lcd = Display()
        hardware.BtnA.isPressed.return_value = False
        hardware.BtnB.isPressed.return_value = False
        hardware.Power.getBatteryLevel.return_value = 80
        network = Mock()
        network.WLAN.return_value.isconnected.return_value = True
        files = {'/flash/pocket-config.json': dict(host='bridge.example.invalid', tls_name='bridge.example.invalid',
            port=8643, server_sha256='a' * 64, device_key='d' * 43, ssid='test', wifi_password='')}
        message = dict(id='b' * 32, durable=True, unread=True, status='done', transcript='Synthetic question',
                       preview='Synthetic question', text='Offline response', conversation='c' * 32)
        if pending:
            files['/flash/pocket-pending.json'] = {'id': message['id']}
        calls, writes, stages = [], [], []
        frame = [0]
        context = {}

        class Worker:
            def __init__(self, client):
                self.busy = False
                self.result = None

            def submit(self, kind, method, path, body=b'', content_type='application/json'):
                original_kind = kind
                if kind.startswith('inbox:'):
                    kind = 'inbox:' + kind.split(':')[-1]
                calls.append((kind, method, path))
                self.busy = True
                if kind == 'health':
                    result = dict(profile='test', speech='ready', message_queue=enabled, unread=1, pending=0)
                elif kind == 'inbox:list':
                    result = dict(items=[message], unread=1)
                elif kind in ('inbox:detail', 'poll'):
                    result = message
                elif kind == 'new_chat':
                    action = files['/flash/pocket-new-chat.json']
                    assert action['kind'] == 'resume' and action['turn_id'] == message['id']
                    assert json.loads(body)['turn_id'] == message['id']
                    result = {'status': 'ready'}
                else:
                    raise AssertionError('Unexpected device request: ' + kind)
                self.result = (original_kind, result, None)
                return True

            def take(self):
                result, self.result = self.result, None
                if result:
                    self.busy = False
                return result

        class Controls:
            def update(self, *args):
                frame[0] += 1
                if frame[0] > 50:
                    raise StopApp()
                inbox = context.get('inbox')
                if not navigate or not inbox or not inbox.active or inbox.loading:
                    return None
                if inbox.mode == 'list' and not stages:
                    stages.append('open')
                    return 'record'
                if inbox.mode == 'detail' and stages == ['open']:
                    stages.append('actions')
                    return 'record'
                if inbox.mode == 'actions' and stages == ['open', 'actions'] and frame[0] % 3 == 0:
                    stages.append('resume')
                    return 'record'
                return None

        def save(path, value):
            files[path] = json.loads(json.dumps(value))
            writes.append((path, files[path]))

        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, M5=hardware, network=network, ubinascii=binascii))
            spec = importlib.util.spec_from_file_location('pocket_app_test', ROOT / 'device/pocket.py')
            app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app)
            real_inbox = app.Inbox
            def inbox(view):
                context['inbox'] = real_inbox(view)
                return context['inbox']
            for name, value in dict(NetWorker=Worker, Controls=Controls, Inbox=inbox, PocketClient=lambda _: None,
                                    load_json=lambda path, fallback=None: files.get(path, fallback), save_json=save).items():
                stack.enter_context(patch.object(app, name, value))
            stack.enter_context(patch.object(app.os, 'remove', lambda path: files.pop(path, None)))
            for name, function in dict(ticks_ms=lambda: frame[0] * 20, ticks_add=lambda x, y: x+y,
                                       ticks_diff=lambda x, y: x-y, sleep_ms=lambda _: None).items():
                stack.enter_context(patch.object(app.time, name, function, create=True))
            stack.enter_context(patch('sys.stdout', io.StringIO()))
            with self.assertRaises(StopApp):
                app.run()
        hardware.Mic.begin.assert_not_called()
        return calls, writes, files, context

    def test_boot_opens_unread_inbox_before_recording_and_persists_resume_action(self):
        calls, writes, files, _ = self.exercise(navigate=True)
        self.assertEqual([c[0] for c in calls[:3]], ['health', 'inbox:list', 'inbox:detail'])
        self.assertTrue(any(path.startswith('/resume/') for _, _, path in calls))
        self.assertEqual(writes[0][1]['kind'], 'resume')
        self.assertNotIn('/flash/pocket-new-chat.json', files)
        self.assertNotIn('/flash/pocket-history.json', files)

    def test_boot_recovers_uncertain_delivery_by_id_without_resending_or_acknowledging(self):
        calls, writes, files, _ = self.exercise(pending=True)
        self.assertEqual([c[0] for c in calls[:2]], ['health', 'poll'])
        self.assertIn('inbox:list', [c[0] for c in calls])
        self.assertNotIn('/flash/pocket-pending.json', files)
        self.assertTrue(all(method == 'GET' for _, method, _ in calls))
        self.assertEqual(writes, [])

    def test_bridge_without_queue_keeps_the_original_device_mode(self):
        calls, _, _, context = self.exercise(enabled=False)
        self.assertEqual([kind for kind, _, _ in calls], ['health'])
        self.assertFalse(context['inbox'].active)


if __name__ == '__main__':
    unittest.main()

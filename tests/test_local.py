import argparse
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / name) for name in ('scripts', 'device')]
import local
from wifi_setup import start_secure_ap, SetupUnavailable


class LocalSetupTests(unittest.TestCase):
    def test_smoke_script_imports_without_network_and_generates_valid_device_code(self):
        with patch('socket.socket') as connect:
            import smoke_device
        connect.assert_not_called()
        compile('c={}\n' + smoke_device.DEVICE_CHECKS, '<device smoke test>', 'exec')
        import smoke_inbox
        compile(smoke_inbox.device_code(), '<inbox smoke test>', 'exec')

    def test_fresh_clone_setup_keeps_secrets_private_and_is_reusable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = dict(host='bridge.example.invalid', tls_name='bridge.example.invalid', port=8643,
                          device_key='d' * 43, server_sha256='a' * 64, ssid='synthetic-wifi', wifi_password='test-password')
            source = root / 'import.json'
            source.write_text(json.dumps(config))
            args = argparse.Namespace(config=source, port='TEST_PORT', wifi=False)
            output = io.StringIO()
            with patch.object(local, 'ROOT', root), patch('sys.stdout', output):
                local.setup(args)
                settings, target = local.load_settings()
                self.assertEqual(settings['port'], 'TEST_PORT')
                self.assertEqual(json.loads(target.read_text())['persist_history'], False)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                local.setup(args)
            self.assertNotIn('test-password', output.getvalue())
            self.assertNotIn('d' * 43, output.getvalue())
            self.assertEqual(json.loads(source.read_text()), config)

    def test_wifi_change_prioritizes_new_network_and_preserves_existing_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = dict(host='bridge.example.invalid', tls_name='bridge.example.invalid', port=8643,
                          device_key='d' * 43, server_sha256='a' * 64, ssid='old-network', wifi_password='old-password')
            source = root / 'import.json'
            source.write_text(json.dumps(config))
            args = argparse.Namespace(config=source, port='TEST_PORT', wifi=True)
            with patch.object(local, 'ROOT', root), patch('builtins.input', return_value='new-network'), patch('local.getpass.getpass', return_value='new-password'), patch('sys.stdout', io.StringIO()):
                local.setup(args)
            saved = json.loads((root / '.private/provisioning/device.json').read_text())
            self.assertEqual(saved['networks'][0], {'ssid': 'new-network', 'password': 'new-password'})
            self.assertEqual(saved['ssid'], 'old-network')
            self.assertEqual(saved['device_key'], config['device_key'])

    def test_firmware_without_inactive_config_never_starts_an_open_ap(self):
        ap = Mock()
        ap.config.side_effect = OSError('Wifi Invalid Mode')
        with self.assertRaises(SetupUnavailable):
            start_secure_ap(ap, 'synthetic-ap', 'synthetic-password', 3)
        self.assertNotIn(((True,), {}), [(c.args, c.kwargs) for c in ap.active.call_args_list])
        ap.active.assert_called_with(False)

    def test_secure_ap_config_precedes_activation(self):
        ap = Mock()
        start_secure_ap(ap, 'synthetic-ap', 'synthetic-password', 3)
        self.assertEqual([call[0] for call in ap.mock_calls], ['active', 'config', 'active'])
        ap.active.assert_called_with(True)


if __name__ == '__main__':
    unittest.main()

import binascii
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('device', 'bridge', 'scripts')]
sys.modules['ubinascii'] = binascii
from configuration import validate
from pocket_net import PocketClient
from server import validate_config, runtime_lock
from check_release import check, release_paths


class SecurityTests(unittest.TestCase):
    def test_runtime_lock_prevents_concurrent_production_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with runtime_lock(root):
                with self.assertRaisesRegex(RuntimeError, 'Another bridge process'):
                    with runtime_lock(root):
                        self.fail('A second process acquired the runtime')
            with runtime_lock(root):
                self.assertEqual((root / '.bridge.lock').stat().st_mode & 0o777, 0o600)

    def test_config_rejects_header_injection_and_invalid_pins(self):
        config = dict(host='bridge.example.invalid', tls_name='bridge.example.invalid',
                      port=8643, device_key='d' * 43, server_sha256='a' * 64, ssid='example', wifi_password='')
        validate(config)
        for key, value in [('host', 'host\r\nInjected: yes'), ('device_key', 'x' * 32 + '\r\n'),
                           ('server_sha256', 'z' * 64), ('port', True), ('persist_history', 'false')]:
            bad = dict(config, **{key: value})
            with self.assertRaises(ValueError):
                validate(bad)

    def test_bridge_rejects_remote_upstream_and_shared_keys(self):
        config = dict(hermes_url='http://127.0.0.1:8642', hermes_key='h' * 43, device_key='d' * 43)
        validate_config(config)
        for patch in ({'hermes_url': 'http://example.invalid:8642'}, {'device_key': 'h' * 43},
                      {'device_key': ''}, {'retention_days': 0}, {'max_turns': False},
                      {'hermes_url': 'http://127.0.0.1:8642/redirect'}):
            with self.assertRaises(ValueError):
                validate_config(dict(config, **patch))

    def test_http_header_reads_are_bounded(self):
        with self.assertRaises(OSError):
            PocketClient.read_line(io.BytesIO(b'x' * 10000))
        self.assertEqual(PocketClient.read_line(io.BytesIO(b'HTTP/1.1 200 OK\r\n')), b'HTTP/1.1 200 OK\r\n')

    def test_release_blocks_private_paths_and_detects_private_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.private').mkdir()
            (root / '.private/device.json').write_text(json.dumps({'device_key': 'synthetic-sensitive-value'}))
            (root / 'example.txt').write_text('synthetic-sensitive-value')
            (root / 'release-manifest.json').write_text('["example.txt"]')
            self.assertTrue(check(root)[1])
            (root / 'release-manifest.json').write_text('[".private/device.json"]')
            with self.assertRaises(ValueError):
                release_paths(root)

    def test_initializer_creates_matching_private_credentials_and_refuses_overwrite(self):
        import hashlib
        import ssl
        import install
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'runtime'
            args = ['install.py', '--root', str(root), '--host', 'bridge.example.invalid']
            with patch.object(sys, 'argv', args), patch('install.getpass.getpass', return_value='h' * 43):
                install.main()
                with self.assertRaises(FileExistsError):
                    install.main()
            bridge = json.loads((root / 'config.json').read_text())
            device = json.loads((root / 'device.json').read_text())
            der = ssl.PEM_cert_to_DER_cert((root / 'tls/server.pem').read_text())
            self.assertEqual(device['server_sha256'], hashlib.sha256(der).hexdigest())
            self.assertEqual(device['device_key'], bridge['device_key'])
            self.assertNotIn('hermes_key', device)
            self.assertEqual(bridge['bind'], '127.0.0.1')
            self.assertFalse(device['persist_history'])
            self.assertEqual((root / 'config.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'tls/server.key').stat().st_mode & 0o777, 0o600)

    def test_installer_is_import_safe(self):
        with patch('subprocess.run') as run:
            import install
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()

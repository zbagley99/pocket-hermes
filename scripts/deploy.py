"""Install Pocket Hermes on existing UiFlow2 firmware with startup backups."""
import argparse
import json
import os
import sys
from pathlib import Path
import time
from device_console import Device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--replace-config', action='store_true', help='Replace saved Wi-Fi settings and credentials (required for pin/key rotation)')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.umask(0o077)
    sys.path.insert(0, str(root / 'device'))
    from configuration import validate
    config = args.config.expanduser()
    if not config.is_file():
        raise SystemExit('Private device config is missing; run scripts/local.py setup first.')
    validate(json.loads(config.read_text()))
    d = Device(args.port)
    try:
        identity = d.execute("import machine, ubinascii; print(ubinascii.hexlify(machine.unique_id()).decode())").strip()
        if not identity or any(c not in '0123456789abcdef' for c in identity):
            raise RuntimeError('Cannot identify device safely')
        private = root / '.private' / 'devices' / identity
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('main.py', 'boot.py'):
            backup = private / ('original-' + name)
            if not backup.exists():
                value = d.execute("import ubinascii; print(ubinascii.hexlify(open('/flash/" + name + "','rb').read()).decode())")
                backup.write_bytes(bytes.fromhex(value.strip()))
        nvs_backup = private / 'original-boot-option.txt'
        if not nvs_backup.exists():
            value = d.execute("import esp32; _n=esp32.NVS('uiflow'); print(_n.get_u8('boot_option'))")
            nvs_backup.write_text(value.strip())
        d.put((private / 'original-main.py').read_bytes(), '/flash/pocket-original-main.py')
        present = d.execute("import os; print('pocket-config.json' in os.listdir('/flash'))").strip()
        if present != 'True' or args.replace_config:
            d.put(config.read_bytes(), '/flash/pocket-config.json')
        for name in ('configuration.py', 'ascii_text.py', 'text_view.py', 'pocket_net.py', 'net_worker.py', 'controls.py', 'wifi_setup.py', 'inbox.py', 'pocket.py'):
            d.put((root / 'device' / name).read_bytes(), '/flash/libs/' + name)
        d.put((root / 'device/main.py').read_bytes(), '/flash/main.py')
        d.execute("import esp32; _n=esp32.NVS('uiflow'); _n.set_u8('boot_option',0); _n.commit(); print('POCKET_INSTALLED')")
        d.port.write(b'\x02\x04')
        end = time.monotonic() + 20
        data = bytearray()
        while time.monotonic() < end:
            chunk = d.port.read(d.port.in_waiting or 1)
            data.extend(chunk)
            if b'POCKET_CONNECTED' in data or b'Traceback' in data:
                time.sleep(.3)
                data.extend(d.port.read(d.port.in_waiting))
                break
        if b'Traceback' in data:
            raise RuntimeError('Device startup failed; inspect locally (console details suppressed)')
        if b'POCKET_CONNECTED' not in data:
            raise RuntimeError('Firmware uploaded, but bridge connection was not verified within 20 seconds')
        print('Device connected; startup and authenticated bridge health check passed.')
    finally:
        d.close()


if __name__ == '__main__':
    main()

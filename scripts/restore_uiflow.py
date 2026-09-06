"""Restore startup from this device's own backup. Credentials are not erased."""
import argparse
from pathlib import Path
from device_console import Device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    args = parser.parse_args()
    d = Device(args.port)
    try:
        identity = d.execute("import machine, ubinascii; print(ubinascii.hexlify(machine.unique_id()).decode())").strip()
        if not identity or any(c not in '0123456789abcdef' for c in identity):
            raise RuntimeError('Cannot identify device safely')
        private = Path(__file__).resolve().parents[1] / '.private/devices' / identity
        files = {name: (private / ('original-' + name)).read_bytes() for name in ('main.py', 'boot.py')}
        option = int((private / 'original-boot-option.txt').read_text())
        if not 0 <= option <= 255:
            raise ValueError('Invalid boot option')
        for name, data in files.items():
            d.put(data, '/flash/' + name)
        d.execute("import esp32; n=esp32.NVS('uiflow'); n.set_u8('boot_option'," + str(option) + "); n.commit()")
        d.port.write(b'\x02\x04')
    finally:
        d.close()
    print('Original UiFlow2 startup restored; Pocket data remains on flash.')


if __name__ == '__main__':
    main()

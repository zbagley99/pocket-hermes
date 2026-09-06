"""Configure a clone once, then deploy/check/restore using ignored local settings."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
from configuration import validate


def write_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Refusing a symlinked private configuration path')
    temp = path.with_suffix('.tmp')
    with temp.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
    temp.chmod(0o600)
    os.replace(temp, path)


def setup(args):
    from serial.tools.list_ports import comports
    source = args.config.expanduser()
    config = json.loads(source.read_text())
    validate(config, wifi=False)
    config.setdefault('persist_history', False)
    if args.wifi or not (config.get('ssid') or config.get('networks')):
        ssid = input('Wi-Fi network name: ')
        password = getpass.getpass('Wi-Fi password (empty for open network): ')
        from wifi_setup import provision
        from urllib.parse import urlencode
        config = provision(config, urlencode({'token': 'local', 'ssid': ssid, 'password': password}).encode(), 'local')
    validate(config)
    port = args.port
    if not port:
        ports = [p.device for p in comports() if p.vid is not None]
        if len(ports) == 1:
            port = ports[0]
        else:
            for index, candidate in enumerate(ports, 1):
                print(str(index) + ': ' + candidate)
            port = input('USB serial port path (or COM port): ').strip()
    if not port:
        raise ValueError('A USB serial port is required')
    private = ROOT / '.private'
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    target = private / 'provisioning/device.json'
    write_private(target, config)
    write_private(private / 'local.json', {'version': 1, 'port': port, 'config': str(target.relative_to(ROOT))})
    print('Local setup saved privately. Run: python scripts/local.py check')
    print('Then deploy: python scripts/local.py deploy')


def load_settings():
    try:
        settings = json.loads((ROOT / '.private/local.json').read_text())
    except FileNotFoundError:
        raise SystemExit('Run scripts/local.py setup --config PATH_TO_PRIVATE_DEVICE_JSON first.')
    if settings.get('version') != 1 or not isinstance(settings.get('port'), str) or not settings['port']:
        raise ValueError('Invalid local settings; rerun setup')
    config = (ROOT / settings['config']).resolve()
    if not config.is_relative_to((ROOT / '.private').resolve()):
        raise ValueError('Local config must remain inside .private')
    validate(json.loads(config.read_text()))
    return settings, config


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('setup', help='Import private bridge-generated device.json and choose USB port')
    create.add_argument('--config', type=Path, required=True)
    create.add_argument('--port')
    create.add_argument('--wifi', action='store_true', help='Prompt for new Wi-Fi credentials')
    commands.add_parser('check', help='Validate local configuration and check USB port presence')
    commands.add_parser('smoke', help='Test firmware over USB with a temporary local HTTPS endpoint')
    commands.add_parser('smoke-inbox', help='Test new inbox code and display in device RAM, then reset')
    deploy = commands.add_parser('deploy')
    deploy.add_argument('--replace-config', action='store_true')
    deploy.add_argument('--port')
    restore = commands.add_parser('restore')
    restore.add_argument('--port')
    args = parser.parse_args()
    if args.command == 'setup':
        setup(args)
        return
    settings, config = load_settings()
    if args.command == 'check':
        from serial.tools.list_ports import comports
        if settings['port'] not in [p.device for p in comports()]:
            raise SystemExit('Config valid; configured USB port is absent. Connect the Stick or rerun setup with --port.')
        print('Private configuration valid; configured USB port is present.')
        return
    if args.command == 'smoke':
        subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_device.py')], check=True)
        return
    if args.command == 'smoke-inbox':
        subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_inbox.py')], check=True)
        return
    port = args.port or settings['port']
    script = 'deploy.py' if args.command == 'deploy' else 'restore_uiflow.py'
    command = [sys.executable, str(ROOT / 'scripts' / script), '--port', port]
    if args.command == 'deploy':
        command.extend(['--config', str(config)])
        if args.replace_config:
            command.append('--replace-config')
    subprocess.run(command, check=True)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
    except (ValueError, OSError) as exc:
        raise SystemExit('Local setup failed (' + type(exc).__name__ + '). Check private files and arguments; secrets are not printed.')

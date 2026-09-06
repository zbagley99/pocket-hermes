"""Check the explicit release manifest; report paths and rule names, never secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'personal home path': re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'private LAN address': re.compile(rb'\b(?:192\.168\.(?!4\.1\b)\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'),
    'service credential': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})'),
}
FORBIDDEN = {'.private', '.venv', '.git', '__pycache__', 'dist', 'build'}
SECRET_SUFFIXES = {'.pem', '.key', '.der', '.sqlite3', '.db', '.wav', '.aiff', '.pyc', '.log'}


def release_paths(root=ROOT):
    root = root.resolve()
    names = json.loads((root / 'release-manifest.json').read_text())
    if not isinstance(names, list) or len(names) != len(set(names)):
        raise ValueError('Invalid release manifest')
    paths = []
    for name in names:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or any(p in FORBIDDEN for p in path.parts) or path.suffix in SECRET_SUFFIXES or path.name in ('config.json', 'device.json', '.env'):
            raise ValueError('Forbidden release path')
        target = root / path
        if not target.is_file() or any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('Missing or symlinked release file: ' + name)
        paths.append(path)
    return paths


def private_values(root):
    values = set()
    sensitive = {'ssid', 'wifi_password', 'password', 'device_key', 'hermes_key', 'host', 'tls_name', 'server_sha256'}
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in sensitive and isinstance(item, str) and len(item) >= 4:
                    values.add(item.encode())
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for path in (root / '.private').rglob('*.json'):
        if path.is_symlink():
            continue
        try:
            walk(json.loads(path.read_text()))
        except (ValueError, UnicodeError):
            pass
    return values


def check(root=ROOT):
    paths = release_paths(root)
    failures = []
    secrets = private_values(root)
    for path in paths:
        data = (root / path).read_bytes()
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append((str(path), label))
        if any(value in data for value in secrets):
            failures.append((str(path), 'matches private configuration value'))
    if (root / '.git').exists():
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
        allowed = {str(path) for path in paths}
        failures.extend((name, 'tracked outside release manifest') for name in tracked if name and name not in allowed)
    return paths, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, help='Create a new source ZIP after checks pass')
    args = parser.parse_args()
    paths, failures = check()
    if failures:
        for name, rule in failures:
            print(name + ': ' + rule)
        raise SystemExit(1)
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.export, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                # Fixed metadata avoids exporting local usernames, permissions or timestamps.
                info = zipfile.ZipInfo('pocket-hermes/' + path.as_posix(), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, (ROOT / path).read_bytes())
    print('Release checks passed for ' + str(len(paths)) + ' files. Heuristic checks are not a guarantee against all PII.')


if __name__ == '__main__':
    main()

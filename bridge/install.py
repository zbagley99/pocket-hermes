"""Create private bridge credentials and TLS material; never edit Hermes or start services."""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='NEW private runtime directory')
    parser.add_argument('--host', required=True, help='Bridge DNS name or IPv4 address reachable by Stick')
    parser.add_argument('--bind', default='127.0.0.1', help='Explicit local interface to listen on')
    parser.add_argument('--port', type=int, default=8643)
    parser.add_argument('--hermes-url', default='http://127.0.0.1:8642')
    parser.add_argument('--profile-config', type=Path)
    parser.add_argument('--message-queue', action='store_true', help='Keep a durable queue and unread inbox on the bridge')
    parser.add_argument('--queue-capacity', type=int, default=32, help='Maximum pending messages, 1-100')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', args.host):
        parser.error('Use a DNS name or IPv4 address for --host')
    ipaddress.ip_address(args.bind)
    from server import validate_config
    config = validate_config(dict(bind=args.bind, port=args.port, hermes_url=args.hermes_url,
        hermes_key=getpass.getpass('Existing Hermes API key (hidden): '), device_key=secrets.token_urlsafe(32),
        retention_days=7, max_turns=10000, whisper_model='tiny.en', language='en',
        message_queue=args.message_queue, queue_capacity=args.queue_capacity))
    if args.profile_config:
        config['profile_config'] = str(args.profile_config.expanduser().resolve(strict=True))
    os.umask(0o077)
    root = args.root.expanduser().absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    tls = root / 'tls'
    tls.mkdir(mode=0o700)
    try:
        ipaddress.ip_address(args.host)
        san = 'IP:' + args.host
    except ValueError:
        san = 'DNS:' + args.host
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes',
        '-keyout', str(tls / 'server.key'), '-out', str(tls / 'server.pem'), '-days', '365',
        '-subj', '/CN=' + args.host, '-addext', 'subjectAltName=' + san,
        '-addext', 'basicConstraints=critical,CA:FALSE'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    der = ssl.PEM_cert_to_DER_cert((tls / 'server.pem').read_text())
    (root / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    device = dict(host=args.host, tls_name=args.host, port=args.port,
        device_key=config['device_key'], server_sha256=hashlib.sha256(der).hexdigest(),
        ssid='', wifi_password='', persist_history=False)
    (root / 'device.json').write_text(json.dumps(device, indent=2) + '\n')
    print('Created private runtime files. Add Wi-Fi settings to device.json; transfer it securely to your provisioning computer.')


if __name__ == '__main__':
    main()

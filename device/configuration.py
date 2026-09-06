"""Validation shared by USB provisioning and MicroPython startup."""

def validate(config, wifi=True):
    if not isinstance(config, dict):
        raise ValueError('Configuration must be an object')
    for key in ('host', 'tls_name'):
        value = config.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 253 or not all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in value):
            raise ValueError('Invalid ' + key)
    port = config.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    pin = config.get('server_sha256', '')
    if not isinstance(pin, str) or len(pin) != 64 or not all(c in '0123456789abcdef' for c in pin):
        raise ValueError('Provision a lowercase SHA-256 certificate pin over USB')
    key = config.get('device_key', '')
    if not isinstance(key, str) or not 32 <= len(key) <= 256 or not all(33 <= ord(c) <= 126 for c in key) or key.startswith('REPLACE_'):
        raise ValueError('Provision a unique 32-256 character device key')
    if type(config.get('persist_history', False)) is not bool:
        raise ValueError('persist_history must be boolean')
    if wifi:
        saved = config.get('networks', [])
        if not isinstance(saved, list) or len(saved) > 8:
            raise ValueError('Expected at most eight saved networks')
        entries = saved + ([{'ssid': config['ssid'], 'password': config.get('wifi_password', '')}] if config.get('ssid') else [])
        if not entries:
            raise ValueError('Configure at least one Wi-Fi network')
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Invalid network')
            ssid, password = entry.get('ssid'), entry.get('password', '')
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32:
                raise ValueError('SSID must be 1-32 bytes')
            if not isinstance(password, str) or (password and not (8 <= len(password.encode()) <= 63 or (len(password) == 64 and all(c in '0123456789abcdefABCDEF' for c in password)))):
                raise ValueError('Invalid Wi-Fi password')
    return config

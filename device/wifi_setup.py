"""Physical-access-only Wi-Fi provisioning; preserves bridge credentials."""
import json
import os

CONFIG = '/flash/pocket-config.json'


class SetupUnavailable(Exception):
    pass


def start_secure_ap(ap, ssid, password, authmode):
    ap.active(False)
    try:
        ap.config(essid=ssid, password=password, authmode=authmode)
        ap.active(True)
    except OSError:
        ap.active(False)
        raise SetupUnavailable('Firmware requires USB Wi-Fi setup')


def networks(config):
    saved = config.get('networks', [])[:]
    if config.get('ssid') and not any(n['ssid'] == config['ssid'] for n in saved):
        saved.append({'ssid': config['ssid'], 'password': config.get('wifi_password', '')})
    return saved


def decode(value):
    value = value.replace(b'+', b' ')
    out = bytearray()
    i = 0
    while i < len(value):
        if value[i] == 37:
            if len(value[i+1:i+3]) != 2:
                raise ValueError('Invalid percent escape')
            out.append(int(value[i+1:i+3], 16))
            i += 3
        else:
            out.append(value[i])
            i += 1
    return out.decode('utf-8')


def provision(config, body, token):
    fields = dict((decode(k), decode(v)) for k, v in (p.split(b'=', 1) for p in body.split(b'&')))
    if fields.get('token') != token:
        raise ValueError('Invalid setup token')
    ssid, password = fields.get('ssid', ''), fields.get('password', '')
    if not 1 <= len(ssid.encode()) <= 32:
        raise ValueError('SSID must be 1-32 bytes')
    if password and not (8 <= len(password.encode()) <= 63 or (len(password) == 64 and all(c in '0123456789abcdefABCDEF' for c in password))):
        raise ValueError('Password must be 8-63 bytes or 64 hex digits')
    result = dict(config)
    result['networks'] = ([{'ssid': ssid, 'password': password}] + [n for n in networks(config) if n['ssid'] != ssid])[:8]
    return result


def run_setup(view, config):
    import network
    import socket
    import time
    import ubinascii
    import M5
    import machine
    ap = network.WLAN(network.AP_IF)
    suffix = ubinascii.hexlify(os.urandom(2)).decode().upper()
    password = ubinascii.hexlify(os.urandom(6)).decode()
    token = ubinascii.hexlify(os.urandom(16)).decode()
    previous = (view.lines[:], view.roles[:], view.request_starts[:], view.base, view.top, view.follow)
    server = None
    try:
        start_secure_ap(ap, 'Hermes-' + suffix, password, network.AUTH_WPA2_PSK)
        address = ap.ifconfig()[0]
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((address, 80))
        server.listen(1)
        server.settimeout(.1)
        view.append('Wi-Fi setup\nJoin: Hermes-' + suffix + '\nKey: ' + password + '\nhttp://' + address + '\nTap B to cancel.', 'system')
        view.bottom()
        view.status = 'Setup / 5 minute timeout'
        view.draw()
        page = ('<!doctype html><meta name="viewport" content="width=device-width"><title>Pocket Hermes Wi-Fi</title>'
                '<style>body{background:#0b1118;color:#dfe7ef;font:18px system-ui;max-width:440px;margin:40px auto;padding:20px}input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 20px}button{background:#65d9c0;border:0;border-radius:6px}</style>'
                '<h1>Pocket Hermes</h1><p>Add a 2.4 GHz Wi-Fi network or phone hotspot. Your home network stays saved.</p>'
                '<form method="post" action="/save"><input type="hidden" name="token" value="' + token + '">'
                '<label>Network name (SSID)<input name="ssid" required maxlength="32"></label>'
                '<label>Password<input name="password" type="password" maxlength="64"></label>'
                '<button>Save network and restart</button></form><p>Remote Hermes access requires a separate route to your home server.</p>')
        deadline = time.ticks_add(time.ticks_ms(), 300000)
        # Wait for the entering hold to be released before accepting cancel.
        while M5.BtnB.isPressed():
            M5.update()
            time.sleep_ms(20)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            M5.update()
            if M5.BtnB.wasPressed():
                break
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            saved = False
            try:
                conn.settimeout(2)
                connection_deadline = time.ticks_add(time.ticks_ms(), 5000)
                data = b''
                while b'\r\n\r\n' not in data and len(data) < 4096:
                    if time.ticks_diff(connection_deadline, time.ticks_ms()) <= 0:
                        raise ValueError('Setup request timed out')
                    part = conn.recv(512)
                    if not part:
                        break
                    data += part
                header, body = data.split(b'\r\n\r\n', 1)
                request = header.split(b'\r\n')[0]
                response, status = page, '200 OK'
                if request.startswith(b'POST /save '):
                    length = 0
                    for line in header.split(b'\r\n')[1:]:
                        if line.lower().startswith(b'content-length:'):
                            length = int(line.split(b':', 1)[1])
                    if not 0 < length <= 2048:
                        raise ValueError('Invalid form size')
                    while len(body) < length:
                        if time.ticks_diff(connection_deadline, time.ticks_ms()) <= 0:
                            raise ValueError('Setup request timed out')
                        part = conn.recv(length-len(body))
                        if not part:
                            raise ValueError('Incomplete form')
                        body += part
                    updated = provision(config, body[:length], token)
                    with open(CONFIG + '.tmp', 'w') as f:
                        json.dump(updated, f)
                    os.rename(CONFIG + '.tmp', CONFIG)
                    response = '<h1>Network saved</h1><p>The Stick is restarting. Reconnect your phone to its usual network.</p>'
                    saved = True
                elif not request.startswith(b'GET / '):
                    status, response = '404 Not Found', 'Not found'
                payload = response.encode()
                conn.write(('HTTP/1.1 ' + status + '\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: ' + str(len(payload)) + '\r\nConnection: close\r\n\r\n').encode())
                conn.write(payload)
            except (ValueError, OSError):
                try:
                    conn.write(b'HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\nInvalid setup form. Go back and check the network name and password.')
                except OSError:
                    pass
            finally:
                conn.close()
            if saved:
                time.sleep_ms(500)
                machine.reset()
    finally:
        if server:
            server.close()
        ap.active(False)
        view.lines, view.roles, view.request_starts, view.base, view.top, view.follow = previous
    view.status = 'Setup closed'
    view.draw()

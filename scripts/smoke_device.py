"""Test firmware over USB using a temporary local HTTPS endpoint and synthetic audio."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'bridge')]
from device_console import Device
from server import validate_wav
from local import load_settings

DEVICE_CHECKS = r'''
import json,os,hashlib,ubinascii,struct,M5
from pocket_net import PocketClient,HTTPError
r={};client=PocketClient(c)
r['health']=client.request('GET','/health')['status']=='ready'
bad=dict(c);bad['server_sha256']='0'*64
try:
 PocketClient(bad).request('GET','/health');r['bad_pin_rejected']=False
except OSError as error:
 r['bad_pin_rejected']='pin mismatch' in str(error)
bad=dict(c);bad['device_key']='incorrect-key'*4
try:
 PocketClient(bad).request('GET','/health');r['bad_key_rejected']=False
except HTTPError as e:
 r['bad_key_rejected']=e.status==401
size=16000
wav=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',size+36,b'WAVE',b'fmt ',16,1,1,16000,32000,2,16,b'data',size)+bytes(size)
ident=ubinascii.hexlify(os.urandom(16)).decode()
r['audio_upload']=client.request('POST','/turn/'+ident,wav,'audio/wav')['status']=='done'
stage='poll';r['poll']=client.request('GET','/turn/'+ident)['text']=='Pocket hardware checks passed.'
stage='duplicate';r['duplicate']=client.request('POST','/turn/'+ident,wav,'audio/wav')['id']==ident
r['history_disabled']=not json.load(open('/flash/pocket-config.json')).get('persist_history',False)
r['no_history_file']='pocket-history.json' not in os.listdir('/flash')
r['hashes']={}
for name in ('configuration.py','ascii_text.py','text_view.py','pocket_net.py','net_worker.py','controls.py','wifi_setup.py','inbox.py','pocket.py'):
 r['hashes'][name]=ubinascii.hexlify(hashlib.sha256(open('/flash/libs/'+name,'rb').read()).digest()).decode()
r['hashes']['main.py']=ubinascii.hexlify(hashlib.sha256(open('/flash/main.py','rb').read()).digest()).decode()
from text_view import TextView
M5.Lcd.setRotation(1);v=TextView(M5.Lcd);v.append('USB hardware checks passed. Restarting the app.','system');v.status='Test complete';v.draw();r['display_draw']=True
print(json.dumps(r))
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    os.umask(0o077)
    settings, config_path = load_settings()
    config = json.loads(config_path.read_text())
    # Select the computer interface with a route to the configured device LAN.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((config['host'], config['port']))
        host = route.getsockname()[0]
    key = secrets.token_urlsafe(32)
    requests, turns = [], {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def handle_request(self):
            self.connection.settimeout(10)
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + key):
                self.send_response(401)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            requests.append(self.path)
            if self.path == '/health':
                result = {'status': 'ready', 'speech': 'test', 'profile': 'isolated-test'}
            elif self.path.startswith('/turn/'):
                ident = self.path.rsplit('/', 1)[1]
                if self.command == 'POST':
                    length = int(self.headers['Content-Length'])
                    if not 0 < length <= 960044:
                        self.send_error(413)
                        return
                    validate_wav(self.rfile.read(length))
                    turns.setdefault(ident, {'id': ident, 'status': 'done',
                        'transcript': 'Synthetic audio test', 'text': 'Pocket hardware checks passed.'})
                result = turns[ident]
            else:
                self.send_error(404)
                return
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = handle_request

    with tempfile.TemporaryDirectory(prefix='pocket-hardware-tls-') as temporary:
        temp = Path(temporary)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(temp / 'key.pem'), '-out', str(temp / 'cert.pem'),
            '-days', '1', '-subj', '/CN=pocket-hardware-test'], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        der = ssl.PEM_cert_to_DER_cert((temp / 'cert.pem').read_text())
        server = ThreadingHTTPServer((host, 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(temp / 'cert.pem', temp / 'key.pem')
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        test_config = dict(config, host=host, port=server.server_address[1],
            tls_name='pocket-hardware-test', device_key=key,
            server_sha256=hashlib.sha256(der).hexdigest())
        device = None
        try:
            device = Device(settings['port'])
            code = 'c=' + repr(test_config) + '\n' + DEVICE_CHECKS
            result = json.loads(device.execute(code, timeout=55))
            result['uploaded_files_match'] = all(
                digest == hashlib.sha256((ROOT / 'device' / name).read_bytes()).hexdigest()
                for name, digest in result.pop('hashes').items())
            result['server_received_one_turn'] = len(turns) == 1
            result['bad_pin_sent_no_http'] = requests.count('/health') == 1
            artifacts = ROOT / '.private/artifacts'
            artifacts.mkdir(mode=0o700, exist_ok=True)
            (artifacts / 'hardware-validation.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, sort_keys=True))
            if not all(result.values()):
                raise RuntimeError('One or more hardware checks failed')
        except RuntimeError:
            if device is not None and getattr(device, 'last_error', None):
                artifacts = ROOT / '.private/artifacts'
                artifacts.mkdir(mode=0o700, exist_ok=True)
                (artifacts / 'hardware-error.log').write_bytes(device.last_error)
            raise
        finally:
            if device is not None:
                device.port.write(b'\x02\x04')
                device.close()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

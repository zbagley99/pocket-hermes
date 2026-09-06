"""HTTPS with mandatory SHA-256 certificate pinning before sending credentials.

UiFlow2 2.4.8 rejects valid certificates with a certificate-date error. Pinning
the exact server certificate provisioned over SSH avoids its broken date check.
There is no trust-on-first-use or unverified-request fallback.
"""
import gc
import hashlib
import json
import socket
import ssl
import ubinascii
from configuration import validate


class HTTPError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__("HTTP " + str(status))


class PocketClient:
    def __init__(self, config):
        self.config = validate(config, wifi=False)
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls.verify_mode = ssl.CERT_NONE
        if len(config.get('server_sha256', '')) != 64:
            raise ValueError('Server certificate pin must be provisioned over USB')

    def request(self, method, path, body=b'', content_type='application/json'):
        gc.collect()
        c = self.config
        raw = socket.socket()
        raw.settimeout(12)
        stream = None
        try:
            raw.connect(socket.getaddrinfo(c['host'], c['port'])[0][-1])
            stream = self.tls.wrap_socket(raw, server_hostname=c['tls_name'])
            peer = stream.getpeercert(True)
            digest = ubinascii.hexlify(hashlib.sha256(peer).digest()).decode()
            if digest != c['server_sha256']:
                raise OSError('Server certificate pin mismatch')
            header = (method + ' ' + path + ' HTTP/1.1\r\nHost: ' + c['tls_name'] +
                      '\r\nAuthorization: Bearer ' + c['device_key'] +
                      '\r\nContent-Type: ' + content_type +
                      '\r\nContent-Length: ' + str(len(body)) + '\r\nConnection: close\r\n\r\n')
            self.write_all(stream, header.encode())
            data = memoryview(body)
            for offset in range(0, len(data), 4096):
                self.write_all(stream, data[offset:offset + 4096])
            status_line = self.read_line(stream)
            status = int(status_line.split()[1])
            length = None
            total_headers = len(status_line)
            while True:
                line = self.read_line(stream)
                total_headers += len(line)
                if total_headers > 8192 or not line:
                    raise OSError('Invalid HTTP headers')
                if line == b'\r\n':
                    break
                if line.lower().startswith(b'content-length:'):
                    length = int(line.split(b':', 1)[1].strip())
            if status >= 400:
                raise HTTPError(status)
            if length is None or length < 0 or length > 65536:
                raise OSError('Response is too large for the display buffer')
            result = bytearray(length)
            pos = 0
            while pos < length:
                chunk = stream.read(min(4096, length - pos))
                if not chunk:
                    raise OSError('Incomplete HTTP response')
                result[pos:pos + len(chunk)] = chunk
                pos += len(chunk)
            return json.loads(result)
        finally:
            if stream is not None:
                stream.close()
            else:
                raw.close()

    @staticmethod
    def read_line(stream):
        line = bytearray()
        while len(line) < 1024:
            char = stream.read(1)
            if not char:
                raise OSError('Incomplete HTTP headers')
            line.extend(char)
            if char == b'\n':
                return bytes(line)
        raise OSError('HTTP header line too large')

    @staticmethod
    def write_all(stream, data):
        pos = 0
        while pos < len(data):
            n = stream.write(data[pos:])
            if not n:
                raise OSError('Connection closed while sending')
            pos += n

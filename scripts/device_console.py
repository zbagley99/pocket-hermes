"""Small raw-REPL helper; never echoes uploaded code or credential files."""
import time
import serial
from preview import read_until


class Device:
    def __init__(self, path):
        self.port = serial.Serial(path, 115200, timeout=.1)
        self.port.write(b"\x02\x03\x03")
        time.sleep(.3)
        self.port.reset_input_buffer()
        self.port.write(b"\x01")
        read_until(self.port, b"raw REPL; CTRL-B to exit\r\n>")

    def execute(self, code, timeout=30):
        if isinstance(code, str):
            code = code.encode()
        for offset in range(0, len(code), 128):
            self.port.write(code[offset:offset+128])
            time.sleep(.005)
        self.port.write(b"\x04")
        output = read_until(self.port, b"\x04>", timeout)
        parts = output.split(b"\x04")
        if len(parts) > 1 and parts[1].strip():
            self.last_error = parts[1]
            raise RuntimeError("Device execution failed; inspect locally (console details suppressed)")
        return parts[0].removeprefix(b"OK").decode(errors="replace")

    def put(self, source, target):
        import binascii
        self.execute("_f=open(" + repr(target) + ",'wb')")
        try:
            for offset in range(0, len(source), 512):
                chunk = binascii.hexlify(source[offset:offset+512]).decode()
                self.execute("import ubinascii; _f.write(ubinascii.unhexlify(" + repr(chunk) + "))")
        finally:
            self.execute("_f.close()")

    def close(self):
        self.port.close()

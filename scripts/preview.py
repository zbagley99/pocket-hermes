"""Run the display preview in RAM without flashing or editing device files."""
import argparse
from pathlib import Path
import time
import serial


def read_until(port, marker, timeout=5):
    output = bytearray()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        output.extend(port.read(port.in_waiting or 1))
        if marker in output:
            return bytes(output)
    raise RuntimeError("Stick console did not reach expected state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    code = ((root / "device/ascii_text.py").read_bytes() + b"\n" +
            (root / "device/text_view.py").read_bytes().replace(b'from ascii_text import display_ascii\n', b'') +
            b"\n" + (root / "device/preview.py").read_bytes())
    with serial.Serial(args.port, 115200, timeout=0.1) as port:
        port.write(b"\x02\x03\x03")
        time.sleep(0.3)
        port.reset_input_buffer()
        port.write(b"\x01")
        read_until(port, b"raw REPL; CTRL-B to exit\r\n>")
        for offset in range(0, len(code), 128):
            port.write(code[offset:offset + 128])
            time.sleep(0.01)
        port.write(b"\x04")
        output = read_until(port, b"PREVIEW_READY", timeout=10)
        time.sleep(0.3)
        output += port.read(port.in_waiting)
        print('Preview loaded.')
    print("Preview running in RAM. A/B scroll; reset returns to UiFlow2.")


if __name__ == "__main__":
    main()

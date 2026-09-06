"""Validate inbox code and drawing in RAM on a Stick; reset the installed app afterward."""
import argparse
import json
import os
from pathlib import Path

from device_console import Device
from local import load_settings

ROOT = Path(__file__).resolve().parents[1]
CHECKS = '''
import M5,json
M5.begin();M5.Speaker.end();M5.Lcd.setRotation(1)
v=TextView(M5.Lcd);v.append('Current chat');i=Inbox(v)
m=dict(id='a'*32,status='done',unread=True,preview='Offline reply test',transcript='Synthetic question',text='The Pi kept this reply while the Stick was off.\\n'*12,conversation='b'*32)
i.open();i.job=None
i.complete('list',dict(items=[m],unread=1,next_before=None),None);v.draw()
assert v.unread==1
i.handle('record');assert i.job==('detail','GET','/turn/'+m['id'])
i.job=None;i.complete('detail',m,None);v.draw()
assert i.job is None and v.top==0
i.handle('down');assert v.top==1;v.draw()
i.handle('record');v.draw()
assert i.handle('record')==('resume',m['id'])
i.handle('down');i.handle('record')
assert i.job==('read','POST','/inbox/'+m['id']+'/read')
i.close();assert v.lines==['Current chat'];v.draw()
v.close()
print(json.dumps(dict(micropython_compile=True,inbox_draw=True,unread_notification=True,scroll=True,explicit_resume=True,explicit_read=True,restore_chat=True)))
'''


def device_code():
    code = ''
    for name in ('pocket.py', 'inbox.py', 'text_view.py'):
        source = (ROOT / 'device' / name).read_text()
        code += 'compile(' + repr(source) + ',' + repr(name) + ',"exec")\n'
    code += (ROOT / 'device/ascii_text.py').read_text() + '\n'
    code += (ROOT / 'device/text_view.py').read_text().replace('from ascii_text import display_ascii\n', '') + '\n'
    code += (ROOT / 'device/inbox.py').read_text() + '\n'
    return code + CHECKS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port')
    args = parser.parse_args()
    os.umask(0o077)
    port = args.port or load_settings()[0]['port']
    device = Device(port)
    try:
        result = json.loads(device.execute(device_code(), timeout=30).strip())
        artifacts = ROOT / '.private/artifacts'
        artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
        (artifacts / 'inbox-hardware-validation.json').write_text(json.dumps(result, indent=2) + '\n')
        if not all(result.values()):
            raise RuntimeError('Inbox hardware checks failed')
        print(json.dumps(result, sort_keys=True))
    except RuntimeError:
        if getattr(device, 'last_error', None):
            artifacts = ROOT / '.private/artifacts'
            artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
            (artifacts / 'inbox-hardware-error.log').write_bytes(device.last_error)
        raise
    finally:
        device.port.write(b'\x02\x04')
        device.close()


if __name__ == '__main__':
    main()

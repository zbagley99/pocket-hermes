"""Push-to-talk, text-only Hermes terminal for M5StickS3 / UiFlow2.

Hold A: record (max 30 s); release: send.
Tap A/B: down/up. Double A/B: previous request/bottom.
Hold B: Wi-Fi setup. Hold A+B: new chat.
"""
import gc
import json
import os
import struct
import time
import ubinascii
import network
import M5
from text_view import TextView
from pocket_net import PocketClient, HTTPError
from net_worker import NetWorker
from controls import Controls
from configuration import validate
from wifi_setup import networks, run_setup, SetupUnavailable
from inbox import Inbox

PENDING = '/flash/pocket-pending.json'
LAST_REPLY = '/flash/pocket-last.json'
HISTORY = '/flash/pocket-history.json'
NEW_CHAT = '/flash/pocket-new-chat.json'
RATE = 16000
MAX_BYTES = RATE * 2 * 30
CHUNK = 1600


def save_json(path, value):
    with open(path + '.tmp', 'w') as f:
        json.dump(value, f)
    os.rename(path + '.tmp', path)


def load_json(path, fallback=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return fallback


def run():
    M5.begin()
    M5.Speaker.end()
    M5.Lcd.setRotation(1)
    M5.Lcd.setBrightness(90)
    M5.Lcd.setTextSize(1)
    M5.Lcd.setFont(M5.Lcd.FONTS.DejaVu12)
    view = TextView(M5.Lcd)
    config = load_json('/flash/pocket-config.json')
    view.append('Hold A to talk.\nDouble A: previous request\nDouble B: bottom\nHold B: Wi-Fi setup\nHold A+B: new chat', 'system')
    persist_history = bool(config and config.get('persist_history', False))
    if not persist_history:
        for path in (HISTORY, LAST_REPLY):
            for candidate in (path, path + '.tmp'):
                try:
                    os.remove(candidate)
                except OSError:
                    pass
    history = load_json(HISTORY, []) if persist_history else []
    for turn in history:
        view.add_request(turn['request'])
        view.append(turn['text'])
    if not history and persist_history:
        last = load_json(LAST_REPLY)
        if last:
            view.append(last['text'])
    if not config:
        view.status = 'USB setup required'
        view.draw()
        return
    try:
        validate(config)
    except ValueError:
        view.status = 'Invalid config / USB setup'
        view.draw()
        return
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    worker = NetWorker(PocketClient(config))
    inbox = Inbox(view)
    queue_enabled = False
    first_health = True
    ui_blocked = False
    next_inbox = 0
    controls = Controls()
    saved_networks = networks(config)
    network_index = 0
    new_chat = load_json(NEW_CHAT)
    record_blocked = False
    pending = load_json(PENDING)
    recording = None
    used = 0
    next_poll = next_connect = 0
    connection_checked = False
    next_health = 0
    next_battery = 0
    mic_ready = False
    last_header = 0
    transcript_seen = ''
    reply_seen = ''
    phase = 'Connecting Wi-Fi'
    view.status = phase
    view.draw()
    print('POCKET_BOOT')

    def show(status, text=None):
        view.status = status
        if text:
            view.append(text, 'system')
        view.draw()

    while True:
        M5.update()
        now = time.ticks_ms()
        if time.ticks_diff(now, next_battery) >= 0:
            try:
                level = int(M5.Power.getBatteryLevel())
                view.battery = max(0, min(100, level)) if level >= 0 else None
            except Exception:
                view.battery = None
            next_battery = time.ticks_add(now, 30000)
        event = controls.update(M5.BtnA, M5.BtnB, now, time.ticks_diff)
        if ui_blocked:
            event = None
            if not M5.BtnA.isPressed() and not M5.BtnB.isPressed():
                ui_blocked = False
        if not M5.BtnA.isPressed():
            record_blocked = False
        if inbox.active:
            if event in ('record', 'wifi', 'new_chat'):
                ui_blocked = True
            action = inbox.handle(event)
            event = None
            if action:
                kind, ident = action
                new_chat = {'id': ubinascii.hexlify(os.urandom(16)).decode(), 'kind': kind}
                if ident:
                    new_chat['turn_id'] = ident
                save_json(NEW_CHAT, new_chat)
                inbox.close()
                show('Continuing chat' if kind == 'resume' else 'Starting new chat')
        elif queue_enabled and event == 'bottom' and recording is None and not pending and not new_chat:
            inbox.open(view.unread > 0)
            event = None
        if event in ('chord', 'new_chat'):
            record_blocked = True
            if recording is not None and not pending:
                M5.Mic.end()
                recording = None
                mic_ready = False
        if event == 'new_chat':
            if pending:
                show('Finish current request first')
            else:
                if not new_chat:
                    new_chat = {'id': ubinascii.hexlify(os.urandom(16)).decode()}
                    save_json(NEW_CHAT, new_chat)
                show('Starting new chat')
        elif event == 'wifi' and recording is None:
            if worker.busy:
                show('Wait for request / then setup')
            else:
                try:
                    run_setup(view, config)
                except SetupUnavailable:
                    show('USB Wi-Fi setup required', 'This firmware needs USB to change Wi-Fi. Run local.py setup --wifi on your computer, then deploy --replace-config.')
                except Exception:
                    show('Wi-Fi setup failed / retry')
                connection_checked = False
                next_connect = 0
        elif event == 'previous':
            view.previous_request()
        elif event == 'bottom':
            view.bottom()
        elif event == 'down':
            view.scroll(1)
        elif event == 'up':
            view.scroll(-1)
        view.connected = wlan.isconnected() and connection_checked
        view.draw()
        completed = worker.take()
        if completed:
            kind, result, error = completed
            if kind == 'health':
                next_health = time.ticks_add(now, 15000)
                if error:
                    connection_checked = False
                    show('Server unavailable / retrying')
                    next_poll = time.ticks_add(now, 3000)
                else:
                    connection_checked = True
                    queue_enabled = result.get('message_queue', False)
                    previous_unread = view.unread
                    view.unread = result.get('unread', 0) if queue_enabled else 0
                    if queue_enabled:
                        if first_health:
                            view.append('Queue enabled. Double B: inbox. Wait for Saved on Pi before powering off.', 'system')
                        if first_health and view.unread and not pending and not new_chat:
                            inbox.open(True)
                        elif not inbox.active and recording is None and not pending and not new_chat:
                            if view.unread:
                                show('%d new replies / double B' % view.unread)
                                view.hint = 'inbox'
                            elif result.get('pending', 0):
                                show('Saved on Pi / %d waiting' % result['pending'])
                                view.hint = 'power off OK'
                            else:
                                view.hint = None
                                show('Ready / double B: inbox')
                        if view.unread > previous_unread:
                            print('INBOX_UNREAD', view.unread)
                    elif not inbox.active:
                        show('Ready / hold A to talk')
                    first_health = False
                    print('POCKET_CONNECTED', result.get('profile'), result.get('speech'))
            elif kind.startswith('inbox:'):
                _, generation, operation = kind.split(':', 2)
                if inbox.active and int(generation) == inbox.generation:
                    inbox.complete(operation, result, error)
                next_inbox = time.ticks_add(now, 2000)
            elif kind == 'new_chat':
                if error:
                    if isinstance(error, HTTPError) and error.status in (400, 404, 410, 507):
                        new_chat = None
                        os.remove(NEW_CHAT)
                        show('Chat unavailable', 'The chat change was rejected. The message may have expired or the Pi needs maintenance.')
                        next_health = 0
                    else:
                        show('Chat change / retrying')
                        next_poll = time.ticks_add(now, 3000)
                else:
                    resumed = new_chat.get('kind') == 'resume'
                    new_chat = None
                    os.remove(NEW_CHAT)
                    history = []
                    if persist_history:
                        save_json(HISTORY, history)
                        save_json(LAST_REPLY, {'text': ''})
                    view.finish_reply()
                    view.delegation = 'idle'
                    view.lines, view.roles, view.request_starts = [], [], []
                    view.top = view.base = 0
                    view.follow = True
                    view.hint = None
                    show('Chat resumed / hold A' if resumed else 'New chat / hold A',
                         'Conversation resumed.' if resumed else 'Fresh conversation ready.')
                    next_health = 0
            elif kind == 'send':
                recording = None
                gc.collect()
                if not error and result.get('durable'):
                    os.remove(PENDING)
                    pending = None
                    show('Saved on Pi', 'Message saved on the Pi. You can power off now. Double B opens the inbox.')
                    view.hint = 'power off OK'
                    next_health = 0
                    print('TURN_SAVED')
                elif isinstance(error, HTTPError) and error.status in (400, 401, 403, 409, 413, 415, 429, 507):
                    os.remove(PENDING)
                    pending = None
                    labels = {429: 'Queue full / try later', 507: 'Pi storage limit reached',
                              401: 'USB setup: check key', 403: 'USB setup: check key'}
                    view.hint = None
                    show(labels.get(error.status, 'Message rejected'), 'Message was not accepted. Record again after resolving the issue.')
                else:
                    show('Checking delivery' if error else 'Transcribing')
                next_poll = 0
            elif kind == 'poll':
                if error:
                    connection_checked = False
                    if view.delegation == 'active':
                        view.delegation = 'unknown'
                    if isinstance(error, HTTPError) and error.status == 404:
                        os.remove(PENDING)
                        pending = None
                        show('Ready / hold A', 'Recording was not received. Please try again.')
                    else:
                        show('Reconnecting to Hermes')
                else:
                    connection_checked = True
                    if queue_enabled and result.get('durable'):
                        os.remove(PENDING)
                        pending = None
                        show('Saved on Pi')
                        view.hint = 'power off OK'
                        inbox.open(result['status'] in ('done', 'error') and not result.get('expired'))
                        next_health = 0
                        print('TURN_SAVED')
                        continue
                    view.delegation = result.get('delegation', 'idle')
                    status = result['status']
                    transcript = result.get('transcript', '')
                    if transcript and transcript != transcript_seen:
                        transcript_seen = transcript
                        view.add_request(transcript)
                    reply = result.get('text', '')
                    if reply and reply != reply_seen:
                        reply_seen = reply
                        view.update_reply(reply)
                    if status in ('done', 'error'):
                        text = result.get('text', '')
                        history.append({'request': transcript_seen or '(recording)', 'text': text})
                        history = history[-12:]
                        if persist_history:
                            save_json(HISTORY, history)
                            save_json(LAST_REPLY, {'text': text})
                        os.remove(PENDING)
                        pending = None
                        view.finish_reply()
                        transcript_seen = reply_seen = ''
                        show('Ready / hold A' if status == 'done' else 'Request error')
                        print('TURN_FINISHED', status, len(text))
                    else:
                        labels = {'queued': 'Queued', 'transcribing': 'Transcribing', 'working': 'Hermes working', 'replying': 'Replying'}
                        label = status[5:20] if status.startswith('tool:') else labels.get(status, 'Working')
                        show(label + ' %ds' % result.get('elapsed_s', 0))

        if not wlan.isconnected():
            connection_checked = False
            if recording is not None and not pending:
                M5.Mic.end()
                recording = None
                mic_ready = False
            if time.ticks_diff(now, next_connect) >= 0:
                show('Connecting Wi-Fi')
                try:
                    selected = saved_networks[network_index % len(saved_networks)]
                    network_index += 1
                    wlan.disconnect()
                    wlan.connect(selected['ssid'], selected['password'])
                except OSError:
                    pass
                next_connect = time.ticks_add(now, 15000)
            time.sleep_ms(30)
            continue

        if not connection_checked:
            if not worker.busy and time.ticks_diff(now, next_poll) >= 0:
                worker.submit('health', 'GET', '/health')
            time.sleep_ms(20)
            continue
        if new_chat:
            if not worker.busy and time.ticks_diff(now, next_poll) >= 0:
                if new_chat.get('kind') == 'resume':
                    worker.submit('new_chat', 'POST', '/resume/' + new_chat['id'],
                                  json.dumps({'turn_id': new_chat['turn_id']}).encode())
                else:
                    worker.submit('new_chat', 'POST', '/chat/' + new_chat['id'])
            time.sleep_ms(20)
            continue
        if pending:
            if not worker.busy and time.ticks_diff(now, next_poll) >= 0:
                worker.submit('poll', 'GET', '/turn/' + pending['id'])
                next_poll = time.ticks_add(now, 1500)
            time.sleep_ms(20)
            continue

        if recording is None and not worker.busy and not M5.BtnA.isPressed() and not M5.BtnB.isPressed() and time.ticks_diff(now, next_health) >= 0:
            worker.submit('health', 'GET', '/health')
            next_health = time.ticks_add(now, 15000)
        if worker.busy:
            time.sleep_ms(15)
            continue

        if inbox.active:
            if inbox.job:
                kind, method, path = inbox.job
                inbox.job = None
                worker.submit('inbox:%d:%s' % (inbox.generation, kind), method, path)
            elif inbox.mode == 'detail' and inbox.message and inbox.message['status'] not in ('done', 'error') and time.ticks_diff(now, next_inbox) >= 0:
                inbox.request('detail', 'GET', '/turn/' + inbox.message['id'])
            time.sleep_ms(20)
            continue

        if event == 'record' and not record_blocked and recording is None:
            view.hint = None
            gc.collect()
            try:
                recording = bytearray(MAX_BYTES + 44)
                used = 0
                if not mic_ready:
                    mic_ready = M5.Mic.begin()
                if not mic_ready:
                    raise OSError('Microphone unavailable')
                show('Listening / release A')
            except Exception:
                recording = None
                show('Microphone/memory error')

        if recording is not None:
            if M5.BtnA.isPressed() and used < MAX_BYTES:
                buf = memoryview(recording)[44 + used:44 + used + CHUNK]
                if not M5.Mic.record(buf, RATE, False):
                    M5.Mic.end()
                    recording = None
                    mic_ready = False
                    show('Microphone error')
                    continue
                deadline = time.ticks_add(time.ticks_ms(), 2000)
                while M5.Mic.isRecording():
                    if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                        M5.Mic.end()
                        recording = None
                        mic_ready = False
                        break
                    M5.update()
                    time.sleep_ms(2)
                if recording is None:
                    show('Microphone timed out')
                    continue
                used += CHUNK
                if time.ticks_diff(now, last_header) > 500:
                    last_header = now
                    show('Listening %ds / release A' % (used // (RATE * 2)))
            else:
                M5.Mic.end()
                mic_ready = False
                if used < 8000:
                    recording = None
                    show('Hold A a little longer')
                    continue
                header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', used + 36, b'WAVE', b'fmt ', 16, 1, 1, RATE, RATE * 2, 2, 16, b'data', used)
                recording[:44] = header
                tid = ubinascii.hexlify(os.urandom(16)).decode()
                pending = {'id': tid}
                save_json(PENDING, pending)
                view.delegation = 'idle'
                show('Sending recording')
                worker.submit('send', 'POST', '/turn/' + tid, memoryview(recording)[:used + 44], 'audio/wav')
                record_blocked = True
                next_poll = 0
        time.sleep_ms(15)


if __name__ == '__main__':
    run()

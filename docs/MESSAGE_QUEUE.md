# Optional message queue and inbox

The bridge can keep messages and replies while the Stick is switched off. It
uses its existing private SQLite database; no Redis, MQTT broker, cloud inbox or
additional dependency is required. The Pi (or other bridge host) and Hermes must
remain running to produce replies. Wi-Fi is required when sending and when
checking the inbox after power-on.

## Enable

For a new installation, add `--message-queue` to the initializer command:

```sh
.venv/bin/python bridge/install.py --root .private/bridge \
  --host BRIDGE_LAN_IP --bind BRIDGE_LAN_IP --message-queue
```

For an existing installation, install this version of both the bridge and device
code, then merge these settings into the bridge's existing private `config.json`:

```json
{
  "message_queue": true,
  "queue_capacity": 32
}
```

Keep the existing keys, certificate and other settings. Restart the bridge after
changing the configuration. Follow the [safe upgrade procedure](SETUP.md#upgrading-an-existing-bridge-safely)
and back up the database first. The new tables are added automatically without
replacing existing request IDs or the current Hermes conversation. Previously
completed turns are not imported into the new inbox.

Queue mode defaults to `false`. The device discovers it through authenticated
health checks, so no matching device flag, Wi-Fi change or token rotation is
needed. Updated firmware works with a bridge that has queue mode disabled.
An older firmware build does not offer the inbox UI.

## Send, switch off, return

1. Hold A, speak, and release to upload the recording.
2. Wait for **Saved on Pi** and **power off OK**. The bridge has committed the
   request, its audio/text and conversation association before this confirmation.
3. You may turn the Stick off, or send another message. The bridge processes
   accepted messages one at a time in order.
4. On power-on and reconnection, unread replies produce a **NEW** count and open
   the unread inbox. While already connected, the count refreshes about every
   15 seconds when idle. Double B opens the inbox at any time from the chat view.
5. Inspect a message, then choose **Continue this chat**, **Mark read**, or
   **Start new chat**. Continuing restores the selected message's conversation;
   starting a new chat leaves other messages and replies available in the inbox.

Powering off during **Sending recording** or **Checking delivery** can lose an
upload that never reached the Pi. The Stick saves its request ID first and checks
that ID on reboot; it does not automatically upload or repeat the recording.
A full queue is rejected explicitly. Resolve the issue and record again.

## Inbox controls

| View | Controls |
| --- | --- |
| Chat | Double B opens inbox; hold A records; hold A+B starts a new chat |
| Inbox list or actions | Tap A/B to move down/up; hold A to select; hold B to go back |
| Message | Tap A/B to scroll; hold A opens actions; hold B or double B returns to inbox; double A jumps to the top |

The inbox starts with unread replies when any exist. **Show all messages** also
shows read replies and requests still waiting. **Older messages** pages through
eight entries at a time; **Refresh / newest** returns to the latest entries.
Waiting messages can be opened to watch their progress. Recording and Wi-Fi
setup are suppressed while navigating the inbox; return to the chat view to use
them. The message body is kept only in RAM unless another feature explicitly
persists it.

Opening or scrolling a message does not mark it read. **Mark read** acknowledges
it explicitly. **Continue this chat** also marks that reply read. Acknowledged
replies remain available under **Show all messages** until expiry. Starting a
new chat does not acknowledge unread replies. Devices sharing a bridge/key share
the same inbox and read state.

## Persistence and recovery

- `queue_capacity` limits pending/running messages to 1–100 (default 32). At the
  maximum recording length, the default queue can hold about 31 MB of raw audio;
  allow extra space for SQLite journals, replies and the model cache.
- Pending audio and text are stored in the owner-only database. Audio is removed
  after transcription or failure; SQLite secure deletion remains enabled.
- Content follows `retention_days` (default seven days from submission), including
  unread replies. Expired queued requests are never executed. Request IDs and
  conversation associations remain as bounded metadata to prevent replay.
- On a bridge restart, jobs still durably marked **queued** can resume. A job
  whose processing began becomes an error explaining that an action may have run.
  This is deliberate: there is no automatic retry of uncertain agent actions.
- Session selection has a durable action ID too. Retrying a lost response does
  not reapply an old selection over a newer chat. New submissions remain bound
  to the conversation selected when the bridge began accepting them, even if
  the active conversation changes while uploading or processing.
- Stop accepting work and let the queue finish before disabling the feature or
  rolling back. Starting with queue mode disabled marks outstanding jobs as
  interrupted errors and removes their saved input; it does not run them.
  Disabling hides the inbox but retains unexpired results. Do not roll the database
  back after accepting new IDs: that can permit replay.

The database uses rollback journaling and `synchronous=EXTRA`; its acknowledgements
depend on the host filesystem and storage honoring sync requests. Backups, storage
failure and independently retained Hermes/provider data remain separate concerns.
See [SQLite's durability settings](https://www.sqlite.org/pragma.html#pragma_synchronous)
and [atomic commit documentation](https://www.sqlite.org/atomiccommit.html).

## Verification

Host tests simulate a disconnected client, bridge restarts, persisted audio,
queue capacity, pagination, expiry, session switching, explicit read state and
the device boot loop. Hermes and transcription are mocked in these tests.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/local.py smoke-inbox
```

`smoke-inbox` compiles the changed device code and exercises the real Stick's
display/navigation in RAM using synthetic messages, then resets its installed
app. It does not deploy code or contact Hermes. Physical button feel and a full
power-off/reconnect cycle against a queue-enabled live bridge should be checked
after deployment.

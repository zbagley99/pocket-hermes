# Pocket Hermes for M5StickS3

A push-to-talk MicroPython terminal: hold a button, speak, and read a short,
scrollable reply. A private Python HTTPS bridge transcribes audio locally and
passes text to your dedicated Hermes agent profile.

**Hardware baseline:** M5StickS3 with UiFlow2 2.4.8. M5StickC, C Plus and C Plus2
are not validated targets; this is not universal M5Stick firmware. The S3 has
8 MB PSRAM, a microphone and a 135×240 display
([hardware documentation](https://docs.m5stack.com/en/core/StickS3)). See
[hardware validation](docs/HARDWARE.md) before deploying to another model.

## Repository layout

```text
device/                 MicroPython application and shared config validation
bridge/                 HTTPS adapter and private-runtime initializer
scripts/                USB deployment, restore, profile setup, release checks
config/                 Placeholder-only configuration examples
profile/                Generic Hermes instruction templates
tests/                  Host tests with mocked hardware and upstream agent
docs/                   Setup, hardware support and security review
.github/workflows/      Tests, release checks and dependency audit
.private/               Ignored local credentials, backups and runtime data
dist/                   Ignored, checked source archives
```

## Setup

### 1. Install UiFlow2 on the StickS3

You need an **M5StickS3**, a USB-C **data** cable, and a 2.4 GHz Wi-Fi network
that can reach your bridge host. If the Stick already runs UiFlow2 **2.4.8**,
continue to step 2. Flashing replaces the current firmware and can erase device
files; save anything you need before proceeding. Pocket's later startup backup
does not back up the firmware you replace here.

1. Download and open [M5Burner for your computer](https://docs.m5stack.com/en/uiflow/m5burner/intro).
2. Find the **StickS3 UiFlow2** firmware entry and download version **2.4.8**,
   the version tested with this project. Other versions require the
   [hardware validation checks](docs/HARDWARE.md).
3. Connect the Stick by USB. Hold its **side reset button** until the internal
   green LED flashes to enter download mode.
4. Click **Burn** for the downloaded firmware, select the Stick's USB serial
   port, then click **Start**.
5. Enter the Wi-Fi settings requested by M5Burner. Set **Boot Option** to
   **Show startup menu and network setup**, then click **Next** to flash.
6. Wait for the successful burn message, reset the Stick, and confirm that the
   UiFlow startup screen appears. Close M5Burner and any serial terminal before
   running this project's deployment commands.

The [official StickS3 flashing guide](https://docs.m5stack.com/en/uiflow2/sticks3/program)
includes screenshots. Pocket is uploaded over USB in step 4 below. Its setup
prompts for Wi-Fi separately from the settings saved by M5Burner.

### 2. Prepare the computer and bridge host

Use Python 3.11 or 3.12 on your computer and bridge host, plus OpenSSL on the
bridge host. Open a terminal in this repository's directory and install into a
new virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-bootstrap.txt
.venv/bin/python -m pip install -r requirements.txt
```

On the bridge host install `requirements-bridge.txt` instead. For Hermes setup,
follow the [official Hermes documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).
This project expects a **dedicated Hermes profile** with its authenticated
Sessions API listening on `127.0.0.1:8642`. The initializer does not change
Hermes settings or start services.

### 3. Initialize and start the Pocket bridge

Create a new runtime directory, replacing `BRIDGE_LAN_IP` with an interface
address on the bridge host that the Stick can reach:

```sh
.venv/bin/python bridge/install.py --root .private/bridge \
  --host BRIDGE_LAN_IP --bind BRIDGE_LAN_IP
```

Enter the existing Hermes API key at the hidden prompt. The initializer creates
a separate random device key, a TLS certificate and its exact SHA-256 pin. It
refuses to overwrite an existing runtime. Without `--bind`, it listens only on
localhost. Keep ports private and restrict the bridge port to trusted devices
in your host firewall.

If the bridge is on another computer, transfer its generated device.json file
through a trusted encrypted channel to your provisioning computer. Only the
device key is in that file; the full Hermes API key stays on the bridge.
Example field names are in [config/](config/); placeholders are rejected.

Start the bridge from the project checkout:

```sh
.venv/bin/python bridge/server.py --root .private/bridge
```

The first start downloads speech model weights. The bridge host needs internet
for that download and whatever access your Hermes model/tools need. For a
persistent Linux service see [setup details](docs/SETUP.md).

### 4. Install Pocket on the Stick

Keep the bridge running. Connect the Stick over USB and let it boot normally
into UiFlow. Import the generated private config into this clone; setup prompts
for Wi-Fi if needed and auto-selects a single connected USB port:

```sh
.venv/bin/python scripts/local.py setup --config .private/bridge/device.json
.venv/bin/python scripts/local.py check
.venv/bin/python scripts/local.py deploy
```

Deployment restarts the Stick into Pocket and reports that startup and the
authenticated bridge health check passed. Hold **A**, say a short sentence,
then release it and wait for a reply. The first request may wait while the
bridge downloads and loads its speech model.

Pass `--port YOUR_SERIAL_PORT` to setup if multiple USB devices are connected.
All machine-specific settings stay in ignored `.private/local.json` and
`.private/provisioning/device.json`; source edits are unnecessary. For a remote
bridge, pass the securely transferred file path to `--config`.

Deployment changes startup files on the existing UiFlow firmware; it does not
reflash the board. Original startup files are saved under
`.private/devices/DEVICE_ID/`. Existing on-device configuration is preserved;
pass `--replace-config` to `scripts/local.py deploy` to rotate the token/pin or replace saved Wi-Fi settings.
Use one configuration/runtime/profile per person. Devices that share a runtime
and token share conversation history and agent authority.

## Controls

- Hold A to record; release to send. Maximum 30 seconds; speaker stays off.
- Tap A/B to scroll down/up. Double A jumps to earlier requests; double B follows new text.
- Hold B for Wi-Fi setup on compatible firmware. On the tested UiFlow build, use USB: rerun local setup with `--wifi`, then deploy with `--replace-config`. The device displays this guidance rather than starting an unsecured access point.
- Hold A+B to start a new chat after the current request finishes. Old Hermes chats remain.
- Hold B during startup to choose the UiFlow menu on the next boot.

For an optional USB/network check after installation, run:

```sh
.venv/bin/python scripts/local.py smoke
```

The `smoke` command tests the uploaded firmware against a temporary
HTTPS endpoint on your computer. It uses synthetic audio, does not contact Hermes,
and leaves saved device credentials unchanged. Your firewall must allow the
Stick to reach the computer. OpenSSL is required for this test.

Pending IDs survive resets so uncertain actions are checked rather than
replayed. Device history persistence is **off by default**; setting
`persist_history` to `true` saves the last 12 turns in readable flash.
Bridge content expires after seven days by default, on startup/result access;
Hermes and its model provider have separate retention. See [SECURITY.md](SECURITY.md).

To restore this device's backed-up startup files:

```sh
.venv/bin/python scripts/local.py restore
```

Restore does not erase credentials or history. See [setup details](docs/SETUP.md)
for retirement and migration of backups from earlier installations.

## Optional offline replies and inbox

Enable `message_queue: true` in the bridge's private configuration (or initialize
with `--message-queue`) to keep requests and replies on the Pi while the Stick is
off. No additional broker is needed. After **Saved on Pi / power off OK**, the
device can be switched off while Hermes works. Unread replies appear on reconnect.

Double B opens the inbox in this mode. Tap A/B to navigate, hold A to open a
message or its actions, and hold B to go back. **Continue this chat** restores
that message's conversation; **Mark read** acknowledges it; **Start new chat**
keeps other replies available. Opening a reply alone does not mark it read.

Queue mode defaults to off and requires updated bridge and device code. The
default capacity is 32 pending messages; reply retention remains seven days.
See [queue setup, controls and recovery](docs/MESSAGE_QUEUE.md).

## Development and sharing

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_release.py
.venv/bin/python scripts/check_release.py --export dist/pocket-hermes-source.zip
```

Share the checked ZIP, not the whole working directory. The explicit
`release-manifest.json` excludes local data even if ignore rules change. Add
new intended source files to that manifest. The scanner also checks any tracked
Git files against it and compares release contents against local config values
without printing those values. These checks supplement manual review; they
cannot prove the absence of every possible kind of PII.

Read the [security review](docs/SECURITY_REVIEW.md) for findings, fixes and
remaining limitations, and [CONTRIBUTING.md](CONTRIBUTING.md) for changes.

## License

[MIT](LICENSE), using the [standard MIT license text](https://opensource.org/license/mit). Third-party firmware, dependencies and model weights are licensed separately.

# Configuration and operations

The bridge accepts `--root` pointing to a private runtime directory. That
contains `config.json`, `device.json` for USB provisioning, `tls/server.pem`,
`tls/server.key`, `state.sqlite3`, a process lock, and the private `audio-tmp/` directory. Code stays in the checkout. Do not put
runtime files into a public repository or copy them into an issue.

| Setting | Meaning |
| --- | --- |
| `bind`, `port` | Local interface and HTTPS port; defaults are loopback and 8643 |
| `hermes_url` | Explicit loopback HTTP API URL including port; redirects rejected |
| `hermes_key` | Existing authenticated API key; distinct from the device key |
| `device_key` | Random device bearer credential generated at installation |
| `profile_config` | Optional absolute path to the profile YAML model selection |
| `whisper_model`, `language` | Defaults `tiny.en`, `en`; use a multilingual model for other languages |
| `retention_days` | 1–365; default 7; content cleared on startup/result access |
| `max_turns` | Request/chat ID capacity, default 10,000 each; fails closed when full |
| `max_reply_chars` | 100–4,000 characters, default 4,000; display output additionally bounded |
| `message_queue` | Boolean, default false; durable requests and unread inbox on the bridge |
| `queue_capacity` | 1–100 pending/running messages; default 32; used when queue mode is enabled |

Use `--profile-config` when initializing to follow a profile's model changes.
Use `--message-queue` to enable offline replies. Existing installations can set
`message_queue` in private config and restart after installing the updated bridge
and firmware. The device discovers the option automatically. See the
[message queue guide](MESSAGE_QUEUE.md) for controls, migration and recovery.
Otherwise the bridge checks `config.yaml` in the runtime directory's parent
for compatibility with older installations; if absent, the Sessions API decides
the model. An optional `session_key` labels the upstream client.

Wi-Fi supports a provisioned SSID and up to eight saved entries. An empty Wi-Fi
password explicitly selects an open network. Prefer a protected network.
The setup form changes only saved networks, preserving the bridge key and pin.
`host` is the address to connect to; `tls_name` is the TLS server name and HTTP
Host value. The initializer makes both equal. Use lowercase hex for the pin.

## Configure a fresh clone

The prerequisites are a StickS3 with UiFlow2 2.4.8, a USB data cable, Python
3.11/3.12, a reachable bridge host, and a dedicated authenticated Hermes Sessions
API. Start with the [StickS3 firmware installation steps](../README.md#1-install-uiflow2-on-the-sticks3)
if the board needs UiFlow2. For Hermes setup, use the
[official Hermes documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).
Then install the declared dependencies, initialize the bridge as described in
README, and securely transfer its generated device.json to the USB computer if
needed.

Run `python scripts/local.py setup --config PATH_TO_DEVICE_JSON`. Missing Wi-Fi
credentials are prompted locally; passwords are hidden. A single USB port is
selected automatically, or use `--port`. Setup copies credentials into ignored
`.private/provisioning/device.json` and records the selected port in
`.private/local.json`. Re-running setup replaces this local configuration; it
does not deploy or change the source/imported file.

`python scripts/local.py check` validates configuration and port presence.
`python scripts/local.py deploy` uploads the firmware while retaining on-device
config. Use `--replace-config` to apply new local settings. To change Wi-Fi:

```sh
python scripts/local.py setup --config .private/provisioning/device.json --wifi
python scripts/local.py deploy --replace-config
```

Your saved networks, key and certificate pin are retained when editing just the
preferred Wi-Fi entry; the new network is tried first. `local.py restore` uses the connected board's own backups.
The lower-level deploy/restore scripts also remain available with explicit flags.

The tested UiFlow build requires an active AP before accepting WPA2 settings.
Pocket refuses that activation sequence and shows USB setup instructions.
The captive portal remains available on firmware that supports secure inactive
AP configuration. Normal Wi-Fi client connectivity is unaffected. See the
[MicroPython WLAN API](https://docs.micropython.org/en/v1.27.0/library/network.WLAN.html).

## Private local layout

```text
.private/local.json                 USB port and local config path
.private/provisioning/device.json   Canonical configuration for deployment
.private/devices/DEVICE_ID/         Original startup and pre-upgrade config
.private/connections/              Existing bridge metadata and trusted certs
.private/backups/                  Archived pre-migration source/recovery data
.private/artifacts/                Private historical tests and verification
```

A newly initialized bridge runtime can live at `.private/bridge/`. A laptop
connected to an existing remote bridge does not need a local bridge runtime.
Never commit these private directories, including archives.

## Optional Linux user service

Create a user unit locally with absolute paths substituted for the placeholders:

```ini
[Unit]
Description=Pocket Hermes HTTPS bridge
After=network-online.target

[Service]
Type=simple
WorkingDirectory=ABSOLUTE_CHECKOUT
ExecStart=ABSOLUTE_CHECKOUT/.venv/bin/python ABSOLUTE_CHECKOUT/bridge/server.py --root ABSOLUTE_PRIVATE_RUNTIME
Environment=HF_HUB_DISABLE_TELEMETRY=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Install as `~/.config/systemd/user/pocket-bridge.service`, then use
`systemctl --user daemon-reload` and `systemctl --user enable --now pocket-bridge`.
Manage the Hermes API service separately. The service account must be able to
write the private runtime and model cache. Never run the bridge as root.

Generic assistant instructions can be copied on the bridge host with
`python scripts/update_profile.py --profile-dir YOUR_PROFILE_DIRECTORY`.
This explicitly replaces SOUL.md and DEVICE.md after backing them up; it does
not configure agent permissions. Review the templates first.

## Existing installations

Source changes do not deploy themselves or alter a running bridge. Back up the
runtime privately before migration. Existing keys of sufficient length remain
valid. Update service commands to pass `--root`. The server imports the ASCII
module from the checkout; keep the whole release layout together.

Older flat `.private/original-*` backups have no device association. Do not use
them on another Stick. Before deploying the new script to that original Stick,
read its `machine.unique_id()` over a trusted USB REPL, verify that it is the
original device, and move/copy those backups into `.private/devices/DEVICE_ID/`.
Otherwise a new backup would capture the already-installed Pocket startup.
The new deploy/restore tools select backups by hardware ID, not serial port.

Certificate renewal requires replacing both certificate and private key on the
bridge and provisioning the new exact pin with `--replace-config`. Token
rotation likewise requires updating bridge config and each authorized device.
Restart the bridge after config changes, with no active turn. A certificate pin
ignores CA/hostname/date validity: rotation and private-key custody are essential.

## Retiring a device or clearing server state

Startup restore is not a factory reset. Use a trusted USB REPL or the vendor's
full erase/reflash process to remove Pocket config, history, pending IDs,
original-main backups, temporary JSON files and installed Pocket modules.
Files are under `/flash/pocket-*` and `/flash/libs/`. UiFlow's own configuration
may also contain Wi-Fi data. File deletion is not guaranteed physical erasure
on flash. Rotate the device key after loss or transfer.

Do not delete bridge request IDs just to reclaim space: stale clients could
replay consequential requests. At capacity, stop the bridge, verify no active
work, rotate the device key, clear/reprovision pending state on all devices,
then archive or delete the database privately and restart with a fresh session.
Old Hermes sessions and backups require independent deletion. Content expiry
is best effort and does not erase filesystem snapshots or storage media.

## Upgrading an existing bridge safely

Stage a separate release and its own virtual environment inside the dedicated
profile. Install `requirements-bootstrap.txt` before `requirements-bridge.txt`,
run the regression tests, and audit the complete installed package inventory
(including pip/setuptools). A direct-dependency-only audit misses bundled tools.

Before switching, require no active request and privately back up the launcher,
configuration and database. Preserve the device/upstream keys, certificate,
request IDs, session ID and upstream session-key header. Set an explicit
`profile_config` path if the new source directory is separate from the runtime.

The existing service can continue launching a small profile-local `server.py`
that sets Linux `no_new_privs` and execs the release's Python with the new bridge
script and `--root RUNTIME`. This avoids changing shared Hermes packages or the
service unit. For new services, the systemd hardening settings above remain
appropriate. The production entry point acquires an exclusive runtime lock
before touching the database. Temporary audio stays in `audio-tmp/`, mode 0700.

Verify pinned HTTPS health and speech readiness after switching. Roll back the
launcher/config if startup fails. Do not automatically restore an old database:
a new request might already have been accepted, and losing its ID permits replay.
Keep the database backup private for controlled recovery instead. Recheck the
actual hardware round trip and file permissions before considering the upgrade
complete. Old releases and backups remain sensitive; manage them separately
from the public repository.

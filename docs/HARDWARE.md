# Hardware support

| Board | Status |
| --- | --- |
| M5StickS3 + UiFlow2 / MicroPython 1.27.0 | USB hardware checks passed; Wi-Fi changes require USB on the tested build |
| M5StickC / C Plus / C Plus2 | Unvalidated; do not assume drop-in support |
| Other ESP32 boards | Requires hardware and firmware adaptation |

The application uses the M5 MicroPython display/canvas/font API, microphone,
battery API, A/B buttons, Wi-Fi, background threads, UiFlow NVS startup selection,
`/flash` storage and TLS peer-certificate access. Board-specific microphone,
RAM and display differences cannot be addressed by a host-address setting.
The S3's documented 8 MB PSRAM supports the roughly 960 KB recording buffer;
actual allocation also depends on firmware and other running code.

Before declaring another firmware/board supported, verify:

1. Back up and restore startup on that exact device; test UiFlow escape.
2. Display, buttons, battery reporting, microphone format and full 30-second recording.
3. TLS failure on an incorrect pin and successful peer DER retrieval with the correct pin.
4. Wi-Fi provisioning with WPA2 active from startup, timeout, cancel and malformed requests.
5. Reconnect and reset during upload, polling and new-chat creation without duplicate agent actions.
6. Multi-device backup separation, config replacement and privacy defaults after reboot.

The Wi-Fi setup AP is configured while inactive to avoid briefly exposing an
open AP. Verify support for inactive `WLAN.config` on the exact UiFlow build;
failure must leave setup disabled. Do not weaken authentication to work around it.

References: [StickS3 specifications](https://docs.m5stack.com/en/core/StickS3),
[MicroPython SSL API](https://docs.micropython.org/en/latest/library/ssl.html).
The original project noted a certificate-date validation error on its UiFlow
build; this review did not independently reproduce that firmware issue.

## Physical-device validation — 2026-09-06

The connected StickS3 reported MicroPython 1.27.0, a 240×135 landscape display,
and sufficient heap for the 960,044-byte recording buffer. A short microphone
capture completed in RAM and was discarded. Display/canvas and A/B APIs exist;
actual finger-operated button gestures and speech intelligibility still need a
user check.

The revised files were uploaded and their hashes matched the checkout. An
isolated HTTPS endpoint on the USB computer verified certificate pinning,
rejection of a wrong token, synthetic WAV submission, polling, duplicate IDs,
and display drawing. The negative pin test sent no HTTP request. History
persistence was disabled and the old history file was absent after startup.

The initial live test was blocked by an unreachable bridge. After the owner
resolved a Pi thermal problem, the bridge service was confirmed active and its
pinned HTTPS health check reported speech recognition ready. A 7.1-second
synthetic speech WAV was then uploaded from the Stick through its actual saved
connection. The Pi transcribed the test, Hermes returned "Pocket Test OK", and
the normal app polled and displayed the reply with no traceback. The completed
turn was read back independently and its transcript/reply matched the test.

This verifies the live network, transcription, model and app reply path. It does
not replace the manual microphone intelligibility/button-gesture check above.
The Stick retains its original bridge credentials. This first live test used
the existing server. A subsequent deployment activated the hardened bridge in
its own environment and repeated the endpoint/security and live audio tests;
see the deployment follow-up in SECURITY_REVIEW.md.

This firmware raises `Wifi Invalid Mode` when configuring an inactive AP.
Pocket now displays USB Wi-Fi setup instructions and leaves the AP disabled.
Use `local.py setup --wifi` followed by `local.py deploy --replace-config`.
The secure captive portal path remains available for compatible firmware.

Reproduce the isolated networking checks after local setup with:

```sh
python scripts/local.py smoke
```

This uses a short-lived authenticated TLS server on your computer and synthetic
silence, not speech recognition or a real agent. It requires OpenSSL and LAN
reachability from the Stick to the computer. Settings injected for the test live
only in RAM; the script resets the normal app afterward. Detailed results stay
in ignored `.private/artifacts/hardware-validation.json`.

## Optional inbox validation

The new queue/inbox build passed MicroPython compilation and synthetic display,
scroll, unread-count and explicit action checks in RAM on this same Stick:

```sh
python scripts/local.py smoke-inbox
```

The test resets the installed app afterward. It does not install the new firmware
or change the Pi. A real queue-enabled power-off/reconnect round trip and manual
button navigation remain deployment checks. See [queue operations](MESSAGE_QUEUE.md).

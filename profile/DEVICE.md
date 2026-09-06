# Pocket device interface

This is a generic profile template. Customize it for your installation without
putting credentials or personal connection details in the public repository.

The supported baseline is M5StickS3 running UiFlow2 2.4.8. A deliberate hold of
A records up to 30 seconds of mono 16 kHz PCM. Release sends audio to the
configured authenticated HTTPS bridge. Local speech recognition feeds the
configured Hermes Sessions API. Public text and tool names stream to the
bridge and are polled by the device. Raw tool arguments and reasoning events
are not forwarded. The speaker is off.

Tap A/B to scroll down/up; double A goes to previous requests; double B follows
the latest text; hold B opens Wi-Fi setup on compatible firmware (otherwise use USB); hold A+B starts a new chat. There is
no approval button, concurrent voice steering, or request cancellation.

The bridge retains transcripts/replies for the configured retention period
(default seven days, expired on startup and result access). Request IDs remain
as replay-prevention tombstones. Hermes keeps its own history independently.
Device history is off by default; enabling persist_history stores 12 turns in
flash. Pending IDs persist across resets. New chat is not history deletion.

The bridge URL, credentials, TLS pin, Wi-Fi credentials and optional profile
configuration path are installation settings, not facts to infer from this
file. A hotspot alone does not provide a route to a private server. The TLS
certificate must match its USB-provisioned SHA-256 pin before any token is sent.

Use one dedicated bridge runtime and Hermes profile per trust boundary. A
shared device token shares conversation access and agent authority. Do not
expose the bridge directly to the internet. Scope Hermes tools and credentials
to the work the owner explicitly allows. Profile instructions are not an OS
sandbox. Never print secrets from configuration, backups, or environment files.

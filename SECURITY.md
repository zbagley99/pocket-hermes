# Security and privacy

This is a trusted-LAN, single-trust-boundary agent terminal, not a public API or
multi-user isolation service. Possession of its bearer key grants access to the
runtime's conversation and the actions allowed by its Hermes profile. Use a
separate runtime, key and profile for each person. Keep the full API loopback-only
and restrict agent tools with OS/account permissions as well as profile policy.

Credentials and optional history are readable to anyone with device flash/USB
access. The firmware does not implement secure boot, encrypted flash or secure
key storage. Treat a lost device as a compromised credential and rotate its key.
Audio is temporary on the bridge, but abrupt termination can leave temporary
files. Transcripts may reach the configured model provider and tool services.
Bridge expiry does not control Hermes/provider logs, backups or snapshots.

Optional queue mode persists input audio/text in the private database until it
can be processed. Replies remain unread until explicitly acknowledged or expired.
Queue capacity and content retention are bounded; a restart only resumes work
that had not started. Interrupted agent actions are never replayed automatically.
See [queue behavior and recovery](docs/MESSAGE_QUEUE.md).

Local `.private/` may contain credentials, personal data and original firmware
backups. It is intentionally excluded from Git and release exports. Never share
the full working directory. Do not upload raw logs, databases, audio or device
configuration when reporting problems. The checked release scanner is heuristic,
not proof that arbitrary prose contains no identifying information.

Report vulnerabilities privately through your hosting provider's private
vulnerability reporting feature if enabled. Otherwise ask the maintainer for a
private reporting channel without posting exploit details or secrets publicly.
Do not test against someone else's device or service without permission.

See [the review](docs/SECURITY_REVIEW.md) for scope and residual risks.

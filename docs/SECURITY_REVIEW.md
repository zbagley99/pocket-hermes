# Security review — 2026-09-06

## Scope and conclusion

Reviewed all application, bridge, deployment, profile and test sources in the
original working directory. Inspected the local artifact inventory and checked
release content against private configuration values without printing secrets.
There was no `.git` directory in the original project, so no local commit history
existed to audit; external repositories, remotes or prior uploads were not checked.
The initial source review made no live changes. Subsequent authorized device
and bridge deployments, with verification, are recorded below.

The revised project is suitable for further testing as a private LAN terminal
with one trust boundary per bridge/profile. It is not a public-facing service,
proof of absence of PII, or a hardware penetration test. The source export is
allowlisted and excludes local credentials, recordings and recovery backups.

## Findings and remediation

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | Installation-specific IPs, account paths and remote deployment target in public source/docs | Replaced with generic templates, explicit CLI settings and local profile-copy utility; no embedded SSH destination |
| High | Installer modified profile credentials/settings and started services during import/execution; late conflict checks could leave partial changes | Replaced with import-safe private-runtime initialization, existing upstream key prompt, distinct generated device key, and refusal to overwrite; service/profile setup is explicit |
| High | Flat startup backups could be restored to another person's device | Deploy and restore require a serial port and associate backups with device unique ID; old backup migration is documented |
| Medium | Configuration allowed weak/empty credentials and header injection; unrestricted upstream URL/redirect behavior | Validate credentials and device fields, reject example keys and shared upstream/device keys, loopback-only upstream URLs, disable redirects |
| Medium | Unlimited persisted conversation content and request IDs | Content expiry defaults to seven days; IDs retained to prevent replay; hard capacity fails closed; device history opt-in |
| Medium | Concurrent uploads, slow bodies, response/event growth and device header lines insufficiently bounded | Four authenticated requests at a time, 15-second handler timeout, existing ~960 KB upload cap, bounded stream aggregation/display replies, one-byte bounded header reads |
| Medium | Wi-Fi AP activated before setting WPA2; slow form reads could prolong setup | Configure WPA2 while inactive, activate afterward, bound connection duration; physical-board verification required |
| Medium | Console and exception dumps could expose private runtime context | Suppress raw console output and turn/transcription exception details; access logs disabled |
| Medium | Ignoring one private directory did not prevent sharing the complete workspace or accidental staging elsewhere | Expanded ignores, explicit release manifest, private-value and pattern checks, tracked-file checks, checked ZIP export and CI |
| Low | No declared dependency versions or public setup/compatibility guidance | Added dependency manifests, tests/CI, setup and hardware checklists; audited resolved dependencies |

Strengths preserved: certificate fingerprint checked before token/audio writes;
constant-time bridge bearer comparison; parameterized SQL; authenticated routes;
strict WAV format/length checks; no automatic replay of uncertain agent actions;
public assistant/tool-name events only; temporary transcription files deleted on
normal completion and exception paths; Wi-Fi setup random password and form token.

## Verification

- 31 tests passed on CPython 3.12.12 and the Pi's CPython 3.11.16 with
  aiohttp 3.14.3, PyYAML 6.0.3 and pyserial 3.5. Tests use ephemeral loopback servers and mock Hermes/STT; a real
  OpenSSL invocation verifies generated certificate pins and file permissions.
- Tests cover unauthorized routes, malformed/oversized payloads, concurrency and
  storage limits, invalid IDs, upstream redirects, wrong certificate pins before
  writes, malformed config, durable idempotency, content expiry tombstones,
  public-only streaming, Wi-Fi form credential preservation, bounded headers,
  private export paths/values and original display/control behavior.
- All Python source compiled successfully using the host parser. This does not
  establish compatibility with every MicroPython build.
- `uv pip compile requirements-bridge.txt` resolved 32 direct/transitive packages
  for Python 3.12; `pip-audit --no-deps --disable-pip` on that fully pinned
  resolution reported no known vulnerabilities on the review date. The resolved
  inventory is in `docs/dependency-review.txt`. It is an audit snapshot, not a
  portable lockfile or a guarantee against unknown vulnerabilities. Model weights
  and vendor firmware were not audited or downloaded.
- Manual source review and release checks found no original personal account
  paths, deployment addresses, or private configuration values in the final
  allowlisted source. The release checker prints paths/rule names, never matches.

## Residual risks and deployment requirements

1. **Agent authority:** anyone holding the bearer key can trigger the profile's
   tools and read its results. There is no per-user authorization, MFA or approval
   UI. Use separate profiles/runtimes/keys and restricted OS accounts/tools.
   Prompt injection and speech-recognition mistakes remain possible; profile
   instructions do not enforce a security boundary.
2. **Physical access:** flash stores Wi-Fi/device credentials and optional history
   without application encryption. Secure boot, encrypted flash and locked USB
   debug access are not implemented. Rotate credentials after loss or transfer.
3. **TLS pin lifecycle:** exact certificate pinning authenticates the server but
   does not validate CA, hostname or expiry. A copied server private key stays
   useful until the pin is rotated. New certificates need USB reprovisioning.
   There is no unverified fallback; the known UiFlow date issue was not reproduced.
4. **Availability:** application limits reduce abuse but do not stop connection
   floods or TLS handshake exhaustion. Keep the bridge off the public internet,
   firewall it and run only one process per runtime. Speech model loading and
   transcription run in threads; Python task cancellation cannot kill a stuck
   native operation. Restart recovery marks uncertain work without replaying it.
5. **Retention:** expiry runs on startup/result access, not continuously while
   idle. Tombstones and old chat IDs stay until controlled maintenance. SQLite
   secure_delete is enabled, but backups/snapshots/flash remnants remain possible.
   Hermes, model providers and tools keep independently governed data. New chat
   and startup restoration do not erase that data. Abrupt kills can leave audio
   temp files. Logs in third-party components are outside the app's redaction.
6. **Existing installations:** original private artifacts were preserved with
   owner-only permissions, including a before-review backup. They remain sensitive
   and must not be shared. No evidence of prior publication was available; this
   review does not prove secrets were never exposed elsewhere. If they were,
   rotation is required even after removing them from a repository.
7. **Compatibility and recovery:** revised firmware needs the hardware checklist,
   especially inactive AP configuration, TLS peer-certificate access, audio RAM,
   and per-device backup/restore. Interrupted USB writes may require local
   recovery. Stock UiFlow may retain additional data/cloud configuration outside
   Pocket's files; review it before sharing a physical device.
8. **Release governance:** heuristic scans cannot recognize all PII in arbitrary
   prose. Manually review new files and any future Git history before publishing.
   MIT was selected as the reusable-source default, with a generic contributor
   copyright notice. Third-party licenses still apply. No remote repository was published.

## Primary references

- [MicroPython SSL documentation](https://docs.micropython.org/en/latest/library/ssl.html)
  for peer certificate and verification APIs; actual build support must be tested.
- [aiohttp server documentation](https://docs.aiohttp.org/en/stable/web_advanced.html)
  for middleware and application lifecycle behavior.
- [M5Stack StickS3 documentation](https://docs.m5stack.com/en/core/StickS3)
  for memory, microphone and display hardware.

## Follow-up: local migration and physical testing

Local setup now imports a generated private config, selects a USB port and saves
ignored clone-specific settings. Repeat deployments import the required NVS
module explicitly and fail if the bridge connection cannot be verified. Original
startup files were associated with the verified device ID. Legacy source backups
were archived, old artifacts separated, duplicate configs removed and the Python
environment rebuilt with declared dependencies.

Physical tests found that this firmware rejects inactive AP configuration. That
path now fails closed with actionable USB setup guidance instead of a generic
error. Local setup preserves existing networks while prioritizing newly entered
Wi-Fi credentials. See HARDWARE.md for the exact successful tests. The initial
bridge reachability issue was resolved by the owner; the live speech-to-Hermes
round trip subsequently passed on the Stick. The service initially remained unchanged. The owner subsequently authorized
remote hardening, completed as described below. The expanded host/Pi suite
passes 31 tests, including fresh-clone setup, generated hardware-test code and
exclusive production runtime locking.

## Remote hardening deployment

The hardened bridge was activated in a versioned, private release directory
under the dedicated profile. Its environment is separate from the shared Hermes
environment. The existing service entry point delegates to that release and
sets Linux `no_new_privs`; the kernel process flag was verified. The existing
service unit and default/profile model, environment and instruction files were
hashed before/after and remained unchanged.

Private backups cover the old launcher/config and a consistent database
snapshot. Request IDs, the active conversation session, both API credentials
and the server certificate were preserved. Automatic startup rollback restores
the old launcher/config but deliberately keeps the database to avoid losing IDs
accepted after an upgrade.

The active runtime enforces seven-day content retention, a 10,000-ID capacity,
4,000-character replies, authenticated request concurrency/body/time limits,
loopback-only upstream configuration and redirect rejection. Config, database
and TLS key files were verified mode 0600; the audio directory is mode 0700.
The deployed server hash matches the reviewed repository source.

All 31 tests passed on the Pi. Auditing the complete environment found known
vulnerabilities in its bundled pip/setuptools; those were upgraded before
activation. A second full audit reported no known vulnerabilities. The exact
installed versions are recorded in pi-dependency-review.txt, and new-clone
instructions now include requirements-bootstrap.txt.

Live endpoint tests confirmed 401 for unauthenticated/wrong-token requests,
400 for malformed IDs/JSON and excessive text, 413 for oversized audio, and
no-store headers. Invalid requests did not create queued turns. A fresh
synthetic speech sample sent from the Stick reached transcription and Hermes,
which returned the expected "Pocket Test OK" response. The normal Stick app
confirmed display completion without errors. A second production process was
rejected by the runtime lock, and no temporary audio files remained afterward.

Residual risks listed earlier still apply: this remains a trusted-LAN bearer-key
service, and physical access to unencrypted device flash exposes credentials.
The hardened bridge reduces application risks; it is not a whole-Pi security
audit or a substitute for isolated OS accounts and protected network access.

## Optional queue follow-up (local build)

This follow-up adds an opt-in SQLite queue and unread inbox. The earlier remote
deployment and source hash describe the pre-queue release, not this new build.
Queue mode remains off by default. New routes use the same authentication, TLS,
request limits and no-store responses. Inbox pages contain at most eight bounded
previews; full content requires a separate authenticated request.

Accepted requests, their input and conversation association commit together
before acknowledgement. Capacity is bounded to 1–100 pending/running messages.
Private SQLite storage now explicitly uses DELETE journaling and EXTRA sync.
Input is securely deleted after processing/failure; expired queued work is not
executed. Unstarted durable jobs survive a restart, while work that may have
triggered an action becomes a visible error. IDs remain durable tombstones.
Conversation selection is explicit and idempotent, and cannot reroute older
queued requests. Opening a reply does not acknowledge it.

All 51 host tests pass. Queue and device-loop tests cover disconnect/reconnect, queue recovery, persisted
audio, unread/read persistence, session isolation, bounded pagination, invalid
inputs, capacity, expiry and disabled-mode compatibility. The connected Stick
also passed RAM-only MicroPython compilation and synthetic inbox rendering,
scrolling, explicit read/resume selection and return-to-chat checks. No new
dependencies were added. Live queue deployment and a real power-off/reconnect
round trip are not yet verified; the previous live tests cover the earlier build.

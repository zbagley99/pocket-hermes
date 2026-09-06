# Contributing

Keep MicroPython device modules compatible with the target UiFlow build; host
Python and device Python have different APIs. Keep hardware dependencies out of
pure helpers so host tests can cover them. Use synthetic fixtures, never captured
conversations or real credentials. Add new shareable files to the release manifest.

Run `python -m unittest discover -s tests -v` and
`python scripts/check_release.py`. Network tests bind ephemeral loopback ports;
they mock transcription and Hermes so no model downloads or live actions occur.
For network/provisioning changes also complete the hardware checklist in docs.

Preserve certificate checking before credential writes, bounded input/output,
private runtime permissions and durable replay prevention. Do not treat deletion
of chat IDs as routine cleanup. Update the security review when assumptions change.

Project source is provided under the MIT license in LICENSE. Third-party
firmware, libraries and model weights retain their own licenses.

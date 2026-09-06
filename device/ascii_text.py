"""ASCII-only presentation for the Stick; raw server-side history stays intact."""

REPLACEMENTS = {
    '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': '"',
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-',
    '\u2212': '-', '\u2026': '...', '\u2022': '-', '\u00b7': '*',
    '\u00a0': ' ', '\u2007': ' ', '\u2009': ' ', '\u202f': ' ',
    '\u2192': '->', '\u2190': '<-', '\u2194': '<->',
    '\u2264': '<=', '\u2265': '>=', '\u2260': '!=',
    '\u00d7': 'x', '\u00f7': '/', '\u00b0': ' degrees',
    '\u2713': '[OK]', '\u2714': '[OK]', '\u2705': '[OK]',
    '\u274c': '[X]', '\u2717': '[X]', '\u26a0': '[!]',
}


def display_ascii(text):
    """Normalize typography, drop decorative emoji, escape other Unicode.

    Unknown letters/identifiers are visibly escaped, never silently respelled.
    This function is idempotent and needs no CPython-only Unicode libraries.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for char in text:
        code = ord(char)
        if 32 <= code <= 126 or char == '\n':
            out.append(char)
        elif char == '\t':
            out.append(' ')
        elif char in REPLACEMENTS:
            out.append(REPLACEMENTS[char])
        elif (code < 32 or code == 127 or 0x80 <= code <= 0x9f or
              code in (0x200b, 0x200c, 0x200d, 0x2060, 0xfeff, 0x20e3) or
              0xfe00 <= code <= 0xfe0f or 0xe0020 <= code <= 0xe007f or
              0x1f000 <= code <= 0x1faff or 0x2600 <= code <= 0x27bf):
            continue
        else:
            out.append(('\\u%04x' if code <= 0xffff else '\\U%08x') % code)
    result = ''.join(out)
    if text.strip() and not result.strip():
        return '[Non-ASCII content omitted]'
    return result

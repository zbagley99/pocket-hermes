"""Buffered terminal rendering with request landmarks and stable scrollback."""
from ascii_text import display_ascii

BG = 0x0B1118
PANEL = 0x111C27
TEXT = 0xDFE7EF
MUTED = 0x8094A6
ACCENT = 0x65D9C0
RULE = 0x243746
GREEN = 0x54D67A
RED = 0xEF6262


class TextView:
    def __init__(self, display, width=240, height=135, max_lines=200):
        self.display = display
        self.width, self.height, self.max_lines = width, height, max_lines
        self.line_height = 16
        self.body_y = 14
        self.body_h = height - self.body_y - 14
        self.visible = self.body_h // self.line_height
        self.footer_y = self.body_y + self.body_h
        self.lines, self.roles, self.request_starts = [], [], []
        self.base = self.top = 0
        self.follow = True
        self.status = 'Ready'
        self.connected = False
        self.battery = None
        self.unread = 0
        self.title = 'H E R M E S'
        self.hint = None
        self.delegation = 'idle'
        self._reply = None
        self._header_key = self._body_key = self._footer_key = None
        # Allocate once. The panel never sees a cleared intermediate frame.
        self.header = display.newCanvas(w=width, h=self.body_y, bpp=16, psram=True)
        self.body = display.newCanvas(w=width, h=self.body_h, bpp=16, psram=True)
        self.footer = display.newCanvas(w=width, h=height-self.footer_y, bpp=16, psram=True)
        for canvas in (self.header, self.body, self.footer):
            canvas.setTextSize(1)
        self.body.setFont(display.FONTS.DejaVu12)
        self.header.setFont(display.FONTS.DejaVu9)
        self.header.setTextSize(0.9)
        self.footer.setFont(display.FONTS.DejaVu9)
        self.footer.setTextSize(0.9)

    def wrap(self, text):
        lines = []
        for paragraph in display_ascii(text).split('\n'):
            line = ''
            for word in paragraph.split():
                candidate = (line + ' ' + word) if line else word
                if self.body.textWidth(candidate) <= self.width - 20:
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                    line = ''
                for char in word:
                    if line and self.body.textWidth(line + char) > self.width - 20:
                        lines.append(line)
                        line = ''
                    line += char
            lines.append(line)
        return lines

    def _trim(self):
        removed = max(0, len(self.lines) - self.max_lines)
        if removed:
            del self.lines[:removed]
            del self.roles[:removed]
            self.base += removed
            self.top = max(0, self.top - removed)
        self.request_starts = [p for p in self.request_starts if p >= self.base]
        self.top = min(self.top, max(0, len(self.lines)-self.visible))
        if self.follow:
            self.top = max(0, len(self.lines)-self.visible)

    def append(self, text, role='assistant'):
        wrapped = self.wrap(text)
        self.lines.extend(wrapped)
        self.roles.extend([role] * len(wrapped))
        self._trim()

    def add_request(self, text):
        self.finish_reply()
        if self.lines and self.lines[-1]:
            self.append('', 'gap')
        self.request_starts.append(self.base + len(self.lines))
        self.append('> ' + text, 'user')

    def begin_reply(self):
        if self._reply is None:
            self._reply = (self.lines[:], self.roles[:], self.base, self.request_starts[:])

    def update_reply(self, text):
        self.begin_reply()
        anchor = self.base + self.top
        lines, roles, base, markers = self._reply
        wrapped = self.wrap(text)
        self.lines = lines + wrapped
        self.roles = roles + ['assistant'] * len(wrapped)
        self.base = base
        self.top = max(0, anchor - base)
        self.request_starts = markers[:]
        self._trim()

    def finish_reply(self):
        self._reply = None

    def scroll(self, delta):
        bottom = max(0, len(self.lines)-self.visible)
        self.top = min(bottom, max(0, self.top+delta))
        self.follow = self.top == bottom

    def bottom(self):
        self.top = max(0, len(self.lines)-self.visible)
        self.follow = True

    def previous_request(self):
        anchor = self.base + self.top
        before = [p for p in self.request_starts if p < anchor]
        self.top = max(0, (before[-1] - self.base) if before else 0)
        self.top = min(self.top, max(0, len(self.lines)-self.visible))
        self.follow = False

    def _fit(self, canvas, text, width):
        text = display_ascii(text).replace('\n', ' ')
        if canvas.textWidth(text) <= width:
            return text
        while text and canvas.textWidth(text + '...') > width:
            text = text[:-1]
        return text + '...'

    @staticmethod
    def _bar_text(canvas, text, x, y, color):
        canvas.setTextColor(color, PANEL)
        canvas.drawString(text, x, y)

    def draw(self):
        header_key = (self.connected, self.battery, self.unread, self.title)
        if header_key != self._header_key:
            c = self.header
            c.fillRect(0, 0, self.width, self.body_y, PANEL)
            c.fillRect(0, 0, 3, self.body_y-1, ACCENT)
            self._bar_text(c, self._fit(c, self.title, 100), 9, 0, TEXT)
            if self.unread:
                self._bar_text(c, str(min(self.unread, 99)) + ' NEW', 113, 0, ACCENT)
            level = self.battery
            label = '--%' if level is None else str(level) + '%'
            color = RED if level is not None and level <= 20 else TEXT
            c.setTextColor(color, PANEL)
            c.drawRightString(label, self.width-44, 0)
            x = self.width-39
            c.fillRect(x, 2, 17, 9, color)
            c.fillRect(x+1, 3, 15, 7, PANEL)
            c.fillRect(x+17, 5, 2, 3, color)
            if level is not None:
                c.fillRect(x+2, 4, 13*level//100, 5, color)
            c.fillCircle(self.width-8, 6, 3, GREEN if self.connected else RED)
            c.drawLine(0, self.body_y-1, self.width-1, self.body_y-1, RULE)
            c.push(0, 0)
            self._header_key = header_key
        visible = tuple(zip(self.lines[self.top:self.top+self.visible], self.roles[self.top:self.top+self.visible]))
        body_key = (visible, self.top, len(self.lines))
        if body_key != self._body_key:
            c = self.body
            c.fillRect(0, 0, self.width, self.body_h, BG)
            for row, (line, role) in enumerate(visible):
                color = ACCENT if role == 'user' else (MUTED if role == 'system' else TEXT)
                c.setTextColor(color, BG)
                c.drawString(display_ascii(line), 8, row*self.line_height+1)
            if len(self.lines) > self.visible:
                rail_h = self.body_h-8
                thumb = max(6, rail_h*self.visible//len(self.lines))
                pos = (rail_h-thumb)*self.top//max(1, len(self.lines)-self.visible)
                c.fillRect(self.width-4, 4, 2, rail_h, RULE)
                c.fillRect(self.width-4, 4+pos, 2, thumb, ACCENT)
            c.push(0, self.body_y)
            self._body_key = body_key
        right = self.hint or {'idle': 'SUB --', 'active': 'SUB...', 'returned': 'SUB sent', 'failed': 'SUB !', 'unknown': 'SUB ?'}.get(self.delegation, 'SUB ?')
        footer_key = (display_ascii(self.status), right)
        if footer_key != self._footer_key:
            c = self.footer
            c.fillRect(0, 0, self.width, self.height-self.footer_y, PANEL)
            c.drawLine(0, 0, self.width-1, 0, RULE)
            right_w = c.textWidth(right)
            self._bar_text(c, self._fit(c, self.status, self.width-right_w-26), 8, 1, MUTED)
            color = RED if self.delegation == 'failed' else (ACCENT if self.delegation == 'active' else MUTED)
            self._bar_text(c, right, self.width-9-right_w, 1, color)
            c.push(0, self.footer_y)
            self._footer_key = footer_key

    def close(self):
        for canvas in (self.header, self.body, self.footer):
            canvas.delete()

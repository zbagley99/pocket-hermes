"""Button arbitration: a chord suppresses individual holds until release."""
class Controls:
    def __init__(self):
        self.chord_start = None
        self.latched = False

    def update(self, a, b, now, diff):
        if a.isPressed() and b.isPressed():
            if self.chord_start is None:
                self.chord_start = now
            if not self.latched and diff(now, self.chord_start) >= 900:
                self.latched = True
                return 'new_chat'
            return 'chord'
        if self.chord_start is not None:
            if not a.isPressed() and not b.isPressed():
                self.chord_start = None
                self.latched = False
            return 'chord'
        if b.pressedFor(1200):
            return 'wifi'
        if a.wasDoubleClicked():
            return 'previous'
        if b.wasDoubleClicked():
            return 'bottom'
        if a.wasSingleClicked():
            return 'down'
        if b.wasSingleClicked():
            return 'up'
        if a.pressedFor(500):
            return 'record'
        return None

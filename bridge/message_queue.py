"""Bounded SQLite outbox/inbox sharing the bridge's private transaction boundary."""
import os


class MessageQueue:
    def __init__(self, db):
        self.db = db
        db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, session_id TEXT)')
        db.execute('''CREATE TABLE IF NOT EXISTS messages (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT UNIQUE NOT NULL,
            conversation TEXT NOT NULL, unread INTEGER NOT NULL DEFAULT 0,
            expired INTEGER NOT NULL DEFAULT 0)''')
        db.execute('CREATE TABLE IF NOT EXISTS queue_jobs (turn_id TEXT PRIMARY KEY, audio BLOB, input_text TEXT)')
        db.commit()

    def current(self):
        row = self.db.execute("SELECT value FROM state WHERE key='conversation_id'").fetchone()
        if row:
            return row[0]
        previous = self.db.execute("SELECT value FROM state WHERE key='session_id'").fetchone()
        ident = os.urandom(16).hex()
        self.db.execute('INSERT INTO conversations VALUES (?,?)', (ident, previous[0] if previous else None))
        self.db.execute("INSERT INTO state VALUES ('conversation_id',?)", (ident,))
        return ident

    def select(self, conversation=None):
        if conversation is None:
            conversation = os.urandom(16).hex()
            self.db.execute('INSERT INTO conversations VALUES (?,NULL)', (conversation,))
        row = self.db.execute('SELECT session_id FROM conversations WHERE id=?', (conversation,)).fetchone()
        if row is None:
            raise ValueError('Unknown conversation')
        self.db.execute("INSERT OR REPLACE INTO state VALUES ('conversation_id',?)", (conversation,))
        self.db.execute("DELETE FROM state WHERE key='session_id'")
        if row[0]:
            self.db.execute("INSERT INTO state VALUES ('session_id',?)", (row[0],))
        return conversation

    def conversation(self, tid):
        row = self.db.execute('SELECT conversation FROM messages WHERE turn_id=?', (tid,)).fetchone()
        return row[0] if row else None

    def session(self, conversation):
        return self.db.execute('SELECT session_id FROM conversations WHERE id=?', (conversation,)).fetchone()[0]

    def save_session(self, conversation, sid):
        self.db.execute('UPDATE conversations SET session_id=? WHERE id=?', (sid, conversation))
        if self.current() == conversation:
            self.db.execute("INSERT OR REPLACE INTO state VALUES ('session_id',?)", (sid,))

    def add(self, tid, audio, text, conversation=None):
        self.db.execute('INSERT INTO messages (turn_id,conversation) VALUES (?,?)', (tid, conversation or self.current()))
        self.db.execute('INSERT INTO queue_jobs VALUES (?,?,?)', (tid, audio, text))

    def next_job(self):
        return self.db.execute('''SELECT q.turn_id,q.audio,q.input_text FROM queue_jobs q
            JOIN turns t ON t.id=q.turn_id JOIN messages m ON m.turn_id=q.turn_id
            WHERE t.status='queued' ORDER BY m.seq LIMIT 1''').fetchone()

    def pending_count(self):
        return self.db.execute("SELECT count(*) FROM messages m JOIN turns t ON t.id=m.turn_id WHERE t.status NOT IN ('done','error')").fetchone()[0]

    def unread_count(self):
        return self.db.execute('SELECT count(*) FROM messages WHERE unread=1 AND expired=0').fetchone()[0]

    def metadata(self, tid):
        row = self.db.execute('SELECT seq,conversation,unread,expired FROM messages WHERE turn_id=?', (tid,)).fetchone()
        if row:
            return dict(sequence=row[0], conversation=row[1], unread=bool(row[2]), expired=bool(row[3]), durable=True)
        return {}

    def complete(self, tid):
        self.db.execute('UPDATE messages SET unread=1 WHERE turn_id=? AND expired=0', (tid,))
        self.db.execute('DELETE FROM queue_jobs WHERE turn_id=?', (tid,))

    def read(self, tid):
        self.db.execute('UPDATE messages SET unread=0 WHERE turn_id=?', (tid,))

    def expire(self, cutoff):
        self.db.execute("""UPDATE messages SET expired=1,unread=0 WHERE turn_id IN
            (SELECT id FROM turns WHERE created < ? AND status IN ('done','error'))""", (cutoff,))

    def page(self, before=0, unread_only=False):
        rows = self.db.execute('''SELECT m.seq,m.turn_id FROM messages m
            WHERE m.expired=0 AND (?=0 OR m.seq < ?) AND (?=0 OR m.unread=1)
            ORDER BY m.seq DESC LIMIT 9''', (before, before, int(unread_only))).fetchall()
        return [row[1] for row in rows[:8]], rows[7][0] if len(rows) > 8 else None

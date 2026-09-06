"""One network operation at a time, keeping buttons and drawing responsive."""
import _thread
import time

class NetWorker:
    def __init__(self, client):
        self.client = client
        self.lock = _thread.allocate_lock()
        self.job = self.result = None
        self.busy = False
        _thread.stack_size(16384)
        _thread.start_new_thread(self.run, ())

    def submit(self, kind, method, path, body=b'', content_type='application/json'):
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            self.job = (kind, method, path, body, content_type)
        return True

    def take(self):
        with self.lock:
            result = self.result
            if result is not None:
                self.result = None
                self.busy = False
            return result

    def run(self):
        while True:
            with self.lock:
                job = self.job
                self.job = None
            if job:
                kind, method, path, body, content_type = job
                try:
                    result = (kind, self.client.request(method, path, body, content_type), None)
                except Exception as exc:
                    result = (kind, None, exc)
                body = job = None
                with self.lock:
                    self.result = result
            time.sleep_ms(20)

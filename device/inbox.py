"""Small, explicit inbox UI. Reading never acknowledges a reply automatically."""


class Inbox:
    def __init__(self, view):
        self.view = view
        self.active = False
        self.mode = 'list'
        self.selection = 0
        self.items = []
        self.options = []
        self.before = 0
        self.next_before = None
        self.unread_only = True
        self.message = None
        self.detail_top = 0
        self.job = None
        self.home = None
        self.loading = False
        self.generation = 0

    def clear(self):
        v = self.view
        v.finish_reply()
        v.lines, v.roles, v.request_starts = [], [], []
        v.top = v.base = 0
        v.follow = False
        v.delegation = 'idle'

    def open(self, unread_only=True):
        if not self.active:
            v = self.view
            self.home = (v.lines, v.roles, v.request_starts, v.top, v.base, v.follow, v.status)
        self.active = True
        self.unread_only = unread_only
        self.before = 0
        self.list_page()

    def close(self):
        self.generation += 1
        self.active = False
        self.job = None
        self.loading = False
        v = self.view
        self.clear()
        v.max_lines = 200
        v.title = 'H E R M E S'
        v.hint = None
        if self.home:
            v.lines, v.roles, v.request_starts, v.top, v.base, v.follow, v.status = self.home
        self.home = None

    def request(self, kind, method, path):
        self.generation += 1
        self.job = (kind, method, path)
        self.loading = True

    def list_page(self):
        self.mode = 'list'
        self.selection = 0
        self.items = []
        self.options = []
        self.clear()
        self.view.title = 'INBOX'
        self.view.hint = 'hold B: back'
        self.view.status = 'Loading messages'
        self.request('list', 'GET', '/inbox?before=%d&unread=%d' % (self.before, self.unread_only))

    def menu(self):
        self.clear()
        v = self.view
        v.max_lines = 200
        for index, (label, _) in enumerate(self.options):
            # One row per choice, even for a long speech preview.
            label = v._fit(v.body, label, v.width - 34)
            v.append(('> ' if index == self.selection else '  ') + label, 'user' if index == self.selection else 'system')
        v.top = max(0, self.selection - v.visible + 1)
        v.status = 'A/B: move'
        v.hint = 'hold A: select'

    def show_list(self, result):
        self.items = result['items']
        self.next_before = result.get('next_before')
        self.view.unread = result.get('unread', 0)
        self.view.title = 'NEW MESSAGES' if self.unread_only else 'INBOX'
        self.options = []
        for item in self.items:
            prefix = '* ' if item['unread'] else ''
            if item['status'] not in ('done', 'error'):
                prefix = '[waiting] '
            elif item['status'] == 'error':
                prefix += '[error] '
            self.options.append((prefix + item['preview'], ('detail', item['id'])))
        if self.next_before:
            self.options.append(('Older messages', ('older', None)))
        self.options.extend([
            ('Show all messages' if self.unread_only else 'Show unread only', ('filter', None)),
            ('Refresh / newest', ('refresh', None)),
            ('Back to current chat', ('close', None)),
            ('Start new chat', ('new_chat', None)),
        ])
        self.selection = min(self.selection, len(self.options) - 1)
        self.menu()
        if not self.items:
            self.view.status = 'No unread replies' if self.unread_only else 'Inbox empty'

    def show_message(self, result):
        refresh = (self.mode == 'detail' and self.message and self.message['id'] == result['id']
                   and self.message.get('transcript') == result.get('transcript'))
        self.mode = 'detail'
        self.message = result
        v = self.view
        v.title = 'MESSAGE'
        v.hint = 'hold A: menu'
        if not refresh:
            self.clear()
            v.max_lines = 1000
            v.add_request(result.get('transcript') or '(voice message)')
        v.update_reply(result.get('text') or 'Waiting for the reply. You can turn off the Stick after delivery is confirmed.')
        v.status = 'Reply ready' if result['status'] == 'done' else ('Request error' if result['status'] == 'error' else 'Saved on Pi / waiting')

    def actions(self):
        self.detail_top = self.view.top
        self.mode = 'actions'
        self.selection = 0
        self.view.title = 'MESSAGE ACTIONS'
        self.options = []
        if self.message['status'] in ('done', 'error') and not self.message.get('expired'):
            self.options.extend([('Continue this chat', ('resume', self.message['id'])),
                                 ('Mark read', ('read', self.message['id']))])
        self.options.extend([('Back to message', ('detail', self.message['id'])),
                             ('Back to inbox', ('refresh', None)),
                             ('Start new chat', ('new_chat', None))])
        self.menu()

    def handle(self, event):
        """Return an explicit session action to the application, or queue a read."""
        if event == 'wifi':
            self.generation += 1
            self.job = None
            self.loading = False
            if self.mode == 'list':
                self.close()
            elif self.mode == 'actions':
                self.show_message(self.message)
                self.view.scroll(self.detail_top)
            else:
                self.list_page()
            return None
        if self.loading and self.mode != 'detail':
            return None
        if self.mode == 'detail':
            if event == 'down':
                self.view.scroll(1)
            elif event == 'up':
                self.view.scroll(-1)
            elif event == 'bottom':
                self.list_page()
            elif event == 'previous':
                self.view.top = 0
                self.view.follow = False
            elif event in ('record', 'new_chat') and not self.loading:
                self.actions()
        elif event in ('down', 'up'):
            self.selection = (self.selection + (1 if event == 'down' else -1)) % len(self.options)
            self.menu()
        elif event == 'record':
            action, ident = self.options[self.selection][1]
            if action == 'detail':
                self.request('detail', 'GET', '/turn/' + ident)
            elif action == 'read':
                self.request('read', 'POST', '/inbox/' + ident + '/read')
            elif action == 'older':
                self.before = self.next_before
                self.list_page()
            elif action in ('refresh', 'filter'):
                self.before = 0
                if action == 'filter':
                    self.unread_only = not self.unread_only
                self.list_page()
            elif action == 'close':
                self.close()
            else:
                return action, ident
        return None

    def complete(self, kind, result, error):
        self.loading = False
        if error:
            self.view.status = 'Inbox unavailable / retry'
            # Offer a way out after failures, including the first list request.
            if not self.options:
                self.options = [('Retry inbox', ('refresh', None)), ('Back to chat', ('close', None))]
                self.menu()
                self.view.status = 'Inbox unavailable / retry'
            return
        if kind == 'list':
            self.show_list(result)
        elif kind == 'detail':
            from_actions = self.mode == 'actions'
            self.show_message(result)
            if from_actions:
                self.view.scroll(self.detail_top)
        elif kind == 'read':
            self.view.unread = result.get('unread', 0)
            self.list_page()

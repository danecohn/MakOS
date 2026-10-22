"""org.freedesktop.Notifications server with original glass banners. GPL-3.0-only.

* ``Model``      pure logic (ids, replace, sync tags, hints, actions, expiry, Do Not Disturb, history,
                 markup stripping). No GTK/D-Bus, covered by tests/test_makos_theme.py.
* ``Notifications``  D-Bus object + layer-shell banner stack (top-right) + history popover content.

Spec 1.2 features: summary/body (markup is reduced to plain text, never rendered as markup),
app icon name/path and ``image-data``/``image-path`` hints, actions (``default`` = click the banner),
``value`` progress hint, urgency (critical never expires and passes Do Not Disturb), ``transient``,
``resident``, ``replaces_id``, sync tags (volume-style replace), ``sound-name``, KDE-style inline
reply (``x-kde-reply-placeholder-text`` + action ``inline-reply`` -> ``NotificationReplied`` signal).
Badge counts for the launcher go to ``makos.badges.default``.
"""
import html
import os
import re
import shutil
import subprocess
import threading
import time
from . import badges

MAX_ACTIONS = 8
MAX_STACK = 4
DEFAULT_TIMEOUT_MS = 6000
BUS_NAME = 'org.freedesktop.Notifications'
PATH = '/org/freedesktop/Notifications'
IFACE = 'org.freedesktop.Notifications'
CAPABILITIES = ['body', 'actions', 'persistence', 'icon-static', 'inline-reply', 'sound', 'action-icons']
SYNC_HINTS = ('x-canonical-private-synchronous', 'synchronous', 'x-dunst-stack-tag')
_TAG = re.compile(r'<[^>]{0,200}>')

XML = '''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationReplied"><arg type="u"/><arg type="s"/></signal>
<signal name="ActivationToken"><arg type="u"/><arg type="s"/></signal>
</interface></node>'''

CLOSED_EXPIRED, CLOSED_DISMISSED, CLOSED_BY_CALL, CLOSED_UNDEFINED = 1, 2, 3, 4


def plain(text, limit):
    """Notification text is untrusted: remove tags, decode entities, drop control characters."""
    text = html.unescape(_TAG.sub('', str(text)))[:limit]
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)


def ago(now, then):
    seconds = max(0, int(now - then))
    if seconds < 45:
        return 'now'
    if seconds < 3600:
        return '%d min ago' % max(1, seconds // 60)
    if seconds < 86400:
        return '%d h ago' % (seconds // 3600)
    return 'yesterday' if seconds < 172800 else '%d days ago' % (seconds // 86400)


def parse_actions(raw):
    pairs = []
    raw = [str(x) for x in (raw or [])]
    for i in range(0, len(raw) - 1, 2):
        key, label = raw[i][:64], plain(raw[i + 1], 60)
        if key:
            pairs.append((key, label))
    return pairs[:MAX_ACTIONS]


def clean_image(data):
    """Validate an image-data struct (iiibiiay); returns a dict or None. Bounded so a hostile app cannot allocate."""
    try:
        width, height, stride, alpha, bits, channels, pixels = data
        pixels = bytes(pixels)
    except (TypeError, ValueError):
        return None
    if not (0 < width <= 512 and 0 < height <= 512 and bits == 8 and channels == (4 if alpha else 3)):
        return None
    if stride < width * channels or len(pixels) < stride * (height - 1) + width * channels:
        return None
    return {'w': width, 'h': height, 'stride': stride, 'alpha': bool(alpha), 'data': pixels}


class Model:
    def __init__(self, now=time.time, known_apps=()):
        self.now = now
        self.known = tuple(known_apps)
        self.next_id = 1
        self.items = {}      # active banners: id -> item
        self.history = []    # newest last, capped
        self.silent = False
        self.sync = {}       # (sender, tag) -> id

    def _new_id(self):
        ident = self.next_id
        self.next_id = self.next_id + 1 if self.next_id < 0xFFFFFFFF else 1
        return ident

    def notify(self, sender, name, replaces, icon, summary, body, actions, hints, timeout):
        """Returns (item, show, replaced)."""
        hints = hints if isinstance(hints, dict) else {}
        urgency = hints.get('urgency', 1)
        urgency = urgency if urgency in (0, 1, 2) else 1
        tag = next((str(hints[h]) for h in SYNC_HINTS if hints.get(h)), None)
        ident = None
        if replaces and replaces in self.items and self.items[replaces]['sender'] == sender:
            ident = replaces
        elif tag and (sender, tag) in self.sync and self.sync[(sender, tag)] in self.items:
            ident = self.sync[(sender, tag)]
        replaced = ident is not None
        if ident is None:
            ident = self._new_id()
        if tag:
            self.sync[(sender, tag)] = ident
        pairs = parse_actions(actions)
        value = hints.get('value')
        value = max(0, min(100, int(value))) if isinstance(value, int) and not isinstance(value, bool) else None
        desktop = plain(hints.get('desktop-entry', ''), 120)
        reply = plain(hints.get('x-kde-reply-placeholder-text', ''), 80) if any(k == 'inline-reply' for k, _ in pairs) else None
        icon = str(hints.get('image-path') or icon or '')[:300]
        if timeout is None or timeout < 0:
            ttl = None if urgency == 2 else DEFAULT_TIMEOUT_MS
        elif timeout == 0:
            ttl = None
        else:
            ttl = max(1500, min(timeout, 60000))
        item = {'id': ident, 'sender': sender, 'name': plain(name, 100), 'app_id': badges.app_id_from_desktop(desktop or name, self.known),
                'desktop_entry': desktop, 'summary': plain(summary, 300), 'body': plain(body, 2000), 'icon': plain(icon, 300),
                'image': clean_image(hints.get('image-data') or hints.get('image_data') or hints.get('icon_data')),
                'actions': [(k, l) for k, l in pairs if k not in ('default', 'inline-reply')],
                'default_action': any(k == 'default' for k, _ in pairs), 'reply': reply, 'value': value, 'urgency': urgency,
                'transient': bool(hints.get('transient')), 'resident': bool(hints.get('resident')),
                'category': plain(hints.get('category', ''), 60), 'time': self.now(), 'ttl': ttl, 'seq': ident,
                'sound': None if hints.get('suppress-sound') else plain(hints.get('sound-name', ''), 80)}
        show = not (self.silent and urgency < 2)
        if not item['summary'] and not item['body']:
            show = False
        if show:
            self.items[ident] = item
        else:
            self.items.pop(ident, None)
        if not item['transient']:
            record = {k: v for k, v in item.items() if k != 'image'}
            self.history = [h for h in self.history if not (replaced and h['id'] == ident)] + [record]
            self.history = self.history[-100:]
        return item, show, replaced

    def close(self, ident, reason=CLOSED_BY_CALL):
        item = self.items.pop(ident, None)
        if item:
            for key in [k for k, v in self.sync.items() if v == ident]:
                self.sync.pop(key, None)
        return item

    def visible(self):
        """Banners to draw: newest MAX_STACK, plus how many are hidden behind them."""
        ordered = sorted(self.items.values(), key=lambda i: i['seq'])
        shown = ordered[-MAX_STACK:]
        return shown, len(ordered) - len(shown)

    def clear_history(self, ident=None):
        before = len(self.history)
        self.history = [] if ident is None else [h for h in self.history if h['id'] != ident]
        return before - len(self.history)


def play_sound(name, which=shutil.which, popen=subprocess.Popen):
    """Play a freedesktop sound-theme event with canberra, detached. Returns True if started."""
    if os.environ.get('MAKOS_NO_SOUND') or not name or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', name):
        return False
    exe = which('canberra-gtk-play')
    if not exe:
        return False
    try:
        proc = popen([exe, '-i', name, '-d', 'MakkOS'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    threading.Thread(target=proc.wait, daemon=True).start()  # reap exactly this child
    return True


class Notifications:
    """D-Bus server plus the banner stack. ``items``, ``history``, ``silent``, ``window`` keep their old meaning."""

    def __init__(self, app):
        from gi.repository import Gio, GLib
        self._Gio, self._GLib = Gio, GLib
        self.app = app
        self.conn = app.bus
        try:
            from . import catalog
            known = [a.id for a in catalog.APPS]
        except Exception:
            known = []
        self.model = Model(known_apps=known)
        self.window = None
        self.cards = {}
        self.timers = {}
        self.hovered = set()
        self.more = None
        self.registration = self.conn.register_object(PATH, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.handle, None, None)
        self.owner = Gio.bus_own_name_on_connection(self.conn, BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
        badges.default.attach(self.conn, known)

    # ---- state shared with the shell
    items = property(lambda self: self.model.items)
    history = property(lambda self: self.model.history)

    @property
    def silent(self):
        return self.model.silent

    @silent.setter
    def silent(self, value):
        self.model.silent = bool(value)
        if self.model.silent:  # entering Do Not Disturb hides non-critical banners at once
            for ident in [i for i, it in self.model.items.items() if it['urgency'] < 2]:
                self.close(ident, CLOSED_UNDEFINED)
        self.render()

    # ---- D-Bus
    def emit(self, item_sender, signal, fmt, values):
        try:
            self.conn.emit_signal(item_sender, PATH, IFACE, signal, self._GLib.Variant(fmt, values))
        except self._GLib.Error:
            pass

    def handle(self, _conn, sender, _path, _iface, method, params, invocation):
        GLib = self._GLib
        if method == 'GetCapabilities':
            invocation.return_value(GLib.Variant('(as)', (CAPABILITIES,)))
        elif method == 'GetServerInformation':
            invocation.return_value(GLib.Variant('(ssss)', ('Makk OS Notifications', 'MakkOS', '0.2.0', '1.2')))
        elif method == 'CloseNotification':
            ident = params.unpack()[0]
            item = self.model.items.get(ident)
            if item and item['sender'] == sender:
                self.close(ident, CLOSED_BY_CALL)
            invocation.return_value(None)
        elif method == 'Notify':
            try:
                name, replaces, icon, summary, body, actions, hints, timeout = params.unpack()
            except (ValueError, TypeError):
                return invocation.return_error_literal(self._Gio.dbus_error_quark(), self._Gio.DBusError.INVALID_ARGS, 'bad arguments')
            item, show, replaced = self.model.notify(sender, name, replaces, icon, summary, body, actions, hints, timeout)
            if item['app_id'] and not replaced:
                badges.default.add(item['app_id'])
            invocation.return_value(GLib.Variant('(u)', (item['id'],)))
            if show:
                self.arm(item)
                self.render()
                if item['sound'] is not None and item['sound'] != '':
                    play_sound(item['sound'])
                elif item['sound'] is not None and not self.model.silent:
                    play_sound('dialog-warning' if item['urgency'] == 2 else 'message-new-instant')
            else:
                GLib.idle_add(lambda i=item: (self.emit(i['sender'], 'NotificationClosed', '(uu)', (i['id'], CLOSED_UNDEFINED)), False)[1])

    # ---- lifecycle
    def arm(self, item):
        GLib = self._GLib
        old = self.timers.pop(item['id'], None)
        if old:
            GLib.source_remove(old)
        if item['ttl'] is not None:
            stamp = item['time']
            self.timers[item['id']] = GLib.timeout_add(item['ttl'], lambda i=item['id']: self.expire(i, stamp))

    def expire(self, ident, stamp):
        self.timers.pop(ident, None)
        item = self.model.items.get(ident)
        if item and item['time'] == stamp:
            if ident in self.hovered:  # the pointer is on it: keep it
                self.timers[ident] = self._GLib.timeout_add(2000, lambda: self.expire(ident, stamp))
            else:
                self.close(ident, CLOSED_EXPIRED)
        return False

    def close(self, ident, reason):
        timer = self.timers.pop(ident, None)
        if timer:
            self._GLib.source_remove(timer)
        self.hovered.discard(ident)
        item = self.model.close(ident, reason)
        if item:
            self.emit(item['sender'], 'NotificationClosed', '(uu)', (ident, reason))
            self.render()

    def action(self, item, key):
        self.emit(item['sender'], 'ActionInvoked', '(us)', (item['id'], key))
        if not item['resident']:
            self.close(item['id'], CLOSED_DISMISSED)

    def reply(self, item, text):
        text = plain(text, 2000).strip()
        if text:
            self.emit(item['sender'], 'NotificationReplied', '(us)', (item['id'], text))
            self.close(item['id'], CLOSED_DISMISSED)

    def clear_history(self, ident=None):
        for entry in list(self.model.history):
            if ident in (None, entry['id']) and entry.get('app_id'):
                badges.default.set(entry['app_id'], max(0, badges.default.get(entry['app_id']) - 1))
        self.model.clear_history(ident)

    # ---- banner stack
    def render(self):
        from gi.repository import Gtk
        from . import ui
        from .shell import layer
        shown, hidden = self.model.visible()
        if not shown:
            self.cards.clear()
            if self.window:
                self.window.destroy()
                self.window = None
            return
        if self.window is None:
            self.window = self.app.surface('Notifications', 'overlay', ('top', 'right'), keyboard='on_demand')
            layer.LS.set_margin(self.window, layer.LS.Edge.TOP, 42)
            layer.LS.set_margin(self.window, layer.LS.Edge.RIGHT, 18)
            self.column = ui.box(True, 10, 'banner-stack')
            self.window.set_child(self.column)
        want = {i['id'] for i in shown}
        for ident in [i for i in self.cards if i not in want]:
            self.column.remove(self.cards.pop(ident))
        previous = None
        for item in shown:
            card = self.cards.get(item['id'])
            fresh = card is None or card._stamp != item['time']
            if fresh:
                if card is not None:
                    self.column.remove(card)
                card = self.build_card(item)
                card._stamp = item['time']
                self.cards[item['id']] = card
                self.column.insert_child_after(card, previous)
            previous = card
        if self.more is not None:
            self.column.remove(self.more)
            self.more = None
        if hidden:
            self.more = Gtk.Label(label='+%d more in Alerts' % hidden, css_classes=['banner-more'])
            self.column.append(self.more)
        self.window.present()

    def build_card(self, item):
        from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
        from . import ui
        card = ui.box(True, 6, 'banner')
        card.set_size_request(360, -1)
        if item['urgency'] == 2:
            card.add_css_class('critical')
        top = ui.box(spacing=10)
        icon = self.icon_widget(item)
        if icon:
            top.append(icon)
        text = ui.box(True, 2)
        text.set_hexpand(True)
        app = Gtk.Label(label=item['name'].upper() or 'NOTIFICATION', xalign=0, css_classes=['banner-app'])
        title = Gtk.Label(label=item['summary'] or item['name'], xalign=0, wrap=True, max_width_chars=34, css_classes=['banner-title'])
        text.append(app)
        text.append(title)
        if item['body']:
            text.append(Gtk.Label(label=item['body'], xalign=0, wrap=True, max_width_chars=40, lines=6, ellipsize=3, css_classes=['banner-body']))
        top.append(text)
        close = Gtk.Button(label='×', valign=Gtk.Align.START, css_classes=['banner-close', 'flat'])
        close.set_tooltip_text('Dismiss')
        close.connect('clicked', lambda *_: self.close(item['id'], CLOSED_DISMISSED))
        top.append(close)
        card.append(top)
        if item['value'] is not None:
            bar = Gtk.ProgressBar(fraction=item['value'] / 100.0)
            bar.add_css_class('banner-progress')
            card.append(bar)
        if item['reply'] is not None:
            row = ui.box(spacing=6)
            entry = Gtk.Entry(placeholder_text=item['reply'] or 'Reply', hexpand=True)
            send = ui.button('Send', lambda: self.reply(item, entry.get_text()), 'suggested-action')
            entry.connect('activate', lambda *_: self.reply(item, entry.get_text()))
            row.append(entry)
            row.append(send)
            card.append(row)
        if item['actions']:
            row = ui.box(spacing=6, css='banner-actions')
            row.set_halign(Gtk.Align.END)
            for n, (key, label) in enumerate(item['actions']):
                row.append(ui.button(label or key, lambda k=key: self.action(item, k), 'suggested-action' if n == 0 else None))
            card.append(row)
        click = Gtk.GestureClick()
        if item['default_action']:
            click.connect('released', lambda *_: self.action(item, 'default'))
            card.set_cursor_from_name('pointer')
        card.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect('enter', lambda *_: self.hovered.add(item['id']))
        motion.connect('leave', lambda *_: self.hovered.discard(item['id']))
        card.add_controller(motion)
        return card

    def icon_widget(self, item):
        from gi.repository import Gtk, Gdk, GLib
        image = item['image']
        if image:
            try:
                from gi.repository import GdkPixbuf
                pix = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(image['data']), GdkPixbuf.Colorspace.RGB, image['alpha'], 8,
                                                      image['w'], image['h'], image['stride'])
                widget = Gtk.Image.new_from_paintable(Gdk.Texture.new_for_pixbuf(pix))
                widget.set_pixel_size(40)
                widget.add_css_class('banner-icon')
                return widget
            except GLib.Error:
                pass
        name = item['icon']
        if name.startswith('file://'):
            name = name[7:]
        widget = None
        if name.startswith('/'):
            if os.path.isfile(name) and os.path.getsize(name) < 5_000_000:
                widget = Gtk.Image.new_from_file(name)
        elif name:
            widget = Gtk.Image.new_from_icon_name(name)
        if widget is None:
            from . import ui
            app_id = item['app_id']
            widget = ui.icon(app_id, 40) if app_id and os.path.exists(str(ui.common.SHARE / 'icons/MakkOS/128x128/apps' / (app_id + '.png'))) else Gtk.Image.new_from_icon_name('makos-makos-logo')
        widget.set_pixel_size(40)
        widget.add_css_class('banner-icon')
        return widget

    # ---- history popover (the Alerts menu in the bar)
    def fill_menu(self, col, pop=None):
        from gi.repository import Gtk
        from . import ui
        head = ui.box(spacing=10)
        head.append(Gtk.Label(label='Alerts', xalign=0, hexpand=True, css_classes=['title-label']))
        head.append(Gtk.Label(label='Do Not Disturb'))
        dnd = Gtk.Switch(active=self.silent, valign=Gtk.Align.CENTER)
        dnd.connect('notify::active', lambda s, _p: setattr(self, 'silent', s.get_active()))
        head.append(dnd)
        col.append(head)
        col.append(Gtk.Separator(margin_top=6, margin_bottom=6))
        entries = list(reversed(self.model.history[-12:]))
        if not entries:
            col.append(Gtk.Label(label='No recent notifications', margin_top=12, margin_bottom=12, css_classes=['dim-label']))
            return
        listing = ui.box(True, 4)
        now = time.time()
        for entry in entries:
            row = ui.box(spacing=8, css='history-row')
            text = ui.box(True, 0)
            text.set_hexpand(True)
            text.append(Gtk.Label(label=entry['summary'] or entry['name'], xalign=0, wrap=True, max_width_chars=34, css_classes=['banner-title']))
            if entry['body']:
                text.append(Gtk.Label(label=entry['body'], xalign=0, wrap=True, max_width_chars=38, lines=2, ellipsize=3, css_classes=['banner-body']))
            text.append(Gtk.Label(label='%s  ·  %s' % (entry['name'] or 'App', ago(now, entry['time'])), xalign=0, css_classes=['banner-app']))
            row.append(text)
            gone = ui.button('×', lambda e=entry['id']: (self.clear_history(e), pop and pop.popdown()), 'flat')
            gone.set_valign(Gtk.Align.START)
            gone.set_tooltip_text('Remove')
            row.append(gone)
            listing.append(row)
        scroller = Gtk.ScrolledWindow(hexpand=True, min_content_height=min(300, 62 * len(entries)), max_content_height=360, propagate_natural_height=True)
        scroller.set_child(listing)
        col.append(scroller)
        col.append(Gtk.Separator(margin_top=6, margin_bottom=6))
        col.append(ui.button('Clear All', lambda: (self.clear_history(), pop and pop.popdown())))

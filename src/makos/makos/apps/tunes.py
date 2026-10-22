"""Tunes: music player over GStreamer with a library from ~/Music, queue, shuffle/repeat and MPRIS."""
import os
import random
import re
import threading
from dataclasses import dataclass
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .. import ui
from .base import AppWindow, clock_text
from .mpris import Mpris

AUDIO = {'.mp3', '.flac', '.ogg', '.oga', '.opus', '.wav', '.m4a', '.aac', '.wma', '.mka'}
MAX_TRACKS = 30000


@dataclass
class Track:
    path: Path
    title: str
    artist: str = ''
    album: str = ''
    seconds: float = 0.0

    @property
    def uri(self):
        return self.path.resolve().as_uri()


def tags_from_name(path):
    """Fallback when no tag library is available: 'Artist - Title.ext' or the file stem."""
    stem = Path(path).stem
    m = re.match(r'^\s*(?:\d+[ .-]+)?(.+?)\s+-\s+(.+)$', stem)
    parent = Path(path).parent.name
    return Track(Path(path), (m.group(2) if m else stem).strip(), m.group(1).strip() if m else '', parent if parent and parent != 'Music' else '')


def read_tags(path):
    """Tags via mutagen when installed; filename-derived otherwise."""
    track = tags_from_name(path)
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None:
            def first(key):
                v = (f.tags or {}).get(key)
                return str(v[0]) if v else ''
            track.title = first('title') or track.title
            track.artist = first('artist') or first('albumartist') or track.artist
            track.album = first('album') or track.album
            track.seconds = float(getattr(f.info, 'length', 0) or 0)
    except Exception:  # unreadable or exotic tags keep the filename fallback
        pass
    return track


def scan_music(root, limit=MAX_TRACKS, reader=read_tags):
    root = Path(root)
    out = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(base, d)))
        for name in sorted(files):
            if Path(name).suffix.lower() in AUDIO and not name.startswith('.'):
                out.append(reader(Path(base) / name))
                if len(out) >= limit:
                    return out
    return out


class TrackQueue:
    """Play order with shuffle and repeat ('None' | 'Track' | 'Playlist')."""

    def __init__(self, rng=None):
        self.tracks, self.order, self.pos, self.shuffle, self.repeat = [], [], -1, False, 'None'
        self.rng = rng or random.Random()

    def _reorder(self, keep):
        self.order = list(range(len(self.tracks)))
        if self.shuffle:
            self.rng.shuffle(self.order)
            if keep is not None and keep in self.order:
                self.order.remove(keep)
                self.order.insert(0, keep)
        self.pos = self.order.index(keep) if keep is not None and keep in self.order else (0 if self.order else -1)

    def set_tracks(self, tracks, start=0):
        self.tracks = list(tracks)
        self._reorder(start if tracks else None)

    def current(self):
        return self.tracks[self.order[self.pos]] if 0 <= self.pos < len(self.order) else None

    def index(self):
        return self.order[self.pos] if 0 <= self.pos < len(self.order) else -1

    def set_shuffle(self, value):
        self.shuffle = value
        self._reorder(self.index() if self.index() >= 0 else None)

    def next(self, auto=False):
        if not self.order:
            return None
        if auto and self.repeat == 'Track':
            return self.current()
        if self.pos + 1 < len(self.order):
            self.pos += 1
        elif self.repeat == 'Playlist' or not auto:
            if self.shuffle:
                self._reorder(None)
            self.pos = 0
        else:
            return None
        return self.current()

    def previous(self, position=0.0):
        if not self.order:
            return None
        if position > 3:
            return self.current()
        self.pos = (self.pos - 1) % len(self.order)
        return self.current()

    def add(self, track):
        self.tracks.append(track)
        self.order.append(len(self.tracks) - 1)
        if self.pos < 0:
            self.pos = 0

    def play_next(self, track):
        self.tracks.append(track)
        new = len(self.tracks) - 1
        self.order.insert(self.pos + 1, new)

    def upcoming(self):
        return [self.tracks[i] for i in self.order[self.pos + 1:]]


MENU = [('File', [('Add Folder to Library…', 'add_folder', '<Primary>o'), ('Reload Library', 'reload', '<Primary>r'), None, ('Close', 'close', '<Primary>w')]),
        ('Controls', [('Play/Pause', 'play_pause', 'space'), ('Next', 'next', '<Primary>Right'), ('Previous', 'previous', '<Primary>Left'), None, ('Shuffle', 'toggle_shuffle', '<Primary>s'), ('Repeat', 'cycle_repeat', '<Primary>r'),
                      None, ('Volume Up', 'vol_up', '<Primary>Up'), ('Volume Down', 'vol_down', '<Primary>Down')])]
_instance = []


class Tunes:
    def __init__(self, app, root=None):
        from gi.repository import Gst
        Gst.init(None)
        self.Gst = Gst
        self.root = Path(root) if root else Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC) or Path.home() / 'Music')
        self.queue = TrackQueue()
        self.library, self.status, self.volume, self.duration = [], 'Stopped', 0.8, 0.0
        self.pipeline = Gst.ElementFactory.make('playbin', 'tunes')
        sink = os.environ.get('MAKOS_AUDIO_SINK')  # rig: fakesink; normally the default PipeWire/Pulse sink
        if sink:
            self.pipeline.set_property('audio-sink', Gst.parse_launch(sink))
        self.pipeline.set_property('video-sink', Gst.ElementFactory.make('fakesink', None))
        self.pipeline.set_property('volume', self.volume)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', lambda *_: self.on_eos())
        bus.connect('message::error', self.on_error)
        self.aw = AppWindow(app, 'Tunes', 940, 640, MENU)
        self.win = self.aw.win
        for name, fn in (('add_folder', self.add_folder), ('reload', self.reload), ('close', self.win.close), ('play_pause', self.play_pause), ('next', self.next), ('previous', self.previous),
                         ('toggle_shuffle', lambda: self.set_shuffle(not self.queue.shuffle)), ('cycle_repeat', self.cycle_repeat), ('vol_up', lambda: self.set_volume(self.volume + .1)), ('vol_down', lambda: self.set_volume(self.volume - .1))):
            self.aw.action(name, fn)
        self.build_ui()
        self.mpris = Mpris(self)
        self.mpris_ok = self.mpris.start()
        GLib.timeout_add(500, self.tick)
        self.win.connect('close-request', self.on_close)
        self.reload()
        _instance[:] = [self]

    # ---- ui
    def build_ui(self):
        top = ui.box(spacing=8, css='metal-toolbar')
        self.search = Gtk.SearchEntry(placeholder_text='Search songs, artists, albums', hexpand=True)
        self.search.connect('search-changed', lambda *_: self.fill())
        self.view = Gtk.DropDown.new_from_strings(['Songs', 'Up Next'])
        self.view.connect('notify::selected', lambda *_: self.fill())
        top.append(self.search)
        top.append(self.view)
        self.list = Gtk.ListBox()
        self.list.connect('row-activated', self.activated)
        bottom = ui.box(spacing=8, css='player-bar')
        self.now = Gtk.Label(label='Nothing playing', xalign=0, ellipsize=3, width_chars=26)
        self.play_b = ui.button('▶', self.play_pause, 'suggested-action')
        self.shuffle_b, self.repeat_b = Gtk.ToggleButton(label='Shuffle'), ui.button('Repeat: off', self.cycle_repeat)
        self.shuffle_b.connect('toggled', lambda b: self.set_shuffle(b.get_active()))
        self.pos = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.pos.set_hexpand(True)
        self.pos.set_draw_value(False)
        self.seeking = False
        self.pos.connect('change-value', lambda _s, _t, v: (self.seek(v), False)[1])
        self.time = Gtk.Label(label='0:00 / 0:00', css_classes=['hint'])
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.vol.set_value(self.volume * 100)
        self.vol.set_size_request(100, -1)
        self.vol.connect('value-changed', lambda s: self.set_volume(s.get_value() / 100, from_ui=True))
        for w in (ui.button('⏮', self.previous), self.play_b, ui.button('⏭', self.next), self.now, self.pos, self.time, self.shuffle_b, self.repeat_b, Gtk.Label(label='Vol'), self.vol):
            bottom.append(w)
        for w in (top, ui.scroll(self.list), bottom):
            self.aw.body.append(w)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', lambda _t, v, _x, _y: (self.open_paths([f.get_path() for f in v.get_files() if f.get_path()]), True)[1])
        self.win.add_controller(drop)

    # ---- library
    def reload(self):
        def work():
            tracks = scan_music(self.root) if self.root.exists() else []
            GLib.idle_add(lambda: (setattr(self, 'library', tracks), self.fill(), self.aw.say(f'{len(tracks)} songs in {self.root}' + ('' if self.mpris_ok else '   (media keys unavailable: no session bus)')), False)[3])
        threading.Thread(target=work, daemon=True).start()

    def add_folder(self):
        dialog = Gtk.FileDialog(title='Choose a music folder')

        def chosen(d, r):
            try:
                f = d.select_folder_finish(r)
            except GLib.Error:
                return
            if f:
                self.root = Path(f.get_path())
                self.reload()
        dialog.select_folder(self.win, None, chosen)

    def fill(self):
        ui.clear(self.list)
        q = self.search.get_text().casefold()
        up_next = self.view.get_selected() == 1
        tracks = self.queue.upcoming() if up_next else [t for t in self.library if q in f'{t.title} {t.artist} {t.album}'.casefold()]
        for t in tracks[:3000]:
            row = Gtk.ListBoxRow()
            row.track = t
            line = ui.box(spacing=10)
            line.set_margin_top(3)
            line.set_margin_bottom(3)
            line.set_margin_start(8)
            for text, width in ((t.title, 300), (t.artist, 200), (t.album, 200), (clock_text(t.seconds) if t.seconds else '', 60)):
                line.append(Gtk.Label(label=text, xalign=0, width_request=width, ellipsize=3))
            row.set_child(line)
            self.list.append(row)

    def activated(self, _b, row):
        shown = [r.track for r in self.rows()]
        if self.view.get_selected() == 1:
            self.play_track_in(shown, shown.index(row.track))
        else:
            self.play_track_in(shown, shown.index(row.track))

    def rows(self):
        out, r = [], self.list.get_first_child()
        while r:
            if hasattr(r, 'track'):
                out.append(r)
            r = r.get_next_sibling()
        return out

    # ---- playback
    def play_track_in(self, tracks, index):
        self.queue.set_tracks(tracks, index)
        self.play_current()

    def open_paths(self, paths):
        tracks = []
        for p in paths:
            p = Path(p)
            if p.is_dir():
                tracks += scan_music(p, 500)
            elif p.suffix.lower() in AUDIO:
                tracks.append(read_tags(p))
        if tracks:
            self.play_track_in(tracks, 0)

    def play_current(self):
        t = self.queue.current()
        if not t:
            return
        Gst = self.Gst
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.set_property('uri', t.uri)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.status, self.duration = 'Playing', t.seconds
        self.after_change()

    def play(self):
        if self.queue.current():
            self.pipeline.set_state(self.Gst.State.PLAYING)
            self.status = 'Playing'
        elif self.library:
            self.play_track_in(self.library, 0)
            return
        self.after_change()

    def pause(self):
        if self.status == 'Playing':
            self.pipeline.set_state(self.Gst.State.PAUSED)
            self.status = 'Paused'
            self.after_change()

    def play_pause(self):
        self.pause() if self.status == 'Playing' else self.play()

    def stop(self):
        self.pipeline.set_state(self.Gst.State.NULL)
        self.status = 'Stopped'
        self.after_change()

    def next(self):
        if self.queue.next():
            self.play_current()

    def previous(self):
        if self.queue.previous(self.position_us() / 1e6):
            self.play_current()

    def on_eos(self):
        if self.queue.next(auto=True):
            self.play_current()
        else:
            self.stop()

    def on_error(self, _bus, msg):
        err, _dbg = msg.parse_error()
        self.aw.say('Cannot play: ' + err.message)
        if self.queue.next(auto=True):
            self.play_current()
        else:
            self.stop()

    def set_shuffle(self, value):
        self.queue.set_shuffle(bool(value))
        if self.shuffle_b.get_active() != bool(value):
            self.shuffle_b.set_active(bool(value))
        self.mpris.changed()

    @property
    def shuffle(self):
        return self.queue.shuffle

    @shuffle.setter
    def shuffle(self, v):
        self.set_shuffle(v)

    @property
    def loop(self):
        return self.queue.repeat

    @loop.setter
    def loop(self, v):
        self.queue.repeat = v
        self.repeat_b.set_label({'None': 'Repeat: off', 'Playlist': 'Repeat: all', 'Track': 'Repeat: one'}[v])

    def cycle_repeat(self):
        self.loop = {'None': 'Playlist', 'Playlist': 'Track', 'Track': 'None'}[self.queue.repeat]
        self.mpris.changed()

    def set_volume(self, v, from_ui=False):
        self.volume = max(0.0, min(1.0, v))
        self.pipeline.set_property('volume', self.volume)
        if not from_ui:
            self.vol.set_value(self.volume * 100)
        self.mpris.changed()

    def seek(self, seconds):
        self.pipeline.seek_simple(self.Gst.Format.TIME, self.Gst.SeekFlags.FLUSH | self.Gst.SeekFlags.KEY_UNIT, int(max(0, seconds) * self.Gst.SECOND))

    # ---- MPRIS adaptor
    def metadata(self):
        t = self.queue.current()
        return {'title': t.title, 'artist': t.artist, 'album': t.album, 'length_us': int((self.duration or t.seconds) * 1e6), 'uri': t.uri} if t else {}

    def position_us(self):
        ok, pos = self.pipeline.query_position(self.Gst.Format.TIME)
        return pos // 1000 if ok else 0

    def seek_us(self, offset):
        self.seek(max(0, (self.position_us() + offset) / 1e6))

    def set_position_us(self, pos):
        self.seek(pos / 1e6)

    def raise_window(self):
        self.win.present()

    def quit(self):
        self.win.close()

    def open_uri(self, uri):
        path = Gio.File.new_for_uri(uri).get_path()
        if path:
            self.open_paths([path])

    def after_change(self):
        self.play_b.set_label('⏸' if self.status == 'Playing' else '▶')
        t = self.queue.current()
        self.now.set_text(f'{t.title} — {t.artist}' if t and t.artist else (t.title if t else 'Nothing playing'))
        self.win.set_title('Tunes' if not t else f'Tunes — {t.title}')
        self.win._title.set_text(self.win.get_title())
        self.mpris.changed()

    def tick(self):
        if self.status in ('Playing', 'Paused'):
            ok, dur = self.pipeline.query_duration(self.Gst.Format.TIME)
            if ok and dur > 0:
                self.duration = dur / self.Gst.SECOND
            pos = self.position_us() / 1e6
            self.pos.set_range(0, max(1, self.duration))
            self.pos.set_value(pos)
            self.time.set_text(f'{clock_text(pos)} / {clock_text(self.duration)}')
        return True

    def on_close(self, *_):
        self.pipeline.set_state(self.Gst.State.NULL)
        self.mpris.stop()
        if self in _instance:
            _instance.remove(self)
        return False


def open_window(app, path=None):
    if _instance:
        t = _instance[0]
        t.win.present()
    else:
        t = Tunes(app)
        t.aw.present()
    if path:
        t.open_paths([path])
    return t

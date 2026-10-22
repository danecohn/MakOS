"""Movies: video player on GStreamer playbin with gtk4paintablesink, subtitles, fullscreen and keyboard shortcuts."""
import os
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .. import ui
from .base import AppWindow, clock_text

VIDEO = {'.mp4', '.m4v', '.mkv', '.webm', '.avi', '.mov', '.ogv', '.ogg', '.mpg', '.mpeg', '.ts', '.wmv', '.flv', '.3gp'}
SUBTITLE = ('.srt', '.vtt', '.ass', '.ssa', '.sub')
FLAG_VIDEO, FLAG_AUDIO, FLAG_TEXT, FLAG_SOFT_VOLUME = 1, 2, 4, 16
SEEK_SMALL, SEEK_BIG = 5, 30


def find_subtitles(video):
    """Subtitle files that sit beside the video and share its name: 'movie.srt', 'movie.en.srt'."""
    video = Path(video)
    found = []
    try:
        for p in sorted(video.parent.iterdir()):
            if p.suffix.lower() in SUBTITLE and p.stem.split('.')[0] == video.stem.split('.')[0] and (p.stem == video.stem or p.stem.startswith(video.stem + '.')):
                found.append(p)
    except OSError:
        pass
    return sorted(found, key=lambda p: (p.stem != video.stem, p.name))


def seek_target(position, delta, duration):
    return max(0.0, min(position + delta, max(0.0, duration - 0.5) if duration else position + delta))


def key_action(keyval, shift=False):
    """Maps a key to (action, argument); pure so the shortcut table can be tested."""
    table = {Gdk.KEY_space: ('toggle', None), Gdk.KEY_k: ('toggle', None), Gdk.KEY_f: ('fullscreen', None), Gdk.KEY_F11: ('fullscreen', None), Gdk.KEY_Escape: ('leave_fullscreen', None),
             Gdk.KEY_m: ('mute', None), Gdk.KEY_s: ('subtitles', None), Gdk.KEY_Up: ('volume', .05), Gdk.KEY_Down: ('volume', -.05),
             Gdk.KEY_Right: ('seek', SEEK_BIG if shift else SEEK_SMALL), Gdk.KEY_Left: ('seek', -(SEEK_BIG if shift else SEEK_SMALL)),
             Gdk.KEY_l: ('seek', 10), Gdk.KEY_j: ('seek', -10), Gdk.KEY_o: ('open', None)}
    return table.get(keyval)


MENU = [('File', [('Open…', 'open', '<Primary>o'), ('Open Subtitles…', 'open_subs', None), None, ('Close', 'close', '<Primary>w')]),
        ('Playback', [('Play/Pause', 'toggle', None), ('Skip Forward 5 s', 'fwd', None), ('Skip Back 5 s', 'back', None), None, ('Subtitles On/Off', 'subtitles', None), ('Mute', 'mute', None)]),
        ('View', [('Full Screen', 'fullscreen', 'F11')])]


class Movies:
    def __init__(self, app, path=None):
        from gi.repository import Gst
        Gst.init(None)
        self.Gst = Gst
        self.app, self.cookie, self.fullscreen, self.subs_on, self.duration, self.hide_timer = app, 0, False, True, 0.0, 0
        self.aw = AppWindow(app, 'Movies', 960, 600, MENU, status=True)
        self.win = self.aw.win
        self.pipeline = Gst.ElementFactory.make('playbin', 'movies')
        self.sink = Gst.ElementFactory.make('gtk4paintablesink', None)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, hexpand=True, vexpand=True, css_classes=['video-stage'])
        self.message = Gtk.Label(label='Drop a video here or choose File → Open', css_classes=['hint'])
        if self.sink is None:
            self.message.set_text('Video output needs the gstreamer1.0-gtk4 plugin, which is not installed.')
        else:
            self.pipeline.set_property('video-sink', self.sink)
            self.picture.set_paintable(self.sink.get_property('paintable'))
        sink = os.environ.get('MAKOS_AUDIO_SINK')
        if sink:
            self.pipeline.set_property('audio-sink', Gst.parse_launch(sink))
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', lambda *_: self.on_eos())
        bus.connect('message::error', lambda _b, m: self.aw.say('Cannot play: ' + m.parse_error()[0].message))
        for name, fn in (('open', self.choose), ('open_subs', self.choose_subs), ('close', self.win.close), ('toggle', self.toggle), ('fwd', lambda: self.seek_by(SEEK_SMALL)), ('back', lambda: self.seek_by(-SEEK_SMALL)),
                         ('subtitles', self.toggle_subs), ('mute', self.toggle_mute), ('fullscreen', self.toggle_fullscreen)):
            self.aw.action(name, fn)
        stage = Gtk.Overlay(child=self.picture)
        stage.add_overlay(self.message)
        self.message.set_halign(Gtk.Align.CENTER)
        self.message.set_valign(Gtk.Align.CENTER)
        self.aw.body.append(stage)
        self.bar = ui.box(spacing=8, css='player-bar')
        self.play_b = ui.button('▶', self.toggle, 'suggested-action')
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.connect('change-value', lambda _s, _t, v: (self.seek_to(v), False)[1])
        self.time = Gtk.Label(label='0:00 / 0:00', css_classes=['hint'])
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.vol.set_value(80)
        self.vol.set_size_request(90, -1)
        self.vol.connect('value-changed', lambda s: self.pipeline.set_property('volume', s.get_value() / 100))
        self.subs_b = Gtk.ToggleButton(label='CC', active=True, tooltip_text='Subtitles (S)')
        self.subs_b.connect('toggled', lambda b: self.set_subs(b.get_active()))
        for w in (self.play_b, self.scale, self.time, self.subs_b, Gtk.Label(label='Vol'), self.vol, ui.button('⛶', self.toggle_fullscreen)):
            self.bar.append(w)
            w.set_focusable(False)
        self.aw.body.append(self.bar)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.on_key)
        self.win.add_controller(keys)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', lambda *_: self.reveal())
        self.win.add_controller(motion)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect('drop', lambda _t, v, _x, _y: (self.load([f.get_path() for f in v.get_files()][0]), True)[1])
        self.win.add_controller(drop)
        GLib.timeout_add(400, self.tick)
        self.win.connect('close-request', self.on_close)
        if path:
            self.load(path)

    # ---- playback
    def load(self, path):
        path = Path(path)
        if not path.exists():
            self.aw.say('File not found.')
            return
        Gst = self.Gst
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.set_property('uri', path.resolve().as_uri())
        subs = find_subtitles(path)
        self.pipeline.set_property('suburi', subs[0].resolve().as_uri() if subs else '')
        self.apply_subs()
        self.pipeline.set_state(Gst.State.PLAYING)
        self.message.set_visible(False)
        self.win.set_title(path.name)
        self.win._title.set_text(path.name)
        self.play_b.set_label('⏸')
        self.inhibit(True)
        self.aw.say(path.name + ('   subtitles: ' + subs[0].name if subs else '   no subtitle file found beside the video'))

    def state(self):
        return self.pipeline.get_state(0)[1]

    def toggle(self):
        Gst = self.Gst
        if self.state() == Gst.State.PLAYING:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.play_b.set_label('▶')
            self.inhibit(False)
        elif self.state() in (Gst.State.PAUSED, Gst.State.READY):
            self.pipeline.set_state(Gst.State.PLAYING)
            self.play_b.set_label('⏸')
            self.inhibit(True)

    def inhibit(self, on):
        """Keep the screen awake only while a video plays."""
        if on and not self.cookie:
            self.cookie = self.app.inhibit(self.win, Gtk.ApplicationInhibitFlags.IDLE, 'Playing a video')
        elif not on and self.cookie:
            self.app.uninhibit(self.cookie)
            self.cookie = 0

    def position(self):
        ok, pos = self.pipeline.query_position(self.Gst.Format.TIME)
        return pos / self.Gst.SECOND if ok else 0.0

    def seek_to(self, seconds):
        self.pipeline.seek_simple(self.Gst.Format.TIME, self.Gst.SeekFlags.FLUSH | self.Gst.SeekFlags.KEY_UNIT, int(seconds * self.Gst.SECOND))

    def seek_by(self, delta):
        self.seek_to(seek_target(self.position(), delta, self.duration))

    def on_eos(self):
        self.pipeline.set_state(self.Gst.State.PAUSED)
        self.seek_to(0)
        self.play_b.set_label('▶')
        self.inhibit(False)

    def tick(self):
        if self.state() in (self.Gst.State.PLAYING, self.Gst.State.PAUSED):
            ok, dur = self.pipeline.query_duration(self.Gst.Format.TIME)
            if ok and dur > 0:
                self.duration = dur / self.Gst.SECOND
            pos = self.position()
            self.scale.set_range(0, max(1, self.duration))
            self.scale.set_value(pos)
            self.time.set_text(f'{clock_text(pos)} / {clock_text(self.duration)}')
        return True

    # ---- subtitles, volume, fullscreen
    def apply_subs(self):
        flags = FLAG_VIDEO | FLAG_AUDIO | FLAG_SOFT_VOLUME | (FLAG_TEXT if self.subs_on else 0)
        self.pipeline.set_property('flags', flags)

    def set_subs(self, on):
        self.subs_on = on
        self.apply_subs()
        self.aw.say('Subtitles ' + ('on' if on else 'off'))

    def toggle_subs(self):
        self.subs_b.set_active(not self.subs_on)

    def toggle_mute(self):
        self.pipeline.set_property('mute', not self.pipeline.get_property('mute'))
        self.aw.say('Muted' if self.pipeline.get_property('mute') else 'Sound on')

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        (self.win.fullscreen if self.fullscreen else self.win.unfullscreen)()
        self.reveal()

    def reveal(self):
        self.bar.set_visible(True)
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0
        if self.fullscreen:
            self.hide_timer = GLib.timeout_add_seconds(3, lambda: (self.bar.set_visible(False), setattr(self, 'hide_timer', 0), False)[2])

    def on_key(self, _c, keyval, _code, state):
        act = key_action(keyval, bool(state & Gdk.ModifierType.SHIFT_MASK))
        if not act:
            return False
        name, arg = act
        if name == 'toggle':
            self.toggle()
        elif name == 'fullscreen':
            self.toggle_fullscreen()
        elif name == 'leave_fullscreen':
            if self.fullscreen:
                self.toggle_fullscreen()
        elif name == 'mute':
            self.toggle_mute()
        elif name == 'subtitles':
            self.toggle_subs()
        elif name == 'volume':
            self.vol.set_value(max(0, min(100, self.vol.get_value() + arg * 100)))
        elif name == 'seek':
            self.seek_by(arg)
        elif name == 'open':
            self.choose()
        return True

    # ---- dialogs
    def choose(self):
        dialog = Gtk.FileDialog(title='Open a video')

        def picked(d, r):
            try:
                f = d.open_finish(r)
            except GLib.Error:
                return
            if f:
                self.load(f.get_path())
        dialog.open(self.win, None, picked)

    def choose_subs(self):
        dialog = Gtk.FileDialog(title='Open subtitles')

        def picked(d, r):
            try:
                f = d.open_finish(r)
            except GLib.Error:
                return
            if f:
                pos = self.position()
                self.pipeline.set_state(self.Gst.State.NULL)
                self.pipeline.set_property('suburi', f.get_uri())
                self.pipeline.set_state(self.Gst.State.PLAYING)
                GLib.timeout_add(500, lambda: (self.seek_to(pos), False)[1])
        dialog.open(self.win, None, picked)

    def on_close(self, *_):
        self.pipeline.set_state(self.Gst.State.NULL)
        self.inhibit(False)
        return False


def open_window(app, path=None):
    m = Movies(app, path if path and not str(path).startswith('--') else None)
    m.aw.present()
    return m

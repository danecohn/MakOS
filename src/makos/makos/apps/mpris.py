"""Minimal MPRIS 2 service (org.mpris.MediaPlayer2) so media keys and desktop widgets can control a player.

The adaptor passed in provides: status ('Playing'|'Paused'|'Stopped'), metadata() -> dict, position_us(),
volume, shuffle, loop ('None'|'Track'|'Playlist') and the methods play/pause/play_pause/stop/next/previous/
seek_us/set_position_us/raise_window/quit/open_uri. Only the session bus is used.
"""
from gi.repository import Gio, GLib

ROOT_XML = '''<node><interface name="org.mpris.MediaPlayer2">
<method name="Raise"/><method name="Quit"/>
<property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/><property name="HasTrackList" type="b" access="read"/>
<property name="Identity" type="s" access="read"/><property name="DesktopEntry" type="s" access="read"/>
<property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
</interface></node>'''
PLAYER_XML = '''<node><interface name="org.mpris.MediaPlayer2.Player">
<method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/><method name="Stop"/><method name="Play"/>
<method name="Seek"><arg type="x" direction="in"/></method>
<method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
<method name="OpenUri"><arg type="s" direction="in"/></method>
<signal name="Seeked"><arg type="x"/></signal>
<property name="PlaybackStatus" type="s" access="read"/><property name="LoopStatus" type="s" access="readwrite"/>
<property name="Rate" type="d" access="read"/><property name="Shuffle" type="b" access="readwrite"/>
<property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="readwrite"/>
<property name="Position" type="x" access="read"/><property name="MinimumRate" type="d" access="read"/><property name="MaximumRate" type="d" access="read"/>
<property name="CanGoNext" type="b" access="read"/><property name="CanGoPrevious" type="b" access="read"/><property name="CanPlay" type="b" access="read"/>
<property name="CanPause" type="b" access="read"/><property name="CanSeek" type="b" access="read"/><property name="CanControl" type="b" access="read"/>
</interface></node>'''
TRACK_PATH = '/org/makos/Tunes/track/'


def metadata_variant(meta):
    """{'title','artist','album','length_us','uri','id'} -> a{sv} with MPRIS keys (artist is a list)."""
    out = {'mpris:trackid': GLib.Variant('o', TRACK_PATH + str(abs(hash(meta.get('uri', ''))) % 10**9 if meta else 0))}
    if not meta:
        out['mpris:trackid'] = GLib.Variant('o', '/org/mpris/MediaPlayer2/TrackList/NoTrack')
        return out
    if meta.get('title'):
        out['xesam:title'] = GLib.Variant('s', meta['title'])
    if meta.get('artist'):
        out['xesam:artist'] = GLib.Variant('as', [meta['artist']])
    if meta.get('album'):
        out['xesam:album'] = GLib.Variant('s', meta['album'])
    if meta.get('length_us'):
        out['mpris:length'] = GLib.Variant('x', int(meta['length_us']))
    if meta.get('uri'):
        out['xesam:url'] = GLib.Variant('s', meta['uri'])
    return out


class Mpris:
    NAME = 'org.mpris.MediaPlayer2.makos_tunes'
    PATH = '/org/mpris/MediaPlayer2'

    def __init__(self, player):
        self.player, self.conn, self.owner, self.regs = player, None, 0, []
        self.last = {}

    def start(self):
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION)
            self.regs = [self.conn.register_object(self.PATH, Gio.DBusNodeInfo.new_for_xml(ROOT_XML).interfaces[0], self.call, self.get, None),
                         self.conn.register_object(self.PATH, Gio.DBusNodeInfo.new_for_xml(PLAYER_XML).interfaces[0], self.call, self.get, self.set)]
            self.owner = Gio.bus_own_name_on_connection(self.conn, self.NAME, Gio.BusNameOwnerFlags.NONE, None, None)
            return True
        except GLib.Error:
            return False

    def stop(self):
        if self.conn:
            for r in self.regs:
                self.conn.unregister_object(r)
            if self.owner:
                Gio.bus_unown_name(self.owner)
        self.conn, self.regs = None, []

    def props(self):
        p = self.player
        return {'PlaybackStatus': GLib.Variant('s', p.status), 'LoopStatus': GLib.Variant('s', p.loop), 'Rate': GLib.Variant('d', 1.0), 'Shuffle': GLib.Variant('b', bool(p.shuffle)),
                'Metadata': GLib.Variant('a{sv}', metadata_variant(p.metadata())), 'Volume': GLib.Variant('d', float(p.volume)), 'Position': GLib.Variant('x', int(p.position_us())),
                'MinimumRate': GLib.Variant('d', 1.0), 'MaximumRate': GLib.Variant('d', 1.0), 'CanGoNext': GLib.Variant('b', True), 'CanGoPrevious': GLib.Variant('b', True),
                'CanPlay': GLib.Variant('b', True), 'CanPause': GLib.Variant('b', True), 'CanSeek': GLib.Variant('b', True), 'CanControl': GLib.Variant('b', True)}

    def get(self, _c, _s, _p, iface, name):
        if iface == 'org.mpris.MediaPlayer2':
            return {'CanQuit': GLib.Variant('b', True), 'CanRaise': GLib.Variant('b', True), 'HasTrackList': GLib.Variant('b', False), 'Identity': GLib.Variant('s', 'Tunes'),
                    'DesktopEntry': GLib.Variant('s', 'makos-tunes'), 'SupportedUriSchemes': GLib.Variant('as', ['file']),
                    'SupportedMimeTypes': GLib.Variant('as', ['audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/x-wav', 'audio/mp4'])}.get(name)
        return self.props().get(name)

    def set(self, _c, _s, _p, iface, name, value):
        if name == 'Volume':
            self.player.volume = max(0.0, min(1.0, value.unpack()))
        elif name == 'Shuffle':
            self.player.shuffle = value.unpack()
        elif name == 'LoopStatus' and value.unpack() in ('None', 'Track', 'Playlist'):
            self.player.loop = value.unpack()
        else:
            return False
        self.changed()
        return True

    def call(self, _c, _s, _p, iface, method, params, inv):
        p = self.player
        args = params.unpack()
        table = {'Raise': p.raise_window, 'Quit': p.quit, 'Next': p.next, 'Previous': p.previous, 'Pause': p.pause, 'PlayPause': p.play_pause, 'Stop': p.stop, 'Play': p.play,
                 'Seek': lambda: p.seek_us(args[0]), 'SetPosition': lambda: p.set_position_us(args[1]), 'OpenUri': lambda: p.open_uri(args[0])}
        fn = table.get(method)
        if not fn:
            inv.return_error_literal(Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method)
            return
        GLib.idle_add(lambda: (fn(), False)[1])
        inv.return_value(None)

    def changed(self):
        """Emit PropertiesChanged for whatever differs since the last call."""
        if not self.conn:
            return
        now = {k: v for k, v in self.props().items() if k != 'Position'}
        diff = {k: v for k, v in now.items() if self.last.get(k) is None or self.last[k].unpack() != v.unpack()}
        self.last = now
        if diff:
            self.conn.emit_signal(None, self.PATH, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                                  GLib.Variant('(sa{sv}as)', ('org.mpris.MediaPlayer2.Player', diff, [])))

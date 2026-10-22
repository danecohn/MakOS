"""Devices (mount/unmount/eject) and Shared/Network locations through GIO + gvfs.

Passwords are never read or stored by MakOS: Gtk.MountOperation shows the standard credential prompt owned by
the system's authentication agent and gvfs/keyring.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from . import model

SCHEMES = ('smb', 'sftp', 'ssh', 'dav', 'davs', 'ftp', 'ftps', 'nfs', 'afp', 'http', 'https')
GIO_SCHEME = {'ssh': 'sftp', 'http': 'dav', 'https': 'davs'}
ATTRS = ('standard::name,standard::display-name,standard::type,standard::size,standard::content-type,standard::is-symlink,'
         'standard::is-hidden,time::modified,time::created,unix::mode,access::can-read,standard::target-uri,'
         'trash::orig-path,trash::deletion-date')


class ServerError(ValueError):
    pass


def normalize_server(text):
    """Turn user input into a safe GIO URI (smb://, sftp://, davs:// ...). Raises ServerError with a human message."""
    text = (text or '').strip()
    if not text:
        raise ServerError('Type a server address, for example smb://server/share or sftp://host.')
    if re.fullmatch(r'\\\\[^\\]+(\\.*)?', text):
        text = 'smb://' + text[2:].replace('\\', '/')
    if re.search(r'\s', text):
        raise ServerError('A server address cannot contain spaces.')
    if '://' not in text:
        raise ServerError('Start the address with its type, for example smb://, sftp://, davs:// or ftp://.')
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in SCHEMES:
        raise ServerError(f'“{scheme}://” is not supported. Use smb, sftp, dav(s), ftp(s) or nfs.')
    if not parts.hostname:
        raise ServerError('The address needs a server name.')
    scheme = GIO_SCHEME.get(scheme, scheme)
    netloc = parts.netloc
    if parts.password:
        # Never keep a password typed into an address: the credential prompt asks for it securely.
        user = parts.username or ''
        host = parts.hostname + (f':{parts.port}' if parts.port else '')
        netloc = f'{user}@{host}' if user else host
    return f'{scheme}://{netloc}{parts.path}' + (f'?{parts.query}' if parts.query else '')


@dataclass
class Device:
    name: str
    icon: str
    root: object = None        # Gio.File when mounted
    mount: object = None
    volume: object = None
    drive: object = None
    removable: bool = False
    network: bool = False

    @property
    def mounted(self):
        return self.mount is not None and self.root is not None

    @property
    def path(self):
        return self.root.get_path() if self.root is not None else None

    @property
    def uri(self):
        return self.root.get_uri() if self.root is not None else None

    @property
    def can_unmount(self):
        return bool(self.mounted and self.mount.can_unmount())

    @property
    def can_eject(self):
        return bool((self.mount is not None and self.mount.can_eject()) or (self.volume is not None and self.volume.can_eject())
                    or (self.drive is not None and self.drive.can_eject()))


def _icon_for(volume=None, mount=None, drive=None, root=None):
    scheme = root.get_uri_scheme() if root is not None else 'file'
    if scheme not in ('file', None):
        return 'drive-network'
    if drive is not None and drive.get_start_stop_type() == Gio.DriveStartStopType.SHUTDOWN:
        return 'drive-external'
    if (drive is not None and drive.is_removable()) or (volume is not None and volume.get_identifier('class') == 'device' and
                                                       drive is not None and drive.is_media_removable()):
        return 'drive-external'
    if volume is not None and volume.get_identifier('class') == 'optical' or (drive is not None and 'optical' in str(drive.get_name()).lower()):
        return 'drive-optical'
    return 'drive-internal'


def devices(include_internal_unmounted=False):
    """Mounted and mountable volumes plus mounts that have no volume (network shares, disk images)."""
    mon = Gio.VolumeMonitor.get()
    out, seen_mounts, seen_volumes = [], set(), set()

    def add_volume(vol, drive=None):
        if id(vol) in seen_volumes:
            return
        seen_volumes.add(id(vol))
        mount = vol.get_mount()
        if mount is not None:
            if mount.is_shadowed():
                return
            seen_mounts.add(mount.get_uuid() or mount.get_name())
        root = mount.get_default_location() if mount else None
        if mount is None and not vol.can_mount():
            return
        if mount is None and not include_internal_unmounted and drive is None:
            ident = vol.get_identifier('class') or ''
            if ident not in ('device', 'network'):
                return
        icon = _icon_for(vol, mount, drive, root)
        out.append(Device(vol.get_name(), icon, root, mount, vol, drive,
                          removable=icon in ('drive-external', 'drive-optical'), network=icon == 'drive-network'))
    for drive in mon.get_connected_drives():
        for vol in drive.get_volumes():
            add_volume(vol, drive)
    for vol in mon.get_volumes():
        add_volume(vol, vol.get_drive())
    for mount in mon.get_mounts():
        key = mount.get_uuid() or mount.get_name()
        if mount.is_shadowed() or key in seen_mounts:
            continue
        if mount.get_volume() is not None and id(mount.get_volume()) in seen_volumes:
            continue
        root = mount.get_default_location() or mount.get_root()
        local = root.get_path() or ''
        if local in ('/', '') and root.get_uri_scheme() == 'file':
            continue
        if local.startswith(('/boot', '/snap', '/var/snap', '/run/snapd')):
            continue
        icon = _icon_for(None, mount, mount.get_drive(), root)
        out.append(Device(mount.get_name(), icon, root, mount, None, mount.get_drive(), removable=icon != 'drive-internal',
                          network=icon == 'drive-network'))
    return out


def _op(parent):
    return Gtk.MountOperation(parent=parent) if parent is not None else Gtk.MountOperation()


def mount_device(device, parent, callback):
    if device.volume is None:
        callback(None, 'This item cannot be mounted.')
        return

    def done(vol, res):
        try:
            vol.mount_finish(res)
            callback(vol, None)
        except GLib.Error as err:
            callback(None, err.message)
    device.volume.mount(Gio.MountMountFlags.NONE, _op(parent), None, done)


def unmount_device(device, parent, callback, eject=False):
    if not device.mounted:
        callback(None, None)
        return

    def done(mount, res):
        try:
            if eject:
                mount.eject_with_operation_finish(res)
            else:
                mount.unmount_with_operation_finish(res)
            callback(True, None)
        except GLib.Error as err:
            callback(None, err.message)
    flags = Gio.MountUnmountFlags.NONE
    if eject and device.mount.can_eject():
        device.mount.eject_with_operation(flags, _op(parent), None, done)
    else:
        device.mount.unmount_with_operation(flags, _op(parent), None, done)


def eject_volume(device, parent, callback):
    """Eject an unmounted volume/drive (e.g. powers down a removable disk)."""
    target = device.volume if device.volume is not None and device.volume.can_eject() else device.drive
    if target is None:
        callback(None, 'This device cannot be ejected.')
        return

    def done(obj, res):
        try:
            obj.eject_with_operation_finish(res)
            callback(True, None)
        except GLib.Error as err:
            callback(None, err.message)
    target.eject_with_operation(Gio.MountUnmountFlags.NONE, _op(parent), None, done)


def mount_location(uri, parent, callback):
    """Mount the share that contains ``uri``. callback(ok, message)."""
    gf = Gio.File.new_for_uri(uri)

    def done(f, res):
        try:
            f.mount_enclosing_volume_finish(res)
            callback(True, None)
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                callback(True, None)
            else:
                callback(False, friendly(err))
    gf.mount_enclosing_volume(Gio.MountMountFlags.NONE, _op(parent), None, done)


def friendly(err):
    e = Gio.IOErrorEnum
    for code, text in [(e.FAILED_HANDLED, 'Cancelled.'), (e.HOST_NOT_FOUND, 'The server could not be found.'),
                       (e.TIMED_OUT, 'The server did not respond.'), (e.PERMISSION_DENIED, 'Access was denied.'),
                       (e.NOT_SUPPORTED, 'This kind of server is not supported on this system (is the gvfs backend installed?).'),
                       (e.HOST_UNREACHABLE, 'The server is unreachable.'), (e.CONNECTION_REFUSED, 'The server refused the connection.'),
                       (e.NETWORK_UNREACHABLE, 'The network is unreachable.'), (e.NOT_FOUND, 'That location does not exist on the server.')]:
        if err.matches(Gio.io_error_quark(), code):
            return text
    return err.message


def entry_from_info(parent, info, parent_uri=''):
    """Build a model.Entry from a Gio.FileInfo of a non-local (or trash) location."""
    name = info.get_name()
    shown = info.get_display_name() or name
    is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
    mime = 'inode/directory' if is_dir else (info.get_content_type() or model.content_type(shown))
    mt = info.get_modification_date_time()
    child = parent.get_child(name)
    target = info.get_attribute_string('standard::target-uri')
    uri = target or child.get_uri()
    e = model.Entry(name=shown, path=child.get_path() if child.is_native() else '', uri=uri if not child.is_native() else '',
                    is_dir=is_dir, is_symlink=info.get_is_symlink(), size=0 if is_dir else info.get_size(),
                    mtime=mt.to_unix() if mt else 0.0, mime=mime, hidden=info.get_is_hidden() or shown.startswith('.'),
                    readable=not info.has_attribute('access::can-read') or info.get_attribute_boolean('access::can-read'),
                    where=parent.get_parse_name())
    e.kind = model.describe(mime, is_dir, e.is_symlink)
    e.icon = model.icon_for(mime, is_dir, shown)
    if is_dir and not e.path and parent.get_uri_scheme() == 'network':
        e.icon = 'folder-network'
        e.kind = 'Network location'
    return e


def list_gio(location, show_hidden=False, cancel=None, limit=model.MAX_ENTRIES):
    """Yield Entry for a GIO location (smb, sftp, network:///...). Raises model.FolderError with human text."""
    gf = location if isinstance(location, Gio.File) else Gio.File.new_for_uri(location)
    cancellable = Gio.Cancellable()
    try:
        en = gf.enumerate_children(ATTRS, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    except GLib.Error as err:
        raise model.FolderError(friendly(err)) from err
    count = 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                cancellable.cancel()
                return
            try:
                infos = en.next_files(256, GLib.PRIORITY_DEFAULT, cancellable) if hasattr(en, 'next_files') else None
            except TypeError:
                infos = None
            if infos is None:
                info = en.next_file(cancellable)
                infos = [info] if info else []
            if not infos:
                break
            for info in infos:
                e = entry_from_info(gf, info)
                if e.hidden and not show_hidden:
                    continue
                yield e
                count += 1
                if count >= limit:
                    return
    except GLib.Error as err:
        raise model.FolderError(friendly(err)) from err
    finally:
        try:
            en.close(None)
        except GLib.Error:
            pass

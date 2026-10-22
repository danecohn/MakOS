"""KWin capture adapted from the existing shell's FD-based screenshot plumbing."""
import os
import threading
from gi.repository import Gio,GLib
import cairo


def capture(bus,method="CaptureWorkspace",window_id=None):
    rfd,wfd=os.pipe()
    chunks=[]
    def drain():
        with os.fdopen(rfd,'rb') as stream:
            chunks.append(stream.read(8192*8192*4+1))
    reader=threading.Thread(target=drain,daemon=True)
    reader.start()
    fds=Gio.UnixFDList.new()
    index=fds.append(wfd)
    os.close(wfd)
    try:
        result,_=bus.call_with_unix_fd_list_sync('org.kde.KWin','/org/kde/KWin/ScreenShot2','org.kde.KWin.ScreenShot2',
            method,GLib.Variant('(sa{sv}h)' if window_id else '(a{sv}h)', ((window_id,) if window_id else ())+({'native-resolution':GLib.Variant('b',True),'include-cursor':GLib.Variant('b',False),'hide-caller-windows':GLib.Variant('b',False),'include-decoration':GLib.Variant('b',True)},index)),
            None,Gio.DBusCallFlags.NONE,15000,fds,None)
    finally:
        for fd in fds.steal_fds():
            os.close(fd)
    reader.join(10)
    meta=result.unpack()[0]
    w,h,stride,fmt=(int(meta[k]) for k in ('width','height','stride','format'))
    if not chunks or w<=0 or h<=0 or w*h>8192*8192 or stride<w*4 or len(chunks[0])<stride*h or fmt not in (4,6):
        raise ValueError('Invalid compositor screenshot')
    return cairo.ImageSurface.create_for_data(bytearray(chunks[0]),cairo.FORMAT_ARGB32 if fmt==6 else cairo.FORMAT_RGB24,w,h,stride)


def workspace(bus):
    return capture(bus)

def window(bus,ident):
    from .windows import ID
    if not ID.fullmatch(ident):
        raise ValueError('Invalid window ID')
    return capture(bus,'CaptureWindow',ident)

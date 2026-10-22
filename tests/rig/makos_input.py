"""Synthetic pointer / keyboard / touch input for the private rig, through KWin's EIS (libei) endpoint.

KWin's `org.kde.KWin.EIS.RemoteDesktop` hands out a socket; libei (loaded with ctypes, no headers or Python bindings
needed) turns calls like move()/click()/key() into real compositor input events, so the Launcher Bar, Spread, the switcher
and KWin shortcuts are exercised through the same path a mouse or keyboard takes. Rig use only: it talks to the private
session bus of makos_launcher_rig.sh.
"""
import ctypes
import os
import select
import time

from gi.repository import Gio, GLib

CAP_POINTER, CAP_POINTER_ABSOLUTE, CAP_KEYBOARD, CAP_TOUCH, CAP_SCROLL, CAP_BUTTON = 1, 2, 4, 8, 16, 32
EV_CONNECT, EV_DISCONNECT, EV_SEAT_ADDED, EV_SEAT_REMOVED, EV_DEVICE_ADDED, EV_DEVICE_REMOVED, EV_DEVICE_PAUSED, EV_DEVICE_RESUMED = 1, 2, 3, 4, 5, 6, 7, 8
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
# evdev key codes used by the checks
KEY = {'esc': 1, 'tab': 15, 'q': 16, 'w': 17, 'h': 35, 'd': 32, 'm': 50, 'f': 33, 'grave': 41, 'space': 57, 'leftctrl': 29,
       'leftshift': 42, 'leftalt': 56, 'leftmeta': 125, 'left': 105, 'right': 106, 'up': 103, 'down': 108, 'enter': 28,
       '1': 2, '2': 3, '3': 4, '4': 5}


class Input:
    def __init__(self, bus=None):
        self.lib = ctypes.CDLL('libei.so.1')
        L = self.lib
        L.ei_new_sender.restype = ctypes.c_void_p
        L.ei_new_sender.argtypes = [ctypes.c_void_p]
        L.ei_configure_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.ei_setup_backend_fd.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.ei_get_fd.argtypes = [ctypes.c_void_p]
        L.ei_dispatch.argtypes = [ctypes.c_void_p]
        L.ei_get_event.restype = ctypes.c_void_p
        L.ei_get_event.argtypes = [ctypes.c_void_p]
        L.ei_event_get_type.argtypes = [ctypes.c_void_p]
        L.ei_event_get_seat.restype = ctypes.c_void_p
        L.ei_event_get_seat.argtypes = [ctypes.c_void_p]
        L.ei_event_get_device.restype = ctypes.c_void_p
        L.ei_event_get_device.argtypes = [ctypes.c_void_p]
        L.ei_event_unref.argtypes = [ctypes.c_void_p]
        L.ei_seat_bind_capabilities.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.ei_device_has_capability.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.ei_device_has_capability.restype = ctypes.c_bool
        L.ei_device_start_emulating.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        L.ei_device_frame.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        L.ei_now.argtypes = [ctypes.c_void_p]
        L.ei_now.restype = ctypes.c_uint64
        L.ei_device_pointer_motion_absolute.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        L.ei_device_pointer_motion.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        L.ei_device_button_button.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool]
        L.ei_device_keyboard_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool]
        L.ei_device_scroll_discrete.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]
        L.ei_device_touch_new.restype = ctypes.c_void_p
        L.ei_device_touch_new.argtypes = [ctypes.c_void_p]
        L.ei_touch_down.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        L.ei_touch_motion.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        L.ei_touch_up.argtypes = [ctypes.c_void_p]
        bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)
        fds = Gio.UnixFDList.new()
        reply, out_fds = bus.call_with_unix_fd_list_sync(
            'org.kde.KWin', '/org/kde/KWin/EIS/RemoteDesktop', 'org.kde.KWin.EIS.RemoteDesktop', 'connectToEIS',
            GLib.Variant('(i)', (CAP_POINTER | CAP_POINTER_ABSOLUTE | CAP_KEYBOARD | CAP_TOUCH | CAP_BUTTON | CAP_SCROLL,)),
            None, Gio.DBusCallFlags.NONE, 5000, fds, None)
        fd = out_fds.get(reply.unpack()[0])
        self.ei = L.ei_new_sender(None)
        L.ei_configure_name(self.ei, b'makos-rig')
        L.ei_setup_backend_fd(self.ei, fd)
        self.devices = {}
        self.seat = None
        self.sequence = 0
        self.touch = None
        self.pump(3.0, until=lambda: {CAP_POINTER, CAP_KEYBOARD, CAP_POINTER_ABSOLUTE} <= set().union(*[d['caps'] for d in self.devices.values() if d['ready']] or [set()]))

    def _ready(self):
        return any(d['ready'] for d in self.devices.values())

    def pump(self, seconds=0.0, until=None):
        L = self.lib
        end = time.monotonic() + seconds
        fd = L.ei_get_fd(self.ei)
        while True:
            select.select([fd], [], [], 0.01)
            L.ei_dispatch(self.ei)
            while True:
                ev = L.ei_get_event(self.ei)
                if not ev:
                    break
                kind = L.ei_event_get_type(ev)
                if kind == EV_SEAT_ADDED:
                    self.seat = L.ei_event_get_seat(ev)
                    L.ei_seat_bind_capabilities(self.seat, CAP_POINTER, CAP_POINTER_ABSOLUTE, CAP_KEYBOARD, CAP_BUTTON, CAP_SCROLL, CAP_TOUCH, 0)
                elif kind == EV_DEVICE_ADDED:
                    dev = L.ei_event_get_device(ev)
                    self.devices[dev] = {'ready': False, 'caps': {c for c in (CAP_POINTER, CAP_POINTER_ABSOLUTE, CAP_KEYBOARD, CAP_TOUCH) if L.ei_device_has_capability(dev, c)}}
                elif kind == EV_DEVICE_RESUMED:
                    dev = L.ei_event_get_device(ev)
                    if dev in self.devices:
                        self.devices[dev]['ready'] = True
                        self.sequence += 1
                        L.ei_device_start_emulating(dev, self.sequence)
                elif kind == EV_DEVICE_PAUSED:
                    dev = L.ei_event_get_device(ev)
                    if dev in self.devices:
                        self.devices[dev]['ready'] = False
                elif kind == EV_DEVICE_REMOVED:
                    self.devices.pop(L.ei_event_get_device(ev), None)
                L.ei_event_unref(ev)
            if until and until():
                return True
            if time.monotonic() >= end:
                return False

    def _device(self, cap):
        for dev, info in self.devices.items():
            if cap in info['caps'] and info['ready']:
                return dev
        raise RuntimeError('no EIS device with capability %d (have %s)' % (cap, list(self.devices.values())))

    def _frame(self, dev):
        self.lib.ei_device_frame(dev, self.lib.ei_now(self.ei))
        self.pump(0.0)

    # ----- pointer
    def move(self, x, y, steps=1, duration=0.0):
        dev = self._device(CAP_POINTER_ABSOLUTE)
        cx, cy = getattr(self, 'pos', (x, y))
        for i in range(1, steps + 1):
            t = i / steps
            self.lib.ei_device_pointer_motion_absolute(dev, cx + (x - cx) * t, cy + (y - cy) * t)
            self._frame(dev)
            if duration:
                time.sleep(duration / steps)
        self.pos = (x, y)

    def button(self, code, press):
        dev = self._device(CAP_POINTER)
        self.lib.ei_device_button_button(dev, code, press)
        self._frame(dev)

    def click(self, x, y, button=BTN_LEFT, hold=0.05):
        self.move(x, y)
        self.pump(0.05)
        self.button(button, True)
        time.sleep(hold)
        self.button(button, False)

    def drag(self, points, button=BTN_LEFT, step_time=0.02):
        x, y = points[0]
        self.move(x, y)
        self.pump(0.05)
        self.button(button, True)
        for (px, py) in points[1:]:
            self.move(px, py)
            time.sleep(step_time)
        self.button(button, False)

    def scroll(self, dx, dy):
        dev = self._device(CAP_POINTER)
        self.lib.ei_device_scroll_discrete(dev, dx * 120, dy * 120)
        self._frame(dev)

    # ----- keyboard
    def key(self, name, press):
        dev = self._device(CAP_KEYBOARD)
        self.lib.ei_device_keyboard_key(dev, KEY[name], press)
        self._frame(dev)

    def chord(self, *names, hold=0.08):
        """Press the keys in order, release in reverse order (e.g. chord('leftmeta', 'tab'))."""
        for n in names:
            self.key(n, True)
            time.sleep(0.03)
        time.sleep(hold)
        for n in reversed(names):
            self.key(n, False)
            time.sleep(0.03)

    # ----- touch
    def touch_down(self, x, y):
        dev = self._device(CAP_TOUCH)
        self.touch = self.lib.ei_device_touch_new(dev)
        self.lib.ei_touch_down(self.touch, x, y)
        self._frame(dev)

    def touch_move(self, x, y):
        self.lib.ei_touch_motion(self.touch, x, y)
        self._frame(self._device(CAP_TOUCH))

    def touch_up(self):
        self.lib.ei_touch_up(self.touch)
        self._frame(self._device(CAP_TOUCH))
        self.touch = None

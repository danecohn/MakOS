"""X11 event input for private XWayland editor fixtures. Never imports the live desktop."""
import ctypes as c
import os
import subprocess
import time
class Keys:
 def __init__(self):
  assert os.environ.get('MAKOS_OFFICE_CHILD')=='1','Private Office rig only'
  self.x=c.CDLL('libX11.so.6');self.xt=c.CDLL('libXtst.so.6');x=self.x
  x.XOpenDisplay.restype=c.c_void_p;self.d=x.XOpenDisplay(None);assert self.d
  x.XSetInputFocus.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_ulong]
  x.XDefaultRootWindow.argtypes=[c.c_void_p];x.XDefaultRootWindow.restype=c.c_ulong
  x.XInternAtom.argtypes=[c.c_void_p,c.c_char_p,c.c_int];x.XInternAtom.restype=c.c_ulong
  x.XGetWindowProperty.argtypes=[c.c_void_p,c.c_ulong,c.c_ulong,c.c_long,c.c_long,c.c_int,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_int),c.POINTER(c.c_ulong),c.POINTER(c.c_ulong),c.POINTER(c.POINTER(c.c_ubyte))]
  x.XFree.argtypes=[c.c_void_p]
  x.XKeysymToKeycode.argtypes=[c.c_void_p,c.c_ulong];x.XKeysymToKeycode.restype=c.c_ubyte
  x.XSync.argtypes=[c.c_void_p,c.c_int]
  self.xt.XTestFakeKeyEvent.argtypes=[c.c_void_p,c.c_uint,c.c_int,c.c_ulong]
 def prop(self,w,name):
  t=c.c_ulong();fmt=c.c_int();n=c.c_ulong();after=c.c_ulong();p=c.POINTER(c.c_ubyte)()
  self.x.XGetWindowProperty(self.d,w,self.x.XInternAtom(self.d,name.encode(),0),0,4096,0,0,c.byref(t),c.byref(fmt),c.byref(n),c.byref(after),c.byref(p))
  v=list(c.cast(p,c.POINTER(c.c_ulong))[:n.value]) if p and fmt.value==32 else []
  if p:self.x.XFree(p)
  return v
 def focus(self,pid):
  wins=[w for w in self.prop(self.x.XDefaultRootWindow(self.d),'_NET_CLIENT_LIST') if self.prop(w,'_NET_WM_PID')==[pid]]
  assert wins,'No XWayland editor window';self.x.XSetInputFocus(self.d,wins[-1],2,0);self.x.XSync(self.d,0)
 def chord(self,*keys):
  class Event(c.Structure):
   _fields_=[('type',c.c_int),('serial',c.c_ulong),('send_event',c.c_int),('display',c.c_void_p),('window',c.c_ulong),('root',c.c_ulong),('subwindow',c.c_ulong),('time',c.c_ulong),('x',c.c_int),('y',c.c_int),('x_root',c.c_int),('y_root',c.c_int),('state',c.c_uint),('keycode',c.c_uint),('same_screen',c.c_int),('pad',c.c_long*12)]
  self.x.XGetInputFocus.argtypes=[c.c_void_p,c.POINTER(c.c_ulong),c.POINTER(c.c_int)]
  self.x.XSendEvent.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_long,c.c_void_p]
  window=c.c_ulong();revert=c.c_int();self.x.XGetInputFocus(self.d,c.byref(window),c.byref(revert))
  event=Event();event.display=self.d;event.window=window.value;event.root=self.x.XDefaultRootWindow(self.d);event.same_screen=1
  event.keycode=self.x.XKeysymToKeycode(self.d,keys[-1]);event.state=(4 if CTRL in keys[:-1] else 0)|(1 if SHIFT in keys[:-1] else 0)
  for kind,mask in [(2,1),(3,2)]:
   event.type=kind;self.x.XSendEvent(self.d,window.value,1,mask,c.byref(event));self.x.XSync(self.d,0)
  time.sleep(.3)
 def paste(self,text):
  code="import gi,sys;gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk;Gtk.init(None);clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);clip.set_text(sys.argv[1],-1);print('ready',flush=True);Gtk.main()"
  child=subprocess.Popen(['python3','-u','-c',code,text],env=dict(os.environ,GDK_BACKEND='x11'),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
  try:
   assert child.stdout.readline().strip()=='ready'
   self.chord(0xffe3,ord('v'));time.sleep(1)
  finally:
   child.terminate();child.wait(timeout=5)

CTRL=0xffe3;SHIFT=0xffe1;ENTER=0xff0d;ESC=0xff1b

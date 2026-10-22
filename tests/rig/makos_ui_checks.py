"""Run in the isolated rig: real GTK widgets, menu protocol, file navigation and frame callbacks."""
import json
import os
import time
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,Gio,GLib
from makos.shell.main import Shell,magnify
from makos.files import Files
from makos.settings import Settings


def spin(check,timeout=15):
    end=time.monotonic()+timeout
    context=GLib.MainContext.default()
    while time.monotonic()<end:
        while context.pending():context.iteration(False)
        if check():return
        time.sleep(.004)
    raise AssertionError('Timed out')


def settle(seconds=.25):
    end=time.monotonic()+seconds
    spin(lambda:time.monotonic()>=end,seconds+2)

app=Shell()
assert app.register(None)
app.activate()
spin(lambda:(Path(os.environ['XDG_RUNTIME_DIR'])/'makos/shell-ready').exists())
files=Files(app,Path.home()/'Documents')
settle()
assert files.path.name=='Documents'
files.new_tab()
files.go(Path.home())
files.tabs.set_current_page(0)
assert files.path.name=='Documents','tab must restore its own path'
files.view('columns');settle()
assert files.tabs.get_n_pages()==2
files.view('list');settle()
assert files.win.get_mapped()
settings=Settings(app)
settings.pane('Appearance');settle()
assert settings.stack.get_visible_child_name()=='pane'
settings.pane('Launcher Bar');settle()
app.preferences['reduce_motion']=True
app.magnify(0)
assert all(img.get_pixel_size()==app.preferences['launcher_size'] for _,img,_,_ in app.launcher_icons)
app.preferences['reduce_motion']=False
assert magnify(0,56)>magnify(80,56)>magnify(240,56)
# Real com.canonical.dbusmenu service; all calls pass through the session bus.
xml='''<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
</interface></node>'''
events=[]
def handle(conn,sender,path,iface,method,params,inv):
    if method=='GetLayout':
        root=params.unpack()[0]
        child=GLib.Variant('(ia{sv}av)',(2,{'label':GLib.Variant('s','Run fixture')},[]))
        menu=GLib.Variant('(ia{sv}av)',(1,{'label':GLib.Variant('s','_Fixture'),'children-display':GLib.Variant('s','submenu')},[child]))
        layout=(0,{},[menu]) if root==0 else (1,{},[child])
        inv.return_value(GLib.Variant('(u(ia{sv}av))',(1,layout)))
    elif method=='AboutToShow':inv.return_value(GLib.Variant('(b)',(False,)))
    else:events.append(params.unpack());inv.return_value(None)
conn=app.bus
reg=conn.register_object('/FixtureMenu',Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],handle,None,None)
settle(.8)
app.bridge.disconnect_by_func(app.windows_changed)
app.globalmenu.set_active({'menuService':conn.get_unique_name(),'menuPath':'/FixtureMenu'})
spin(lambda:len(app.globalmenu.buttons)==1)
b=app.globalmenu.buttons[0]
assert b.get_label()=='Fixture'
b.emit('clicked')
settle(.4)
remote=b.remote
assert remote.pop.get_visible()
remote._select(2,False)
spin(lambda:bool(events))
assert events[-1][0:2]==(2,'clicked')
app.globalmenu.set_active({})
conn.unregister_object(reg)
# Banners are driven by the real freedesktop notification interface.
reply=[]
def notified(source,result):
    reply.append(source.call_finish(result).unpack()[0])
conn.call(conn.get_unique_name(),'/org/freedesktop/Notifications','org.freedesktop.Notifications','Notify',
    GLib.Variant('(susssasa{sv}i)',('Rig',0,'','MakOS notification','A real isolated notification',[],{},0)),
    None,Gio.DBusCallFlags.NONE,3000,None,notified)
spin(lambda:bool(reply))
assert app.notifications.items[reply[0]]['summary']=='MakOS notification'
assert app.notifications.window.get_visible()
app.notifications.close(reply[0],2)
assert reply[0] not in app.notifications.items
# Frame-clock sample on a changing launcher widget. This is virtual-rig timing only.
times=[]
def frame(widget,clock):
    times.append(clock.get_frame_time())
    app.magnify((len(times)//3)%len(app.launcher_icons))
    return len(times)<121
app.launcher.add_tick_callback(frame)
spin(lambda:len(times)>=121,20)
deltas=[(b-a)/1000 for a,b in zip(times,times[1:]) if b>a]
deltas.sort()
metrics={'frames':len(times),'median_ms':deltas[len(deltas)//2] if deltas else None,'p95_ms':deltas[int(len(deltas)*.95)] if deltas else None,'scope':'virtual KWin frame callbacks; not a physical-display 60 fps certification'}
(Path(os.environ['MAKOS_RIG_SHOTS'])/'frame-timing.json').write_text(json.dumps(metrics,indent=2)+'\n')
files.win.destroy();settings.win.destroy()
app.quit()
print('MAKOS UI PASS: tabs, views, appearance, reduce motion, real DBusMenu render/click, frame-clock timing',flush=True)

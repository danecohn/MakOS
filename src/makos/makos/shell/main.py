"""MakOS shell: own surfaces on KWin. No global theme/default-session mutations."""
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

STARTED = time.monotonic()
import gi

gi.require_version('Gtk','4.0')
gi.require_version('Gdk','4.0')
from gi.repository import Gtk,Gdk,Gio,GLib
# The library has already been loaded by the launcher; never propagate it to apps.
os.environ.pop('LD_PRELOAD',None)
from .. import common,ui,catalog,search
from ..apps import launch
from ..windows import WindowBridge
from ..globalmenu import GlobalMenu
from ..backends import system,netman,bluetooth
from . import layer

CONTROL='''<node><interface name="org.makos.Control"><method name="Action"><arg type="s" direction="in"/></method>
<method name="State"><arg type="s" direction="out"/></method></interface></node>'''


def magnify(distance,base,reduce=False):
    return base if reduce else round(base*(1+.55*math.exp(-distance*distance/(2*78*78))))


class Shell(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.makos.Shell',flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.status={}
        self.overlay=None
        self.launched=[]
        self.remote_windows=[]
        self.preferences=common.load_settings()
        self.search_generation=0
        self._menu_signature=None
        self._clock_signature=None
        self.status_busy=False

    def surface(self,name,kind,anchors,exclusive=None,keyboard='none'):
        win=Gtk.ApplicationWindow(application=self,title=name,decorated=False)
        win.add_css_class('background-surface')
        if not layer.setup(win,kind,anchors,exclusive=exclusive,keyboard=keyboard,namespace='makos-'+name.lower().replace(' ','-')):
            raise RuntimeError('gtk4-layer-shell unavailable: refusing an invisible desktop')
        return win

    def do_activate(self):
        if hasattr(self,'bar'):
            return
        self.hold()
        if not layer.available():
            print('MakOS needs a KWin Wayland session with gtk4-layer-shell.',flush=True)
            self.quit()
            return
        self.theme=ui.install_theme()
        self.bus=Gio.bus_get_sync(Gio.BusType.SESSION)
        self.owner=Gio.bus_own_name_on_connection(self.bus,'org.makos.Shell',Gio.BusNameOwnerFlags.NONE,None,None)
        self.bus.register_object('/Control',Gio.DBusNodeInfo.new_for_xml(CONTROL).interfaces[0],self.control,None,None)
        common.RUNTIME.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.bridge=WindowBridge(self.bus,common.SHARE/'bridge/bridge.js')
        self.bridge.export()
        self.bridge.connect('changed',self.windows_changed)
        self.bridge.load()
        # launcher-and-windows: desktop layer (wallpaper), Launcher Bar, Spread, Desks, switcher live in shell/glue.py
        from .glue import Services
        self.services=Services(self)
        self.services.build_desktop()
        self.build_bar()
        self.build_launcher()
        from ..notifications import Notifications
        self.notifications=Notifications(self)
        GLib.timeout_add_seconds(10,self.poll_status)
        self.poll_status()
        GLib.timeout_add_seconds(1,self.tick)
        self.tick()
        # Ready means mapped surfaces and live control export, not simply import success.
        GLib.timeout_add(500,self.mark_ready)

    def mark_ready(self):
        if self.bar.get_mapped() and self.launcher.get_mapped() and self.desktop.get_mapped():
            (common.RUNTIME/'shell-ready').write_text(str(os.getpid()))
            print('MAKOS_READY '+json.dumps({'startup_seconds':round(time.monotonic()-STARTED,3),'pid':os.getpid()}),flush=True)
            return False
        return True

    def control(self,_conn,_sender,_path,_iface,method,params,invocation):
        if method=='State':
            invocation.return_value(GLib.Variant('(s)',(json.dumps({'windows':self.bridge.state,'preferences':self.preferences,'ready':self.bar.get_mapped()}),)))
        else:
            name=params.unpack()[0]
            # Test-only screenshot action writes only to a fixed explicit rig directory.
            if name.startswith('shot:') and os.environ.get('MAKOS_RIG_SHOTS'):
                self.widget_shot(name[5:])
            else:
                self.action(name)
            invocation.return_value(None)

    def widget_shot(self,name):
        if name=='desktop':
            from ..capture import workspace
            def save(result):
                print('COMPOSITOR_SHOT_FINISHED',flush=True)
            def capture():
                dest=Path(os.environ['MAKOS_RIG_SHOTS'])/'desktop.png'
                temporary=dest.with_suffix('.tmp.png')
                workspace(self.bus).write_to_png(str(temporary))
                temporary.replace(dest)
            self.background(capture,save)
            return
        if name not in ('bar','launcher','overlay','files','settings'):
            return
        target={'bar':self.bar,'launcher':self.launcher,'overlay':self.overlay}.get(name)
        if target is None:
            target=next((w for w in self.get_windows() if w.get_title()==name.title()),None)
        if target and target.get_width()>0:
            from gi.repository import Graphene
            paint=Gtk.WidgetPaintable.new(target)
            snap=Gtk.Snapshot()
            paint.snapshot(snap,target.get_width(),target.get_height())
            node=snap.to_node()
            rect=Graphene.Rect().init(0,0,target.get_width(),target.get_height())
            texture=target.get_renderer().render_texture(node,rect)
            dest=Path(os.environ['MAKOS_RIG_SHOTS'])/(name+'.png')
            texture.save_to_png(str(dest))
            print('SHOT '+str(dest),flush=True)

    def popover(self,anchor,builder):
        old=getattr(anchor,'_pop',None)
        if old:
            old.popdown()
            old.unparent()
        pop=Gtk.Popover()
        pop.set_parent(anchor)
        col=ui.box(True,2)
        col.set_size_request(235,-1)
        builder(col,pop)
        pop.set_child(col)
        anchor._pop=pop
        pop.popup()
        return pop

    def menu(self,parent,label,builder):
        b=Gtk.Button(label=label)
        b.connect('clicked',lambda *_:self.popover(b,builder))
        parent.append(b)
        return b

    def item(self,col,pop,label,fn):
        def action():
            pop.popdown()
            fn()
        col.append(ui.button(label,action))

    def build_bar(self):
        self.bar=self.surface('Menu Bar','top',('top','left','right'),exclusive='auto',keyboard='on_demand')
        row=ui.box(css='menu-bar')
        self.menu(row,'◈',self.system_menu)
        self.active_label=Gtk.Label(label='Files',css_classes=['title-label'],margin_start=6,margin_end=10)
        row.append(self.active_label)
        self.app_menus=ui.box()
        row.append(self.app_menus)
        self.globalmenu=GlobalMenu(self.bus,self.app_menus)
        self.window_menu=self.menu(row,'Window',self.window_actions)
        row.append(Gtk.Box(hexpand=True))
        self.wifi_button=self.menu(row,'Wi-Fi',self.wifi_menu)
        self.menu(row,'Bluetooth',self.bluetooth_menu)
        self.menu(row,'Sound',self.sound_menu)
        self.battery_button=self.menu(row,'Battery',self.battery_menu)
        self.clock_button=self.menu(row,'',self.clock_menu)
        self.menu(row,'Alerts',self.alerts_menu)
        # settings-and-Seek: a menu-bar search field (opens the Seek panel with the typed text); plain menu button if it cannot load
        try:
            from ..seek.panel import install_bar_field
            install_bar_field(self,row)
        except Exception as error:
            print('SEEK_BAR_FALLBACK '+type(error).__name__,flush=True)
            self.menu(row,'Seek',lambda _col,pop:(pop.popdown(),self.action('seek')))
        self.bar.set_child(row)
        self.bar.present()

    def system_menu(self,col,pop):
        self.item(col,pop,'About MakOS',lambda:launch(self,'system-info'))
        self.item(col,pop,'Settings…',lambda:launch(self,'settings'))
        self.item(col,pop,'Applications…',lambda:self.action('applications'))
        col.append(Gtk.Separator())
        self.item(col,pop,'Spread',lambda:self.action('spread'))
        self.item(col,pop,'Desks',lambda:self.action('desktops'))
        col.append(Gtk.Separator())
        self.item(col,pop,'Sleep',lambda:self.confirm_power('suspend'))
        self.item(col,pop,'Restart…',lambda:self.confirm_power('restart'))
        self.item(col,pop,'Shut Down…',lambda:self.confirm_power('poweroff'))
        self.item(col,pop,'Log Out…',lambda:self.confirm_power('logout'))

    def confirm_power(self,action):
        w=ui.window(self,'Session',410,180)
        col=ui.box(True,16,'sheet')
        col.append(Gtk.Label(label={'suspend':'Put this computer to sleep?','restart':'Restart this computer?','poweroff':'Shut down this computer?','logout':'Log out of MakOS?'}[action]))
        row=ui.box(spacing=12)
        row.append(ui.button('Cancel',w.close))
        def perform():
            w.close()
            if action=='logout':
                self.quit()
            else:
                system.power_action('reboot' if action=='restart' else action)
        row.append(ui.button('Continue',perform,'suggested-action'))
        col.append(row)
        w.set_child(col)
        w.present()

    def window_actions(self,col,pop):
        active=next((w for w in self.bridge.app_windows() if w.get('active')),None)
        if active:
            for label,action in [('Minimize','minimize'),('Zoom','maximize'),('Close','close')]:
                self.item(col,pop,label,lambda a=action:self.bridge.command(a,active['id']))
        for w in self.bridge.app_windows():
            self.item(col,pop,w['caption'][:50],lambda w=w:self.bridge.command('activate',w['id']))
        if not self.bridge.app_windows():
            col.append(Gtk.Label(label='No open windows',margin_top=10,margin_bottom=10))

    def wifi_menu(self,col,pop):
        col.append(Gtk.Label(label='Wireless networks',css_classes=['title-label']))
        networks=(self.status.get('wifi') or [])
        for n in networks:
            self.item(col,pop,('✓ ' if n['connected'] else '')+n['ssid']+f"  {n['signal']}%",lambda n=n:self.connect_wifi(n))
        if not networks:
            col.append(Gtk.Label(label='No networks reported',margin_top=10,margin_bottom=10))
        self.item(col,pop,'Refresh',self.poll_status)

    def connect_wifi(self,network):
        # Delegate all secret input to NetworkManager's own agent/terminal; MakOS never captures a password.
        if not network.get('saved'):
            ui.message(self,'Network','This preview can activate saved wireless profiles. Add new credentials using the system network connection editor.')
            return
        self.background(lambda:netman.join(network['ssid']),lambda _:self.poll_status())

    def bluetooth_menu(self,col,pop):
        for device in (self.status.get('bluetooth') or []):
            col.append(Gtk.Label(label=device.get('name',device.get('alias','Device')),margin_top=6,margin_bottom=6))
        self.item(col,pop,'Bluetooth Settings…',lambda:launch(self,'settings').pane('Bluetooth'))

    def sound_menu(self,col,pop):
        col.append(Gtk.Label(label='Output volume',css_classes=['title-label']))
        scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        volume=self.status.get('volume') or {}
        scale.set_value(volume.get('percent',50))
        def changed(s):
            value=round(s.get_value())
            if getattr(self,'_volume_timer',0):
                GLib.source_remove(self._volume_timer)
            def set_value():
                self._volume_timer=0
                self.background(lambda:system.set_volume(value),lambda _:None)
                return False
            self._volume_timer=GLib.timeout_add(120,set_value)
        scale.connect('value-changed',changed)
        col.append(scale)
        self.item(col,pop,'Sound Settings…',lambda:launch(self,'settings').pane('Sound'))

    def battery_menu(self,col,pop):
        battery=self.status.get('battery')
        col.append(Gtk.Label(label=(f"{battery['percent']}% • {battery['state']}" if battery else 'Battery information unavailable'),margin_top=10,margin_bottom=10))
        if battery and battery.get('remaining'):
            col.append(Gtk.Label(label=battery['remaining']))
        self.item(col,pop,'Energy Saver…',lambda:launch(self,'settings').pane('Energy Saver'))

    def alerts_menu(self,col,pop):
        # theme-and-system-skin: history popover (Do Not Disturb, clear, per-entry remove) lives in makos.notifications
        self.notifications.fill_menu(col,pop)

    def clock_menu(self,col,pop):
        col.append(Gtk.Calendar())

    def tick(self):
        stamp=time.strftime('%a %b %d  %I:%M %p')
        if stamp!=self._clock_signature:
            self.clock_button.set_label(stamp)
            self._clock_signature=stamp
        return True

    def background(self,fn,done):
        def work():
            try:
                result=fn()
            except Exception:
                result=None
                print('BACKGROUND_ERROR '+type(sys.exc_info()[1]).__name__,flush=True)
            def deliver():
                done(result)
                return False
            GLib.idle_add(deliver)
        threading.Thread(target=work,daemon=True).start()

    def poll_status(self):
        if self.status_busy:
            return True
        self.status_busy=True
        def read():
            result={}
            for key,fn in [('volume',system.volume),('battery',system.battery),('wifi',netman.wifi_list),('bluetooth',bluetooth.devices)]:
                try:
                    result[key]=fn()
                except Exception:
                    result[key]=None
            return result
        def apply(result):
            self.status_busy=False
            if result:
                self.status=result
                b=result.get('battery')
                self.battery_button.set_label(f"{b['percent']}%" if b else 'Power')
        self.background(read,apply)
        return True

    def build_launcher(self):
        # launcher-and-windows: see shell/dock.py (Launcher Bar) and shell/glue.py
        return self.services.build_launcher()

    def magnify(self,index):
        # kept for the rig: pointer over item `index` (None: pointer left)
        dock=self.services.dock
        if index is None:
            dock.sim_leave()
        else:
            dock.sim_pointer(dock.rest()[index].start+dock.rest()[index].length/2)

    def launch(self,app_id):
        launch(self,app_id)

    def update_indicators(self):
        self.services.windows_changed()

    def windows_changed(self,*_):
        active=next((w for w in self.bridge.app_windows() if w.get('active')),None) or {}
        cls=active.get('cls','')
        name=active.get('caption','Files')
        if cls.startswith('org.makos'):
            name=active.get('caption','Files')
        for app in catalog.APPS:
            if cls in (app.id,'makos-'+app.id,'org.makos.apps.'+app.id.replace('-','_')):name=app.name
        from .launcher import app_id_for_window
        record = catalog.BY_ID.get(app_id_for_window(active)) if active else None
        if record:name=record.name
        self.active_label.set_text(name.split(' — ')[-1][:35] if active else 'Files')
        if active:
            self.globalmenu.set_active(active)
        self.services.windows_changed()

    def reload_preferences(self):
        previous=self.preferences
        self.preferences=common.load_settings()
        self.services.apply_preferences()
        Gtk.Settings.get_default().set_property('gtk-enable-animations',not self.preferences['reduce_motion'])
        for w in self.get_windows():
            if w not in (self.desktop,self.bar,self.launcher,self.overlay):
                (w.add_css_class if self.preferences['pinstripes'] else w.remove_css_class)('pinstripes')

    def close_overlay(self):
        self.search_generation+=1
        if self.overlay:
            self.overlay.destroy()
            self.overlay=None

    def new_overlay(self,title,full=False):
        self.close_overlay()
        self.overlay=self.surface(title,'overlay',('top','left','right','bottom') if full else ('top',),keyboard='exclusive')
        if not full:
            layer.LS.set_margin(self.overlay,layer.LS.Edge.TOP,100)
        keys=Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed',lambda _c,key,*_: (self.close_overlay(),True)[1] if key==Gdk.KEY_Escape else False)
        self.overlay.add_controller(keys)
        return self.overlay

    def action(self,name):
        if self.services.action(name):
            return
        if name.startswith(('capture:','screenshot:')):  # core-apps: Screenshot app asks the shell (the authorised ScreenShot2 client)
            from ..apps.screenshot import shell_action
            return shell_action(self,name)
        if name in catalog.BY_ID and name not in ('seek','spread','desktops','widgets'):
            self.launch(name)
        elif name in ('seek','applications'):
            self.seek(applications_only=name=='applications')
        elif name in ('spread','switcher'):
            self.spread()
        elif name=='desktops':
            self.desks()
        elif name=='widgets':
            self.widgets()
        elif name=='close-overlay':
            self.close_overlay()
        elif name=='quit' and os.environ.get('MAKOS_RIG_SHOTS'):
            self.quit()

    def seek(self,applications_only=False):
        # settings-and-Seek: the full panel (groups, preview, index) is makos/seek/panel.py; the basic panel below is only a fallback
        try:
            from ..seek.panel import open_seek
            return open_seek(self,applications_only)
        except Exception as error:
            print('SEEK_PANEL_FALLBACK '+type(error).__name__+': '+str(error)[:120],flush=True)
        w=self.new_overlay('Seek')
        panel=ui.box(True,12,'seek-sheet')
        panel.set_size_request(640,-1)
        heading=ui.box(spacing=12)
        heading.append(ui.icon('seek',32))
        entry=Gtk.SearchEntry(hexpand=True,placeholder_text='Search applications' if applications_only else 'Search this computer')
        heading.append(entry)
        panel.append(heading)
        results=ui.box(True,2)
        scroller=ui.scroll(results)
        scroller.set_size_request(-1,400)
        panel.append(scroller)
        panel.append(Gtk.Label(label='Applications' if applications_only else 'Applications  •  Documents  •  Calculator  •  Unit conversion',css_classes=['subtitle']))
        self._first_result=None
        def choose(fn):
            self.close_overlay()
            fn()
        def row(label,fn,icon=None):
            if self._first_result is None:self._first_result=fn
            b=ui.button(label,lambda:choose(fn))
            results.append(b)
        def changed(*_):
            self.search_generation+=1
            generation=self.search_generation
            ui.clear(results)
            self._first_result=None
            q=entry.get_text()
            if not applications_only:
                try:
                    value=search.convert(q) or search.calculate(q)
                    row(value,lambda v=value:self.clipboard(v))
                except (SyntaxError,ValueError,ZeroDivisionError,OverflowError):
                    pass
            for record in search.applications(q):
                row(record.name,lambda a=record.id:self.launch(a))
            if not applications_only and len(q)>1:
                def found(paths):
                    if generation!=self.search_generation or not self.overlay:
                        return
                    for path in paths or []:
                        row(path.name+'  —  '+str(path.parent),lambda p=path:self.open_file(p))
                self.background(lambda:search.documents(q),found)
        entry.connect('search-changed',changed)
        entry.connect('activate',lambda *_:choose(self._first_result) if self._first_result else None)
        w.set_child(panel)
        changed()
        w.present()
        entry.grab_focus()

    def clipboard(self,text):
        Gdk.Display.get_default().get_clipboard().set(text)

    def open_file(self,path):
        from ..files import open_uri
        try:
            open_uri(path)
        except Exception as error:
            ui.message(self,'Cannot open',str(error))

    def spread(self):
        w=self.new_overlay('Spread',True)
        outer=ui.box(True,24,'overview')
        outer.append(Gtk.Label(label='Spread',css_classes=['hero']))
        outer.append(Gtk.Label(label='Choose a window • Escape returns to your desk',css_classes=['subtitle']))
        flow=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,valign=Gtk.Align.CENTER,halign=Gtk.Align.CENTER,column_spacing=22,row_spacing=22,max_children_per_line=4)
        for win in self.bridge.app_windows():
            def activate(win=win):
                self.close_overlay()
                self.bridge.command('activate',win['id'])
            card=ui.box(True,10)
            thumbnail=Gtk.Picture(width_request=290,height_request=180,can_shrink=True)
            thumbnail.set_content_fit(Gtk.ContentFit.CONTAIN)
            card.append(thumbnail)
            card.append(Gtk.Label(label=win['caption'][:60],wrap=True,max_width_chars=35))
            b=ui.button('',activate)
            b.set_child(card)
            flow.append(b)
            def get_thumbnail(ident=win['id']):
                import io
                from ..capture import window
                stream=io.BytesIO()
                window(self.bus,ident).write_to_png(stream)
                return stream.getvalue()
            def display(data,picture=thumbnail,overlay=w):
                if data and self.overlay is overlay:
                    try:
                        picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
                    except GLib.Error:
                        pass
            self.background(get_thumbnail,display)
        if not self.bridge.app_windows():
            flow.append(Gtk.Label(label='No windows are open'))
        outer.append(flow)
        w.set_child(outer)
        w.present()

    def desks(self):
        w=self.new_overlay('Desks',True)
        outer=ui.box(True,24,'overview')
        outer.append(Gtk.Label(label='Desks',css_classes=['hero']))
        for d in self.bridge.state.get('desktops',[]):
            def select(n=d['n']):
                self.close_overlay()
                self.bridge.switch_desktop(n)
            outer.append(ui.button(f"{d['n']}  {d['name']}",select))
        w.set_child(outer)
        w.present()

    def widgets(self):
        # core-apps: the Widgets layer lives in makos/widgets (toggle: the hotkey opens and closes it)
        from ..widgets import toggle
        toggle(self)

    def do_shutdown(self):
        ready=common.RUNTIME/'shell-ready'
        if ready.exists() and ready.read_text()==str(os.getpid()):
            ready.unlink()
        Gtk.Application.do_shutdown(self)


def main():
    return Shell().run(sys.argv)

if __name__=='__main__':
    sys.exit(main())

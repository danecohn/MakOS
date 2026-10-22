"""Freedesktop notification server with original glass banners; text is always plain."""
import time
from gi.repository import Gio,GLib,Gtk
from . import ui
from .shell import layer

XML='''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface></node>'''

class Notifications:
    def __init__(self,app):
        self.app=app
        self.conn=app.bus
        self.next_id=1
        self.items={}
        self.silent=False
        self.history=[]
        self.window=None
        self.registration=self.conn.register_object('/org/freedesktop/Notifications',Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],self.handle,None,None)
        self.owner=Gio.bus_own_name_on_connection(self.conn,'org.freedesktop.Notifications',Gio.BusNameOwnerFlags.NONE,None,None)

    def handle(self,_conn,sender,_path,_iface,method,params,invocation):
        if method=='GetCapabilities':
            invocation.return_value(GLib.Variant('(as)',(['body','actions','persistence'],)))
        elif method=='GetServerInformation':
            invocation.return_value(GLib.Variant('(ssss)',('MakOS Notifications','MakOS','0.1.0','1.2')))
        elif method=='CloseNotification':
            ident=params.unpack()[0]
            if ident in self.items and self.items[ident]['sender']==sender:
                self.close(ident,3)
            invocation.return_value(None)
        else:
            name,replaces,icon,summary,body,actions,hints,timeout=params.unpack()
            ident=replaces if replaces in self.items and self.items[replaces]['sender']==sender else self.next_id
            if ident==self.next_id:self.next_id+=1
            notification={'id':ident,'sender':sender,'name':name[:100],'summary':summary[:300],'body':body[:2000],'actions':actions[:16],'time':time.time()}
            self.items[ident]=notification
            self.history.append(notification)
            self.history=self.history[-100:]
            self.render()
            if timeout!=0:
                expiry=max(1500,min(timeout if timeout>0 else 6000,60000))
                GLib.timeout_add(expiry,lambda:self.expire(ident,notification['time']))
            invocation.return_value(GLib.Variant('(u)',(ident,)))

    def expire(self,ident,stamp):
        if self.items.get(ident,{}).get('time')==stamp:
            self.close(ident,1)
        return False

    def close(self,ident,reason):
        item=self.items.pop(ident,None)
        if item:
            self.conn.emit_signal(item['sender'],'/org/freedesktop/Notifications','org.freedesktop.Notifications','NotificationClosed',GLib.Variant('(uu)',(ident,reason)))
            self.render()

    def action(self,item,key):
        self.conn.emit_signal(item['sender'],'/org/freedesktop/Notifications','org.freedesktop.Notifications','ActionInvoked',GLib.Variant('(us)',(item['id'],key)))
        self.close(item['id'],2)

    def render(self):
        if self.window:self.window.destroy();self.window=None
        if not self.items or self.silent:return
        self.window=self.app.surface('Notifications','overlay',('top','right'),keyboard='on_demand')
        layer.LS.set_margin(self.window,layer.LS.Edge.TOP,42)
        layer.LS.set_margin(self.window,layer.LS.Edge.RIGHT,18)
        col=ui.box(True,10)
        for item in list(self.items.values())[-3:]:
            card=ui.box(True,8,'seek-sheet')
            card.set_size_request(340,-1)
            header=ui.box(spacing=10)
            header.append(Gtk.Label(label=item['summary'],wrap=True,max_width_chars=32,hexpand=True,xalign=0,css_classes=['title-label']))
            header.append(ui.button('×',lambda i=item['id']:self.close(i,2)))
            card.append(header)
            card.append(Gtk.Label(label=item['body'],wrap=True,max_width_chars=40,xalign=0))
            for at in range(0,len(item['actions'])-1,2):
                key,label=item['actions'][at:at+2]
                card.append(ui.button(label,lambda i=item,k=key:self.action(i,k)))
            col.append(card)
        self.window.set_child(col)
        self.window.present()

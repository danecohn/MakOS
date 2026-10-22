// MakOS compositor bridge; no session-wide configuration writes.
var SERVICE = 'org.makos.Shell';
function id(w) { return String(w.internalId); }
function report() {
    callDBus(SERVICE, '/Windows', 'org.makos.Windows', 'Report', JSON.stringify({
        windows: workspace.windowList().filter(function(w) { return w.normalWindow; }).map(function(w) {
            var g = w.frameGeometry;
            return {id:id(w),caption:w.caption,cls:String(w.resourceClass),desktopFile:w.desktopFileName,pid:w.pid,
                    active:workspace.activeWindow===w,normal:w.normalWindow,skip:w.skipTaskbar,minimized:w.minimized,
                    x:g.x,y:g.y,w:g.width,h:g.height,desktops:w.desktops.map(function(d){return d.x11DesktopNumber;}),
                    menuService:w.applicationMenuServiceName || '',menuPath:w.applicationMenuObjectPath || ''};
        }), desktops:workspace.desktops.map(function(d){return {n:d.x11DesktopNumber,name:d.name};}),
        current:workspace.currentDesktop.x11DesktopNumber
    }));
}
function watch(w) {
    [w.captionChanged,w.minimizedChanged,w.desktopsChanged,w.applicationMenuChanged].forEach(function(s){if(s && s.connect) s.connect(report);});
}
workspace.windowList().forEach(watch);
workspace.windowAdded.connect(function(w){watch(w);report();});
workspace.windowRemoved.connect(report);
workspace.windowActivated.connect(report);
workspace.currentDesktopChanged.connect(report);
workspace.desktopsChanged.connect(report);
function action(name){callDBus(SERVICE,'/Control','org.makos.Control','Action',name);}
function key(name, seq, fn){registerShortcut('MakOS: '+name,name,seq,fn);}
key('Seek','Meta+Space',function(){action('seek');});
key('Applications','Meta',function(){action('applications');});
key('Settings','Meta+,',function(){action('settings');});
key('Spread','Meta+Ctrl+Up',function(){action('spread');});
key('Desks','Meta+Ctrl+Down',function(){action('desktops');});
key('Application switcher','Meta+Tab',function(){action('switcher');});
key('Next application window','Meta+QuoteLeft',function(){
    var w=workspace.activeWindow;if(!w)return;
    var list=workspace.windowList().filter(function(x){return x.normalWindow && String(x.resourceClass)===String(w.resourceClass);});
    var next=list[(list.indexOf(w)+1)%list.length];if(next){next.minimized=false;workspace.activeWindow=next;}
});
key('Close window','Meta+Q',function(){if(workspace.activeWindow)workspace.activeWindow.closeWindow();});
key('Minimize window','Meta+M',function(){if(workspace.activeWindow)workspace.activeWindow.minimized=true;});
key('Show desktop','Meta+D',function(){workspace.showingDesktop=!workspace.showingDesktop;});
['Left','Right'].forEach(function(side){key('Tile '+side,'Meta+'+side,function(){
    var w=workspace.activeWindow;if(!w)return;var a=workspace.clientArea(KWin.MaximizeArea,w);
    w.setMaximize(false,false);w.frameGeometry={x:a.x+(side==='Right'?a.width/2:0),y:a.y,width:a.width/2,height:a.height};
});});
key('Zoom window','Meta+Up',function(){if(workspace.activeWindow)workspace.activeWindow.setMaximize(true,true);});
key('Restore window','Meta+Down',function(){if(workspace.activeWindow)workspace.activeWindow.setMaximize(false,false);});
report();

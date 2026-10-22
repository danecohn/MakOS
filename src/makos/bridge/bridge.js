// MakOS compositor bridge; no session-wide configuration writes.
// Window state goes to the shell over D-Bus (org.makos.Windows.Report); shell-owned actions come back through
// org.makos.Control.Action. Keyboard shortcuts, screen edges (hot corners) and per-application window memory live here
// because only the compositor sees them in time. Optional settings are read with readConfig() from kwinrc
// [Script-makos-bridge]: HotTopLeft/HotTopRight/HotBottomLeft/HotBottomRight, Memory (JSON), Snap, Memory on/off.
var SERVICE = 'org.makos.Shell';
var stamp = 0;            // activation / minimization counter: larger = more recent
var mru = {};             // internalId -> stamp of the last activation
var minimizedAt = {};     // internalId -> stamp of the last minimization
var memory = {};          // application class (lower case) -> {x,y,w,h} of its last normal window geometry
var memoryDirty = false;
var remembered = {};      // internalId -> true once its remembered geometry was applied
var GRACE = 0;
function id(w) { return String(w.internalId); }
function cfg(name, dflt) { try { return readConfig(name, dflt); } catch (e) { return dflt; } }
function klass(w) { return String(w.resourceClass).toLowerCase(); }
try { memory = JSON.parse(String(cfg('Memory', '{}'))) || {}; } catch (e) { memory = {}; }
var memoryOn = String(cfg('WindowMemory', 'true')) !== 'false';
function touch(w) { if (w) mru[id(w)] = ++stamp; }
workspace.windowList().sort(function (a, b) { return a.stackingOrder - b.stackingOrder; }).forEach(touch);
touch(workspace.activeWindow);

function area(w) {
    try { return workspace.clientArea(KWin.MaximizeArea, w); } catch (e) { return {x: 0, y: 0, width: 1920, height: 1080}; }
}
function isMaximized(w) {
    var a = area(w), g = w.frameGeometry;
    return Math.abs(g.width - a.width) < 6 && Math.abs(g.height - a.height) < 6;
}
function describe(w) {
    var g = w.frameGeometry;
    return {id: id(w), caption: w.caption, cls: String(w.resourceClass), desktopFile: w.desktopFileName, pid: w.pid,
            active: workspace.activeWindow === w, normal: w.normalWindow, skip: w.skipTaskbar, minimized: w.minimized,
            fullscreen: !!w.fullScreen, maximized: isMaximized(w), mru: mru[id(w)] || 0, minimizedAt: minimizedAt[id(w)] || 0,
            stack: w.stackingOrder, output: w.output ? String(w.output.name) : '',
            x: g.x, y: g.y, w: g.width, h: g.height, desktops: w.desktops.map(function (d) { return d.x11DesktopNumber; }),
            menuService: w.applicationMenuServiceName || '', menuPath: w.applicationMenuObjectPath || ''};
}
function report() {
    var a = workspace.activeWindow, scr = [], wa = {x: 0, y: 0, w: 1920, h: 1080};
    try {
        scr = workspace.screens.map(function (o) { var g = o.geometry; return {name: String(o.name), x: g.x, y: g.y, w: g.width, h: g.height}; });
        var c = workspace.clientArea(KWin.MaximizeArea, workspace.activeScreen, workspace.currentDesktop);
        wa = {x: c.x, y: c.y, w: c.width, h: c.height};
    } catch (e) {}
    callDBus(SERVICE, '/Windows', 'org.makos.Windows', 'Report', JSON.stringify({
        windows: workspace.windowList().filter(function (w) { return w.normalWindow; }).map(describe),
        screens: scr, workarea: wa, showingDesktop: !!workspace.showingDesktop,
        desktops: workspace.desktops.map(function (d) { return {n: d.x11DesktopNumber, name: d.name}; }),
        current: workspace.currentDesktop.x11DesktopNumber,
        memory: memoryDirty ? memory : undefined
    }));
    memoryDirty = false;
}
function remember(w) {
    if (!memoryOn || !w || !w.normalWindow || w.fullScreen || w.minimized || isMaximized(w)) return;
    var g = w.frameGeometry, k = klass(w);
    if (!k || g.width < 120 || g.height < 80) return;
    memory[k] = {x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height)};
    memoryDirty = true;
}
function restoreMemory(w) {
    // First map of a window of an application MakOS has seen before: open it where and how big it was. The offset
    // keeps a second window of the same application from landing exactly on top of the first.
    if (!memoryOn || !w.normalWindow || remembered[id(w)] || w.fullScreen || !w.resizeable) return;
    remembered[id(w)] = true;
    var m = memory[klass(w)];
    if (!m || w.transient) return;
    var a = area(w), same = workspace.windowList().filter(function (x) { return x !== w && x.normalWindow && klass(x) === klass(w); }).length;
    var off = (same % 6) * 28;
    var width = Math.min(m.w, a.width), height = Math.min(m.h, a.height);
    var x = Math.max(a.x, Math.min(m.x + off, a.x + a.width - Math.min(width, 120)));
    var y = Math.max(a.y, Math.min(m.y + off, a.y + a.height - 80));
    w.frameGeometry = {x: x, y: y, width: width, height: height};
}
function watch(w) {
    [w.captionChanged, w.desktopsChanged, w.applicationMenuChanged, w.fullScreenChanged].forEach(function (s) { if (s && s.connect) s.connect(report); });
    if (w.minimizedChanged && w.minimizedChanged.connect) w.minimizedChanged.connect(function () {
        if (w.minimized) minimizedAt[id(w)] = ++stamp; else touch(w);
        report();
    });
    if (w.interactiveMoveResizeFinished && w.interactiveMoveResizeFinished.connect) w.interactiveMoveResizeFinished.connect(function () { remember(w); report(); });
    if (w.maximizedChanged && w.maximizedChanged.connect) w.maximizedChanged.connect(function () { report(); });
}
workspace.windowList().forEach(watch);
workspace.windowAdded.connect(function (w) { watch(w); restoreMemory(w); touch(w); report(); });
workspace.windowRemoved.connect(function (w) { delete mru[id(w)]; delete minimizedAt[id(w)]; delete remembered[id(w)]; report(); });
workspace.windowActivated.connect(function (w) { touch(w); report(); });
workspace.currentDesktopChanged.connect(report);
workspace.desktopsChanged.connect(report);
if (workspace.showingDesktopChanged && workspace.showingDesktopChanged.connect) workspace.showingDesktopChanged.connect(report);

function action(name) { callDBus(SERVICE, '/Control', 'org.makos.Control', 'Action', name); }
function key(name, seq, fn) { registerShortcut('MakOS: ' + name, name, seq, fn); }
function active() { var w = workspace.activeWindow; return (w && w.normalWindow) ? w : null; }
function appWindows(w) { return workspace.windowList().filter(function (x) { return x.normalWindow && !x.skipTaskbar && klass(x) === klass(w); }); }

key('Seek', 'Meta+Space', function () { action('seek'); });
key('Applications', 'Meta', function () { action('applications'); });
key('Settings', 'Meta+,', function () { action('settings'); });
key('Spread', 'Meta+Ctrl+Up', function () { action('spread'); });
key('Spread application windows', 'Meta+Ctrl+Shift+Up', function () { action('spread-app'); });
key('Desks', 'Meta+Ctrl+Down', function () { action('desktops'); });
// core-apps: Widgets layer, Screenshot and Tunes media keys (all rebindable in the shortcut settings: they are ordinary KWin global shortcuts)
key('Widgets', 'Meta+F12', function () { action('widgets'); });
key('Screenshot', 'Print', function () { action('screenshot'); });
key('Screenshot: entire screen', 'Meta+Shift+3', function () { action('screenshot:full'); });
key('Screenshot: selection', 'Meta+Shift+4', function () { action('screenshot:selection'); });
key('Screenshot: window', 'Meta+Shift+5', function () { action('screenshot:window'); });
function tunes(method) { callDBus('org.mpris.MediaPlayer2.makos_tunes', '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', method); }
key('Media play/pause', 'Media Play', function () { tunes('PlayPause'); });
key('Media next', 'Media Next', function () { tunes('Next'); });
key('Media previous', 'Media Previous', function () { tunes('Previous'); });
// Application switcher: Meta+Tab walks through *applications* (each with all of its windows), most recent first. The shell
// opens the strip, keeps cycling while Meta is held and commits when it is released (see shell/switcher.py).
key('Application switcher', 'Meta+Tab', function () { action('switcher:next'); });
key('Application switcher backwards', 'Meta+Shift+Tab', function () { action('switcher:prev'); });
function cycleWindows(step) {
    var w = active(); if (!w) return;
    var ring = appWindows(w).sort(function (a, b) { return id(a) < id(b) ? -1 : 1; });
    if (ring.length < 2) return;
    var next = ring[(ring.indexOf(w) + step + ring.length) % ring.length];
    next.minimized = false; workspace.activeWindow = next;
}
key('Next application window', 'Meta+QuoteLeft', function () { cycleWindows(1); });
key('Previous application window', 'Meta+Alt+QuoteLeft', function () { cycleWindows(-1); });
key('Close window', 'Meta+W', function () { var w = active(); if (w) w.closeWindow(); });
key('Quit application', 'Meta+Q', function () { action('quit-app'); });
key('Hide application', 'Meta+H', function () { action('hide-app'); });
key('Hide other applications', 'Meta+Alt+H', function () { action('hide-others'); });
key('Minimize window', 'Meta+M', function () { var w = active(); if (w) w.minimized = true; });
key('Show desktop', 'Meta+D', function () { workspace.showingDesktop = !workspace.showingDesktop; });
key('Full screen', 'Meta+Ctrl+F', function () { var w = active(); if (w) w.fullScreen = !w.fullScreen; });
function tile(w, side) {
    var a = area(w), h = {x: a.x, y: a.y, width: a.width, height: a.height};
    if (side === 'left' || side === 'tl' || side === 'bl') h.width = a.width / 2;
    if (side === 'right' || side === 'tr' || side === 'br') { h.x = a.x + a.width / 2; h.width = a.width / 2; }
    if (side === 'top' || side === 'tl' || side === 'tr') h.height = a.height / 2;
    if (side === 'bottom' || side === 'bl' || side === 'br') { h.y = a.y + a.height / 2; h.height = a.height / 2; }
    w.setMaximize(false, false); w.frameGeometry = h;
}
['Left', 'Right'].forEach(function (side) { key('Tile ' + side, 'Meta+' + side, function () {
    var w = active(); if (w) tile(w, side.toLowerCase());
}); });
key('Zoom window', 'Meta+Up', function () { var w = active(); if (!w) return; if (isMaximized(w)) w.setMaximize(false, false); else { remember(w); w.setMaximize(true, true); } });
key('Restore window', 'Meta+Down', function () { var w = active(); if (w) { w.setMaximize(false, false); w.fullScreen = false; } });
key('Tile top', 'Meta+Shift+Up', function () { var w = active(); if (w) tile(w, 'top'); });
key('Tile bottom', 'Meta+Shift+Down', function () { var w = active(); if (w) tile(w, 'bottom'); });
// Desks
function desk(n) { return workspace.desktops[Math.max(0, Math.min(workspace.desktops.length - 1, n))]; }
function curIndex() { return workspace.desktops.indexOf(workspace.currentDesktop); }
key('Previous desk', 'Meta+Ctrl+Left', function () { workspace.currentDesktop = desk(curIndex() - 1); });
key('Next desk', 'Meta+Ctrl+Right', function () { workspace.currentDesktop = desk(curIndex() + 1); });
key('Move window to previous desk', 'Meta+Ctrl+Shift+Left', function () { var w = active(); if (!w) return; var d = desk(curIndex() - 1); w.desktops = [d]; workspace.currentDesktop = d; workspace.activeWindow = w; });
key('Move window to next desk', 'Meta+Ctrl+Shift+Right', function () { var w = active(); if (!w) return; var d = desk(curIndex() + 1); w.desktops = [d]; workspace.currentDesktop = d; workspace.activeWindow = w; });
[1, 2, 3, 4, 5, 6].forEach(function (n) {
    key('Switch to desk ' + n, 'Meta+' + n, function () { if (workspace.desktops.length >= n) workspace.currentDesktop = desk(n - 1); });
});
// ---- hot corners (Settings > Desks & Spread): kwinrc [Script-makos-bridge] HotTopLeft=none|spread|desks|seek|show_desktop|lock_screen|...
(function () {
    var edges = {HotTopLeft: 'ElectricTopLeft', HotTopRight: 'ElectricTopRight', HotBottomLeft: 'ElectricBottomLeft', HotBottomRight: 'ElectricBottomRight'};
    Object.keys(edges).forEach(function (name) {
        var what = String(readConfig(name, 'none'));
        if (what === 'none' || KWin[edges[name]] === undefined || typeof registerScreenEdge !== 'function') return;
        registerScreenEdge(KWin[edges[name]], function () {
            if (what === 'spread') action('spread');
            else if (what === 'app_windows') action('spread-app');
            else if (what === 'desks') action('desktops');
            else if (what === 'seek') action('seek');
            else if (what === 'launcher') action('launcher-reveal');
            else if (what === 'show_desktop') workspace.showingDesktop = !workspace.showingDesktop;
            else if (what === 'lock_screen') callDBus('org.freedesktop.ScreenSaver', '/ScreenSaver', 'org.freedesktop.ScreenSaver', 'Lock');
        });
    });
    // The top edge reveals the menu bar while a full screen application hides it (shell/fullscreen.py decides).
    if (typeof registerScreenEdge === 'function' && KWin.ElectricTop !== undefined) registerScreenEdge(KWin.ElectricTop, function () { action('edge:top'); });
})();
report();

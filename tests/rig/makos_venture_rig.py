"""Real installed browser engine with private MakkOS profile and test-only Marionette."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).parent))
import makos_launcher_lib as L
sys.path.insert(0,str(L.ROOT/'src/makos'))
from makos import venture
out=L.ROOT/'dist/makos/venture-rig';out.mkdir(parents=True,exist_ok=True)
env=L.sh_env()
profile=venture.prepare(Path(os.environ['XDG_DATA_HOME'])/'makos/venture',L.ROOT/'src/makos/venture')
with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
with (profile/'user.js').open('a') as stream:stream.write(f'user_pref("marionette.port", {port});\n')
log=(out/'browser.log').open('w');proc=None;client=None;serial=0

def receive():
    header=b''
    while not header.endswith(b':'):
        byte=client.recv(1)
        if not byte:raise EOFError()
        header+=byte
    remaining=int(header[:-1]);data=b''
    while len(data)<remaining:data+=client.recv(remaining-len(data))
    return json.loads(data)

def call(name,params=None):
    global serial
    serial+=1;data=json.dumps([0,serial,name,params or {}]).encode();client.sendall(str(len(data)).encode()+b':'+data)
    while True:
        reply=receive()
        if reply[0]==1 and reply[1]==serial:
            if reply[2]:raise AssertionError(reply[2])
            return reply[3]

def script(text):return call('WebDriver:ExecuteScript',{'script':text,'args':[],'newSandbox':True,'sandbox':'default'})['value']

try:
    L.start_shell()
    proc=subprocess.Popen([str(L.ROOT/'src/makos/bin/makos-venture'),'--marionette','--remote-allow-system-access'],env=env,stdout=log,stderr=subprocess.STDOUT)
    def connect():
        global client
        if proc.poll() is not None:raise AssertionError((out/'browser.log').read_text())
        try:client=socket.create_connection(('127.0.0.1',port),.3);client.settimeout(20);return True
        except OSError:return False
    L.wait_for(connect,40,'browser Marionette')
    receive();call('WebDriver:NewSession',{'capabilities':{'alwaysMatch':{}}})
    call('WebDriver:SetWindowRect',{'width':1280,'height':850})
    call('Marionette:SetContext',{'value':'chrome'})
    time.sleep(3)
    geometry=script('return Object.fromEntries(["nav-bar","PersonalToolbar","TabsToolbar","searchbar-new","urlbar"].map(id=>{let r=document.getElementById(id).getBoundingClientRect();return [id,{x:r.x,y:r.y,w:r.width,h:r.height}]}));')
    print('CHROME',json.dumps(geometry),flush=True)
    print('LAYOUT',script('return {state:Services.prefs.getStringPref("browser.uiCustomization.state",""),nav:Array.from(document.getElementById("nav-bar-customization-target").children).map(x=>x.id),search:CustomizableUI.getPlacementOfWidget("search-container"),toolbar:document.getElementById("PersonalToolbar").outerHTML.slice(0,500),bookmarks:Services.prefs.getStringPref("browser.toolbars.bookmarks.visibility"),version:Services.appinfo.version};'),flush=True)
    L.control('shot:desktop');time.sleep(2)
    (out/'desktop.png').write_bytes((L.SHOTS/'desktop.png').read_bytes())
    assert geometry['nav-bar']['y']<geometry['PersonalToolbar']['y']<geometry['TabsToolbar']['y']
    assert geometry['searchbar-new']['w']>=140
    assert geometry['urlbar']['w']>300
    # Branded title and a real new-tab navigation, not only the startup preference.
    assert script('return Services.strings.createBundle("chrome://branding/locale/brand.properties").GetStringFromName("brandShortName");')=='Venture'
    script('BrowserCommands.openTab();return true;')
    time.sleep(2)
    call('Marionette:SetContext',{'value':'content'})
    page=script('return document.body.innerText;')
    assert 'Venture' in page and 'Artemis Softworks LLC' in page and 'Amerika' not in page,page
    call('Marionette:SetContext',{'value':'chrome'})
    script('gBrowser.removeCurrentTab();return true;')
    # Identity control visibility is page-dependent on Firefox internal resources.
    # Verify it on a local HTTP page instead; no security preference is changed.
    import http.server,threading
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    call('Marionette:SetContext',{'value':'content'})
    call('WebDriver:Navigate',{'url':f'http://127.0.0.1:{server.server_port}/'})
    call('Marionette:SetContext',{'value':'chrome'})
    assert script('return getComputedStyle(document.getElementById("identity-box")).display;')!='none'
    server.shutdown()
    count=script('return gBrowser.tabs.length;')
    script('gBrowser.selectedTab=gBrowser.addTab("about:blank",{triggeringPrincipal:Services.scriptSecurityManager.getSystemPrincipal()});return true;')
    assert script('return gBrowser.tabs.length;')==count+1
    script('gBrowser.removeCurrentTab();return true;')
    assert script('return gBrowser.tabs.length;')==count
    # A second invocation must hand its URL to the running dedicated profile.
    other=subprocess.run([str(L.ROOT/'src/makos/bin/makos-venture'),'about:blank'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
    assert other.returncode==0,other.stdout.decode()[-500:]
    time.sleep(2)
    assert script('return gBrowser.tabs.length;')==count+1
    client.close();client=None
    proc.terminate();proc.wait(timeout=10)
    proc=subprocess.Popen([str(L.ROOT/'src/makos/bin/makos-venture')],env=env,stdout=log,stderr=subprocess.STDOUT)
    time.sleep(6)
    L.control('shot:desktop');time.sleep(2)
    (out/'desktop.png').write_bytes((L.SHOTS/'desktop.png').read_bytes())
    (out/'geometry.json').write_text(json.dumps(geometry,indent=2)+'\n')
    print('VENTURE RIG PASS: real chrome layout, identity indicator, tabs and URL handoff; private profile',flush=True)
finally:
    if client:client.close()
    if proc and proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    log.close();L.cleanup()

"""Test extracted Debian payloads, with real utilities in separate processes."""
import ast
import json
import os
import signal
import subprocess
import time
from pathlib import Path

root=Path(os.environ['ROOT'])
temp=Path(os.environ['T'])
payload=temp/'payload'
shots=root/'dist/makos/package-rig';shots.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,MAKOS_SHARE=str(payload/'usr/share/makos'),PYTHONPATH=str(payload/'usr/lib/python3/dist-packages'),MAKOS_RIG_SHOTS=str(shots),GTK_A11Y='none')
env.pop('MAKOS_RIG_EMBED_APPS',None)
env['PATH']=str(payload/'usr/bin')+':'+env['PATH']
log=temp/'packaged-shell.log'
handle=log.open('w')
shell=subprocess.Popen([str(payload/'usr/bin/makos-shell')],env=env,stdout=handle,stderr=subprocess.STDOUT)
children=[]
for folder in ('Documents','Downloads','Pictures','Desktop','Music'):(Path.home()/folder).mkdir(exist_ok=True)
(Path.home()/'Documents/Welcome.txt').write_text('MakkOS private-rig sample document.\n')

def wait(fn,seconds=25):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if shell.poll() is not None:raise AssertionError(log.read_text())
        result=fn()
        if result:return result
        time.sleep(.2)
    raise AssertionError('Packaged app did not become ready')

def call(method,*args):
    return subprocess.check_output(['gdbus','call','--session','--dest','org.makos.Shell','--object-path','/Control','--method','org.makos.Control.'+method,*args],env=env,text=True,timeout=10)

def state():
    return json.loads(ast.literal_eval(call('State'))[0])['windows']['windows']

try:
    wait(lambda:(Path(env['XDG_RUNTIME_DIR'])/'makos/shell-ready').exists(),40)
    call('Action','files')
    wait(lambda:any(w.get('cls')=='org.makos.Apps.files' and not w['skip'] for w in state()))
    call('Action','settings')
    wins=wait(lambda:[w for w in state() if w.get('cls') in ('org.makos.Apps.files','org.makos.Apps.settings') and not w['skip']] if len([w for w in state() if w.get('cls') in ('org.makos.Apps.files','org.makos.Apps.settings') and not w['skip']])>=2 else None)
    children=[int(w['pid']) for w in wins]
    assert all(p!=shell.pid for p in children),'Apps must be separate from the desktop shell'
    assert len(set(children))==2,'Files and Settings must have distinct processes'
    time.sleep(1)  # Let compositor open/focus animations settle before evidence capture.
    (shots/'desktop.png').unlink(missing_ok=True)
    call('Action','shot:desktop')
    wait(lambda:(shots/'desktop.png').exists())
    from PIL import Image
    with Image.open(shots/'desktop.png') as im:
        assert im.getbbox() is not None
        from PIL import ImageStat
        background=ImageStat.Stat(im.convert('RGB').crop((10,100,300,700)))
        assert max(background.stddev)>3 and max(background.extrema[0])>10, 'Packaged wallpaper is blank'
    print('PACKAGED RIG PASS: extracted shell, Files and Settings ready in independent processes; real compositor pixels captured',flush=True)
finally:
    for pid in children:
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass
    if shell.poll() is None:
        call('Action','quit')
        shell.wait(timeout=10)
    handle.close()
    (shots/'shell.log').write_text(log.read_text())
    assert 'Traceback' not in log.read_text(),log.read_text()

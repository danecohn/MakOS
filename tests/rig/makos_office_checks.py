"""Probe installed upstream wrapper and editor modes through real KWin window metadata."""
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import time

root=Path(os.environ['ROOT']);out=Path(os.environ['OUT'])
env=dict(os.environ,MAKOS_RIG_SHOTS=str(out))
log=(out/'shell.log').open('w')
shell=subprocess.Popen([str(root/'src/makos/bin/makos-shell')],env=env,stdout=log,stderr=subprocess.STDOUT)
processes=[]

def wait(fn,seconds=45):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if shell.poll() is not None:raise AssertionError('shell exited')
        result=fn()
        if result:return result
        time.sleep(.2)
    raise AssertionError('Timed out')

def call(method,*args):
    return subprocess.check_output(['gdbus','call','--session','--dest','org.makos.Shell','--object-path','/Control','--method','org.makos.Control.'+method,*args],text=True,timeout=8)
def wins():
    return json.loads(ast.literal_eval(call('State'))[0])['windows']['windows']

try:
    wait(lambda:(Path(os.environ['XDG_RUNTIME_DIR'])/'makos/shell-ready').exists())
    from makos import catalog
    for app_id,kind in [('paper','word'),('digits','cell'),('slides','slide')]:
        command=catalog.resolve(catalog.BY_ID[app_id],__import__('shutil').which)
        assert command==['euro-office-euro-office','--new:'+kind]
        child_env=dict(env,QT_QPA_PLATFORM='xcb')
        child_env.pop('LD_PRELOAD',None)
        handle=(out/(app_id+'.log')).open('w')
        proc=subprocess.Popen(command,env=child_env,stdout=handle,stderr=subprocess.STDOUT)
        processes.append(proc)
        window=wait(lambda:next((w for w in wins() if 'euro-office' in w.get('cls','').lower() and w.get('caption') and not w.get('skip')),None),60)
        print(app_id,json.dumps({k:window.get(k) for k in ('caption','cls','pid')}),flush=True)
        time.sleep(5)
        assert proc.poll() is None or proc.returncode==0,'upstream process crashed'
        target=out/'desktop.png';target.unlink(missing_ok=True)
        call('Action','shot:desktop');wait(lambda:target.exists())
        from PIL import Image
        with Image.open(target) as im:assert im.getbbox() is not None
        (out/(app_id+'.png')).write_bytes(target.read_bytes())
        # All editor documents belong to this private fixture; terminate the exact editor PID between modes.
        pid=window['pid']
        os.kill(pid,signal.SIGTERM)
        if proc.poll() is None:
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        handle.close()
        wait(lambda:not any(w.get('pid')==pid for w in wins()),10)
    print('MAK OFFICE RIG PASS: installed wrapper, three editor modes, KWin windows and compositor pixels; save/edit acceptance remains open',flush=True)
finally:
    for proc in processes:
        if proc.poll() is None:proc.terminate()
    if shell.poll() is None:shell.terminate();shell.wait(timeout=10)
    log.close()

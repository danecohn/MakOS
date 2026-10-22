"""Real installed Euro-Office editing, serialization and reopening on private fixtures.

Uses X11 clipboard/event delivery inside the isolated compositor. No owner file,
profile, credentials or system input permissions are accessed.
"""
import ast
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET
from makos_xinput import Keys,CTRL,ENTER

root=Path(os.environ['ROOT']);out=Path(os.environ['OUT']);home=Path.home()
env=dict(os.environ,MAKOS_RIG_SHOTS=str(out));env.pop('LD_PRELOAD',None)
log=(out/'shell.log').open('w')
shell=subprocess.Popen([str(root/'src/makos/bin/makos-shell')],env=env,stdout=log,stderr=subprocess.STDOUT)
processes=[]
MARKER='Makk Office roundtrip fixture'
def wait(fn,seconds=45):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if shell.poll() is not None:raise AssertionError('shell exited')
  value=fn()
  if value:return value
  time.sleep(.2)
 raise AssertionError('Timed out')
def call(method,*args):
 return subprocess.check_output(['gdbus','call','--session','--dest','org.makos.Shell','--object-path','/Control','--method','org.makos.Control.'+method,*args],text=True,timeout=8)
def wins():return json.loads(ast.literal_eval(call('State'))[0])['windows']['windows']
def capture(name):
 target=out/'desktop.png';target.unlink(missing_ok=True);call('Action','shot:desktop');wait(lambda:target.exists());shutil.copy2(target,out/name)
def launch(path,app):
 handle=(out/(app+'.log')).open('a')
 proc=subprocess.Popen(['euro-office-euro-office',str(path)],env=dict(env,QT_QPA_PLATFORM='xcb',GDK_BACKEND='x11'),stdout=handle,stderr=subprocess.STDOUT)
 processes.append(proc)
 window=wait(lambda:next((w for w in wins() if 'euro-office' in w.get('cls','').lower() and path.name in w.get('caption','') and not w.get('skip')),None),60)
 time.sleep(4);return proc,window,handle

def stop(proc,window,handle):
 os.kill(window['pid'],signal.SIGTERM)
 if proc.poll() is None:
  try:proc.wait(timeout=10)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
 handle.close();wait(lambda:not any(w.get('pid')==window['pid'] for w in wins()),10)

def ppt_fixture(path):
 p='http://schemas.openxmlformats.org/presentationml/2006/main';a='http://schemas.openxmlformats.org/drawingml/2006/main'
 ET.register_namespace('p',p);ET.register_namespace('a',a)
 with zipfile.ZipFile(path) as z:data={n:z.read(n) for n in z.namelist()}
 slide=ET.fromstring(data['ppt/slides/slide1.xml']);tree=slide.find('.//{'+p+'}spTree')
 shape=ET.fromstring(f'<p:sp xmlns:p="{p}" xmlns:a="{a}"><p:nvSpPr><p:cNvPr id="101" name="Roundtrip fixture"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="7315200" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2800"/><a:t>{MARKER}</a:t></a:r></a:p></p:txBody></p:sp>')
 tree.append(shape);data['ppt/slides/slide1.xml']=ET.tostring(slide,encoding='utf-8',xml_declaration=True)
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
  for name,content in data.items():z.writestr(name,content)
 return len([n for n in data if n.startswith('ppt/slides/slide') and n.endswith('.xml')])
try:
 wait(lambda:(Path(os.environ['XDG_RUNTIME_DIR'])/'makos/shell-ready').exists())
 for app,ext in [('paper','docx'),('digits','xlsx'),('slides','pptx')]:
  if os.environ.get('MAKOS_OFFICE_ONLY') and app!=os.environ['MAKOS_OFFICE_ONLY']:continue
  path=home/('Makk-roundtrip.'+ext);shutil.copy2('/opt/euro-office/euro-office/converter/empty/en-US/new.'+ext,path)
  slide_count=ppt_fixture(path) if app=='slides' else 0
  before=path.read_bytes();proc,window,handle=launch(path,app)
  keys=Keys();keys.focus(window['pid'])
  if app=='slides':
   capture('slides-before.png');keys.chord(CTRL,ord('m'));time.sleep(2);capture('slides-edit.png')
  else:
   keys.paste(MARKER)
   if app=='digits':keys.chord(ENTER)
  keys.chord(CTRL,ord('s'));wait(lambda:path.read_bytes()!=before,20);time.sleep(1)
  with zipfile.ZipFile(path) as z:
   assert any(MARKER.encode() in z.read(n) for n in z.namelist() if n.endswith('.xml')),app+' content missing'
   if app=='slides':assert len([n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')])>slide_count
  capture(app+'-saved.png');stop(proc,window,handle)
  proc,window,handle=launch(path,app);capture(app+'-reopened.png')
  print(app,'EDIT/SAVE/REOPEN PASS',json.dumps({'file':path.name,'bytes':path.stat().st_size,'caption':window['caption']}),flush=True)
  stop(proc,window,handle)
 print('MAKK OFFICE ROUNDTRIP PASS: three real editor modes; serialized content checked; independent reopen windows captured',flush=True)
finally:
 for proc in processes:
  if proc.poll() is None:proc.terminate()
 if shell.poll() is None:shell.terminate();shell.wait(timeout=10)
 log.close()

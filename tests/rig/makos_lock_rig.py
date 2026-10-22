"""Real KDE lock greeter in test mode inside the private compositor; no authentication."""
import subprocess,time
import makos_launcher_lib as L
log=None;proc=None
try:
 L.start_shell()
 out=L.ROOT/'dist/makos/lock-rig';out.mkdir(parents=True,exist_ok=True)
 log=(out/'greeter.log').open('w')
 proc=subprocess.Popen(['/usr/lib/aarch64-linux-gnu/libexec/kscreenlocker_greet','--testing','--shell',str(L.ROOT/'src/makos/theme/lockscreen')],env=L.sh_env(),stdout=log,stderr=subprocess.STDOUT)
 time.sleep(4)
 from makos_input import Input
 input=Input();input.chord('space');time.sleep(2)
 assert proc.poll() is None,(out/'greeter.log').read_text()
 L.control('shot:desktop');time.sleep(1)
 (out/'lock.png').write_bytes((L.SHOTS/'desktop.png').read_bytes())
 text=(out/'greeter.log').read_text()
 assert 'failed to load' not in text.lower(),text
 print('LOCK RIG PASS: native KDE test greeter rendered without authentication or session change',flush=True)
finally:
 if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=10)
 if log:log.close()
 L.cleanup()

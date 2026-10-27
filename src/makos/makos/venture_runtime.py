"""Venture resource overlay. Original engine and all existing browser profiles stay intact.

Only presentation resources are changed. Mozilla's MPL code and upstream licence
files remain available from the installed engine. No security preferences change.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import zipfile


def runtime(engine, share, cache=None):
    engine=Path(engine);share=Path(share)
    required=('firefox','firefox-bin','application.ini','browser/omni.ja')
    if not all((engine/n).is_file() for n in required):
        raise RuntimeError('The installed Venture engine layout is unsupported.')
    digest=hashlib.sha256(b'venture-overlay-v2')
    for n in required:
        stat=(engine/n).stat();digest.update(f'{n}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    for n in ('start.html','vigilos.svg'):
        digest.update((share/n).read_bytes())
    base=Path(cache or Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'makos/venture-runtime')
    base.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=base/digest.hexdigest()[:20]
    with (base/'build.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (target/'ready').exists():return target/'firefox'
        temp=Path(tempfile.mkdtemp(prefix='building-',dir=base))
        try:
            for child in engine.iterdir():
                if child.name=='browser':continue
                if child.name in ('firefox','firefox-bin'):
                    shutil.copy2(child,temp/child.name)
                elif child.name=='application.ini':
                    text=child.read_text().replace('Vendor=Artemis Softworks LLC','Vendor=VigilTech').replace('Name=AmerikaVenture','Name=Venture').replace('RemotingName=amerika-venture','RemotingName=makos-venture')
                    (temp/child.name).write_text(text)
                elif child.name=='distribution':
                    dest=temp/'distribution';dest.mkdir()
                    # Keep engine safety policies, while adopting the Venture start page.
                    import json
                    policy=json.loads((child/'policies.json').read_text())
                    policy['policies']['Homepage']={'URL':'resource://venture/index.html','Locked':False,'StartPage':'homepage'}
                    policy['policies']['DisplayBookmarksToolbar']='always'
                    prefs=policy['policies'].setdefault('Preferences',{})
                    prefs['extensions.activeThemeID']={'Value':'default-theme@mozilla.org','Status':'default'}
                    prefs['app.releaseNotesURL']={'Value':'https://github.com/danecohn/MakOS','Status':'default'}
                    (dest/'policies.json').write_text(json.dumps(policy))
                    (dest/'distribution.ini').write_text('[Global]\nid=org.makos.venture\nversion=1\nabout=Venture for VigilOS by VigilTech\n[Preferences]\napp.distributor="VigilTech"\napp.distributor.channel="venture"\n')
                else:(temp/child.name).symlink_to(child)
            browser=temp/'browser';browser.mkdir()
            for child in (engine/'browser').iterdir():
                if child.name!='omni.ja':(browser/child.name).symlink_to(child)
            replacements={
                'venture/index.html':(share/'start.html').read_bytes(),
                'venture/vigilos.svg':(share/'vigilos.svg').read_bytes(),
            }
            with zipfile.ZipFile(engine/'browser/omni.ja') as src, zipfile.ZipFile(browser/'omni.ja','w',zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data=src.read(info.filename)
                    if info.filename in replacements:data=replacements.pop(info.filename)
                    elif '/branding/' in info.filename and info.filename.endswith(('.ftl','.properties','.svg','.css')):
                        data=data.decode().replace('Amerika Venture','Venture').replace('Artemis Softworks LLC','VigilTech').encode()
                    if info.filename.endswith('aboutDialog.css'):
                        data+=b'\n#aboutDialogContainer,#bottomBox{background:#f6f1f4!important;color:#17101a!important}\n'
                    dst.writestr(info,data)
                for name,data in replacements.items():dst.writestr(name,data)
            (temp/'ready').touch();temp.rename(target)
        except BaseException:
            shutil.rmtree(temp);raise
    return target/'firefox'

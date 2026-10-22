"""Venture's original MakkOS chrome, confined to a dedicated profile. No Firefox profile is modified."""
import json
import os
from pathlib import Path
import shutil
import sys

from . import common

BEGIN='// BEGIN MAKOS VENTURE\n'
END='// END MAKOS VENTURE\n'


def managed_text(previous, content, begin=BEGIN, end=END):
    if begin in previous and end in previous:
        start=previous.index(begin);stop=previous.index(end,start)+len(end)
        previous=previous[:start]+previous[stop:]
    return previous.rstrip()+'\n'+begin+content+end


def prepare(profile=None, share=None):
    profile=Path(profile or Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'makos/venture')
    share=Path(share or common.SHARE/'venture')
    profile.mkdir(parents=True,exist_ok=True,mode=0o700)
    chrome=profile/'chrome';chrome.mkdir(exist_ok=True)
    css=chrome/'userChrome.css'
    old=css.read_text() if css.exists() else ''
    css.write_text(managed_text(old, '@import url('+json.dumps((share/'venture.css').as_uri())+');\n',
        '/* BEGIN MAKOS VENTURE */\n','/* END MAKOS VENTURE */\n'))
    preferences={
        'toolkit.legacyUserProfileCustomizations.stylesheets':True,
        'browser.tabs.inTitlebar':0,
        'browser.compactmode.show':True,
        'browser.uidensity':1,
        'browser.search.widget.inNavBar':True,
        'browser.toolbars.bookmarks.visibility':'always',
        'browser.startup.homepage':(share/'start.html').as_uri(),
        'browser.startup.page':1,
        'browser.shell.checkDefaultBrowser':False,
    }
    prefs=profile/'user.js';old=prefs.read_text() if prefs.exists() else ''
    prefs.write_text(managed_text(old,''.join('user_pref('+json.dumps(k)+', '+json.dumps(v)+');\n' for k,v in preferences.items())))
    # Seed toolbar layout only once. Subsequent customization belongs to the user.
    marker=profile/'makos-layout-v1'
    if not marker.exists():
        layout={'placements':{'nav-bar':['back-button','forward-button','stop-reload-button','home-button','urlbar-container','search-container','downloads-button','unified-extensions-button'], 'PersonalToolbar':['personal-bookmarks'], 'TabsToolbar':['tabbrowser-tabs','new-tab-button','alltabs-button']},'currentVersion':23,'newElementCount':0,'dirtyAreaCache':[]}
        with prefs.open('a') as stream:stream.write('user_pref("browser.uiCustomization.state", '+json.dumps(json.dumps(layout))+');\n')
        xulstore=profile/'xulstore.json'
        if not xulstore.exists():
            xulstore.write_text(json.dumps({'chrome://browser/content/browser.xhtml':{'PersonalToolbar':{'collapsed':'false'}}}))
        marker.touch()
    return profile


def command(args=(), which=shutil.which, profile=None):
    backend=next((which(exe) for exe in ('amerika-venture','firefox') if which(exe)),None)
    if not backend:raise RuntimeError('Venture requires the installed amerika-venture or Firefox browser engine.')
    return [backend,'--profile',str(prepare(profile)),*args]


def main():
    try:argv=command(sys.argv[1:])
    except (OSError,RuntimeError) as exc:sys.exit(str(exc))
    env=dict(os.environ);env.pop('LD_PRELOAD',None)
    os.execvpe(argv[0],argv,env)

if __name__=='__main__':main()

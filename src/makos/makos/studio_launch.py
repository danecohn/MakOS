"""MakOS cosmetic overlays for the retained Studio suite; upstream identities stay stable."""
import os
import sys
from pathlib import Path
from . import common


def main(argv=None):
    argv=list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] not in ('studio','render','engine','sprite','makbox'):
        return 2
    app=argv.pop(0)
    base=common.SHARE/'compat'
    sys.path.insert(0,str(base/'python'))
    os.environ['AMERIKA_STUDIO_WEB']=str(base/'studio-web')
    os.environ['AMERIKA_STUDIO_SHARE']='/usr/share/amerika-studio'
    os.environ['AMERIKA_NO_GAMEMODE']='1'
    if app=='studio':
        from amerika_studio.hub import main as start
        return start()
    if app in ('sprite','makbox'):
        from amerika_studio.webview import main as start
        ident='box' if app=='makbox' else 'sprite'
        title='MakBox' if app=='makbox' else 'Sprite'
        return start(['--app',ident,'--dir',str(base/ident),'--title',title,*argv])
    if app=='engine':
        os.environ['AMERIKA_ENGINE_SHARE']=str(base/'engine')
        from amerika_engine.launcher import main as start
        return start(argv)
    if app=='render':
        os.environ['AMERIKA_RENDER_SHARE']=str(base/'render')
        os.environ['AMERIKA_RENDER_CONFIG']=str(common.CONFIG/'render')
        os.execv('/usr/bin/amerika-render',['/usr/bin/amerika-render',*argv])
    return 0

if __name__=='__main__':
    sys.exit(main())

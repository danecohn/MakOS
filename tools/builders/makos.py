"""Separate MakOS packages. No dependencies added to Amerika's metapackage."""
import shutil
import subprocess

VERSION='0.1.0~dev2'
NAMES=('makos-session','makos-shell','makos-theme','makos-icons','makos-apps','makos-desktop')


def register(b):
    source=b.SRC/'makos'
    def package(name,description,depends='',arch='all'):
        p=b.Pkg(name,VERSION,description,depends=depends,arch=arch)
        p.copyright('MakOS original code and vectors: GPL-3.0-only.\nGenerated artwork: dedicated to CC0-1.0 by the owner.\nReused Amerika plumbing: GPL-3.0-only; attribution in ASSETS.md.\nFonts are provided by Ubuntu fonts-dejavu-core under its upstream licence.\n')
        p.copy(b.ROOT/'docs/makos/ASSETS.md',f'/usr/share/doc/{name}/ASSETS.md')
        return p
    def shell():
        p=package('makos-shell','MakOS desktop shell and native utilities',
                  'python3, libpython3.14, python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0 (>= 4.10), gir1.2-gtk4layershell-1.0, libgtk4-layer-shell0, makos-theme, makos-icons, network-manager, wireplumber, upower, fonts-dejavu-core',arch='arm64')
        shutil.copytree(source/'makos',p.path('/usr/lib/python3/dist-packages/makos'),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(source/'bridge',p.path('/usr/share/makos/bridge'))
        for name in ('makos-shell','makos-app','makos-studio-app'):
            p.copy(source/'bin'/name,'/usr/bin/'+name,0o755)
        output=p.path('/usr/libexec/makos/makos-shell-host')
        output.parent.mkdir(parents=True,exist_ok=True)
        flags=subprocess.check_output(['python3-config','--embed','--ldflags'],text=True).split()
        b.sh('cc','-O2','-Wl,-z,relro,-z,now',source/'shell-host.c','-o',output,*flags)
        p.file('/usr/share/applications/org.makos.Shell.desktop','[Desktop Entry]\nType=Application\nName=MakOS Shell\nExec=/usr/libexec/makos/makos-shell-host\nNoDisplay=true\nX-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n')
        p.copy(source/'helpers/makos-settings-helper','/usr/libexec/makos/makos-settings-helper',0o755)
        p.copy(source/'helpers/org.makos.settings.policy','/usr/share/polkit-1/actions/org.makos.settings.policy')
        return p
    def session():
        p=package('makos-session','MakOS independent KWin Wayland login session',
                  'kwin-wayland (>= 4:6.7), kwin-style-aurorae (>= 6.7), xwayland, dbus-user-session, makos-shell, polkit-kde-agent-1',arch='arm64')
        p.copy(source/'session/makos-session','/usr/bin/makos-session',0o755)
        for name in ('session-start','makos-xkb-override'):
            p.copy(source/'session'/name,'/usr/libexec/makos/'+name,0o755)
        p.copy(source/'session/makos.desktop','/usr/share/wayland-sessions/makos.desktop')
        p.copy(source/'session/kwinrc','/usr/share/makos/session/kwinrc')
        return p
    def theme():
        p=package('makos-theme','Original MakOS Glass & Metal appearance', 'fonts-dejavu-core')
        shutil.copytree(source/'theme',p.path('/usr/share/makos/theme'),ignore=shutil.ignore_patterns('decoration'))
        shutil.copytree(source/'theme/decoration',p.path('/usr/share/kwin/decorations/org.makos.glass'))
        shutil.copytree(source/'wallpapers',p.path('/usr/share/makos/wallpapers'))
        shutil.copytree(source/'sounds',p.path('/usr/share/makos/sounds'))
        if (source/'icons/MakOS-Cursors').exists():
            shutil.copytree(source/'icons/MakOS-Cursors',p.path('/usr/share/icons/MakOS-Cursors'))
        return p
    def icons():
        p=package('makos-icons','Original MakOS icon theme')
        shutil.copytree(source/'icons',p.path('/usr/share/makos/icons'))
        shutil.copytree(source/'icons/MakOS',p.path('/usr/share/icons/MakOS'))
        return p
    def apps():
        # core-apps: runtime needs of Preview/Pictures (Pillow, poppler), Tunes/Movies (GStreamer + gtk4paintablesink),
        # Disk Utility (udisks2, lsblk), Software Center (pkexec + the helper below) and Activity (procps).
        p=package('makos-apps','Curated MakOS application entries with one app per role','makos-shell, python3-pil, poppler-utils, udisks2, util-linux, pkexec, gir1.2-gstreamer-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-gtk4, procps',arch='arm64')
        p.recommends='ptyxis, python3-mutagen, gstreamer1.0-libav, gstreamer1.0-pipewire, flatpak, smartmontools, amerika-venture, mak-office, amerika-studio, amerika-render, amerika-engine, amerika-sprite, amerika-box'
        shutil.copytree(source/'compat',p.path('/usr/share/makos/compat'),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for path in (source/'applications').glob('*.desktop'):
            p.copy(path,'/usr/share/applications/'+path.name)
        # Software Center: privileged half runs only through pkexec under this polkit action (fixed allowlist, see the helper).
        p.copy(source/'libexec/makos-software-helper','/usr/libexec/makos/makos-software-helper',0o755)
        p.copy(source/'polkit/org.makos.software.policy','/usr/share/polkit-1/actions/org.makos.software.policy')
        return p
    def meta():
        p=package('makos-desktop','MakOS desktop development preview for Ubuntu ARM64',', '.join(n+f' (= {VERSION})' for n in NAMES if n!='makos-desktop'),arch='arm64')
        p.copy(b.ROOT/'docs/makos/README.md','/usr/share/doc/makos-desktop/README.md')
        p.copy(b.ROOT/'docs/makos/INTEGRATION.md','/usr/share/doc/makos-desktop/INTEGRATION.md')
        return p
    return dict(zip(NAMES,(session,shell,theme,icons,apps,meta)))

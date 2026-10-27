"""Separate VigilOS packages (package names keep the makos- prefix so upgrades work). No dependencies added to Amerika's metapackage."""
import shutil
import os
import subprocess

VERSION='0.1.0~dev7'
NAMES=('makos-session','makos-shell','makos-theme','makos-icons','makos-apps','makos-desktop')


def register(b):
    source=b.SRC/'makos'
    def package(name,description,depends='',arch='all'):
        p=b.Pkg(name,VERSION,description,depends=depends,arch=arch)
        p.copyright('Copyright 2026 VigilTech.\nVigilOS code, icons, wallpapers and sounds: GPL-3.0-only.\nVigil Sans: SIL OFL 1.1 (brand/vigiltech/fonts/OFL.txt).\nUpstream components under compat/ keep their own licences (see compat/notices).\nFallback font DejaVu Sans is provided by Ubuntu fonts-dejavu-core under its upstream licence.\n')
        p.copy(b.ROOT/'docs/makos/ASSETS.md',f'/usr/share/doc/{name}/ASSETS.md')
        return p
    def shell():
        p=package('makos-shell','VigilOS desktop shell and native utilities',
                  'python3, libpython3.14, python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-4.0 (>= 4.10), gir1.2-gtk4layershell-1.0, libgtk4-layer-shell0, makos-theme, makos-icons, network-manager, wireplumber, upower, fonts-dejavu-core',arch='arm64')
        shutil.copytree(source/'makos',p.path('/usr/lib/python3/dist-packages/makos'),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(source/'bridge',p.path('/usr/share/makos/bridge'))
        shutil.copytree(source/'venture',p.path('/usr/share/makos/venture'))
        for name in ('makos-shell','makos-app','makos-studio-app','makos-venture'):
            p.copy(source/'bin'/name,'/usr/bin/'+name,0o755)
        output=p.path('/usr/libexec/makos/makos-shell-host')
        output.parent.mkdir(parents=True,exist_ok=True)
        flags=subprocess.check_output(['python3-config','--embed','--ldflags'],text=True).split()
        b.sh('cc','-O2','-Wl,-z,relro,-z,now',source/'shell-host.c','-o',output,*flags)
        p.file('/usr/share/applications/org.makos.Shell.desktop','[Desktop Entry]\nType=Application\nName=VigilOS Shell\nExec=/usr/libexec/makos/makos-shell-host\nNoDisplay=true\nX-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n')
        p.copy(source/'helpers/makos-settings-helper','/usr/libexec/makos/makos-settings-helper',0o755)
        p.copy(source/'helpers/org.makos.settings.policy','/usr/share/polkit-1/actions/org.makos.settings.policy')
        return p
    def session():
        p=package('makos-session','VigilOS independent KWin Wayland login session',
                  'kwin-wayland (>= 4:6.7), kwin-style-aurorae (>= 6.7), xwayland, dbus-user-session, makos-shell, polkit-kde-agent-1',arch='arm64')
        p.copy(source/'session/makos-session','/usr/bin/makos-session',0o755)
        for name in ('session-start','makos-xkb-override'):
            p.copy(source/'session'/name,'/usr/libexec/makos/'+name,0o755)
        p.copy(source/'session/makos.desktop','/usr/share/wayland-sessions/makos.desktop')
        p.copy(source/'session/kwinrc','/usr/share/makos/session/kwinrc')
        return p
    def theme():
        p=package('makos-theme','VigilOS appearance: VigilTech theme, wallpapers, sounds and Vigil Sans', 'fonts-dejavu-core')
        shutil.copytree(source/'theme',p.path('/usr/share/makos/theme'),ignore=shutil.ignore_patterns('decoration'))
        shutil.copytree(source/'theme/lockscreen',p.path('/usr/share/plasma/shells/org.makk.desktop'))
        shutil.copytree(source/'theme/sddm',p.path('/usr/share/sddm/themes/makk'))
        shutil.copytree(source/'theme/plymouth',p.path('/usr/share/plymouth/themes/makk'))
        p.copy(source/'libexec/makk-branding','/usr/sbin/makk-branding',0o755)
        p.copy(source/'libexec/makk-boot-check','/usr/sbin/makk-boot-check',0o755)
        p.copy(source/'libexec/makk-boot-check-hook','/usr/share/initramfs-tools/hooks/makk-boot-check',0o755)
        shutil.copytree(source/'theme/decoration',p.path('/usr/share/kwin/decorations/org.makos.glass'))
        shutil.copytree(source/'wallpapers',p.path('/usr/share/makos/wallpapers'))
        shutil.copytree(source/'sounds',p.path('/usr/share/makos/sounds'))
        for font in sorted((b.ROOT/'brand/vigiltech/fonts').glob('VigilSans-*.ttf')):
            p.copy(font,'/usr/share/fonts/truetype/vigil-sans/'+font.name)
        p.copy(b.ROOT/'brand/vigiltech/fonts/OFL.txt','/usr/share/doc/makos-theme/OFL-VigilSans.txt')
        if (source/'icons/MakkOS-Cursors').exists():
            shutil.copytree(source/'icons/MakkOS-Cursors',p.path('/usr/share/icons/MakkOS-Cursors'))
            shutil.copytree(p.path('/usr/share/icons/MakkOS-Cursors'), p.path('/usr/share/icons/MakOS-Cursors'), copy_function=os.link)
        return p
    def icons():
        p=package('makos-icons','Original VigilOS icon theme')
        shutil.copytree(source/'icons/MakkOS',p.path('/usr/share/makos/icons/MakkOS'))
        # Keep existing running apps and saved theme selections working.
        shutil.copytree(p.path('/usr/share/makos/icons/MakkOS'), p.path('/usr/share/makos/icons/MakOS'), copy_function=os.link)
        shutil.copytree(source/'icons/MakkOS',p.path('/usr/share/icons/MakkOS'))
        shutil.copytree(p.path('/usr/share/icons/MakkOS'), p.path('/usr/share/icons/MakOS'), copy_function=os.link)
        return p
    def apps():
        # core-apps: runtime needs of Preview/Pictures (Pillow, poppler), Tunes/Movies (GStreamer + gtk4paintablesink),
        # Disk Utility (udisks2, lsblk), Software Center (pkexec + the helper below) and Activity (procps).
        p=package('makos-apps','Curated VigilOS application entries with one app per role','makos-shell, python3-pil, poppler-utils, udisks2, util-linux, pkexec, gir1.2-gstreamer-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-gtk4, procps',arch='arm64')
        p.recommends='ptyxis, python3-mutagen, gstreamer1.0-libav, gstreamer1.0-pipewire, flatpak, smartmontools, amerika-venture, mak-office, amerika-studio, amerika-render, amerika-engine, amerika-sprite, amerika-box'
        p.copy(source/'branding/vigilos.svg','/usr/share/makos/branding/vigilos.svg')
        shutil.copytree(source/'compat',p.path('/usr/share/makos/compat'),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for path in (source/'applications').glob('*.desktop'):
            p.copy(path,'/usr/share/applications/'+path.name)
        # Software Center: privileged half runs only through pkexec under this polkit action (fixed allowlist, see the helper).
        p.copy(source/'libexec/makos-software-helper','/usr/libexec/makos/makos-software-helper',0o755)
        p.copy(source/'polkit/org.makos.software.policy','/usr/share/polkit-1/actions/org.makos.software.policy')
        return p
    def meta():
        p=package('makos-desktop','VigilOS desktop development preview for Ubuntu ARM64',', '.join(n+f' (= {VERSION})' for n in NAMES if n!='makos-desktop'),arch='arm64')
        p.copy(b.ROOT/'docs/makos/README.md','/usr/share/doc/makos-desktop/README.md')
        p.copy(b.ROOT/'docs/makos/INTEGRATION.md','/usr/share/doc/makos-desktop/INTEGRATION.md')
        return p
    return dict(zip(NAMES,(session,shell,theme,icons,apps,meta)))

# MakOS development preview

MakOS is an original Glass & Metal desktop for Ubuntu ARM64 on KWin Wayland.
**This is an early installable development preview, not a completed desktop.**
Do not remove fallback desktops or everyday file tools on the strength of this preview.
The owner has not confirmed a real MakOS login or app compatibility.

## Implemented and scoped

* Independent login entry, shell, config, theme, icon theme and six Debian packages.
* Original silver GTK window chrome, left glass buttons, gel controls, source list,
  a new KWin QML decoration, own generated wallpaper and nine AI app icons.
* Top menu bar, asynchronous Wi-Fi/Bluetooth/battery readouts, volume control, calendar.
  Saved Wi-Fi activation delegates to the existing backend; MakOS never captures passwords.
* DBusMenu registrar and KWin Wayland menu endpoints, with Window fallback.
* Gaussian icon magnification, launcher pins/removal, right-click menus, position/size preferences.
* Window/desk selection overlays and compositor shortcuts for close, minimize, zoom,
  snapping and showing the desktop. Spread currently shows window cards, not thumbnails.
* Files browser: icon, list and two-column views, tabs, Places, mounted volumes,
  parent/path navigation, spacebar image/text/audio/video preview, default-app opening.
* Seek: curated apps, local filename fallback, safe calculator, common length/mass conversion.
* Settings pane grid; appearance/launcher controls; read-only hardware status for some panes.
* Small Text Editor, Notes, Calculator, Calendar, Activity, System Information and read-only Disks.
* Original catalog: Venture, Paper, Digits, Slides, MakBox, Studio, Render, Engine, Sprite;
  ChatGPT and Claude remain available. Terminal has one visible entry and a preferred backend.
* Studio cosmetic copies do not replace upstream engines or edit user projects/configuration.

## Release gates — not implemented or not yet proven

Universal GTK/Qt/Electron menus; DBusMenu root live-update race coverage; complete Qt and
browser skins; all requested settings mutations; file operations/trash/tags/network search,
full column stack and cover previews; PDF/Office embedded previews; an indexer;
contacts/dictionary providers; launcher drag reorder, stacks, badges, bounce/reflections,
all autohide cases, minimization destinations; app-group switcher semantics; live window
thumbnails, drag between desks, hot corners and gestures; complete touchscreen/pen testing;
SDDM/Plymouth enable/revert themes; full notifications and sound set; cursor theme;
software front-end; Photos/Music/Video apps; printer/account/security controls;
accessibility audits, fractional/multi-monitor hardware tests, battery and physical 60 fps tests.
Some Settings panes explicitly identify their unimplemented status. They do not pretend to
apply changes. Graphite is not exposed because its full appearance is unfinished.

## Build and test

Run from this repository:

```sh
python3 tools/make_makos_vectors.py
python3 tools/ingest_makos_assets.py --normalize
python3 -m unittest discover -s tests -q
sh tests/rig/makos_rig.sh
python3 tools/build_makos.py --no-repo
```

The output of the private rig is evidence for that rig only. It does not establish
that the owner's normal session, all real apps, physical touch/pen or login/boot works.

## Try and return

After inspecting the verification report, install only the local MakOS packages with
the provided installer. It does not remove apps, stop the current desktop, select a
default session, modify PAM or enable any login/boot theme. Finish current work,
log out normally, choose **MakOS** in the login screen's session selector and log in.

To return: log out, choose **Plasma (Wayland)** or **Amerika OS**, and log in.
If MakOS is blank, press Ctrl+Alt+F3, log in yourself and inspect:

```sh
tail -100 ~/.local/state/makos/shell.log
```

To uninstall (keep configuration for recovery):

```sh
sudo apt remove makos-desktop makos-apps makos-shell makos-session makos-theme makos-icons
```

Do not run `apt autoremove` as part of this cleanup: the previous desktop metapackage
was removed together with the explicitly unwanted Agent; retained packages are marked
manual to protect the fallback. No real `.claude`, `.codex` or `.openclaw` config is modified.

## Cleanup decision

The user explicitly requested removal of Amerika Agent/OpenClaw. Its user services
were stopped/disabled and its package removed, along with the dependent metapackage.
About 359 MB of installed files were removed. Existing user data was left untouched;
no secret store or `.openclaw` directory was inspected. ChatGPT, Claude, Studio suite,
KWin, Plasma and Amerika session packages are preserved. Broad package cleanup is
pending MakOS completion and verification. Curated MakOS launcher presentation is
separate from claiming that all other packages have been uninstalled.

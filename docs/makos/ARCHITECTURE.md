# MakkOS architecture

MakkOS is an independent, opt-in ARM64 Wayland session on Ubuntu. It reuses the
working compositor/session patterns from Amerika OS without running either
Plasma shell or GNOME Shell. Internal inspiration: classic 2009-era Mac desktop conventions.
All product-facing names and shipped graphics are original.

## Measurements and choice

Measured on the execution host on 2026-10-22: aarch64; KWin 6.7.5;
GTK 4.24.1; gtk4-layer-shell 1.3.0; Mesa Vulkan drivers 26.2.4;
DejaVu Sans 2.37. This proves the available environment, not an owner's acceptance test.
The existing 408-test suite passed (one skip); the existing private KWin tray rig passed.
Early MakkOS smoke starts reached mapped-shell ready in 2.27–2.32 seconds,
including Python import and library startup. Screenshot and timing logs accompany builds.

Keep GTK4/layer-shell: it is already installed and proven with KWin on this machine;
there is no measured justification to replace the toolkit. No comparative Qt benchmark
was performed. Startup is measured; a physical-display 60 fps claim is not justified.
DejaVu Sans is selected for its clear humanist forms, broad language coverage and
redistribution licence already shipped with Ubuntu; no font is copied from a proprietary OS.

## Boundaries

* `src/makos/makos`: own Python namespace, settings, shell, Files and utilities.
* `src/makos/session`: separate `makos.desktop`, KWin entry point, crash supervision,
  per-session XKB include and diagnostic log in `~/.local/state/makos/shell.log`.
* KWin alone reads `~/.config/makos/compositor/kwinrc`. `session-start` restores the
  original XDG config home before spawning the shell or any application. Existing
  compositor defaults are not changed by installation. Explicit Settings actions can
  write the relevant user/system setting through their backend; these are distinct
  from package installation and require hardware verification.
* gtk4-layer-shell preload is applied to the shell executable only and removed
  immediately from Python's launch environment. No application inherits it.
* `org.makos.Shell` owns `/Control` and `/Windows`. Window commands reuse the
  proven validated one-shot KWin-script pattern. It does not share Amerika bus names.
  Files and Settings launch in separate processes; private widget rigs can embed them.
* DBusMenu registrar implements `com.canonical.AppMenu.Registrar`; Wayland menu
  service/path comes from KWin surface properties. Only genuinely exported menus
  appear. GTK4's GMenu export is a different protocol, not magically DBusMenu.
  Apps with no compatible export keep their in-window menus and receive Window actions.
* Backend modules are GPL copies of the existing system/audio/network/storage helpers,
  isolated under `makos.backends`. They are not all exposed as writable settings yet.
* All slow status and document search work runs off GTK's main thread. Calculator
  parses a bounded AST and implements a fixed operator allowlist (never eval).
* Seek has a separate low-priority SQLite FTS index over visible user folders,
  excludes secret/configuration locations and never follows symlinks. It can query
  localsearch when reachable. Hardware-scale indexing is still an acceptance gate.
* MakkOS's curated app catalog offers one visible entry per task. It does not enumerate
  every installed launcher. This is presentation cleanup, not package removal.
* Studio cosmetics are generated copies under `compat/`; serialized project formats,
  backend IDs, licences and configuration remain compatible. No credential files are read
  or modified during source preparation. The unmodified engines remain dependencies.

## Files implementation choice

The installed file managers provide much broader filesystem operations but lack the
required original column layout. The first Files implementation uses GTK4 + GIO for
volume enumeration/default handlers, with original icon/list/two-column navigation.
No external codebase was fetched or relicensed. It is currently a browser, not a
replacement for mature file managers' full safe editing/trash/network functionality.

## Packaging

`tools/builders/makos.py` registers six separate packages with an independent
`0.1.0~dev1` version. It adds no MakkOS dependency to Amerika OS. Only the new
packages are built; existing large packages are never regenerated. `makos-apps`
recommends the real terminal/browser/office engines, it does not misrepresent wrappers
as new rendering engines. Local signed staging is isolated under `dist/makos`.
Install does not change the login manager, default session, boot theme or PAM.

See README.md for the explicit unfinished-feature matrix and recovery path.

## Verified integration details

KWin 6.7's Aurorae theme identifier is `org.makos.glass`, without the historical
`__qml__` prefix. The rig launches a real Qt terminal window to exercise the native
decoration; the theme loaded and its screenshot was inspected. Shell-owned capture
sets `hide-caller-windows=false` for ScreenShot2 v5. No software-rendering workaround
is used in the final rig. Native utilities normally run in their own processes; the
UI introspection rig embeds them explicitly and also tests the separate entry point.
MakkOS-owned widget CSS has priority above existing per-user CSS so an older desktop's
custom styling cannot override the shell; those configuration files are never edited.

The session supervisor also guards the ready marker: a process that stays alive but
never maps its shell is terminated and restarted, with at most five attempts before
returning to the login manager. Fixtures verify both a never-ready process and a
ready process that exits normally. The normal timeout is 30 seconds.

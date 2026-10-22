#!/bin/sh
# Files-only rig: private D-Bus + KWin (own Wayland socket, so it can run beside makos_rig.sh) + private HOME.
# Screenshots are rendered from the GTK widgets themselves into dist/makos/files-rig/.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
OUT="$ROOT/dist/makos/files-rig"
mkdir -p "$OUT"
rm -f "$OUT"/*.png "$OUT"/report.txt
export ROOT T OUT
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME" "$HOME"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
export SOCK="makos-files-$$"
dbus-run-session -- sh -c '
  kwin_wayland --virtual --socket "$SOCK" --width 1600 --height 1000 --no-lockscreen >"$T/kwin.log" 2>&1 &
  kw=$!
  trap "kill $kw 2>/dev/null || true" EXIT
  n=0
  until [ -S "$XDG_RUNTIME_DIR/$SOCK" ] || [ $n -ge 40 ]; do n=$((n+1)); sleep .25; done
  export WAYLAND_DISPLAY="$SOCK" GDK_BACKEND=wayland GTK_A11Y=none
  dbus-update-activation-environment WAYLAND_DISPLAY GDK_BACKEND QT_QPA_PLATFORM
  export PYTHONPATH="$ROOT/src/makos" MAKOS_SHARE="$ROOT/src/makos" MAKOS_RIG_SHOTS="$OUT"
  python3 -X faulthandler "$ROOT/tests/rig/makos_files_ui.py" >"$T/files-ui.log" 2>&1
  echo $? >"$T/files-ui.status"
' >"$T/dbus.out" 2>&1
cat "$T/files-ui.log" | grep -v "dconf\|portal\|Gdk-WARNING\|goa" | tail -60
if [ "$(cat "$T/files-ui.status" 2>/dev/null)" != 0 ]; then echo "FILES RIG FAIL (see $T/files-ui.log)"; exit 1; fi
if grep -E 'Traceback|CRITICAL|Gtk-WARNING|GLib-GObject-WARNING|CSS parser' "$T/files-ui.log" "$T/kwin.log" >/dev/null 2>&1; then
  grep -E -B2 -A12 'Traceback|CRITICAL|Gtk-WARNING|GLib-GObject-WARNING|CSS parser' "$T/files-ui.log" | head -60
  echo "FILES RIG FAIL (warnings)"; exit 1
fi
cp "$T/files-ui.log" "$OUT/report.txt"
rm -rf "$T"
echo "FILES RIG PASS"

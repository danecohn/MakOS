#!/bin/sh
# Private KWin + D-Bus rig for the Settings panes and Seek. Separate temp dir and screenshot directory from makos_rig.sh, so it
# can run next to it. Screenshots: dist/makos/rig-settings/. Exits non-zero on any Traceback or failed assertion.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
OUT="$ROOT/dist/makos/rig-settings"
mkdir -p "$OUT"
rm -f "$OUT"/*.png "$OUT"/*.log "$OUT"/*.txt 2>/dev/null || true
export ROOT T OUT
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$HOME/Documents" "$HOME/Desktop" "$HOME/Pictures/Wallpapers" "$HOME/.local/share/contacts"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
export MAKOS_SHARE="$ROOT/src/makos" PYTHONPATH="$ROOT/src/makos:$ROOT/tests" GTK_A11Y=none MAKOS_LAYERSHELL_LIB="${AMERIKA_LAYERSHELL_LIB:-/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0}"
exec dbus-run-session -- sh -c '
  kwin_wayland --virtual --socket makos-settings-rig --width 1920 --height 1080 --no-lockscreen >"$OUT/kwin.log" 2>&1 &
  kw=$!
  trap "kill $kw 2>/dev/null || true" EXIT
  sleep 4
  export WAYLAND_DISPLAY=makos-settings-rig GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
  python3 "$ROOT/tests/rig/makos_settings_rig.py" 2>&1 | tee "$OUT/settings.log"
  rc=$?
  LD_PRELOAD="$MAKOS_LAYERSHELL_LIB" python3 "$ROOT/tests/rig/makos_seek_rig.py" 2>&1 | tee "$OUT/seek.log"
  if grep -E "Traceback|CRITICAL|CSS parser error" "$OUT/settings.log" "$OUT/seek.log" ; then exit 1; fi
  grep -q "SETTINGS RIG PASS" "$OUT/settings.log" && grep -q "SEEK RIG PASS" "$OUT/seek.log"
'

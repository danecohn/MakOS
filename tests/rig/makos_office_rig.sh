#!/bin/sh
# Installed Mak Office, isolated HOME/config/bus and compositor; no owner document is opened.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
OUT="$ROOT/dist/makos/office-rig"
mkdir -p "$OUT"
export ROOT T OUT
export HOME="$T/home" XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_DATA_HOME/applications"
chmod 700 "$XDG_RUNTIME_DIR"
export XDG_CURRENT_DESKTOP=MakkOS XDG_SESSION_TYPE=wayland
export PYTHONPATH="$ROOT/src/makos" MAKOS_SHARE="$ROOT/src/makos" GTK_A11Y=none
export MAKOS_SHELL_HOST="$ROOT/dist/makos/makos-shell-host"
cat > "$XDG_DATA_HOME/applications/org.makos.Shell.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MakkOS Shell
Exec=$MAKOS_SHELL_HOST
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOF
export MAKOS_OFFICE_CHILD=1
# KWin passes its own DISPLAY and WAYLAND_DISPLAY to the session child (XWayland is lazy-started).
dbus-run-session -- kwin_wayland --virtual --xwayland --width 1920 --height 1080 --no-lockscreen --exit-with-session="$ROOT/tests/rig/makos_office_checks.sh" >"$OUT/compositor.log" 2>&1
cat "$OUT/report.log"
rg -q 'MAK OFFICE RIG PASS' "$OUT/report.log"

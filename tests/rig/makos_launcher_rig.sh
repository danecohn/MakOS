#!/bin/sh
# Private session for the launcher-and-windows checks: its own D-Bus, KWin (laid out like the real session: KWin reads
# <config>/makos/compositor/kwinrc, the shell and apps keep <config>), runtime/state/home and screenshot authorisation.
# Usage: sh tests/rig/makos_launcher_rig.sh [script.sh|script.py]   (default: tests/rig/makos_launcher_checks.sh)
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT=${1:-$ROOT/tests/rig/makos_launcher_checks.sh}
T=$(mktemp -d)
mkdir -p "$ROOT/dist/makos" "$ROOT/dist/makos/rig-launcher"
printf '%s\n' "$T" > "$ROOT/dist/makos/rig-launcher-dir"
export ROOT T SCRIPT
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
export MAKOS_USER_CONFIG_HOME="$T/config" KWIN_CONFIG_HOME="$T/config/makos/compositor"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$KWIN_CONFIG_HOME" "$XDG_DATA_HOME/applications" "$XDG_DATA_HOME/kwin/decorations" "$XDG_DATA_HOME/kwin/effects" "$HOME"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$KWIN_CONFIG_HOME/kwinrc"
cp -R "$ROOT/src/makos/theme/decoration" "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
# KWin effects shipped by MakOS (the package installs them to /usr/share/kwin/effects)
if [ -d "$ROOT/src/makos/bridge/effects" ]; then cp -R "$ROOT/src/makos/bridge/effects/." "$XDG_DATA_HOME/kwin/effects/"; fi
export MAKOS_SHELL_HOST="$ROOT/dist/makos/makos-shell-host"
if [ ! -x "$MAKOS_SHELL_HOST" ]; then cc -O2 "$ROOT/src/makos/shell-host.c" -o "$MAKOS_SHELL_HOST" $(python3-config --embed --ldflags); fi
cat > "$XDG_DATA_HOME/applications/org.makos.Shell.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MakOS Shell
Exec=$MAKOS_SHELL_HOST
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOF
exec dbus-run-session -- sh -c '
  XDG_CONFIG_HOME="$KWIN_CONFIG_HOME" kwin_wayland --virtual --socket makos-rig --width 1920 --height 1080 --no-lockscreen >"$T/kwin.log" 2>&1 &
  kw=$!
  trap "kill $kw 2>/dev/null || true" EXIT
  sleep 4
  export WAYLAND_DISPLAY=makos-rig GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
  dbus-update-activation-environment WAYLAND_DISPLAY GDK_BACKEND QT_QPA_PLATFORM
  case "$SCRIPT" in
    *.py) python3 "$SCRIPT" ;;
    *) sh "$SCRIPT" ;;
  esac
' 

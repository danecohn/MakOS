#!/bin/sh
# Core-app rig: private D-Bus + KWin + seeded HOME. Screenshots land in dist/makos/rig-apps/ (inspect them).
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
mkdir -p "$ROOT/dist/makos/rig-apps"
printf '%s\n' "$T" > "$ROOT/dist/makos/rig-apps/rig-dir"
export ROOT T
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME/applications" "$XDG_DATA_HOME/kwin/decorations" "$HOME"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
cp -R "$ROOT/src/makos/theme/decoration" "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
export MAKOS_SHELL_HOST="$ROOT/dist/makos/rig-apps/makos-shell-host"
cc -O2 "$ROOT/src/makos/shell-host.c" -o "$MAKOS_SHELL_HOST" $(python3-config --embed --ldflags)
cat > "$XDG_DATA_HOME/applications/org.makos.Shell.desktop" <<EOT
[Desktop Entry]
Type=Application
Name=MakOS Shell
Exec=$MAKOS_SHELL_HOST
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOT
exec dbus-run-session -- sh -c '
  kwin_wayland --virtual --socket makos-apps-rig --width 1920 --height 1080 --no-lockscreen >"$T/kwin.log" 2>&1 &
  kw=$!
  trap "kill $kw 2>/dev/null || true" EXIT
  sleep 4
  export WAYLAND_DISPLAY=makos-apps-rig GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
  python3 "$ROOT/tests/rig/makos_apps_rig.py" >"$T/apps-rig.log" 2>&1
  rc=$?
  cat "$T/apps-rig.log"
  exit $rc
'

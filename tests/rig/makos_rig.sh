#!/bin/sh
# Independent compositor, D-Bus, user folders, metadata and KWin configuration.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
mkdir -p "$ROOT/dist/makos"
printf '%s\n' "$T" > "$ROOT/dist/makos/rig-dir"
export ROOT T
export XDG_CURRENT_DESKTOP=MakkOS XDG_SESSION_DESKTOP=MakkOS XDG_SESSION_TYPE=wayland
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME/applications" "$XDG_DATA_HOME/kwin/decorations" "$HOME"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
cp -R "$ROOT/src/makos/theme/decoration" "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
export MAKOS_SHELL_HOST="$ROOT/dist/makos/makos-shell-host"
if [ "${MAKOS_PACKAGE_RIG:-0}" = 1 ]; then
  mkdir -p "$T/payload"
  for deb in "$ROOT"/dist/makos/packages/*.deb; do dpkg-deb -x "$deb" "$T/payload"; done
  export MAKOS_SHELL_HOST="$T/payload/usr/libexec/makos/makos-shell-host"
  cp "$T/payload/usr/share/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
  rm -rf "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
  cp -R "$T/payload/usr/share/kwin/decorations/org.makos.glass" "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
else
  cc -O2 "$ROOT/src/makos/shell-host.c" -o "$MAKOS_SHELL_HOST" $(python3-config --embed --ldflags)
fi
cat > "$XDG_DATA_HOME/applications/org.makos.Shell.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MakkOS Shell
Exec=$MAKOS_SHELL_HOST
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOF
exec dbus-run-session -- sh -eu -c '
  kwin_wayland --virtual --socket makos-rig --width 1920 --height 1080 --no-lockscreen >"$T/kwin.log" 2>&1 &
  kw=$!
  trap "kill $kw 2>/dev/null || true" EXIT
  sleep 4
  export WAYLAND_DISPLAY=makos-rig GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
  dbus-update-activation-environment WAYLAND_DISPLAY GDK_BACKEND QT_QPA_PLATFORM XDG_CURRENT_DESKTOP
  if [ "${MAKOS_PACKAGE_RIG:-0}" = 1 ]; then
    python3 "$ROOT/tests/rig/makos_packages_smoke.py" >"$T/script.log" 2>&1
  else
    sh "$ROOT/tests/rig/makos_smoke.sh" >"$T/script.log" 2>&1
    sh "$ROOT/tests/rig/makos_ui_checks.sh" >"$T/ui-checks.log" 2>&1
    cp "$T/ui-checks.log" "$ROOT/dist/makos/rig/ui-checks.log"
  fi
  if rg "Couldn.t find QML|ReferenceError|TypeError|Error loading QML" "$T/kwin.log"; then exit 1; fi
'

#!/bin/sh
# Theme/system-skin rig: private D-Bus + KWin + the MakkOS shell, then real third-party style windows
# (GTK 4/3 widget gallery in every variant, Qt widgets, KWin decorations, notification banners,
# global-menu coverage) photographed through KWin. Evidence for this rig only.
#   STAGES="gtk qt deco notify menu hidpi"  sh tests/rig/makos_theme_rig.sh      (default: all)
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
OUT="$ROOT/dist/makos/rig/theme"
mkdir -p "$ROOT/dist/makos" "$OUT"
rm -f "$OUT/summary.txt"
export ROOT T OUT STAGES="${STAGES:-gtk qt deco notify menu xmenu hidpi}"
export XDG_RUNTIME_DIR="$T/runtime" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" XDG_STATE_HOME="$T/state" HOME="$T/home"
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME/applications" "$XDG_DATA_HOME/kwin/decorations" "$XDG_DATA_HOME/themes" "$HOME"
chmod 700 "$XDG_RUNTIME_DIR"
cp "$ROOT/src/makos/session/kwinrc" "$XDG_CONFIG_HOME/kwinrc"
cp -R "$ROOT/src/makos/theme/decoration" "$XDG_DATA_HOME/kwin/decorations/org.makos.glass"
# Installed-style themes for third-party apps (GTK_THEME=MakkOS ...), generated exactly like the package does.
PYTHONPATH="$ROOT/src/makos" python3 -m makos.appearance install-themes "$XDG_DATA_HOME/themes" >/dev/null
export MAKOS_SHELL_HOST="$ROOT/dist/makos/makos-shell-host"
[ -x "$MAKOS_SHELL_HOST" ] || cc -O2 "$ROOT/src/makos/shell-host.c" -o "$MAKOS_SHELL_HOST" $(python3-config --embed --ldflags)
cat > "$XDG_DATA_HOME/applications/org.makos.Shell.desktop" <<EOD
[Desktop Entry]
Type=Application
Name=MakkOS Shell
Exec=$MAKOS_SHELL_HOST
NoDisplay=true
X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2
EOD
run() {  # run SCALE STAGES: KWin runs the stage script as its session command, so DISPLAY is the rig's own Xwayland
  # Never inherit the developer's real DISPLAY/WAYLAND_DISPLAY: an X11 fallback would open windows on the real desktop.
  SCALE=$1 STG="$2" dbus-run-session -- sh -c '
    unset DISPLAY WAYLAND_DISPLAY
    dbus-update-activation-environment WAYLAND_DISPLAY=makos-theme 2>/dev/null || true
    STAGES="$STG" kwin_wayland --virtual --socket makos-theme --xwayland --width 1920 --height 1080 --scale "$SCALE" --no-lockscreen \
      --exit-with-session="sh $ROOT/tests/rig/makos_theme_run.sh" >"$T/kwin-$SCALE.log" 2>&1
  '
}
FILTER='dbus-daemon|portal|goa-|gvfs|fuse|dconf'
run 1 "$(echo $STAGES | sed "s/xmenu//")" 2>&1 | grep -a -v -E "$FILTER" || true
case " $STAGES " in *" xmenu "*) MAKOS_APPMENU_REGISTRAR=canonical run 1 "xmenu" 2>&1 | grep -a -v -E "$FILTER" || true;; esac
case " $STAGES " in *" hidpi "*) run 2 "deco" 2>&1 | grep -a -v -E "$FILTER" || true;; esac
cat "$OUT/summary.txt" 2>/dev/null
echo "theme rig output: $OUT (work dir $T)"

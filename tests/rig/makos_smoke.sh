#!/bin/sh
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
export PYTHONPATH="$ROOT/src/makos:$ROOT/src/os"
export MAKOS_SHARE="$ROOT/src/makos"
export MAKOS_LAYERSHELL_LIB="${AMERIKA_LAYERSHELL_LIB:-/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0}"
export MAKOS_RIG_SHOTS="$ROOT/dist/makos/rig"
export GTK_A11Y=none
mkdir -p "$MAKOS_RIG_SHOTS" "$HOME/Documents" "$MAKOS_SHARE/wallpapers"
printf 'A private rig document.\n' > "$HOME/Documents/Welcome.txt"
"$ROOT/src/makos/bin/makos-shell" > "$T/makos-shell.log" 2>&1 &
SHELL_PID=$!
QT_PID=""
trap 'kill "$SHELL_PID" 2>/dev/null || true; [ -z "$QT_PID" ] || kill "$QT_PID" 2>/dev/null || true' EXIT
n=0
until [ -f "$XDG_RUNTIME_DIR/makos/shell-ready" ]; do
  kill -0 "$SHELL_PID" 2>/dev/null || { cat "$T/makos-shell.log"; exit 1; }
  n=$((n+1)); [ "$n" -lt 80 ] || { cat "$T/makos-shell.log"; exit 1; }
  sleep .25
done
call() { gdbus call --session --dest org.makos.Shell --object-path /Control --method org.makos.Control.Action "$1"; }
call files
sleep 1
call shot:files
call settings
sleep 1
call shot:settings
gdbus call --session --dest org.kde.KWin --object-path /KWin --method org.kde.KWin.supportInformation > "$MAKOS_RIG_SHOTS/kwin-support.txt"
call shot:desktop
sleep 2
python3 - <<'PYTEST'
from PIL import Image
import os
im=Image.open(os.environ['MAKOS_RIG_SHOTS']+'/desktop.png')
assert im.getbbox() is not None,'Compositor capture is empty'
assert max(im.convert('RGB').getextrema()[0])>100,'Compositor capture is unexpectedly dark'
PYTEST
call seek
sleep 1
call shot:overlay
call close-overlay
call spread
sleep 1
call close-overlay
call shot:bar
call shot:launcher
sleep 1
gdbus call --session --dest org.makos.Shell --object-path /Control --method org.makos.Control.State
if command -v konsole >/dev/null; then
  konsole --separate --hide-menubar -e /bin/sleep 30 > "$T/qt-app.log" 2>&1 &
  QT_PID=$!
  sleep 2
  call shot:desktop
  sleep 2
  cp "$MAKOS_RIG_SHOTS/desktop.png" "$MAKOS_RIG_SHOTS/qt-decoration.png"
  kill "$QT_PID" 2>/dev/null || true
  QT_PID=""
  sleep .5
  call shot:desktop
  sleep 1
fi
call quit
wait "$SHELL_PID"
if rg 'Traceback|CRITICAL|CSS parser error' "$T/makos-shell.log"; then cat "$T/makos-shell.log"; exit 1; fi
cp "$T/makos-shell.log" "$MAKOS_RIG_SHOTS/shell.log"
printf 'MAKOS SMOKE PASS\n'

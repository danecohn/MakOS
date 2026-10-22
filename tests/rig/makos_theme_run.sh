#!/bin/sh
# Runs inside the private KWin/D-Bus of makos_theme_rig.sh.
set -u
export QT_QPA_PLATFORM=wayland GDK_BACKEND=wayland
export PYTHONPATH="$ROOT/src/makos:$ROOT/src/os"
export MAKOS_SHARE="$ROOT/src/makos" GTK_A11Y=none MAKOS_NO_SOUND=1
export MAKOS_RIG_SHOTS="$OUT"
export MAKOS_LAYERSHELL_LIB="${AMERIKA_LAYERSHELL_LIB:-/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0}"
mkdir -p "$HOME/Documents"
printf 'A private rig document.\n' > "$HOME/Documents/Welcome.txt"
"$ROOT/src/makos/bin/makos-shell" > "$T/makos-shell.log" 2>&1 &
SHELL_PID=$!
APP_PID=""
trap 'kill "$SHELL_PID" 2>/dev/null || true; [ -z "$APP_PID" ] || kill "$APP_PID" 2>/dev/null || true' EXIT
n=0
until [ -f "$XDG_RUNTIME_DIR/makos/shell-ready" ]; do
  kill -0 "$SHELL_PID" 2>/dev/null || { cat "$T/makos-shell.log"; exit 1; }
  n=$((n+1)); [ "$n" -lt 80 ] || { cat "$T/makos-shell.log"; exit 1; }
  sleep .25
done
say() { echo "$*"; echo "$*" >> "$OUT/summary.txt"; }
call() { gdbus call --session --dest org.makos.Shell --object-path /Control --method org.makos.Control.Action "$1" >/dev/null; }
shot() {  # shot NAME [settle]: compositor capture through the shell's rig-only action, then rename
  sleep "${2:-1.5}"
  rm -f "$OUT/desktop.png"
  call shot:desktop
  i=0
  until [ -s "$OUT/desktop.png" ] && tail -c 12 "$OUT/desktop.png" | grep -aq IEND; do i=$((i+1)); [ "$i" -lt 40 ] || { echo "no screenshot for $1"; return 1; }; sleep .25; done
  dest="$OUT/$1.png"; [ "$SCALE" = 1 ] || dest="$OUT/$1-x$SCALE.png"
  mv "$OUT/desktop.png" "$dest"
}
mkdir -p "$OUT" 2>/dev/null
stop() { [ -z "$APP_PID" ] || kill "$APP_PID" 2>/dev/null || true; wait "$APP_PID" 2>/dev/null || true; APP_PID=""; sleep .4; }
has() { case " $STAGES " in *" $1 "*) return 0;; esac; return 1; }
gallery() {  # gallery NAME GTKVER THEME [args]
  name=$1; ver=$2; theme=$3; shift 3
  GTK_THEME=$theme python3 "$ROOT/tests/rig/makos_gallery.py" --gtk "$ver" --hold 25 "$@" >"$T/gallery-$name.log" 2>&1 &
  APP_PID=$!
  shot "$name" 2.5
  stop
}
if has gtk; then
  gallery gallery-gtk4 4 MakOS
  gallery gallery-gtk3 3 MakOS
  gallery gallery-gtk4-graphite 4 MakOS-Graphite
  gallery gallery-gtk3-graphite 3 MakOS-Graphite
  gallery gallery-gtk4-green 4 MakOS-Green
  gallery gallery-gtk4-menu 4 MakOS --menu
  gallery gallery-gtk3-menu 3 MakOS --menu
  gallery gallery-gtk4-sheet 4 MakOS --sheet
  gallery gallery-gtk3-sheet 3 MakOS --sheet
fi
qtenv() { eval "$(python3 -m makos.qtskin env)"; python3 -m makos.qtskin setup >/dev/null; }
if has qt; then
  ( qtenv; python3 "$ROOT/tests/rig/makos_qt_window.py" --hold 25 >"$T/qt-main.log" 2>&1 ) &
  APP_PID=$!
  shot qt-skin 3
  stop
fi
if has deco; then
  ( qtenv; python3 "$ROOT/tests/rig/makos_qt_window.py" --hold 25 --title "Active window" >"$T/qt-deco1.log" 2>&1 ) & P1=$!
  sleep 2
  ( qtenv; python3 "$ROOT/tests/rig/makos_qt_window.py" --mode tool --hold 25 >"$T/qt-deco2.log" 2>&1 ) & P2=$!
  sleep 1.5
  ( qtenv; python3 "$ROOT/tests/rig/makos_qt_window.py" --mode dialog --hold 25 >"$T/qt-deco3.log" 2>&1 ) & P3=$!
  sleep 2
  shot decoration-states 1
  kill $P1 $P2 $P3 2>/dev/null; wait $P1 $P2 $P3 2>/dev/null
fi
if has notify; then
  python3 "$ROOT/tests/rig/makos_theme_notify.py" >"$T/notify.log" 2>&1 &
  APP_PID=$!
  sleep 5
  shot notifications 0.5
  wait "$APP_PID" 2>/dev/null; APP_PID=""
  cat "$T/notify.log"
fi
menu_case() {  # menu_case NAME COMMAND...: start an app, dump the registrar, photograph the bar
  name=$1; shift
  "$@" >"$T/menu-$name.log" 2>&1 &
  APP_PID=$!
  sleep 4
  say "MENU $name: $(python3 "$ROOT/tests/rig/makos_menu_probe.py")"
  shot "menu-$name" 1
  stop
}
if has menu; then   # default registrar (private name): Wayland-native clients must keep their in-window menus
  menu_case qt-wayland sh -c 'eval "$(python3 -m makos.qtskin env)"; exec python3 "$ROOT/tests/rig/makos_qt_window.py" --hold 30'
  menu_case gtk3-wayland sh -c 'GTK_THEME=MakOS exec python3 "$ROOT/tests/rig/makos_gtk3_menu_app.py" 30'
fi
if has xmenu; then  # canonical registrar name + XWayland clients (registered by X11 window id, matched by PID)
  say "DISPLAY for X11 clients: $DISPLAY"
  menu_case qt-xwayland sh -c 'eval "$(python3 -m makos.qtskin env)"; QT_QPA_PLATFORM=xcb exec python3 "$ROOT/tests/rig/makos_qt_window.py" --hold 30'
  menu_case gtk3-xwayland sh -c 'GDK_BACKEND=x11 GTK_MODULES=appmenu-gtk-module GTK_THEME=MakOS exec python3 "$ROOT/tests/rig/makos_gtk3_menu_app.py" 30'
  menu_case gtk3-wayland-hidden sh -c 'GTK_MODULES=appmenu-gtk-module GTK_THEME=MakOS exec python3 "$ROOT/tests/rig/makos_gtk3_menu_app.py" 30'
fi
call quit
wait "$SHELL_PID" 2>/dev/null
if grep -E 'Traceback|CRITICAL|CSS parser error' "$T/makos-shell.log"; then cat "$T/makos-shell.log"; exit 1; fi
for f in "$T"/gallery-*.log "$T"/qt-*.log; do [ -s "$f" ] && { echo "== $f"; grep -E "Traceback|Error|CRITICAL" "$f" | head -5; }; done
cp "$T/makos-shell.log" "$OUT/shell.log" 2>/dev/null
say "THEME RIG DONE scale=$SCALE"

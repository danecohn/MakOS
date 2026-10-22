#!/bin/sh
set -eu
export GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
dbus-update-activation-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP
exec python3 -u "$ROOT/tests/rig/makos_office_checks.py" >"$OUT/report.log" 2>&1

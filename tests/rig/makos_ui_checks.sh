#!/bin/sh
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
export PYTHONPATH="$ROOT/src/makos:$ROOT/src/os"
export MAKOS_SHARE="$ROOT/src/makos" GTK_A11Y=none
export MAKOS_RIG_SHOTS="$ROOT/dist/makos/rig"
export LD_PRELOAD=/usr/lib/aarch64-linux-gnu/libgtk4-layer-shell.so.0
mkdir -p "$MAKOS_RIG_SHOTS" "$HOME/Documents"
python3 "$ROOT/tests/rig/makos_ui_checks.py"

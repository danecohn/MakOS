#!/bin/sh
# Entry used by makos_launcher_rig.sh: runs the Python checks inside the private session.
exec python3 "$(dirname "$0")/makos_launcher_checks.py"

#!/usr/bin/env bash
# Double-click this file in Finder to start PCB Inspector on macOS.
# (First time: right-click > Open, to get past Gatekeeper.)
cd "$(dirname "$0")"
./run.sh "$@"
status=$?
if [ $status -ne 0 ]; then
    echo
    read -r -p "PCB Inspector exited with an error ($status). Press Enter to close..." _
fi
exit $status

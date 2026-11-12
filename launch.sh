#!/bin/bash
# NetForge desktop launcher — no terminal window
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
LOG="$DIR/launch_error.log"

if [ -x "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
elif [ -x "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

"$PYTHON" "$DIR/main.py" "$@" 2>"$LOG"
STATUS=$?

if [ $STATUS -ne 0 ]; then
    MSG="NetForge failed to start (exit $STATUS)

Python: $PYTHON
Log: $LOG

$(tail -n 25 "$LOG" 2>/dev/null)"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title="NetForge" --width=480 --text="$MSG" 2>/dev/null || true
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send -u critical "NetForge failed" "See $LOG"
    fi
fi
exit $STATUS

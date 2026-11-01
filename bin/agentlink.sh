#!/usr/bin/env sh
# Portable launcher: run agentlink from an install dir or a checkout, no pip install.
set -eu

# resolve symlinks first: ~/.local/bin/agentlink points at this file, and
# dirname "$0" alone would then look for src/ in ~/.local
SELF=$0
while [ -h "$SELF" ]; do
  TARGET=$(readlink "$SELF" 2>/dev/null || true)
  [ -n "$TARGET" ] || break
  case $TARGET in
    /*) SELF=$TARGET ;;
    *) SELF=$(dirname -- "$SELF")/$TARGET ;;
  esac
done
HERE=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd -P)

# the installer records the interpreter it actually used (py -3, python3, ...)
MARKER="$HERE/../.agentlink-python"
if [ -f "$MARKER" ]; then
  PY=$(cat "$MARKER")
elif [ -x "$HERE/../.venv/bin/python" ]; then
  PY="$HERE/../.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

PYTHONPATH="$HERE/../src${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m agentlink "$@"

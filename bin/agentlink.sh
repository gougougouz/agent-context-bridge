#!/usr/bin/env sh
# Portable launcher for agentlink: works from a checkout without pip install.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$HERE/../.venv/bin/python" ]; then
  PY="$HERE/../.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
PYTHONPATH="$HERE/../src${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m agentlink "$@"
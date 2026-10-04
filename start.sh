#!/usr/bin/env bash
# Launch RC AI Surveyor with the right interpreter and docker group.
#
# The system python3 is PEP 668-locked on Ubuntu 24.04 and cannot see
# google-genai, so live mode MUST run from .venv. This wrapper makes that
# impossible to get wrong.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "error: $PY missing. Create it with:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install google-genai" >&2
  exit 1
fi

cmd="exec $(printf '%q' "$PY") $(printf '%q' "$DIR/run.py")"
for arg in "$@"; do cmd="$cmd $(printf '%q' "$arg")"; done

# sg docker is only needed until the next WSL restart picks up the group.
if id -nG | tr ' ' '\n' | grep -qx docker; then
  eval "$cmd"
else
  exec sg docker -c "$cmd"
fi

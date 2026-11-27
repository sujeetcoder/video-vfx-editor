#!/usr/bin/env bash
# Thin wrapper — all logic lives in install/ensure.py and install/setup.py.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
py="${PYTHON:-}"
if [ -z "$py" ]; then
  if command -v python3 >/dev/null 2>&1; then py=python3; else py=python; fi
fi
"$py" "$here/ensure.py" "$@"
status=$?
"$py" "$here/doctor.py" || true
exit $status

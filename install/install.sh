#!/usr/bin/env bash
# Thin wrapper — all logic lives in install/ensure.py and install/setup.py.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="${PYTHON:-}"
if [ -z "$py" ]; then
  if command -v python3 >/dev/null 2>&1; then py=python3; else py=python; fi
fi
"$py" "$here/ensure.py" "$@"
status=$?
doctor_py="$HOME/.vfe/venv/bin/python"
[ -x "$doctor_py" ] || doctor_py="$py"
"$doctor_py" "$here/doctor.py" || true
exit $status

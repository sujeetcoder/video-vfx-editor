# Thin wrapper — all logic lives in install/ensure.py and install/setup.py.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $py "$here\ensure.py" @args
$status = $LASTEXITCODE
& $py "$here\doctor.py"
exit $status

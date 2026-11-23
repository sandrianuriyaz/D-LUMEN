$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$python = if ($env:DLUMEN_BOOTSTRAP_PYTHON) { $env:DLUMEN_BOOTSTRAP_PYTHON } else { "python" }
if (-not (Test-Path ".venv")) { & $python -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Host "SETUP OK: $env:COMPUTERNAME"

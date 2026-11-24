param([ValidateSet("master", "worker")][string]$Role = "worker")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv")) {
  if ($env:DLUMEN_BOOTSTRAP_PYTHON) {
    & $env:DLUMEN_BOOTSTRAP_PYTHON -m venv .venv
  } elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv .venv
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
  } else {
    throw "Python tidak ditemukan. Install Python 3.12+ lalu buka ulang PowerShell."
  }
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r "requirements-$Role.txt"
Write-Host "SETUP OK: $env:COMPUTERNAME role=$Role"

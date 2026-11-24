$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (Test-Path ".env") {
  Get-Content ".env" | Where-Object { $_ -match '^[^#][^=]*=' } | ForEach-Object {
    $pair = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
  }
}
$python = if ($env:DLUMEN_PYTHON) { $env:DLUMEN_PYTHON } elseif (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python -m worker.worker_node

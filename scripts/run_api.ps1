# Start SVRMON24 API (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "Missing .venv. Create it with: python -m venv .venv"
}

. .\.venv\Scripts\Activate.ps1
python -m app.main

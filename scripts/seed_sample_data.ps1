# Seed idempotent demo-* sample data for SVRMON24 (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Missing .venv. Create it with: python -m venv .venv && pip install -r requirements.txt"
}

$argsList = $args
& .\.venv\Scripts\python.exe scripts\seed_sample_data.py @argsList
exit $LASTEXITCODE

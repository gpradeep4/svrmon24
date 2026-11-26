# Start SVRMON24 API monolith (Windows PowerShell).
# Prefer: Copy-Item .env.example .env  →  edit secrets  →  .\scripts\run_api.ps1
# Health: http://127.0.0.1:8200/health
# Live masters stay fail-closed until env + Configuration → Live / Runtime.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "Missing .venv. Create it with: python -m venv .venv"
}

if (-not (Test-Path ".\.env")) {
    Write-Warning "No .env found. Copy .env.example to .env before production use."
}

. .\.venv\Scripts\Activate.ps1
python -m app.main

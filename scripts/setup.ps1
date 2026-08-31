<#
.SYNOPSIS
    Sets up and runs the Azure DevOps Agile Metrics Portal on Windows.

.DESCRIPTION
    Runs, in order: create venv, activate, install dependencies, ensure .env exists,
    optionally build a wheel/sdist, then start Streamlit.

.PARAMETER Build
    Also generate a wheel/sdist package with `python -m build` before running.

.PARAMETER SkipRun
    Set up the environment but do not start Streamlit.

.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -Build
    .\scripts\setup.ps1 -SkipRun
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Step($message) {
    Write-Host "`n==> $message" -ForegroundColor Cyan
}

Step "Checking Python installation"
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python launcher 'py' not found. Install Python 3.11+ from python.org and select 'Add Python to PATH'."
}

Step "Creating virtual environment (.venv)"
if (-not (Test-Path ".venv")) {
    py -m venv .venv
} else {
    Write-Host ".venv already exists, skipping creation."
}

Step "Activating virtual environment"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
. .\.venv\Scripts\Activate.ps1

Step "Installing dependencies"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Step "Ensuring .env exists"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Edit it with your Azure DevOps values before running." -ForegroundColor Yellow
} else {
    Write-Host ".env already exists, skipping."
}

if ($Build) {
    Step "Building wheel/sdist"
    python -m pip install --upgrade build
    Remove-Item -Recurse -Force build, dist, src\ado_agile_metrics.egg-info -ErrorAction SilentlyContinue
    python -m build
}

Step "Running tests"
$env:PYTHONPATH = "src"
python -m pytest -q

if (-not $SkipRun) {
    Step "Starting Streamlit portal"
    python -m streamlit run app.py
} else {
    Write-Host "`nSetup complete. Run 'python -m streamlit run app.py' to start the portal." -ForegroundColor Green
}

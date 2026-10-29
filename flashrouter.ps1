$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $Venv "bin/python"
}

if (-not (Test-Path $Python)) {
    Write-Host "[flashrouter] Creating virtual environment..."
    python -m venv $Venv
}

& $Python -c "import flashrouter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[flashrouter] Installing dependencies..."
    & $Python -m pip install --upgrade pip | Out-Null
    & $Python -m pip install -e $Root
}

& $Python -m flashrouter @args

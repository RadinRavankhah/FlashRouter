@echo off
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [flashrouter] Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 exit /b 1
)

"%PY%" -c "import flashrouter" >nul 2>&1
if errorlevel 1 (
    echo [flashrouter] Installing dependencies...
    "%PY%" -m pip install --upgrade pip >nul
    "%PY%" -m pip install -e "%ROOT%"
    if errorlevel 1 exit /b 1
)

"%PY%" -m flashrouter %*

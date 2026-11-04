@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Workbench] First run: preparing virtual environment...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH. Install Python 3.10+ first.
        pause
        exit /b 1
    )
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python 3.10 or newer is required.
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
    echo [Workbench] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check your network.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m app.main
if errorlevel 1 pause

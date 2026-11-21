@echo off
setlocal
cd /d "%~dp0"
title RecoverX - Quick Recovery
set "RECOVERX_HOME=%LOCALAPPDATA%\RecoverX"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 (
    echo RecoverX must be set up first.
    echo Double-click SETUP_WINDOWS.cmd, then try again.
    pause
    exit /b 1
)
if not exist "%~dp0tools\tsk\tsk_recover.exe" if not exist "%~dp0tools\tsk\bin\tsk_recover.exe" (
    echo Sleuth Kit binaries are not installed.
    echo Run SETUP_WINDOWS.cmd again.
    pause
    exit /b 1
)
"%PYTHON%" -m streamlit run "%~dp0app.py" --server.address=127.0.0.1 --server.port=8501 --server.headless=false --browser.gatherUsageStats=false
if errorlevel 1 (
    echo.
    echo RecoverX stopped with an error. Check the messages above.
    pause
)

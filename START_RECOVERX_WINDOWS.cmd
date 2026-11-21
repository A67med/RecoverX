@echo off
setlocal
cd /d "%~dp0"
title RecoverX - Quick Recovery
set "RECOVERX_SIMPLE_UI=1"
set "RECOVERX_HOME=%LOCALAPPDATA%\RecoverX"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
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
if not exist "%~dp0tools\photorec\photorec_win.exe" (
    echo PhotoRec binaries are not installed.
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

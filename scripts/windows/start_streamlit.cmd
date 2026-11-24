@echo off
setlocal
rem Launcher lives in scripts\windows; work from the repository root.
cd /d "%~dp0..\.."
title RecoverX - Quick Recovery (keep this window open)
set "RECOVERX_HOME=%LOCALAPPDATA%\RecoverX"
set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" goto needsetup
"%PYTHON%" -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 goto needsetup
"%PYTHON%" -c "import recoverx, streamlit" >nul 2>&1
if errorlevel 1 goto needsetup
if not exist "%CD%\tools\tsk\tsk_recover.exe" (
    echo The Sleuth Kit is not installed. Run scripts\windows\setup_streamlit.cmd first.
    pause
    exit /b 1
)
"%PYTHON%" "%CD%\scripts\windows_launcher.py" %*
if errorlevel 1 (
    echo.
    echo RecoverX stopped with an error. Read the messages above.
    pause
)
exit /b

:needsetup
echo RecoverX is not set up yet (or its Python environment is damaged).
echo Run scripts\windows\setup_streamlit.cmd, then start RecoverX again.
pause
exit /b 1

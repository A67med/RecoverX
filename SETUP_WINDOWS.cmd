@echo off
setlocal
cd /d "%~dp0"
title RecoverX for Windows - Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
if errorlevel 1 (
    echo.
    echo SETUP FAILED - read the message above. No disk has been formatted or modified.
    pause
    exit /b 1
)
echo.
echo Setup is complete. Double-click START_RECOVERX_WINDOWS.cmd or the RecoverX desktop shortcut.
pause

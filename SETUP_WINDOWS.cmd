@echo off
setlocal
cd /d "%~dp0"
title RecoverX v0.4 for Windows - Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo SETUP FAILED - read the message above. No disk has been formatted or modified.
    pause
    exit /b 1
)
echo.
echo Setup is complete. Double-click the RecoverX desktop icon or START_RECOVERX_WINDOWS.cmd.
pause

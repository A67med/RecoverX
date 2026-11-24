@echo off
setlocal
cd /d "%~dp0"
set "RXQA=%TEMP%\RecoverX-validation-%RANDOM%-%RANDOM%"
mkdir "%RXQA%" || exit /b 1
echo Running tests against synthetic disk images. Results folder:
echo %RXQA%
"runtime\python.exe" -B "validation\recovery_checks.py" "%RXQA%\engines"
if errorlevel 1 goto fail
"DesktopChecks.exe" "%RXQA%\desktop"
if errorlevel 1 goto fail
echo Validation passed. Reports and native screenshots are in %RXQA%
pause
exit /b 0
:fail
echo Validation failed. Keep %RXQA% for diagnosis.
pause
exit /b 1

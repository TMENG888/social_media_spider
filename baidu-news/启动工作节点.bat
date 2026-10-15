@echo off
chcp 65001 >nul
setlocal
set "SCRIPT_DIR=%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-worker.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Worker failed with exit code %EXIT_CODE%.
pause
endlocal & exit /b %EXIT_CODE%

@echo off
chcp 65001 >nul
setlocal
set "SCRIPT_DIR=%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-worker.ps1" -Mode check
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
endlocal & exit /b %EXIT_CODE%

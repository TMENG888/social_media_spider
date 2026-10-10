@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0common\start-central-log-sink.ps1"
set "CODE=%ERRORLEVEL%"
echo.
echo Central log receiver exited with code %CODE%.
pause
exit /b %CODE%

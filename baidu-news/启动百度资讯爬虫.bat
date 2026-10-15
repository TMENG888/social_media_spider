@echo off
setlocal
set "SCRIPT=%~dp0run-rpa.ps1"
if not exist "%SCRIPT%" (
  echo ERROR: run-rpa.ps1 was not found beside this BAT file.
  pause
  exit /b 2
)
pushd "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
echo.
if not "%EXIT_CODE%"=="0" echo ERROR: RPA exited with code %EXIT_CODE%. Review the message above.
pause
endlocal & exit /b %EXIT_CODE%

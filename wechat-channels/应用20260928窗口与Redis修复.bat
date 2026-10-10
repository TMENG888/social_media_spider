@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0应用20260928窗口与Redis修复.ps1"
if errorlevel 1 (
  echo Update failed. Review the error above.
) else (
  echo Update completed successfully.
)
pause

@echo off
setlocal
cd /d "%~dp0"
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo PowerShell was not found.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo AI Test Navigator failed to start.
  pause
  exit /b 1
)
endlocal

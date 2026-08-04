@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-kie.ps1"
if errorlevel 1 (
  echo.
  echo Kie.ai setup failed. Review the message above.
  pause
  exit /b 1
)
echo.
echo Kie.ai setup completed successfully.
pause

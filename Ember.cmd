@echo off
setlocal
if not "%~1"=="" (
  echo Ember does not accept arguments. Run Ember.cmd directly.
  if not defined EMBER_LAUNCH_NONINTERACTIVE pause
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\launch-ember-cli.ps1"
set "EMBER_EXIT=%ERRORLEVEL%"
if not "%EMBER_EXIT%"=="0" (
  if not defined EMBER_LAUNCH_NONINTERACTIVE pause
  exit /b %EMBER_EXIT%
)
exit /b 0

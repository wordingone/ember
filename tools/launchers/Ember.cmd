@echo off
setlocal
for %%I in ("%~dp0..\..") do set "EMBER_REPO_ROOT=%%~fI\"
if not "%~1"=="" (
  echo Ember does not accept arguments. Run tools\launchers\Ember.cmd directly.
  if not defined EMBER_LAUNCH_NONINTERACTIVE pause
  exit /b 2
)

if not defined EMBER_LAUNCH_TEST_MODE goto governed_cockpit
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%EMBER_REPO_ROOT%scripts\prepare-ember-cockpit.ps1"
set "EMBER_EXIT=%ERRORLEVEL%"
if not "%EMBER_EXIT%"=="0" if not defined EMBER_LAUNCH_NONINTERACTIVE pause
exit /b %EMBER_EXIT%

:governed_cockpit
for /f "usebackq tokens=1,* delims==" %%A in (`powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%EMBER_REPO_ROOT%scripts\prepare-ember-cockpit.ps1"`) do (
  if "%%A"=="EMBER_APPLICATION" set "EMBER_APPLICATION=%%B"
  if "%%A"=="EMBER_LAB" set "EMBER_LAB=%%B"
  if "%%A"=="EMBER_SOURCE_COMMIT" set "EMBER_SOURCE_COMMIT=%%B"
  if "%%A"=="EMBER_STATE_ROOT" set "EMBER_STATE_ROOT=%%B"
)
if not defined EMBER_APPLICATION goto prep_failed
if not defined EMBER_LAB goto prep_failed
if not defined EMBER_SOURCE_COMMIT goto prep_failed
if not defined EMBER_STATE_ROOT goto prep_failed

"%EMBER_LAB%" cockpit --root "%EMBER_REPO_ROOT%" --application "%EMBER_APPLICATION%" --source-commit "%EMBER_SOURCE_COMMIT%" --state-root "%EMBER_STATE_ROOT%"
set "EMBER_EXIT=%ERRORLEVEL%"
if not "%EMBER_EXIT%"=="0" (
  if not defined EMBER_LAUNCH_NONINTERACTIVE pause
  exit /b %EMBER_EXIT%
)
exit /b 0

:prep_failed
echo Ember could not prepare the cockpit. Run scripts\prepare-ember-cockpit.ps1 directly to see why.
if not defined EMBER_LAUNCH_NONINTERACTIVE pause
exit /b 1

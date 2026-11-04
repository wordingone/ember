@echo off
rem Ember-Open-Setup: one-command setup for ember-cli in open-weights mode (Windows).
rem   Ember-Open-Setup             check prerequisites, install Bun + dependencies, pick/pull/calibrate a model
rem   Ember-Open-Setup -DryRun     the same, but only plan the model download
rem   Ember-Open-Setup -Yes        do not ask before installing Bun
rem Safe to run again: finished steps are skipped. Guide: docs\ember-cli\INSTALL.md
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\ember\infrastructure\tools\ember-cli\scripts\install-open-weights.ps1" %*
set "EMBER_SETUP_EXIT=%ERRORLEVEL%"
echo %cmdcmdline% | find /i "/c" >nul && if not defined EMBER_SETUP_NO_PAUSE pause
exit /b %EMBER_SETUP_EXIT%

@echo off
rem Ember-Open: run ember-cli in the OPEN_WEIGHTS harness mode with an
rem operator-selected non-Ember model (see `Ember-Open pull --help`).
rem   Ember-Open-Setup           first-time setup: Bun, dependencies, model (docs\ember-cli\INSTALL.md)
rem   Ember-Open pull            fetch the best model that fits this machine
rem   Ember-Open                 interactive session in the current directory
rem   Ember-Open -p "task"       one headless task
rem The governed Ember.cmd launcher is unchanged; this one never claims an
rem owned model and never touches training state.
setlocal
set "EMBER_OPEN_WEIGHTS=1"
if not defined EMBER_SOURCE_ROOT set "EMBER_SOURCE_ROOT=%~dp0."
where bun >nul 2>nul || if exist "%USERPROFILE%\.bun\bin\bun.exe" set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
where bun >nul 2>nul || (echo Ember-Open needs Bun on PATH. Run Ember-Open-Setup.cmd, or see docs\ember-cli\INSTALL.md & exit /b 2)
bun run "%~dp0src\ember\infrastructure\tools\ember-cli\src\entrypoints\main.ts" %*
exit /b %ERRORLEVEL%

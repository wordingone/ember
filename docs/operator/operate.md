# Operating the Cockpit: Launch, Teardown, Interrupted-Stop Resume

This documents the ACTIVATE / DEACTIVATE operator verb: how to bring an
ember-cli operator surface up, take it down cleanly, and recover it after an
unplanned interruption (a crash, a closed terminal, a killed process).

The example below uses the real `/watch` telemetry mechanism
(`tools/ember-cli/src/services/telemetry-watch.ts`'s `startTelemetryWatch()`)
running as its own OS process, wrapped by a small launcher
(`scratch/ind3-operate-worker/telemetry-watch-worker.ts`) that gives it a
file-based ready/stop protocol so it can be operated the same way any
long-running ember process is operated — this is the same mechanism the
live `/watch` slash command wires into the cockpit; the wrapper only adds
the process-level start/stop signaling a standalone launch needs.

## Launch

Start the worker with three paths: a telemetry channel file, a heartbeat
file, and a stop-marker file.

```
bun run scratch/ind3-operate-worker/telemetry-watch-worker.ts <channel> <heartbeat> <stopmarker>
```

The process is up once `<heartbeat>` contains `{"status":"ready", "pid": ...}`.
Verify it independently with the OS process table (Windows `tasklist`, or
the platform-equivalent) rather than trusting the launch command's own exit
status — a launcher process and the process that actually runs the script
can be two different PIDs (observed directly: `bun run` on this host reports
one PID from the launch command and the running script reports a different
one via its own `process.pid`). Always verify and record the PID the
running process itself reports, not the launcher's.

## Teardown (clean stop)

Write anything to the stop-marker path. The worker polls for it, stops the
real telemetry watcher (`handle.stop()`), records `{"status":"stopped"}` to
the heartbeat, and exits 0. After it exits, verify with the process table
again that no process with that PID survives, and that no GPU/model-server
state was touched (there is none in this surface — orphaned GPU state is
trivially false here).

## Interrupted stop + resume

An unplanned stop (crash, closed terminal, killed process) does not go
through the stop-marker path at all — that is the point of testing it. Kill
the process tree directly (e.g. `taskkill /F /T /PID <launcher pid>` on
Windows — the tree-kill flag matters: killing only the inner worker pid can
leave the launcher process itself running as an orphan). Verify
independently that both the launcher and the worker pid are gone, then
relaunch fresh with a new heartbeat/stop-marker pair. The system resumes
cleanly: no persisted telemetry state depends on the previous process
having exited gracefully.

## Receipts

Each of the three legs above (`launch`, `teardown`, `interrupted_resume`)
writes a receipt under `receipts/ind3-operate/`, read by
`scripts/ember_totality/test_c_ind.py`'s IND-3 OPERATE check.

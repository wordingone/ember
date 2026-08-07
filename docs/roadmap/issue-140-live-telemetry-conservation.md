# Issue #140 live-telemetry conservation

Status: `SUPERSEDED_CURRENT_EMBER_03`

## Ruling

Issue #140 is tied to a removed C14/C-SURFACE2 execution window and a replay harness whose named hydration inputs and cured-executable path are absent from the current repository. Reconstructing those historical paths would restore stale authority and would not prove current Ember behavior.

The issue's unique invariant—real live telemetry must be bound to a currently running governed process and must never be inferred from replay—is preserved by the accepted current-owner transfer below. The historical tracker can therefore close as superseded without claiming that a current governed training run or live telemetry capture has occurred.

## Historical boundary

The original issue and its 2026-08-01 evidence establish:

- the old receipt was replay provenance, not live evidence;
- the old capture script referenced missing historical run files;
- no qualifying live governed run or built historical executable was present;
- a truthful cure had to instrument a real future governed run rather than fabricate or relabel replay.

Those are negative custody facts, not a result to reproduce.

## Lossless current-owner transfer

Canonical owner: [EMBER-03/#1117](https://github.com/wordingone/ember/issues/1117).

Accepted transfer: https://github.com/wordingone/ember/issues/1117#issuecomment-5221715046

The accepted transfer preserves:

1. currently-live run/job/lease/process identity;
2. exact source/executable/telemetry/capture/window identity;
3. strict live-versus-replay/stale/offline/malformed/foreign classification;
4. honest field-level binding for loss, step, progress, throughput or step time, VRAM, and checkpoint events;
5. installed UI capture and content-addressed reopening;
6. negative/refusal/deletion evidence and rollback;
7. no training, checkpoint, capability, sufficient-pretraining, or milestone inference.

## Architecture and claim boundary

Ember Lab plus the existing CLI telemetry and custody paths remain the sole runtime and observability authority. This ruling adds no board condition, capture daemon, dashboard, launcher, telemetry producer, or receipt family.

`NO_NEW_PARALLEL_AUTHORITY`

No live run, GPU execution, training success, checkpoint, benchmark, capability, sufficient-pretraining, or milestone-completion claim is made.

## Rollback

Revert the conservation commit and reopen #140 if the accepted transfer is removed or narrowed.

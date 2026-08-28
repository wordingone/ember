# 04 — Training Pipeline

## Active entry point: tools/ember-restart-3b/

The current production entry point for the `ember-sparse-3b-v2` subject is
`tools/ember-restart-3b/` (`docs/ember-restart/ember-restart-3b-governed-runner-v1.md`
calls it "the public production entrypoint... constructs the real model and
optimizer, consumes the checked-in owned training authority, executes the
real training path, and publishes manifest-last checkpoint bundles through
the repository disk governor"). The doc is explicit about scope: "The runner
does not confer sufficient-pretraining, multimodal capability, reasoning,
tool-use, competitiveness, admission, or Verified Expert Accretion credit. A
successful bounded run is execution and restart evidence only."

Notable modules under `tools/ember-restart-3b/`:
- `model.py` — the network implementation matching `configs/ember-restart-3b.json`
- `certified_train_launch.py` — the certified-launch validator. It holds every gate a certified launch must pass: declaration-ledger membership, completion-receipt and conjunct authority, requested-scope subset, run-scoped custody, resume and specialist and semantic and A1 route validation, and runner argv derivation. It is NOT directly runnable and has no command-line entry point (issue 898); the daemon dispatches it as a caged child with its path and sha256 pinned in a manifest the daemon builds. Contributors do not invoke it — see "Launch discipline" below for the one command that starts a governed run.
- `checkpoint_artifacts.py`, `checkpoint_scratch.py` — checkpoint bundle publication
- `disk_budget_runner.py` — wraps any command with a hard C:/B: drive write-budget preflight (see the CPU-only launch example in `docs/ember-restart/ember-restart-3b-governed-runner-v1.md`, which caps `--max-c-write-gib 0` for the canary preflight)
- `build_owned_audio_frames.py`, `build_owned_vision_scenes.py`, `build_owned_reasoning_tool_trajectories.py`, `build_owned_curriculum.py` — owned (non-borrowed) data construction per modality, matching the 03_MODEL_ARCHITECTURE.md expert set
- `domain_manifest.py`, `input_identity.py`, `custody_process_scope_worker.py` — custody/identity bookkeeping feeding condition `C0`/custody chain

## Launch discipline

A governed run starts with one command and no manual steps before it:

```
ember-lab launch --root <repo-root> --certificate <certificate.json> \
  --declaration-ledger <declaration-ledger.jsonl> --run-spec <run-spec.json> \
  --custody-receipt-sha256 <64hex> --pipe <\\.\pipe\ember-lab> \
  --receipt <custody>/certified-launch.json
```

Every argument comes from the launch packet the run already has; a contributor
writes nothing by hand. The daemon hash-pins the certified-launch validator,
builds and snapshots the dispatch manifest itself, and dispatches the validator
as a caged child, so the run is born inside the job object and behind the commit
ceiling, the VRAM ceiling and the foreign-process fence. The validator's exit
code is returned unchanged and its stderr relayed verbatim, so a refusal still
names the gate that refused — declaration-ledger membership, custody, scope, or
route — rather than being flattened into a daemon-level error.

The training program the validator then runs is `run_vertical_slice.py` under
`disk_budget_runner.py`'s bounded write roots, exactly as before; what changed is
that nothing outside the daemon starts it. There is no launcher script to run by
hand: the standalone entry points were removed under issue 898 and the repo
guard's `[launcher-shape]` check refuses their reintroduction.

## Retired pipeline (see 03_MODEL_ARCHITECTURE.md)

`scripts/timeshare_pretrain.py` and its `t2_*` round/family scripts
implemented the c03 sub-3B pipeline (checkpointing with sha256-manifested
files, bit-exact resume assertions, `fp19_bench`-pinned governor floor). That
pipeline is `historical_only` / execution-denied under the current
`EMBER-02` goal and is preserved for reference, not for launching.

## Current gaps — honestly stated

This doc describes the pipeline's real, on-disk shape. It does not claim a
completed training run: `C-BASE` (see 03_MODEL_ARCHITECTURE.md) was RED on
the last board render for lack of visible owned-checkpoint bytes. Whether the
governed runner has produced any bounded canary run beyond preflight, and
what that run's actual receipts show, is tracked by the board's `C-BASE`,
`C0`, and related rows — this doc is the architecture map, not a claim of
execution history.

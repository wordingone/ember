# Ember certified run-root layout v1

The canonical `certified_train_launch.py` owns one run root. It creates the
following relative layout and never accepts a caller-authored retention
destination:

```text
<run-root>/
  artifacts/                         # current attempt's selectable outputs
  telemetry/                         # append-only train_step JSONL
  runner-receipt*.json               # current attempt authority/evidence
  runner-receipt-child.log           # current attempt child stdout/stderr
  run-spec.json                      # persistent launch declaration
  certificate.json                   # persistent launch authority
  attempt-<n>-<REASON>-<UTCSTAMP>/   # retained failed attempt, non-selectable
    artifacts/                       # prior attempt outputs, including telemetry
    runner-receipt*.json             # prior attempt root-level receipts/logs
    runner-receipt-child.log
    attempt-retention.json            # closed retention evidence
  .checkpoint-quarantine/             # non-selectable checkpoint evidence
```

`artifacts/` is renamed into a fresh attempt directory before a retry after a
non-zero child exit. The new empty `artifacts/` directory is the only place a
retry may publish current checkpoint/evaluation artifacts. The retention name
is a closed basename (`attempt-<positive integer>-<uppercase reason>-<UTC
timestamp>`); absolute paths, traversal, symlinks, and caller-selected roots
are refused.

The validated certificate, declaration ledger, run spec, linked completion
receipt, and optional training-verification receipt are protected authority
inputs and remain at their exact live-root paths across retention. Their
relative names are recorded in `attempt-retention.json`; they are never
protected by a guessed filename allowlist.

R1 discovery follows this contract: checkpoint, runner, frontier, frozen-eval,
registry, intervention, wall, and other receipt globs exclude retained
`attempt-*` evidence, while telemetry discovery deliberately includes JSONL
inside retained attempts so failed-attempt rows remain part of the selected
run's measured history. Quarantine is always non-selectable for both classes.

## Registry and frontier receipt ordering (#1510)

The certified launch sequence records every `spawn/terminal` event before it
enters `quiesce`: the append-only run registry is closed for the current
attempt, and no further registry append is permitted during receipt minting.
After quiesce, the launcher must mint all frontier receipts from that closed
registry snapshot, then run the battery against those receipts. The invariant
is strict: no launch may start after mint. A retry opens a new attempt and a
new registry phase; it never appends to or rewrites the already-minted frontier
receipts from the prior attempt.

This document is descriptive authority only; the certified launcher and
`scripts/r1_exit_battery.py` are the executable consumers. No second launcher,
receipt family, or cleanup authority is introduced.

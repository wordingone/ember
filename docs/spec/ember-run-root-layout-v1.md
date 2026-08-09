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
  frontier-receipt.json              # current E5 frontier candidate
  frozen-eval-results.json           # frozen evaluation evidence
  energy-proxy-receipt.json          # bounded energy evidence
  human-interventions.json           # intervention ledger
  walls-checklist.json               # physiology/wall evidence
  run-spec.json                      # persistent launch declaration
  certificate.json                   # persistent launch authority
  attempt-<n>-<REASON>-<UTCSTAMP>/   # retained failed attempt, non-selectable
    artifacts/                       # prior attempt outputs, including telemetry
    runner-receipt*.json             # prior attempt root-level receipts/logs
    runner-receipt-child.log
    attempt-retention.json            # closed retention evidence
  .checkpoint-quarantine/             # non-selectable checkpoint evidence
```

The append-only attempt registry is repo-relative at
`receipts/run-attempts.jsonl`; it is not moved into a run root or an attempt
archive. Discovery may accept equivalent producer-selected receipt basenames
only where the battery already defines that glob explicitly.

`artifacts/` is renamed into a fresh attempt directory before a retry after a
non-zero child exit. The new empty `artifacts/` directory is the only place a
retry may publish current checkpoint/evaluation artifacts. The retention name
is a closed basename (`attempt-<positive integer>-<uppercase reason>-<UTC
timestamp>`); absolute paths, traversal, symlinks, and caller-selected roots
are refused.

The validated certificate, declaration ledger, run spec, linked completion
receipt, optional training-verification receipt, and any live-root resume
checkpoint/evidence or specialist authority inputs are protected and remain
at their exact paths across retention. Their relative names are recorded in
`attempt-retention.json`; they are never protected by a guessed filename
allowlist.

R1 discovery follows this contract: checkpoint, runner, frontier, frozen-eval,
registry, intervention, wall, and other receipt globs exclude retained
`attempt-*` evidence, while telemetry discovery deliberately includes JSONL
inside retained attempts so failed-attempt rows remain part of the selected
run's measured history. Quarantine is always non-selectable for both classes.

This document is descriptive authority only; the certified launcher and
`scripts/r1_exit_battery.py` are the executable consumers. No second launcher,
receipt family, or cleanup authority is introduced.

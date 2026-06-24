# sp-6b B-run designation rule v0 — FROZEN (part of #282)

The B3 comparison (fp33-surpass-prereg-v1) replays the frozen duty battery on
both seats. The E2B seat is fixed (google/gemma-4-E2B-it @ b324173, receipted
in #312). The ember seat is a CHECKPOINT CHOICE — and an unfrozen choice is
the most obvious bias channel in B3: with many WSD checkpoints on disk, the
gater could shop for the one that flatters ember. This rule freezes the
choice mechanically, NOW, while exactly one checkpoint's duty behavior is
known (step-25000: mute, 4/20 silence-only — #314). No checkpoint's battery
performance beyond that baseline has been observed by anyone at freeze time.

## The rule (deterministic, no discretion)

**Designated ember seat = the COMPLETE checkpoint with the HIGHEST step
number, among the checkpoints of the v0 pretrain lineage, at resolution
time.**

- **Lineage** = run 12c050e7 and any receipted resume/continuation of it
  (same config contract, WSD continuation per the frozen launch chain).
  Checkpoints dir(s) named at resolution; a resume adds its dir to the scan.
- **COMPLETE** = `model.pt` present AND non-empty AND `manifest.json`
  present and JSON-parseable. Incomplete/in-flight checkpoint dirs are
  skipped (never refused — the writer may be mid-flush at resolution).
- **Resolution window** = 2026-06-20T00:00Z .. 2026-06-21T23:59Z. The
  resolver REFUSES outside the window (B-run too early = wastes the
  remaining training days; too late = no audit margin before 06-22).
  fp-30b-class registered deviation required to override.
- **Tie-break**: step number is the sole ordinal; equal steps across
  lineage dirs (a resume re-emitting a step) → the LATER dir in the named
  scan order wins, and the receipt must flag the collision.
- The resolution emits a **designation receipt** binding:
  `{rule_version, rule_doc_sha256, resolved_at, window, candidates[]
  (path, step, complete, mtime), designated {path, step, model_pt_sha256},
  template_hash}` — the B-run receipt must embed this designation receipt's
  sha and bind the SAME checkpoint sha, or the B-run is void.

## What the rule deliberately does NOT condition on

- **No capability conditions** (verify-floor, loss, probe verdicts). Any
  performance-coupled filter re-opens the shopping channel through the side
  door ("newest checkpoint that passes X" lets X selection do the shopping).
  The goal is "ember at its best honest state by the deadline" — that is
  recency under the frozen training plan, full stop.
- **No battery-coupled inputs.** The resolver reads the checkpoints
  directory and nothing from receipts/ — battery scores cannot reach the
  choice even by accident.

## Resolver

`scripts/nck/b_run_designation.py` — pure function of the named checkpoint
dirs + clock; `--now` injectable for the selftest, defaults to system UTC;
`--write` emits the receipt; bare invocation = staged exit 1 (evidence-
promotion gate, house pattern). Selftest
`scripts/nck/selftest_b_run_designation.py` (fail-closed, no model, tmp
fixtures only).

## Freeze semantics

This rule + the resolver constants are frozen as of this commit. Post-freeze
edits = fp-30b-class registered deviation (receipt naming superseded bytes +
reason, BEFORE resolution); edits after a resolution receipt exists void
that resolution. The B-run executes on the designated checkpoint per the
frozen prereg's replay-identical protocol; 20 paired episodes, McNemar exact
p < 0.05, ember strictly better (B3).

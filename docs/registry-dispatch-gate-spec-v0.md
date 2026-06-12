# sp-7 — technique-registry dispatch gate, spec v0 (#256, Leo half)

User directive 2026-06-12: the optimization thread (docs/technique-registry.md
+ .jsonl) is permanent and exhaustively tested. This spec makes the registry
BINDING at dispatch time instead of advisory prose: a training dispatch that
silently ignores an ADOPT row is refused, fail-closed, with the row named.

## Contract

Every training-run config carries a top-level `registry` block:

```json
{"registry": {
  "consumes": ["muon", "wsd-schedule", "qat", "governor-pacing"],
  "exemptions": [
    {"row_id": "qat", "reason": "eval-only job, no weight updates",
     "receipt_path": "receipts/<...>.json", "scope": "eval",
     "expiry": "2026-06-22"}
  ]
}}
```

Gate rule (fail-closed, deterministic):
1. Every row with `status == "ADOPT"` in technique-registry.jsonl must appear
   in `consumes` OR in `exemptions`.
2. An exemption is valid only if `receipt_path` exists on disk AND `expiry`
   (ISO date) has not passed. Invalid exemption = the row is unconsumed.
3. **Corroboration (anti-gaming):** declaring `consumes` is not enough where
   a config predicate is defined (table below). If the predicate's config
   key exists and contradicts the declaration, verdict is
   `declared-but-not-configured` = FAIL. Missing key = WARN (recorded), not
   FAIL — config shapes vary by job class; the declaration stands.
4. Verdict receipt: one jsonl line `{ts, config_path, registry_sha, ok,
   missing[], invalid_exemptions[], contradicted[], warns[]}` appended to
   `receipts/registry-gate.jsonl`.

## ADOPT-row config predicates (v0 — extend with every new ADOPT)

| row id          | predicate (corroborates `consumes`)                          |
|-----------------|--------------------------------------------------------------|
| muon            | any config key named `optimizer*` has value containing `muon` |
| wsd-schedule    | any key named `*sched*` has value containing `wsd`            |
| qat             | any key named `*qat*` is truthy                               |
| governor-pacing | `*vram_fraction*` present and <= 0.85, or `EMBER_VRAM_FRACTION` in an `env` block |

Predicates are substring/threshold checks over a flattened (dotted-key)
config — declarative, shape-tolerant, defined in `scripts/registry_gate.py`
(`PREDICATES`). Adding an ADOPT row without a predicate is allowed (rule 3
then has nothing to corroborate; rules 1-2 still bind), but the selftest
flags it as a coverage WARN so the table never silently rots.

## Status semantics the gate reads (unchanged from registry doc)

- `ADOPT` — binds dispatch (this gate). `CANDIDATE`/`TESTED`/`WATCH-NEGATIVE`
  — never bind; they are worked through the proxy harness. `KILL` is a
  status, not a removal; killed rows never bind.
- Promotion to ADOPT requires a TESTED proxy receipt + `measured_multiplier`
  set; that promotion discipline lives in the registry doc — the gate only
  trusts `status`.

## Proxy-speedrun harness contract (#256 second half — build is eng, behind E4/E5)

- Frozen target: ~50-100M params, fixed architecture, trained on the pinned
  shards-v0 slice; seeds {16, 17, 18}; governed (vram fraction + pacer).
- Output per arm: wall-clock-to-target and tokens-to-target at a frozen
  loss/eval target, jsonl receipt with config sha + registry row(s) under
  test. One row (or one declared composition) per arm — no multi-variable
  arms.
- A TESTED verdict = paired delta vs the frozen baseline arm on the same
  seeds; `measured_multiplier` = baseline/arm wall-clock ratio (>1 is a win).

## Wiring (eng successor)

`python scripts/registry_gate.py --config <path>` exits 0/1 — Eli wires it
as a dispatch precondition in the train-daemon path (same precheck family as
the governor asserts). The reference implementation in this repo is the
contract; the daemon calls it, never reimplements it.

## Selftest

`scripts/registry_gate_selftest.py` — validates the live registry (parse,
required fields, legal statuses), asserts predicate coverage of every ADOPT
row (WARN-level for gaps), and runs the gate against PASS / missing-row /
invalid-exemption / contradicted fixtures. Fail-closed on any mismatch.

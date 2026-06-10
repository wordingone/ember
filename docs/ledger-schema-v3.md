# Ledger schema v3 — one schema, documented absences (freeze-spec gap 1)

*2026-06-10. Closes pre-freeze gap 1 by SPEC + w2 alignment, not by ledger
rewrite: the 1,909 existing entries remain byte-untouched and valid under v3
via documented-absence semantics. Append-only is preserved — nothing is
migrated, future appends conform.*

## Why now

ARC seed entries and (unfired) w2 W-code records had diverged on five fields,
and NEITHER carried the receipt reference that kernel freeze-surface member 3
requires ("every entry carries an execution receipt reference"). Caught
before any w2 append — w2_ingest is patched to emit v3; the seed entries get
blanket-receipt semantics below.

## v3 fields

**Required on every NEW append:**

| field | meaning |
|---|---|
| `key` | `task:sha1_16(src)` — dedup identity (unchanged) |
| `task` | world task id (`007bbfb7`, `tid#a2`, `mbpp:601`, …) |
| `src` | the program text — the artifact V blessed |
| `verified` | V's verdict, explicit boolean (w2 was omitting it — fixed) |
| `ts` | UTC compact timestamp of verification |
| `origin` | provenance string: `seed-dsl-orig`, `seed-verifier-rearc-v2`, or sampler identity `model[+adapter]` (absorbs w2's `sampler` — one provenance field, not two) |
| `receipt` | filename of the receipt whose run produced/blessed the entry |

**Optional, world-dependent (absence is DEFINED, not ambiguous):**

| field | absent ⇒ |
|---|---|
| `prompt` | derivable by the frozen renderer: ARC = `task_prompt(pairs)`; W-code = `problem_prompt(task)` |
| `sampler` | superseded by `origin` (kept as passthrough where w1 rows carry it; readers MUST use `origin`) |
| `round` | round 1 (seed) |
| `pairs`, `test` | non-ARC world (V used the task's own asserts) |
| `solved` | equals `verified` where the world has no held-back test (W-code) |

## Status of the existing 1,909 seed entries

Valid v3 with documented absences: `receipt` absent ⇒ blanket receipt
`receipts/t3-seed-20260610T021308Z.json` (the run that admitted all 1,909 at
96.4%); `prompt` absent ⇒ renderer-derivable; `round` absent ⇒ 1. No
rewrite — provenance already explicit in `origin` + `ts`.

## Reader contract

`t2_round.build_dataset` renders absent prompts (branch landed with w2);
any consumer filtering verified entries must treat `verified` as required
going forward and `True` for the seed block (they were admit-gated by t3's
sandbox; failures went to control_pool).

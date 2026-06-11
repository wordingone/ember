# fp-27 — owned-core accumulation round-1 prereg (#198)

Owner: Leo. Status: **FROZEN** — receipt
`receipts/fp27-prereg-20260611T130743Z.json` (`prereg_frozen:true`,
receipt_check clean), emitted with zero checkpoint-era receipts on disk
(the freeze-beats-checkpoint-1 guard held live). Artifact:
`scripts/fp27_round1_prereg.py` (`--selftest` / `--freeze`). fp-26 froze the
round-3 SHAPE — (b) owned-core in-dist accumulation; this freezes the ROUND:
every constant that will shape and judge the first accumulation round on
ember-v0, pinned before any checkpoint exists.

## Split discipline (the load-bearing design)

All inside fp-23's frozen envelope (probe buckets 0–9 untouchable;
training-time generation only in 10–99), tighten-only partition:

| Region | Buckets | Use |
|---|---|---|
| Floor probe | 0–9 | fp-23/fp-24 floor protocol only |
| Train | 10–89 | sampling + verified-episode ingest |
| Round gate | 90–99 | eval only (N=100, seed 23 generator), never trained |

Same generator, same grammar, same distribution → the round gate is in-dist
by construction (the (b) shape's defining property) while instance-disjoint
via the sha1 bucket function. Selftest proves: disjoint, exhaustive over
10–99, probe untouched, and the live `bucket()` routes instances to all
three regions.

## Frozen round constants

- **Base policy:** terminal v0 checkpoint (full 6,973,632,296-token budget),
  by terminal-receipt sha; calendar fallback (mechanical: terminal receipt
  absent by 2026-06-18T00:00Z) = highest-token PASS-floored checkpoint ≥4B.
  Round-1 dispatches ONLY after a PASS floor verdict on the base.
- **Sampling:** 200 L1 + 56 L2 tasks from train buckets, k=8, **seed 31**
  (virgin — 16/23/3407 burned), temp 0.8, top_p 0.95, max_new 512. The
  sampling receipt's pacing block carries the retargeted fp-20c (#146)
  re-check.
- **Accumulation:** verified episodes append to the owned ledger; retrain
  FROM BASE on the full ledger each round (GOAL replay-buffer convention).
- **Arms:** sft binding; mtp/grpo information-only if governed windows allow.
- **Round gate:** stats_exact paired vs base on the round-gate split; D-gate
  (round-adapter quarantine vs owned base) + P-gate per sp-2 (#201).
  Flat/negative round = DATA for round-2 design, never a rung-kill.

## Kill wiring (composes, never mutates)

Floor protocol untouched (fp-23 bar 1.0 at 2B, single retry, fp-24
executes). fp-29 gates the KILL: valid only with a receipted 2B→4B
synthesis attempt. **Mandatory-in-window binding (new here):** a 2B
RETRY-AT-4B OBLIGATES the receipted synthesis mix in the continued pretrain
before the 4B leg — so the fp-29 refusal state (un-receipted KILL) is
unreachable under correct execution, and fp-22's no-third-retry stands.

## Adversarial panel (pre-freeze, 3 Haiku lenses)

Leakage and contradiction lenses: NOT refuted (partition mechanically sound;
consistent with fp-23/fp-26/fp-29 — line-level cross-check). Goalposts lens
REFUTED with 6 findings; disposition:

- **Time-variant calendar fallback (×2) — FIXED:** base selection is now
  ts-bounded (PASS-floor verdict-receipt ts < 2026-06-18T00:00Z), making the
  lookup time-invariant; chosen base sha recorded immutably in the dispatch
  receipt.
- **Self-reported synthesis asserts (×2) — FIXED:** fp-29 shape gains
  `episodes_manifest_sha256` + a named gate-time audit obligation (eng-53
  byte-scan pattern): bucket membership and episode count are re-derived
  from the manifest, never trusted from the boolean asserts.
- **Round-verdict spin risk — FIXED:** verdict vocabulary frozen mechanical
  (GAIN / FLAT / NEGATIVE by paired CI on the binding arm); no other words.
- **`rate >= 1.0` tie + pacing interpretation — HELD AS-IS:** the boundary
  and the rate convention are fp-23 FROZEN ("verified episodes / governed
  wall-clock minutes, pacing INCLUDED — fp-14 convention"); the convention
  is unambiguous and tighten-only forbids moving the bar in either
  direction. A tie at exactly 1.0 passes, deterministically.

The leakage lens also correctly observed that fp-27/fp-29 are declarative
preregs — the executing harness enforces the bucket constraints at run
time. That is by design (the prereg freezes WHAT the harness must enforce;
the audit obligation above is the enforcement check).

## Freeze guards

`--freeze` refuses on: fp-26 decision sha drift; missing frozen fp-26
prereg receipt; **any checkpoint-era receipt already on disk** (a round-1
prereg frozen after checkpoint-1 is not a prereg); bucket partition
violating the fp-23 envelope.

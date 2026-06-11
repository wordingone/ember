# June-22 critical path — frozen 2026-06-11 ~02:20Z (task #37)

User directive 2026-06-11 (goal re-issue): **finish Ember by June 22, by
whatever means possible**; ≥5 open tasks each (Leo + Eli), always in
motion. This map freezes the day-level sequence. The deadline narrows
SCHEDULE, never the evidence bar (never-reduce-scope: every gate keeps
its receipts-grade AC; the artifact list is sequenced, not trimmed).

## 1. Terminal conditions (persistence clause) → receipt status today

| # | Condition | Status | Receipt(s) / gap |
|---|-----------|--------|------------------|
| 1 | Runs locally | ✓ | daemon + t1/t2/t4/w1/w4 receipt families |
| 2 | Generates verified experience | ✓ | ledger 2,865 rows; V + extended tests (eng-11) + reachability guard (eng-23) + strict comparator (eng-21/24); soundness stream fp-1..18 |
| 3 | Trains/updates from it | ✓ | r1w arms (plain/control/MTP/GRPO-iter); 956 episodes are the core's OWN on-policy verified samples |
| 4 | Improves held-out transfer | PARTIAL | MTP +5.23pp CI [+0.58,+10.47] on validation-43 — ONE receipt, one round. Gap: round-2 replication with ACCUMULATED self-generated episodes (the loop, not a pass) |
| 5 | Beats matched control | PARTIAL | MTP +7.85pp CI [+3.49,+13.08] — same single-round caveat |
| 6 | Gain disappears on deletion | PARTIAL | deletion = adapter-unload, base floors receipted — ad-hoc, no STANDING harness (task #36) |
| 7 | Persists across sessions | MISSING (as receipt) | adapters persist on disk trivially; the CLAIM needs a session-boundary eval-pair receipt (task #36) |
| 8 | Loop without cloud/borrowed-core load-bearing | SPLIT — see §2 | |

## 2. Condition 8 — two readings, both named, neither blurred

- **8a (loop-machinery, June-22 achievable):** the generate→verify→
  ingest→train→gate loop executes end-to-end from LOCAL jobs (daemon +
  local sampler + local verifier), founders/cloud authoring the harness
  but absent from the loop path. Receipt: one full round run config-only
  with zero cloud calls in the loop path.
- **8b (owned substrate, the full goal):** the borrowed core (Qwen) is
  never the terminal substrate (NC2-own contract). STATE's standing
  estimate (0.1–1B, ~20B tokens ≈ 3 weeks continuous 4090) does NOT fit
  11 days. **fp-19 (#111) computes what DOES fit** — measured
  throughput × {0.1B, 0.3B} × {ternary, QAT} × achievable tokens ×
  a world whose verify floor the envelope core clears.
- June-22 claim shape, honest version: conditions 1–7 + 8a receipted on
  the borrowed instrument core, PLUS an owned v0 core pretrained from
  scratch inside the fp-19 envelope with a floor receipt — and, if the
  floor clears, a micro-loop receipt on the owned core (8b at v0
  scale = owned-substrate existence proof). NOT claimable by June-22:
  owned core at borrowed-core capability. If fp-19's envelope returns
  empty (no config clears any floor), the rung-kill fires → hardware
  escalation to the user (his call; the loop result stands either way).

## 3. GPU budget (the binding resource)

- 11 days. Reservations: round-2 ≈ 1 GPU-day spread (sampling k≈16–24
  on the W-code pool with the r1 MTP adapter + 3 arms train + G1/w4 +
  powered t5); round-3 ≈ 1 GPU-day (cluster-cap arm + fp-15 band
  transfer); persistence/deletion gates ≈ CPU + small eval windows.
- Owned-core v0 pilot: ~7–8 continuous GPU-days IF launched by ~06-13.
- **Timeshare rule (serialization memory: one model at a time):**
  pretrain holds the GPU by default and CHECKPOINTS OUT for named round
  windows; handoff is checkpoint-resume, never concurrent. Mechanical
  enforcement rides the governor. Checkpoint-resume harness = eng slice
  minted WHEN fp-19 names a config (eng-32 candidate; not before — no
  vapor issues).

## 4. Frozen sequence (day-level; gates keep full AC)

- **06-11:** fp-19 micro-benchmark + envelope verdict (GPU minutes,
  governed). Round-2 prereg freeze (#35) — consumes eng-28 (#104) exact
  stats + eng-30 (#106) arm plumbing as they land. Eng queue runs
  (#101/#103/#104/#106 active; #105 at next zero-in-flight window).
- **06-12:** **Round-2 LAUNCH** — self-generated episodes sampled WITH
  r1w-q3-mtp (accumulation semantics verified in build_dataset),
  ingest (+ eng-25 sidecar stamps), 3 arms, G1/w4 paired + POWERED t5
  (full sanitized test split, per-problem paired, MDE on any FLAT).
  fp-15 (#90) fires on this round; fp-14 (#88) on its sampling run.
- **06-13:** Round-2 gates. **Owned-core v0 pretrain LAUNCH** if fp-19
  names a config (governed fraction; timeshare per §3).
- **06-14/15:** Round-3 (cluster-cap arm per fp-17 prereg, consumes
  eng-26 #101 build path; revision criterion live). Deletion-test +
  cross-session persistence STANDING gates land (#36 spec → eng harness
  → first receipts on the r1w/r2w adapters).
- **06-16–20:** Pretrain continues; mid-train K1-equivalent verify-floor
  probes in fp-19's named world at checkpoints. Round-4+ accumulation
  on the borrowed core only if GPU windows allow (evidence redundancy,
  not a gate requirement).
- **06-21:** Owned-core v0 floor receipt. If floor clears: micro-loop
  smoke on the owned core (generate→verify→train one micro-round) = the
  8b existence-proof receipt.
- **06-22:** Terminal-condition audit against THIS table; every row
  quoted with its receipt or its named gap. No row blurred.

## 5. Standing risks (named now, not discovered later)

1. fp-19 envelope empty → rung-kill → user hardware call (§2).
2. Round-2 G1 null on accumulated episodes → the loop's first
   REPLICATION failure — t5/G1 receipts decide round-3 method, not
   improvisation; fp-15's band-transfer claim falsifies alongside.
3. Daemon eval-log hazard until #105 lands (hand-serialization stays
   mandatory until the per-job-logs receipt).
4. Fable access ends 06-22 — every load-bearing decision goes to disk
   same-session (standing June-22 priority-inversion rule).
5. GPU timeshare contention (pretrain vs rounds) — checkpoint-resume
   handoff only; concurrent loads BANNED (serialization memory; 06-10
   crash precedent).

*Owner: Leo (task #37). Updates ride gate entries in STATE; this file
re-frozen only on a sequence change, with the change named.*

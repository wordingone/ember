# DT-4 — Retro-citation audit (Search-origin imports lacking the header)

**Status:** DONE 2026-06-14 (the lead audit). Verdict: **zero remediation items** — no
Search-origin local-update primitive is currently imported into nc-ladder code, so
the citation-header requirement (`docs/citation-policy-search-to-ember.md`, DT-2)
has nothing to retro-fit. Residual risk (renamed/paraphrased import) routed to an agent
for an adversarial pass.

## What the audit checked

The citation policy binds **Search-origin primitives** (a lifted script /
algorithm / math body) that land in `nc-ladder/`. The retro-audit asks: is any
such primitive already present **without** the header? Two greps over
`nc-ladder/**/*.py`:

1. **Primitive-body grep** — the predecessor-map names:
   `step0778|step0785|step916|fluxcore|atomic_fold|living.seed|delta.rule|echo.state|reservoir`.
   **Result: 0 files.** No local-update primitive body is present.

2. **Header / Search-reference grep** —
   `Search source|Search-origin|Widrow|citation|[UNIQUE]|step0778|the-search`.
   **Result: 17 files**, all explained as incidental string-matches (below).
   `Widrow` / `[UNIQUE]` / `step0778` / `Search source` matched **nothing** in
   content — confirming neither a header nor a primitive body.

## The 17 hits — verified incidental (real-import vs string-match)

| class | files | why it is NOT a primitive import |
|---|---|---|
| **the-search = DATA PATH** | t0_preflight, t1_probe, t1c_contamination, t4_eval, arcade | reference `<local-path>` (ARC-AGI puzzle data) and `the-search/environment_files` (25-game corpus). A path to where the **dataset** lives is a data dependency, not a lifted algorithm. Out of scope: the policy covers primitives, not data locations. |
| **"citation"/"elicitation"/"calibration" substring** | c04_receipt3 (`density_citations` receipt field), fp6_provenance (license citations in receipt), w1_owned_sampler ("mirrored for citation"), calibrate / calibration_decomp / r2_arms / t2_r2_* / w1_mbpp / w1_humaneval / w1_r1_focus_q3 (P(verify) **elicitation** passes, eng #6) | substring collisions with `citation`. None lifts a Search local-update primitive; these are ember-native eval/calibration harnesses. |

## Verdict

- **No retro-remediation.** Zero files require a header added after the fact,
  because zero Search-origin local-update primitives are imported into nc-ladder
  code today. The family (delta-rule, fold-memory, AtomicFold, Living-Seed,
  echo-state) exists only in the **diagnostic prereg docs** (DT-1), awaiting the engineer's
  implementation.
- **Enforcement is forward, not retro.** The header becomes load-bearing at the
  moment the engineer writes the DT-1 diagnostic code — already bound via DT-2 (lineage
  reconstructed in the citation policy's predecessor map; bound into the engineer's code
  per mail 15442). No new eng item needed; the requirement applies at write-time.

## Claim scope (honest bound) → an agent adversarial pass

This audit proves absence **by primitive name and by the-search path reference**.
It does **not** by itself exclude a **renamed / paraphrased** import — Search
update-math copied into nc-ladder under a different identifier (e.g. an
`W -= eta * outer(err, x)` body without the `delta`/`step0778` name). That escape
vector is the one residual risk and is routed to an agent as an adversarial pass:
grep the characteristic update shapes (error-modulated outer-product; cosine
winner-take-all additive attraction; attention-weights-as-credit) across
nc-ladder code and confirm none appears unheadered. A clean an agent pass closes DT-4
fully; any hit an agent finds becomes a named remediation item.

Per user direction.

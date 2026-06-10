# Next-world admission analysis — round 2 (#33)

Survey detail in `research/drafts/world-choice-r2-draft.md` (Haiku draft,
gated here; receipts cited per claim, UNVERIFIED marked). This file is the
binding read: criteria from `research/world-choice.md` §7 — (a) floor
accessibility MEASURED at affordable k, (b) verification density, (c)
portfolio coupling.

## Decision

1. **Round-2's TRAINING world stays W-code (MBPP-graded).** Its floor is
   the best-measured object in the project (90.7% validation feed,
   `w1-floor-g1-base-20260610T215814Z`), the G1+t5 chain just produced the
   first control-beating gain on it, and bits remain (frontier/dead strata
   + ext-clean accounting). No world switch mid-ladder.
2. **HumanEval+ (evalplus) = next world, admission probe FIRST.**
   Apache-2.0, evalplus is ALREADY a local dependency (v_extended uses its
   mbppplus split), ~80× extended tests = highest verification density
   available locally. Roles on admission: new heldout transfer surface
   immediately; training-world candidate only after the split rule below.
3. **ARC-AGI-3 policy world = R2-parallel candidate, blocked on harness.**
   Game API/judge infra is separate from the t1_probe sandbox; no floor
   receipt is possible until an arcade harness exists. Portfolio coupling
   strong (policies-in-inspectable-worlds is the goal's own language).
4. **IFC/building world = deferred to the corpus prerequisite** (vault L1
   + kernel verifier instrumentation). Strongest portfolio coupling,
   unmeasurable floor today.
5. **LiveCodeBench = not admitted**: no LICENSE at repo root (GitHub API
   license=null, draft-verified) — fails the local-rights bar without
   sign-off; revisit only if licensing clarifies.

## Fireable probe spec — HumanEval+ admission (w1-class)

- Script: `scripts/w1_humaneval.py`, cloned from w1_mbpp semantics
  (governed generation, t1_probe sandbox, per-sample rows with src,
  receipts + samples.jsonl). Dataset: `evalplus/humanevalplus` (164
  problems; plus-tests as the verifier — V is born hardened on this world,
  unlike MBPP where extended joined at eng #21).
- **K3 split discipline (draft missed this — binding):** HumanEval has no
  published train/val/test split. Deterministic split by task index before
  ANY use: task_id % 5 == 3 → heldout-eval (33), % 5 == 4 → harm-reserve
  (33), else → train-pool (98). The probe runs on the TRAIN-POOL ONLY;
  heldout/harm stay untouched until their gates need them.
- Budget: 98 tasks × k=8, batch 8, seed 14 — same shape as the MBPP probe
  that took 363.9s at 1.5B / 428.7s at 3B (receipts w1-floor-q15/q3) →
  affordable single GPU window.
- **Admission criterion (per §7, replacing the draft's arbitrary ≥20%):**
  floor > 0 with Wilson CI excluding 0 at the probe budget. The measured
  band then sets expectations (strata + bits via frontier.py annotations,
  same as MBPP ingest); a single-digit floor admits the world as
  frontier-heavy, it does not reject it.
- Published anchors (context only, never the verdict): StarCoder2-3B 27.4%
  pass@1 HumanEval+ (arXiv 2402.19173); Qwen2.5-Coder-3B ~45% on original
  HumanEval (draft, GitHub-issue-sourced, UNVERIFIED). OUR number = the
  probe receipt.

## Named successors

- HumanEval+ admission probe → new eng issue (script + one GPU window).
- ARC-AGI-3 arcade harness → new eng issue (infra; floor probe spec rides
  on it). Win-rate ACs from the draft are NOT adopted — same §7 rule:
  measured floor, CI excluding 0.

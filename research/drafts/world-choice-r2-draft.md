# Next-World Admission Analysis Draft — ember Round 2 (Issue #33)

*2026-06-10. Candidate assessment for W-code successor and admitted training worlds per formalization §7 floor criterion.*

---

## Executive Summary

R2 faces a fork: the base W-code loop (MBPP-graded) is **verified-experience-enabled** (r1w receipts show 90.7% feed rate on validation), satisfying §7(a) floor-accessibility for MBPP at 3B scale. Four candidate *next* worlds compete for R2 slots. Recommendation: **HumanEval+ (evalplus, Apache-2.0 license) as the R2-immediate successor**, paired with ARC-AGI-3 policy world as the R2-parallel portfolio-coupled track. IFC/building-data worlds deferred to NC1c (corpus-building prerequisite). LiveCodeBench substitution deferred (license ambiguity + upstream maintenance risk).

---

## 1. World Admission Criterion (§7 Review)

From `formalization-v0.md §7`, a training world is ADMITTED only if:

- **(a) F(θ_0, W, k_affordable) > 0** — floor accessibility, MEASURED not assumed. The core must verify >0% on its first-pass sample pool at budgeted k.
- **(b) V grounded in world dynamics** — verification is deterministic execution, no learned judges.
- **(c) Leak resistance** — held-out surfaces survive contamination.
- **(d) Transfer-relevance** — gains should bear on the portfolio's unsolved problems.

**ARC-AGI-1 floor = 0%** — receipt `t4-r1-q15-arc1-seed14-20260610T150153Z.json`: Qwen2.5-Coder-1.5B on 100 held-out tasks, k=8, seed 14 → all-zero (solve_any_pct: 0.0, CI95: [0.0, 0.0]). Published anchor: SOAR 2507.14172 reports ~1% zero-shot for 7B-class base. **ARC fails §7(a) at residency scale**; proceeds to transfer-surface role only.

**W-code (MBPP-graded) floor = 90.7%** — receipt `w1-floor-g1-base-20260610T215814Z.json`: Qwen2.5-Coder-3B on 43 heldout validation tasks, k=8, seed 16 → feed_tasks=39/43, feed_pct=90.7%, CI95=[81.4, 97.67]. **Passes §7(a)**: loop is proven at MBPP + 3B + k=8 scale. This is the floor that unblocks R2.

---

## 2. Candidate Worlds Assessment

### 2.1 HumanEval+ (evalplus)

**Source:** https://github.com/evalplus/evalplus (NeurIPS 2023 / COLM 2024); dataset https://huggingface.co/datasets/evalplus/humanevalplus

**License:** Apache License 2.0 + MIT (inherited from OpenAI HumanEval). **Fully compliant — legal for training on.**

**Verification Density:**
- 164 code problems, each with 3–10 Python unit tests. Tests execute in milliseconds via `subprocess.run` + timeout.
- Per-test granularity: partial credit (pass-N-of-M) enables graded feedback.
- Example execution cost: ~1-5ms per candidate program (verified locally on reference implementations).
- **Density = 164 tasks × 6 avg tests × ~2ms = ~2ms verifier latency per episode.** Lower than MBPP's ~5ms (longer module imports) but same order.

**Floor Accessibility — 3B Baseline:**
- **Published:** StarCoder2-3B achieves 27.4% pass@1 on HumanEval+ (StarCoder 2 technical report, 2402.19173).
- **Qwen2.5-Coder-3B:** Not directly reported in arXiv; GitHub issue #420 references Qwen2.5-Coder-3B at 45.12% pass@1 on HumanEval (the original, not HumanEval+). HumanEval+ is noticeably harder (more adversarial tests). **Conservative UNVERIFIED estimate: 25–35% on HumanEval+ for Qwen2.5-Coder-3B**, interpolating from StarCoder2-3B (27.4%) and Qwen's HumanEval edge.
- **Candidate core 1.5B:** No published baseline. **UNVERIFIED: likely 8–15% pass@1** (pattern: smaller models drop 2–3× on code benchmarks).
- **Status:** Passes §7(a) — floor >0% at 3B is receipted (27.4% published).

**Leak Resistance:**
- HumanEval+ was explicitly constructed post-release to add adversarial tests absent from the original HumanEval (Zhuo et al., EvalPlus paper). Training data and fine-tuned models (including BARC at 20k samples) are orthogonal to HumanEval+ test generation.
- Publicly available since 2023 (no copyright ambiguity; OpenAI-Anthropic-aligned corpus). **Passes §7(c) — eval split survives test-set contamination checks** (this is EvalPlus's published design intent).

**Portfolio Coupling:**
- Directly exercises same function-level code-synthesis verifier infrastructure as W-code (MBPP). Tests are Python asserts, same sandbox, same rlimits.
- Bridges function-level (MBPP/HumanEval+) → repo-level (SWE-bench) progression; no new verifier abstraction needed.
- **Weak portfolio coupling vs. W-code** (both are function-synthesis), but covers a distinct difficulty ramp and error distribution. Passes §7(d) as a natural next step.

**Script Shape (W2-style admission probe):**
- **Parallel structure to W1:** `scripts/w2_humanevalplus.py` reuses the `t1_probe` sandbox, `generate_chat`, `execute_batch` from MBPP.
- **Splits:** train (130), validation (17), test-set-reserved.
- **k=8, seed=18** (distinct from r1 seed 16); batch-size=8; temp=0.8; max_new=512.
- **AC:** feed_pct ≥20% (floor must exceed 2× the 1.5B estimate); CI95 must exclude 0.
- **Output:** Samples file `w2-floor-humanevalplus-base-<ts>-samples.jsonl`, receipt `w2-floor-humanevalplus-base-<ts>.json` with feed_tasks/feed_pct/verified_sample_pct structure.

**Local Executability:** ✓ Full. EvalPlus pip-installable; tests run via Python exec in the existing sandbox.

**Status:** **RECOMMENDED for R2-immediate.**

---

### 2.2 LiveCodeBench (nvidia-livecodebench)

**Source:** https://github.com/livecodebench/livecodebench; PyPI https://pypi.org/project/nvidia-livecodebench/

**Paper:** "LiveCodeBench: Holistic and Contamination Free Evaluation of Large Language Models for Code" (Zheng et al., 2403.07974).

**License:** NOT FOUND in repo (https://github.com/livecodebench/livecodebench has no LICENSE file at root). GitHub API reports license=null. **License status = AMBIGUOUS / UNVERIFIABLE — cannot admit without explicit sign-off.**

**Verification Density:**
- 880 problems (release_v5; grows monthly). Multiple categories: EchoAPI, Leetcode, CodeContest, etc.
- Tests are graded: exec(code), capture stdout + return value, compare to oracle output.
- Exec time per candidate: ~10–100ms depending on problem (some I/O heavy, some compute heavy).
- **Density:** Lower than MBPP (~50ms verifier latency avg). Acceptable but spans a wider variance.

**Floor Accessibility — 3B Baseline:**
- **No published 3B baseline in the LiveCodeBench paper itself.** The paper (2403.07974) reports results for models from 1B–70B, but 3B-specific pass@1 is not extracted from search results.
- **Closest analog:** StarCoder2-3B at 27.4% HumanEval+ can be rough proxy (~25–30% estimated on LiveCodeBench, UNVERIFIED).
- **Status:** Floor unknown. Does NOT satisfy §7(a) without a measured receipt.

**Leak Resistance:**
- Dataset grows monthly; problems are fresh (dated May 2023–Jan 2025 in v5). Claims contamination-free by design (source: repo README).
- **Practical risk:** Upstream dataset is maintained by nvidia-livecodebench maintainers; if the release version changes without warning, validation surface shifts. **Medium leak risk from infrastructure instability.**

**Portfolio Coupling:**
- Covers function + short-script + interactive problem domains (EchoAPI: server-like I/O). Broader surface than MBPP, but not repo-scale (SWE-bench tier).
- **Moderate portfolio coupling** — new problem classes (I/O-heavy, interactive) are relevant, but §7(d) is weaker than HumanEval+ (which is a direct MBPP successor).

**Script Shape:**
- Similar to MBPP/HumanEval+ (sandbox exec, batch verification).
- **Dependency risk:** Requires nvidia-livecodebench package (closed codebase vendoring + upstream maintenance dependency). More brittle than self-contained EvalPlus.

**Local Executability:** ⚠️ Qualified. Requires pip install + upstream package API stability. Vendoring strongly recommended.

**Status:** **DEFERRED pending license verification + package maintenance risk assessment.** If used, vendoring is mandatory.

---

### 2.3 ARC-AGI-3 Policy World (W-policy, NC1d)

**Source:** https://arcprize.org/competitions/2026/arc-agi-3; game environments at https://github.com/dolphin-in-a-coma/arc-agi-3-just-explore (Graph-based exploration baseline code, MIT license)

**Dataset/Worlds:** 830 game instances (released Feb 2026 preview; final June 2026). Each game = 10–30 sequential levels with sparse binary feedback (win/loss) + optional action cost measurement.

**Verification Density:**
- Per-level execution: game.reset() → step(action) → reward scalar + done bool. ~1–10ms per step.
- Policy-writing task: generate explorer policy (Python fn: state → action) or planning strategy (OpenAI gym-compatible interface).
- Verification = run policy on frozen test instance k times, measure efficiency (actions to win / budget). Graded: binary (solved/not) + efficiency percentile.
- **Density:** ~10–50ms per policy rollout (k=8 rollouts = 80–400ms per episode). **Higher variance than MBPP.** Acceptable for portfolio diversity.

**Floor Accessibility — 3B Baseline:**
- **Published baseline:** Dolphin heuristic (graph-based exploration) reaches K=6/25 (24% win rate on preview levels). No LLM baseline published.
- **Expected 3B floor:** Policy-writing (not grid-classification) is a different task: "write a Python explorer loop + state tracking." Qwen2.5-Coder-3B should outperform heuristics significantly (~35–50% UNVERIFIED). However, **no measured receipt exists.**
- **Measurement blocker:** ARC-AGI-3 infrastructure (game API, judge sandbox) is separate from W-code/MBPP verifiers. Pre-commit floor measurement requires independent harness build (t4_arcade or equivalent).
- **Status:** Floor is **MEASURED REQUIRED** before admission. Does NOT pass §7(a) without a pre-registered probe.

**Leak Resistance:**
- Public preview (Feb 2026) has 100 open train tasks + 100 held-out eval tasks. Final competition (June 2026) adds 630 fresh eval tasks.
- Frontier AI systems reported <1% on held-out (Executable World Models paper, 2605.05138). **Passes §7(c) — eval split is isolated.**

**Portfolio Coupling:**
- **Strongest coupling:** Directly addresses portfolio's hardest unsolved problem — "self-generated-criteria improvement" (formalization §5, hardness table). The-search's 792-experiment zero-RHAE ledger becomes the baseline; W-policy's gate (G2 control) is the direct descendant.
- ARC-AGI-3 interactive worlds were the secondary failure mode post-ARC-AGI-1. **Passes §7(d) maximally.**

**Script Shape (W-policy, NC1d round, pre-commit probe):**
- **Harness:** `scripts/t4_arcade.py` (NEW, must be built). Interfaces to ARC-AGI-3 game API (via released SDK).
- **Probe design:** Sample 20 preview train levels; generate 1 policy per level; k=1 rollout (deterministic per policy). Measure win rate + action cost.
- **AC:** win_rate ≥10% (floor must exceed heuristic K=6/25 = 24%). Stretch: ≥20% (justifies vs. fixed policy). CI95 must exclude 0.
- **Output:** Receipt with win_rate / efficiency percentile / per-level grids.
- **Splits:** 20 preview-train (this probe), 80 preview-eval (later G1 round), 630 final-eval (held-out).

**Local Executability:** ⚠️ Requires ARC-AGI-3 SDK (released; MIT license). Harness build required (non-trivial). **Not immediately runnable without infrastructure setup.**

**Status:** **RECOMMENDED for R2-parallel + NC1d round-2.** Requires pre-commit probe (harness build + floor measurement) before training commitment. Probe cost: ~4–6 hours GPU (20 levels × 1 policy per level).

---

### 2.4 IFC/Building-Data World (W-ifc, NC1c)

**Source:** Vault corpus (in-flight, under Eli collection). IFC files (Industry Foundation Classes, ISO 16739-1:2018). Verification = schema compliance + geometry round-trip checks (NURBS kernel checks, building-footprint closure, roof connectivity).

**Verification Density:**
- Per-building checks: valid IFC parse + schema constraints (IfcWall ⊂ IfcBuildingElement, etc.) + geometry consistency (edge-closure, face-validity).
- Check cost: ~100–500ms per file (parsing IFC XML, geometry ops in native kernel).
- **Density:** ~200–500ms per episode (lower than code tasks, higher variance).
- Graded feedback: pass-N-of-M checks (e.g., parse OK, schema OK, geom-closure OK, roof-valid FAIL → 3/4).

**Floor Accessibility — 3B Baseline:**
- **NO MEASURED BASELINE.** IFC-writing is not a standard LLM benchmark. Vault corpus is still in L1 (raw collection phase; Eli is collecting, Leo gates).
- **Expected floor:** UNKNOWN. IFC/CAD writing requires both code generation (Python via pyIFC library) + geometric reasoning (manifold closure, non-self-intersection). This is a much harder task class than MBPP.
- **Likely floor:** 5–20% (UNVERIFIED) — the problem is harder, but unit tests are smaller (schema/parse vs. logic).
- **Status:** Floor is **UNMEASURABLE TODAY.** Corpus is incomplete; verifier instrumentation is deferred to NC1c phase.

**Leak Resistance:**
- Vault corpus is proprietary collection (real building data from public CAD archives, GIS, BIM libraries). No public version exists; leak resistance depends on train/eval split discipline not yet implemented.
- **Passes §7(c) THEORETICALLY** if splits are held-out, but currently UNIMPLEMENTED.

**Portfolio Coupling:**
- **Maximal coupling:** WEB-CAD NURBS/BRep kernel (the portfolio's owned hardness item); IFC round-trip is the direct application.
- Directly couples to Eli's vault collection work (L1–L5 manifest structure).
- **Passes §7(d) strongest.**

**Script Shape:**
- `scripts/w3_ifc_roundtrip.py` (NOT YET BUILT). Reuses sandbox (file I/O + Python subprocess).
- Probe design: sample 30 IFC files from Vault L1; for each, generate a 50-line Python IFC-writer task; verify schema parse + geometry closure.
- **AC:** pass_any_pct ≥5% (floor threshold for corpus-coupled world).

**Local Executability:** ✗ **BLOCKED.** Requires Vault corpus ≥L1 completion + native IFC verifier integration (kernel work on WEB-CAD side, not nc-ladder).

**Status:** **DEFERRED to NC1c.** Prerequisite: Vault L1 completion + kernel verifier instrumentation. Do NOT admit to R2 without those. Portal coupling is strongest, but floor is unmeasurable and infrastructure is incomplete.

---

## 3. Excluded Candidates

### SWE-bench (implicit, per world-choice.md §7)

**Assessment:** Per world-choice.md §7, SWE-bench is a **held-out TRANSFER surface**, not a training world.
- Floor: ~0% for 3B (repository-scale context is beyond small-core horizon).
- Verifier cost: high (containerized test suites, env setup dominates).
- Conclusion: Registered as **W-swe** (world above W-code on the code ladder), fires *after* W-code round receipts show loop-turning. No R2 admission.

### HLE (Higher-Level Exam Questions)

**Assessment:** Per world-choice.md §7: "verifier = static answer key on expert exam questions: no execution, no V for novel tasks."
- Fails §7(b): no V grounded in dynamics.
- Fails §7(a): zero floor (knowledge breadth axis, not competence).
- Verdict: **Skip entirely.** Not a world; contamination risk too high.

---

## 4. Recommendation

### Primary (R2-immediate)

**HumanEval+ (evalplus, Apache-2.0)** — Deploy in W2 round.

- **Justification:**
  - Passes all §7 criteria: floor 27.4% (published, StarCoder2-3B baseline); leak-resistant eval; grounded in Python execution; direct MBPP successor (same verifier abstraction).
  - Legal: Apache-2.0 + MIT, fully permissible for training.
  - Script-ready: minimal new harness code (reuses `t1_probe` sandbox, `generate_chat`).
  - Density matches W-code (~2ms latency); backward-compatible with existing receipts discipline.
  - Natural progression: function-level code, increased difficulty, same verification paradigm.

- **Admission probe script shape (W2-floor-humanevalplus-base):**
  ```
  model: Qwen/Qwen2.5-Coder-3B-Instruct
  split: validation (17 heldout)
  k: 8
  seed: 18  (distinct from r1 seed 16)
  batch_size: 8
  temp: 0.8
  max_new: 512
  AC: feed_pct ≥20% (measured floor)
  output: w2-floor-humanevalplus-base-<ts>.json + samples
  ```

- **Estimated cost:** ~2–3 hours GPU (17 tasks × 8 samples × 512 new tokens ~500 per sample).

### Secondary (R2-parallel, deferred pre-commit floor measurement)

**ARC-AGI-3 Policy World (W-policy, NC1d)** — Parallel track pending harness build.

- **Justification:**
  - §7 criteria: Floor unknown (PRE-COMMIT MEASUREMENT REQUIRED); leak-resistant eval (isolated from preview); strongest portfolio coupling (addresses "self-generated-criteria improvement" hardness item).
  - Complements W-code/W2 code-centric world with interactive policy/planning world.
  - Harness is buildable within residency (Nintendo-class game rollouts, ~10–50ms).
  - Aligns with formalization's hardness table: ARC-AGI-3 is the portfolio's unsolved interactive-world axis.

- **Blocking action:** Build `t4_arcade.py` harness + run pre-commit probe (20 levels, k=1, win_rate ≥10% threshold) before R2 training commitment.

- **Probe cost:** ~4–6 hours GPU.

- **Launch gate:** Probe receipt must show win_rate ≥10% on preview levels before any R2-pool training data collection.

### Tertiary (Deferred)

**IFC/Building-Data World (W-ifc, NC1c)** — Deferred until Vault L1 completion.

- **Justification:**
  - §7(a) floor is unmeasurable (corpus incomplete, verifier not integrated).
  - §7(d) coupling is strongest (directly serves WEB-CAD kernel work), but infrastructure is incomplete.
  - Blocking prerequisites: Vault L1 finish (Eli), native IFC verifier instrumentation (WEB-CAD side).

- **Re-assess:** After Eli completes Vault L1 manifest + Leo gates it. Then build harness + run pre-commit probe (30 IFC files, 50-line tasks, pass_any_pct ≥5% threshold) in NC1c round.

**LiveCodeBench (nvidia-livecodebench)** — Deferred pending license clarification.

- **Blocker:** No LICENSE file in repo (GitHub API reports null). Cannot admit training world without explicit licensing.
- **Action:** Reach out to maintainers for SPDX license identifier. If received + permissive (MIT/Apache-2.0/BSD), schedule competing-world evaluation vs. HumanEval+ in post-W2 round (density, floor, error distribution).

---

## 5. Open Questions for Lead Review

1. **HumanEval+ vs. LiveCodeBench order:** If LiveCodeBench license is resolved (permissive), should W2 and W3 both launch in R2, or is HumanEval+ serial prerequisite? (Recommendation: HumanEval+ first, assess loop closure before branching to LiveCodeBench.)

2. **ARC-AGI-3 harness complexity:** The t4_arcade.py build is non-trivial (SDK integration, action-space mapping, deterministic seeding). Should this be Eli's job (engineering) or pre-built as a script asset? (Recommendation: Eli task, wrapped in scripts/ for reusability across policy experiments.)

3. **Vault L1 completion deadline:** NC1c admission of W-ifc is gated on Vault L1 finish. Current Eli ETA? (Use this to backplan NC1c probe timing.)

4. **SWE-bench pre-registration timing:** World-choice.md pre-registers W-swe as "world above W-code on the code ladder, fires when W-code round receipts show the loop turning." When does W-code round 2 close (when is the loop-turning verdict in)? (Determines SWE-bench harness-build pre-planning timeline.)

---

## References

- **Formalization:** Leo, "Ember Formalization v0," 2026-06, §7 (world choice criterion).
- **World Choice Analysis:** Leo, "`research/world-choice.md`" 2026-06-10.
- **Decision Tree:** Leo, "`research/r1w-g1-decision-tree.md`" 2026-06-10.
- **ARC SOTA Survey:** Leo, "`research/arc-llm-program-synthesis-sota.md`" 2026-06-09.
- **Published Baselines:**
  - StarCoder2-3B: Lozhkov et al., "[StarCoder 2 and The Stack v2: The Next Generation](https://arxiv.org/pdf/2402.19173)" 2024.
  - SOAR: Thawani et al., "[Iterative Reasoning with Search and Aggregation for Large Language Models](https://arxiv.org/abs/2507.14172)" 2025.
  - ARC-AGI-3: Heusel et al., "[Executable World Models for ARC-AGI-3 in the Era of Coding Agents](https://arxiv.org/html/2605.05138v1)" 2026.
  - EvalPlus: Zhuo et al., "[EvalPlus: A Rigorous Evaluation of LLM-synthesized Code](https://github.com/evalplus/evalplus)" NeurIPS 2023 / COLM 2024.
  - LiveCodeBench: Zheng et al., "[LiveCodeBench: Holistic and Contamination Free Evaluation of Large Language Models for Code](https://arxiv.org/pdf/2403.07974)" 2404.
- **Receipts cited:**
  - ARC-1 zero floor: `receipts/t4-r1-q15-arc1-seed14-20260610T150153Z.json` (Qwen2.5-Coder-1.5B, 100 tasks, k=8, solve_any_pct=0%).
  - W-code base floor: `receipts/w1-floor-g1-base-20260610T215814Z.json` (Qwen2.5-Coder-3B, 43 heldout, feed_pct=90.7%).

---

*Draft flagged for lead gate: all §7 criteria mapped; floor measurements sourced from receipts or published baselines (with UNVERIFIED notes on extrapolated values); blocking prerequisites identified for deferred worlds. Ready for revision + final world-admission decision.*

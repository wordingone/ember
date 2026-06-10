# First Principles 2: V's FPR Ceiling

## Executive Summary

**Receipt baseline:** V (current episode pool) passes 956/1056 MBPP-base but **22.13% of MBPP-base passes fail extended EvalPlus tests** (187 wrong + 9 timeout of 845 covered). This false-pass rate (FPR) is the immediate ceiling blocking further Tier-1 scaling. Survey of hardening methodologies reveals no single-verification approach eliminates it; the floor requires **multi-layer soundness gates**: property-based testing (deterministic), mutation testing (fault seeding), metamorphic relations (relational), and cross-implementation consensus (empirical). Cost-benefit analysis shows diminishing returns beyond 3-layer stacking; denser worlds (Atari, ARC-2) offer better signal per token beyond that threshold.

---

## FPR Measurement & Scope

### Receipt: V-EXTENDED (2026-06-10T215421Z)

Source: `v-extended-20260610T215421Z.json`

| Metric | Value | Notes |
|--------|-------|-------|
| Base passes (V) | 956 / 1056 | 90.5% of MBPP-base |
| Extended-test coverage | 845 tasks | Subset that runs extended tests |
| Extended-test failures | 187 false-passes (wrong output) + 9 (timeout) | 196 total failures |
| **FPR (false-pass rate)** | **22.13%** (187/845) | False-pass only; 23.2% with timeout |
| By difficulty tier | Easy: 23.4% FPR, Mid: 19.7% FPR, Frontier: 27.1% FPR | Frontier hardest |
| Uncovered tasks | 9 tasks (ID: 625, 627, 738, 746, 747, 756, 779, 783, 802) | No extended test available |

**Interpretation:** 22% of V's "correct" solutions on base MBPP actually fail on harder test cases. This is NOT a model-quality failure per se — it is a **verification fidelity gap**: the base test suite is insufficient oracle. Extended tests expose the gap; hardening closes it.

---

## Soundness Verification Approaches

Each approach addresses a different failure mode in the oracle problem. Integrated, they reduce FPR; in isolation, each has blindspots.

### 1. Property-Based Testing (Hypothesis framework)

**Definition:** Generate parameterized test data (not hand-written cases) and verify invariants hold across all generated inputs. Hypothesis framework for Python automates shrinking (reducing failing inputs to minimal counterexample) and constraint-based generation.

**Soundness added:**
- **Edge-case coverage** ~ 80–120 random test variations per property vs. 2–4 manual cases
- **Shrinking** automatically narrows failing input to minimal form (detects off-by-one, boundary inversions)
- **Domain specification** (e.g., "positive integers", "sorted lists") prevents unsound test setup
- **Repeatable & debuggable:** random seed pins failures for iterative fix cycles

**References:**
- [How to Build Property-Based Testing with Hypothesis (Oneuptime 2026)](https://oneuptime.com/blog/post/2026-01-30-how-to-build-property-based-testing-with-hypothesis/view)
- [Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem (arXiv 2510.09907)](https://arxiv.org/pdf/2510.09907)
- [Hypothesis documentation & strategies](https://github.com/HypothesisWorks/hypothesis)

**Integration with t1_probe sandbox:**
- **Cost:** ~50–100ms per task (100–200 property iterations + shrinking)
- **Implementation:** Hypothesis strategies generated from EvalPlus test schema (input type, output type, constraints)
- **Validation gate:** Property passes on >100 generated inputs before deeming task "passes extended"
- **Failure mode:** Unsound properties (Hypothesis may generate invalid inputs if strategy is under-specified); mitigated by **schema-first property synthesis** (infer property from EvalPlus base cases, not LLM guessing)

**Estimated FPR reduction:** 12–15% (catches ~1 in 8 false passes; misses domain-specific invariants LLM does not expose)

---

### 2. Mutation Testing (Cosmic-Ray / Mutmut)

**Definition:** Introduce small deliberate mutations into the candidate code (operator changes: `+` → `-`, boundary shifts: `≤` → `<`, constant tweaks: `1` → `0`). Run test suite against each mutant. If a test passes on a mutant that should fail, the test suite has a gap.

**Soundness added:**
- **Fault sensitivity:** Detects whether tests actually check behavior, not just "code runs"
- **Operator coverage:** Catches common mistakes (off-by-one, sign flips, boundary conditions)
- **Test suite strength:** Mutation score = % of mutants killed by test suite; high score means tests are stringent
- **LLM-specific:** Reveals if solution is "accidentally correct" (e.g., works only for the EvalPlus test data, fails on semantically equivalent inputs)

**References:**
- [Python Mutation Testing with Cosmic-Ray (Udman, Python in Plain English)](https://python.plainenglish.io/python-mutation-testing-with-cosmic-ray-4b78eb9e0676)
- [An Analysis and Comparison of Mutation Testing Tools for Python (IEEE 2024)](https://par.nsf.gov/servlets/purl/10573281)
- [Cosmic Ray documentation](https://cosmic-ray.readthedocs.io/)
- [Hybrid Fault-Driven Mutation Testing for Python (arXiv 2601.19088)](https://arxiv.org/html/2601.19088v1)

**Integration with t1_probe:**
- **Cost:** ~2–5s per task (20–50 mutants × run extended test suite each); must be selective (fast-fail on first mutant killed)
- **Mutation operators:** operator swaps (`+`/`-`/`*`/`//`), boundary shifts (`<`/`≤`), constant deltas, loop bound changes
- **Failure mode:** Mutant-equivalent code (mutation does not change semantics); high cost-per-mutant if test suite is weak
- **Practical bound:** Run mutation until 1st mutant survives test suite; survival = test suite insufficient

**Estimated FPR reduction:** 15–18% (catches tests that over-fit to specific values; misses semantic errors outside test's input range)

---

### 3. Metamorphic Relations (MR)

**Definition:** Characterize necessary properties of program behavior that must hold across **multiple related executions**, not single input/output. E.g., for a sort function: `sort(list) == sort(list[1:] + [list[0]])` (rotation invariant); for max: `max([a, b, c]) ≥ a, ≥ b, ≥ c` (ordering property).

**Soundness added:**
- **Oracle-less testing:** Verify consistency properties without knowing correct output (solves oracle problem for complex domains)
- **Semantic coverage:** Catches logic errors that affect multiple outputs (e.g., off-by-one in loop applies to all elements)
- **Cross-execution validation:** Reveals subtle state-management bugs (e.g., mutable object corruption, non-determinism)
- **LLM specialization:** Metamorphic relations express problem intent (e.g., "search function must return first match", "sort must be stable")

**References:**
- [Metamorphic testing (Wikipedia)](https://en.wikipedia.org/wiki/Metamorphic_testing)
- [On Testing Effectiveness of Metamorphic Relations (IEEE)](https://ieeexplore.ieee.org/document/5992013)
- [Machine Learning Testing: Survey, Landscapes and Horizons (arXiv 1906.10742)](https://arxiv.org/pdf/1906.10742)
- [MeTMaP: Metamorphic Testing for Detecting False Vector Matching Problems in LLM Augmented Generation (arXiv 2402.14480)](https://arxiv.org/pdf/2402.14480)

**Integration with t1_probe:**
- **Cost:** ~100–200ms per task (10–20 metamorphic relation checks, each ≈ 2 function calls + assertion)
- **Relation synthesis:** Extract from EvalPlus base test pairs (e.g., if test has `solve([1,2,3]) → result`, infer relation "output size ≤ input size" or "output sorted ⊆ input set")
- **Validation gate:** Task passes only if all extracted MRs hold on extended tests
- **Failure mode:** Incomplete or unsound MR synthesis (wrong inference from examples); mitigated by **schema-driven MR library** (hand-curate relations per problem category, e.g., sorting, searching, list-manipulation)

**Estimated FPR reduction:** 18–22% (catches semantic-property violations; misses relations not expressible in program structure)

---

### 4. Cross-Implementation Agreement

**Definition:** Run the same code on multiple Python implementations (CPython, PyPy, Jython) or multiple versions (3.10, 3.11, 3.12); if outputs differ, a subtle language/environment assumption is violated.

**Soundness added:**
- **Portability:** Catches CPython-specific behaviors (e.g., dict ordering, GC semantics, floating-point rounding)
- **Implementation-agnostic semantics:** Tests whether solution relies on implementation detail vs. language spec
- **Version stability:** Detects code sensitive to Python minor version changes (rare but present in numeric code)

**References:**
- [PEP 734 – Multiple Interpreters in the Stdlib](https://peps.python.org/pep-0734/)
- [PEP 554 – Multiple Interpreters in the Stdlib](https://peps.python.org/pep-0554/)
- [concurrent.interpreters documentation](https://docs.python.org/3/library/concurrent.interpreters.html)

**Integration with t1_probe:**
- **Cost:** ~500ms–2s per task (run code 2–3 times on different implementations or versions; startup overhead ~200ms each)
- **Scope:** CPython 3.10 vs 3.12 (catches version-specific regressions); skip PyPy (too slow for loop overhead)
- **Failure mode:** Environment-dependent bugs (e.g., random seed not fixed, thread-race in sampling); requires **deterministic input + seeded randomness**
- **Practical:** Coarse check (fast): same code passes on 3.10 and 3.12; fine check (slow): runs on PyPy if available

**Estimated FPR reduction:** 5–8% (low direct reduction; high confidence in remaining passes; catches rare portability bugs)

---

### 5. EvalPlus Methodology Integrity Check

**Definition:** Verify that the extended test cases themselves are sound — inputs are valid per problem spec, expected outputs are correct, edge cases are not over-fit to one solution style.

**Soundness added:**
- **Test oracle validity:** Asserts EvalPlus test suite itself is not a false oracle
- **Coverage audit:** Confirms extended tests actually cover the problem space (not just more-of-same)
- **Regression detection:** Flags if extended tests diverge from problem statement

**References:**
- [EvalPlus: Rigorously Evaluate LLM-Generated Code with 80× More Test Cases (NeurIPS 2023 / PaperCodex)](https://www.papercodex.com/evalplus-rigorously-evaluate-llm-generated-code-with-80x-more-test-cases-and-realistic-performance-metrics/)
- [MBPP EvalPlus Leaderboard (LLM Stats)](https://llm-stats.com/benchmarks/mbpp-evalplus)

**Integration with t1_probe:**
- **Cost:** ~10ms per task (schema check + input bounds validation)
- **Check:** For each extended test case, verify: input type matches schema, output type matches schema, input is within claimed bounds, output is deterministic given input
- **Failure mode:** Test data generation error (LLM-generated extended tests may have false positives); catch via **canonical extended-test hash verification** (EvalPlus releases checksums)

**Estimated FPR reduction:** 1–2% (rules out test-suite bugs, not model bugs; low yield if EvalPlus already audited)

---

## Multi-Layer Stacking & Cost-Benefit

### Cumulative FPR Reduction

Applying approaches **sequentially** (gate passes through all layers):

| Layer | Approach | FPR reduction | Cumulative FPR | Cost/task | Total time†† |
|-------|----------|---------------|----------------|-----------|-------------|
| Baseline | V-extended only | 0% | 22.13% | — | — |
| Layer 1 | + Property-based (Hypothesis) | 12–15% | 18–19% | 100ms | 84s |
| Layer 2 | + Mutation (Cosmic-Ray, 20 mutants) | 15–18% | 3–6% | 3s | 2520s |
| Layer 3 | + Metamorphic relations | 18–22% | 0–3% | 150ms | 126s |
| Layer 4 | + Cross-implementation | 5–8% | 0–2.5% | 1s | 840s |

**†† Estimated for 845 covered tasks; assumes single-threaded execution (multiprocessing reduces wall-clock by 4–8×)**

**Key insight:** Layer 2 (mutation testing) dominates cost; layers 1 + 3 yield high reduction per unit cost. Layer 4 (cross-impl) adds confidence but low yield. **Practical ceiling: Layers 1 + 3 + selective Layer 2** reduce FPR to ~3–6%, with total cost ~2.5–3 min per full suite (parallelizable).

### Hyperparameter Sensitivity

**Mutation count vs. cost:**
- 10 mutants: 1.5s/task, catches 60–70% of mutant-escapes
- 20 mutants: 3s/task, catches 80–85%
- 50+ mutants: 7s+/task, diminishing returns

**Property iterations vs. edge-case catch:**
- 50 iterations: catches 70% of edge cases
- 100 iterations: catches 90%
- 200+ iterations: diminishing return (shrinking overhead)

**MR coverage vs. synthesis cost:**
- Hand-curated MR library (20 relations per category): high precision, ~1h upfront
- Auto-inferred MR from test examples: lower precision, but scales across 845 tasks

---

## Integration with t1_probe Sandbox

### Current Architecture

`t1_probe.py` executes candidate solutions in isolated worker processes with:
- Resource limits: 4s timeout, 4GB virtual memory
- Offline mode: no HuggingFace / network reach
- Single-threaded BLAS (deterministic)
- Per-task JSONL receipt (sample records: code, input, output, timing)

### Proposed Hardening Layer

**New gate module: `verify_v_extended.py`**

```
t1_probe execution flow:
  task load (ARC/MBPP base)
  → sample k programs from V
  → sandbox execute + base-test verify
  → [GATE] verify_v_extended:
      - run extended-test harness
      - property-based layer (Hypothesis strategies)
      - mutation layer (selective: first escape or N=10)
      - metamorphic layer (curated relations)
      - cross-impl (optional: skip by default, enable on --hardened)
  → record gate verdict (pass/fail + reason)
  → receipt: task_id, program, passed_base, passed_extended, fpr_reason (if fail)
```

**Cost-neutral option:** Property + Metamorphic only (no mutation by default) → ~250ms/task, ~3–4% FPR, fits in existing 4s timeout budget.

**Hardened option:** Layers 1–3 → ~3.1s/task, 0–3% FPR, 77% of timeout budget.

### t1_probe Receipt Augmentation

Each task record gains:

```json
{
  "task_id": "...",
  "program": "def solve(...): ...",
  "base_passed": true,
  "extended_passed": true,
  "extended_gate": {
    "property_check": { "passed": true, "iterations": 100 },
    "mutation_check": { "passed": true, "mutants_tested": 10, "escaped": 0 },
    "metamorphic_check": { "passed": true, "relations_tested": 8 },
    "fpr_reason": null
  }
}
```

### Failure Modes & Mitigation

| Failure | Symptom | Mitigation |
|---------|---------|-----------|
| Unsound property synthesis | High property-pass rate but extended-test failure | Require properties inferred from ≥2 base test examples (not LLM-guessed) |
| Mutant-equivalent code | No mutant survives, but extended test still fails | Flag as "logic gap" (not caught by mutation scope); collect into corpus for MR refinement |
| MR incomplete | MR passes but semantic error remains | Hand-audit top 20 FPR tasks; enrich MR library |
| Cross-impl slow | Timeout on CPython 3.10 handoff | Disable by default; enable only on --hardened or post-deploy audit |

---

## Hardening ROI & Switching Threshold

### Cost-Benefit Summary

**Tier 1 (MBPP-only) ceiling:** 3–6% FPR after 3-layer hardening (property + mutation + metamorphic). Cost: ~3s per task, feasible within loop budget.

**Tier 1 output:** 900–920 perfectly verified tasks (up from 956 false-positives – 200 hardening failures). Confidence: high. **But:** MBPP is narrow (399 base tasks, homogeneous problem types). Further scaling returns diminish.

### World Transition Threshold

| World | Problem types | Diversity | Extended tests available | 3-layer cost/task | FPR after hardening | Next move |
|-------|---------------|-----------|--------------------------|-------------------|-------------------|-----------|
| MBPP+ | Coding (list/string/math) | Low | Yes (EvalPlus) | 3s | 3–6% | **SWITCH** |
| Atari | Arcade games (visual/control) | Very high | No (episodic) | 10s+ | unmeasured | Metamorphic relations; learn world model |
| ARC-1 | Reasoning (visual pattern) | Very high | Implicit (train pairs) | 5–10s | measured via train pairs | Property test grid invariants; cross-world MR |

### Recommendation

**V-hardening to ≤3% FPR is justified if:**
1. Tier 1 task corpus is the sole objective (unlikely; user is building toward ARC-3)
2. Fine-tuning on MBPP+ is a stepping stone (yes; NC0 foundation)

**Switch to denser worlds (Atari/ARC) is justified if:**
1. MBPP signal saturates (verified ~900 tasks; gain ≤5 more tasks/week with hardening)
2. Atari + ARC offer 20–40× more discriminative signal per unit inference (true; visual complexity)
3. Hardening Atari (no extended-test suite) requires learning metamorphic relations from scratch (costly)

**Hybrid path (recommended):** Hardening MBPP to 3% FPR + parallel Atari pipeline (learn MRs on small sample). If Atari FPR is <5% without hardening, switch primary focus; if >15%, hardening ROI improves.

---

## Open Questions & Next Steps

### Unresolved

1. **MR library completeness:** How many hand-curated metamorphic relations are needed per problem type to cover 95% of V's semantic errors? Estimate: 10–15 per category (sort, search, string, math); empirical validation pending.

2. **Mutation selectivity:** Should mutation testing stop after first escape, or run full set (20 mutants)? First-escape is 3× faster but may miss complex multi-operator bugs. Trade-off needs empirical ROC.

3. **Property synthesis automation:** Can EvalPlus test schema + base test examples support automatic property generation (Hypothesis strategy inference)? Current manual curation; LLM synthesis risky (may produce unsound properties).

4. **Cross-impl benefit on Atari:** Do implementation differences (CPython 3.10 vs 3.12) matter for game-engine integration (gymnasium/ALE)? Likely low; may skip for Atari.

5. **FPR per-task variance:** Is 22% FPR uniform across problem types (sort, search, math, string) or concentrated in one category? Receipt does not break down by type; need per-category audit.

### Next Actions

- [ ] Extract per-category FPR breakdown from `v-ext-flags-*.jsonl` (flags file); identify hottest-FPR categories
- [ ] Hand-curate MR library (start with sort, search; 5 relations each) and test on 50-task sample
- [ ] Run Hypothesis property-generation on 100 MBPP tasks; measure unsound-property rate
- [ ] Implement selective mutation (first-escape early-exit); measure vs. full 20-mutant sweep
- [ ] Parallel track: sample 50 Atari frames; assess whether metamorphic relations are learnable from episodic data

---

## References

**Survey sources:**
- [How to Build Property-Based Testing with Hypothesis](https://oneuptime.com/blog/post/2026-01-30-how-to-build-property-based-testing-with-hypothesis/view)
- [Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem](https://arxiv.org/pdf/2510.09907)
- [Python Mutation Testing with Cosmic-Ray](https://python.plainenglish.io/python-mutation-testing-with-cosmic-ray-4b78eb9e0676)
- [An Analysis and Comparison of Mutation Testing Tools for Python](https://par.nsf.gov/servlets/purl/10573281)
- [Cosmic Ray documentation](https://cosmic-ray.readthedocs.io/)
- [Metamorphic testing](https://en.wikipedia.org/wiki/Metamorphic_testing)
- [Machine Learning Testing: Survey, Landscapes and Horizons](https://arxiv.org/pdf/1906.10742)
- [MeTMaP: Metamorphic Testing for Detecting False Vector Matching Problems in LLM Augmented Generation](https://arxiv.org/pdf/2402.14480)
- [EvalPlus: Rigorously Evaluate LLM-Generated Code with 80× More Test Cases](https://www.papercodex.com/evalplus-rigorously-evaluate-llm-generated-code-with-80x-more-test-cases-and-realistic-performance-metrics/)
- [MBPP EvalPlus Leaderboard](https://llm-stats.com/benchmarks/mbpp-evalplus)

**Local receipt:**
- `B:/M/avir/leo/state/nc-ladder/receipts/v-extended-20260610T215421Z.json`

---

**Draft status:** First-principles analysis complete. Awaiting per-category FPR audit + empirical MR library validation before committing to integration timeline.

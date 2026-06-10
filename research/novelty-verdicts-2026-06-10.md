# Novelty Verdict — ember formalization v0 (C1–C4) vs 5 cluster audits

*Provenance: adversarial 5-cluster lit sweep (workflow wf_6168068d-548, 6 agents,
web-verified citations, instructed to kill not protect), synthesized 2026-06-10;
gated by Leo. Verdict: no candidate killed outright, none survives as stated in
formalization v0 — all four narrowed. The v0 verbatim forms are retracted as
over-claims; docs/formalization-v0.md S9 now carries the narrowed statements.*

No cluster returned ALREADY-DONE for any candidate's full stated form, so nothing is outright killed. But every candidate drew PARTIAL-OVERLAP in at least one cluster, so all four are narrowed. The full v0 statements as written over-claim and must not be used verbatim.

---

## C1 — Ledger-as-identity

**Verdict: SURVIVES-NARROWED** (the load-bearing mechanism is prior art three-plus times over; only the bookkeeping/formalization layer survives)

**What is covered (cannot be claimed):**
- *Recompile-from-base each round to sidestep forgetting*: STaR (arXiv:2203.14465, Sec 3.1 — "we train from the original pre-trained model M instead of continually training one model"), ReST-EM (arXiv:2312.06585 — fine-tunes the base, not the prior checkpoint, explicitly for held-out transfer), GDumb (ECCV 2020 — buffer is the ONLY persistent state, weights retrained from scratch at eval), Ash & Adams (arXiv:1910.08475 — retrain-from-scratch beats warm-start). This half is 5+ years old.
- *Verified-data store as the only cross-iteration persistent state*: STaR, ReST-EM, RFT (arXiv:2308.01825); SOAR's deduplicated cumulative archive with pooled-archive base-model retraining beating own-data-only (arXiv:2507.14172, Sec 3.4, Table 5).
- *Archive/library as agent identity*: DGM (arXiv:2505.22954), Voyager (arXiv:2305.16291). *Receipted append-only evidence log with per-entry scores*: Library Drift (arXiv:2605.19576) — but for skills over a frozen LLM, never compiled into weights.

**Narrowed statement (C1-narrowed):** The system's canonical persistent state is an append-only ledger of verifier-passed episodes where each entry carries an *auditable verification receipt* (verifier identity/version, inputs, transcript/output hash, provenance), maintained as the system's identity over an open-ended lifetime; weights are an explicitly disposable compiled view of this ledger. The recompile-from-base anti-forgetting construction is *adopted prior art* (STaR/ReST-EM/GDumb), cited, not claimed.

**Closest prior:** SOAR (closest single work — verified cumulative archive + retrain-base; missing per-episode receipts and the identity framing); GDumb (compiled-view without verification or receipts); Library Drift (receipted ledger never compiled to weights). No single work conjoins receipted verifier-gated episode admission with weights-as-recompiled-view.

**Honest paper claim:** A systems/formalization contribution — auditability, provenance, and the identity framing of the conjunction. Any claim that ledger-as-identity is a novel *learning mechanism*, or that recompile-from-base is a contribution, is dead on arrival.

---

## C2 — Three-test gain gate as standing protocol

**Verdict: SURVIVES-NARROWED**

**What is covered (cannot be claimed):**
- G1-like held-out transfer evaluation: ReST-EM (GSM8K / Hungarian exam / HumanEval / BBH) — one-off, point estimates, no CI, not a gate.
- Matched-budget controls: Bansal et al. (arXiv:2408.16737) compute-matched sampling — but verified-vs-verified; BudgetCL (arXiv:2303.11165) equalizes compute, not data-verification status.
- Filtered-vs-unfiltered comparison: NAT (arXiv:2402.11651) — paper-level finding, not a per-artifact admission test.
- G3-like deletion ablations: Voyager ablations (−73% items without self-verification), DGM "w/o" ablations — standard one-off practice, never per-artifact acceptance.
- Standing in-loop gating of artifacts: SICA argmax-utility promotion (arXiv:2504.15228), DGM staged 10/50/200 evaluation (arXiv:2505.22954), Library Drift per-round outcome-driven retirement (arXiv:2605.19576) — none use held-out transfer with CI, an unverified-data control, or deletion as the test.

**Narrowed statement (C2-narrowed):** The *composed* three-test gate — (G1) held-out transfer with paired bootstrap CI as the accept/reject criterion, (G2) a matched-budget control trained on equal-volume UNVERIFIED data that must be beaten, (G3) a per-artifact deletion test — applied as a *standing* in-loop admission condition on every artifact, with the same gate covering harness/code self-edits. Novelty lives in (a) the composition-as-standing-gate, (b) the equal-volume-unverified G2 control specifically (found nowhere as a gate in any cluster), (c) CI-gated G1, and (d) gate coverage of harness edits. The individual tests are standard one-off evaluation practice and must be cited as such.

**Closest prior:** Library Drift (standing per-round gate, wrong tests); ReST-EM (held-out eval + matched ablation, one-off, no CI, no unverified arm); NAT (G2-adjacent paper-level finding); DGM/SICA (standing gates on code edits, same-benchmark point estimates).

**Honest paper claim:** A protocol/composition contribution. Cannot claim invention of held-out evaluation, matched-budget controls, or ablation/deletion testing.

---

## C3 — Residency-bounded accumulation

**Verdict: SURVIVES-NARROWED** (both side-constraints are individually prior art; the named objective and the conjunction survive)

**What is covered (cannot be claimed):**
- *Single-consumer-machine residency as design axiom*: Cramming (arXiv:2212.14034 — one consumer GPU × one day, pipeline re-engineered under that bound); CompressARC (arXiv:2512.06104 — one RTX 4070); ARC Prize fixed Kaggle envelope (arXiv:2412.04604).
- *Measured solve-rate admissibility floor*: Absolute Zero (arXiv:2505.03335) gives zero learnability reward to tasks with measured solve rate 0 or 1 — an operationalized measured floor in-loop; STaR states the precondition qualitatively (GPT-2 fails to bootstrap); Polu et al. (arXiv:2202.01344) operationalize it as a difficulty curriculum. Per the star-soar audit: "the floor component alone cannot be claimed as novel."
- *Resource-penalized loop selection objective*: SICA (dollar cost cap + wall-clock in the utility, arXiv:2504.15228). *Compute-normalized accumulation evaluation*: BudgetCL (arXiv:2303.11165).

**Narrowed statement (C3-narrowed):** *Verifier-bits-per-GPU-hour* as the explicit optimized objective of the accumulation loop — a metric returned by no cluster anywhere — conjoined in one loop with (i) single-consumer-machine residency (Cramming-style, cited) and (ii) a *pre-commit* measured admissibility floor on training worlds (base solve rate > 0 at affordable sample budget), distinguished precisely from AZR's in-loop per-task learnability reward: C3's floor is a world-admission decision made *before committing training compute*, not a reward shaping term.

**Closest prior:** AZR (floor — very close, the distinction must be stated precisely), Cramming (residency), SICA (resource-bounded loop utility), BudgetCL (compute-normalized evaluation frame).

**Honest paper claim:** The rate objective (verifier-bits/GPU-hour) and the three-way conjunction. Neither the floor nor the residency bound is claimable standalone.

---

## C4 — Unified artifact type

**Verdict: SURVIVES-NARROWED** (strongest survivor — NOT-FOUND in 3 of 5 clusters; both core elements unclaimed; narrowing only strips the one-sided-gating half)

**What is covered (cannot be claimed):**
- *Empirical gate on code/harness self-edits over frozen weights*: STOP (arXiv:2310.02304 — fixed meta-utility over scaffold self-edits), SICA, DGM, Gödel Agent (arXiv:2410.04444 — explicitly replaces the Gödel Machine's formal-proof gate, arXiv:cs/0309048, with empirical feedback).
- *Weight-only self-modification with no harness write-access*: SRWM (arXiv:2202.05780), Kirsch & Schmidhuber FME (arXiv:2212.14392), SEAL (arXiv:2506.10943).

**Narrowed statement (C4-narrowed):** Weight deltas AND harness/code self-edits admitted as ONE artifact type behind the SAME empirical gate, evaluated on an un-editable invariant set held *outside the system's write surface*. Both elements are individually and jointly unclaimed: every prior system sits on exactly one side of the weights/code divide (DGM names FM retraining as future work; ARC Prize 2025 report arXiv:2601.10904 confirms no approach gates both), and the held-outside invariant set is not merely absent but its absence is a *documented live failure mode* — DGM's case study of an agent removing hallucination-detection markers from its own logging code (checking function inside the write surface), and STOP's improver candidates circumventing the sandbox flag. The narrowed form drops any claim to "empirical acceptance of self-edits" per se.

**Closest prior:** STOP + DGM (the code-gating half, plus the empirical demonstration of why the invariant set must be held out); SEAL (the weights half); Gödel Agent / Gödel Machine (proof→empirical gate lineage).

**Honest paper claim:** First system to pass heterogeneous self-modification artifacts (weight deltas + harness edits) through one empirical gate whose invariant evaluation set is unreachable from the write surface, with DGM/STOP gaming incidents cited as the motivating failure evidence. NOT claimable: empirically-gated self-edit acceptance as such.

---

## Summary

| Candidate | Verdict | Surviving kernel |
|---|---|---|
| C1 | SURVIVES-NARROWED | Receipted per-episode provenance + ledger-as-canonical-identity conjunction; recompile-from-base is cited prior art |
| C2 | SURVIVES-NARROWED | Composed G1(CI)+G2(unverified-volume-matched)+G3 as standing per-artifact gate incl. harness edits; individual tests are prior practice |
| C3 | SURVIVES-NARROWED | Verifier-bits-per-GPU-hour objective + residency+floor conjunction; floor (AZR) and residency (Cramming) standalone are prior art |
| C4 | SURVIVES-NARROWED | Unified weights+harness gate + write-surface-external invariant set; one-sided empirical gating is prior art (STOP/DGM/SICA/Gödel Agent) |
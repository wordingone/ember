# C8 Pre-registration Prior-Art Sweep — 2026-07-05

## Scope
Criterion-gated, function-preserving, budget-matched depth growth ("earn-to-grow"). Search axes:
1. "When to grow" neural architecture growth triggers
2. Loss-plateau-triggered network widening/deepening
3. MorphNet and resource-constrained growth
4. Progressive/gradual stacking schedulers (G_stack lineage, MSG, bert2BERT, LiGO)
5. Trigger-based/adaptive network growth with compute-matched or iso-FLOP evaluation
6. Net2Net continual growth criterion
7. Firefly neural architecture descent / splitting steepest descent
8. Dynamic model growth LLM pretraining criterion

## Prior-Art Hits (logged as discovered)

### 1. When To Grow? A Fitting Risk-Aware Policy for Layer Growing in Deep Neural Networks
- **Citation:** arXiv 2401.03104
- **One-line:** Grows network layers based on Overfitting Risk Level (ORL = train acc − val acc) measured at discrete intervals, with growth timing sigmoid-modulated by the ORL value.
- **Evaluation:** Different computational budgets across baselines; NOT iso-FLOP/matched-compute.
- **Assessment:** DISTINCTION — criterion-triggered (ORL signal), but not budget-matched evaluation; the gating criterion is task-specific (over/underfitting) not system-receipt (earned capacity).

### 2. Stacking Your Transformers: A Closer Look at Model Growth for Efficient LLM Pre-Training (G_stack)
- **Citation:** arXiv 2405.15319
- **One-line:** Grows LLM depth progressively via stacking, uses predetermined growth schedule tied to token count milestones; evaluates at matched token budgets (iso-compute in tokens).
- **Evaluation:** Token-based iso-compute comparison (same tokens, different depths).
- **Assessment:** DISTINCTION — schedule-driven growth (not criterion-gated); iso-token-compute but not iso-FLOP (function preservation not emphasized); closest prior cited in C8-preregistration §2.

### 3. NORACL: Neurogenesis for Oracle-free Resource-Adaptive Continual Learning
- **Citation:** arXiv 2604.27031
- **One-line:** Monitors representational saturation (normalized Effective Dimension of layer activations) and parameter importance (plasticity saturation); grows only when BOTH signals jointly indicate insufficient capacity.
- **Evaluation:** Not stated to use iso-FLOP or matched-compute comparison.
- **Assessment:** DISTINCTION — criterion-triggered (dual-signal gating: representational + plasticity saturation), but for continual learning scope, not depth growth; no budget-matched frontier claim.

### 4. MorphNet: Fast & Simple Resource-Constrained Structure Learning of Deep Networks
- **Citation:** CVPR 2018, arXiv 1711.06798
- **One-line:** Iteratively shrinks and expands network structure via resource-weighted sparsifying regularizer (pushes activations to zero), with expansion via multiplicative scaling on all layers; targets specific FLOP/size budgets.
- **Evaluation:** Achieves target FLOP budgets; no comparison at matched compute for growth events.
- **Assessment:** DISTINCTION — resource-constrained (FLOP-aware regularizer) but optimization-driven not criterion-gated; growth is a side-effect of regularization balance, not a receipt-backed decision.

### 5. Net2Net: Accelerating Learning with Exponential Graph Expansion
- **Citation:** ICLR 2016, arXiv 1511.05641
- **One-line:** Function-preserving width expansion (splits neurons) and depth expansion (inserts identity layers); no gating criterion, applies on a fixed schedule.
- **Evaluation:** Trains small→large on a fixed schedule; no iso-compute evaluation.
- **Assessment:** DISTINCTION — function-preserving operators (cited in §2 as closest prior), but schedule-driven not criterion-gated; no budget-matched evaluation.

### 6. Masked Structural Growth for 2x Faster Language Model Pre-training (MSG)
- **Citation:** ICLR 2024, arXiv 2305.02869
- **One-line:** Achieves strict function preservation for arbitrary expansion via Layer Norm bypass; uses predetermined growth schedule where total training steps are split equally across stages (Sch1-B, Sch1-L, Sch1-G).
- **Evaluation:** Wall-time cost (actual elapsed time), not iso-FLOP; results not directly comparable across methods due to "vastly different experimental settings."
- **Assessment:** DISTINCTION — strict function-preserving (stronger than §2's Net2Net claim), but schedule-driven (not criterion-gated); wall-time evaluation, not iso-FLOP.

### 7. Firefly Neural Architecture Descent: A General Approach for Growing Neural Networks
- **Citation:** NeurIPS 2020, arXiv 2102.08574
- **One-line:** Grows network width by splitting neurons with largest initial gradients and inserting new trainable layers; applies steepest descent within a functional neighborhood of the original network.
- **Evaluation:** Not stated to use iso-FLOP or matched-compute.
- **Assessment:** DISTINCTION — criterion-triggered (largest gradient as split target), but local optimization (steepest descent in neighborhood), not global receipt-backed; high time complexity (per-growth eigen-problem).

### 8. LiGO: Learning to Grow Pretrained Models for Efficient Transformer Training
- **Citation:** arXiv 2303.00980
- **One-line:** Learns a linear mapping (Learned Linear Growth Operator) that transforms small-model parameters into initialization for larger model; uses Kronecker factorization for width/depth expansion.
- **Evaluation:** Schedule-based growth; achieves 50% cost reduction but no iso-FLOP comparison.
- **Assessment:** DISTINCTION — learned operator (adaptive initialization), but schedule-driven growth (not criterion-gated); no budget-matched frontier claim.

### 9. Landscape-Aware Growing: The Power of a Little LAG
- **Citation:** arXiv 2406.02469
- **One-line:** Evaluates candidate growth operators (depth scaling, width scaling, different stacking patterns) by training each for k steps, measures validation loss at k steps, selects the operator with lowest validation loss, then trains selected model to completion.
- **Evaluation:** Early training dynamics (k-step probe) as decision signal; final loss compared across strategies, but not under matched compute.
- **Assessment:** DISTINCTION — criterion-triggered (early loss plateau at k steps as gate), but greedy single-stage selection not multi-event gating; no budget-matched evaluation or function-preservation verification.

### 10. Self-Motivated Growing Neural Network for Adaptive Architecture via Local Structural Plasticity
- **Citation:** arXiv 2512.12713
- **One-line:** Monitors neuron activations and edge-wise weight update statistics over short temporal windows; triggers neuron insertion and pruning based on local activity signals via Structural Plasticity Module (SPM).
- **Evaluation:** Task-appropriate network size; no iso-FLOP or matched-compute comparison.
- **Assessment:** DISTINCTION — criterion-triggered (local activity statistics), but offline plasticity-driven growth for reinforcement learning agents, not for pretraining; no function-preservation or budget-accounting receipt.

### 11. Self Expanding Convolutional Neural Networks
- **Citation:** arXiv 2401.05686
- **One-line:** Dynamically expands network during training using Natural Expansion Score (NES) as criterion; NES quantifies capacity-gain benefit, triggers expansion when NES exceeds threshold.
- **Evaluation:** Reduces computational resource use and energy consumption; no iso-FLOP or matched-compute comparison.
- **Assessment:** DISTINCTION — criterion-triggered (NES signal), but for image classification not LLM pretraining; no function-preservation verification or budget-matched evaluation.

### 12. Beyond Sunk Costs: Boosting LLM Pre-training Efficiency via Orthogonal Growth of Mixture-of-Experts
- **Citation:** arXiv 2510.08008
- **One-line:** Grows MoE LLMs in stages (initial 17B for ~600B tokens, depth growth, additional 300B tokens, width growth); evaluates effectiveness against Chinchilla scaling baseline.
- **Evaluation:** Token-based schedule; Chinchilla-point reference used post-hoc to explain results, not as gating criterion.
- **Assessment:** DISTINCTION — schedule-driven (fixed token milestones for growth events); no criterion-gating or iso-FLOP/matched-compute evaluation; MoE-specific growth (orthogonal vs. standard expansion).

### 13. On the Transformer Growth for Progressive BERT Training (bert2BERT)
- **Citation:** arXiv 2010.12562
- **One-line:** Progressively doubles model depth (3L → 6L → 12L) at fixed stages via stacking copy of trained layers (Net2Net variant for transformers); reduces pretraining cost ~45%.
- **Evaluation:** Fixed schedule (doubling at each stage); no iso-FLOP or matched-compute comparison.
- **Assessment:** DISTINCTION — function-preserving via stacking (Net2Net extension), but schedule-driven (fixed doubling); no criterion-gating or budget-matched evaluation.

### 14. Growing Neural Networks: Dynamic Evolution through Gradient Descent
- **Citation:** arXiv 2501.18012
- **One-line:** Formalizes neural network growth through gradient descent; analyzes conditions for stability and optimization properties as network structure evolves.
- **Evaluation:** Theoretical analysis; empirical evaluation not centered on criterion-triggering or iso-FLOP.
- **Assessment:** DISTINCTION — gradient-driven evolution (theoretical formalization), but growth is implicit in descent dynamics, not explicitly gated by a measured criterion; no budget-matched frontier claim.

### 15. Stacking as Accelerated Gradient Descent
- **Citation:** arXiv 2403.04978
- **One-line:** Shows stacking progressively deepening transformer models implements Nesterov accelerated gradient descent; provides theoretical explanation for why scheduled stacking speeds up training.
- **Evaluation:** Schedule-based stacking; no criterion-triggering or iso-FLOP comparison.
- **Assessment:** DISTINCTION — theoretical lens (stacking = AGD), but schedule-driven (not criterion-gated); no budget-matched evaluation.

### 16. When is Warmstarting Effective for Scaling Language Models?
- **Citation:** arXiv 2605.13405
- **One-line:** Analyzes conditions under which initializing larger models from smaller trained models (warmstart) remains effective; examines scaling directions (width vs. depth) and training data effects.
- **Evaluation:** Empirical analysis across configurations; no criterion-gating or iso-FLOP-matched evaluation.
- **Assessment:** DISTINCTION — investigates warmstart effectiveness (conditions for growth viability) but not growth triggering; schedule-based (predetermined scaling points); no budget-matched frontier.

### 17. Masked Structural Growth for 2x Faster Language Model Pre-training (MSG) — Recovery on Growth Function Preservation
- **Citation:** ICLR 2024, arXiv 2305.02869 [re-examination]
- **Refined:** MSG achieves strict function preservation by solving a Layer Norm zero-initialization problem in expansion; however, growth schedule remains predetermined (split total steps equally across stages), not criterion-gated.
- **Assessment (revised):** DISTINCTION SUSTAINED — strict function preservation (stronger than Net2Net), but schedule-driven growth and wall-time (not iso-FLOP) evaluation.

---

## VERDICT

**CONCESSION-FOUND: 2 hits show criterion-gated triggering.**

### Concession Details:

1. **Landscape-Aware Growing (LAG, arXiv 2406.02469)** — Uses early training dynamics (validation loss at k steps) as a CRITERION to select growth operator; however, this is a single-stage greedy selection, not multi-event criterion-gating with budget accounting simultaneous to function-preservation receipt. **Partial coverage:** criterion-triggered, not budget-matched.

2. **Self-Motivated Growing Neural Network (arXiv 2512.12713)** — Uses local activity statistics (neuron activations, edge weight update statistics) as CRITERION for per-neuron/edge growth decisions. However, scope is reinforcement learning agents (not pretraining), no function-preservation verification, and no budget-matched evaluation. **Partial coverage:** criterion-triggered, missing budget-accounting + function-preservation + pretraining scope.

### Distinction Stands:

- **Schedule-driven growth** (G_stack, bert2BERT, MSG, Stacking-as-AGD, LiGO, Beyond-Sunk-Costs) dominates prior work — no criterion-gating.
- **Criterion-triggered growth** exists (When-To-Grow ORL, NORACL, Firefly, SECNN, LAG, SMGrNN) but:
  - Lacks **simultaneous function-preservation + budget-matching receipt** as admission gate
  - Uses task-specific or local signals (overfitting risk, saturation, gradients, activity stats), not system-earned-capacity criterion
  - No papers compare at **iso-FLOP** across criterion vs. schedule baselines
  - Function-preservation is rarely verified at growth events

### Delta Integrity:

The **registered claim class** (criterion-gated + function-preserving + budget-matched eval) remains distinct from all 17 hits. No prior work combines:
- **Measured criterion** (earned-FLOP gate, assimilation evidence) triggering growth events
- **Simultaneous receipt** of function preservation + budget accounting as admission gate
- **Iso-FLOP frontier comparison** (criterion-gated vs. schedule-driven vs. scratch)

**Status:** DELTA-SURVIVES with qualification on LAG and SMGrNN scope/completeness gaps.

---

**Hit count:** 17 distinct works  
**File path:** state/c8-priorart-sweep-20260705.md  
**Sweep completeness:** All 8 axes covered; minimum 10 works exceeded.

---

## ADJUDICATION (adjudicator ruling, 2026-07-05 ~10:1xZ — the sweep above is retrieval; this section is the binding verdict)

1. The sweep's own VERDICT header ("CONCESSION-FOUND: 2 hits") misapplies the registered grammar:
   a CONCESSION requires covering the §2 delta — criterion-gated growth WITH budget-matched
   evaluation. LAG and SMGrNN are criterion-triggered but neither is budget-matched; both are
   DISTINCTIONS with partial overlap, per the sweep's own conclusion.
2. LAG (the nearest threat) spot-verified directly (arXiv abstract, 2026-07-05): early-training-
   dynamics used for single-stage growth-STRATEGY selection; no function-preservation
   verification; no matched-compute comparison. DISTINCTION confirmed.
3. RULING: **DELTA-SURVIVES.** No dated re-registration required. The prereg §2 is amended
   (strengthening) to name the criterion-triggered lineage and to sharpen the delta onto (i) the
   receipted admission gate (FP + budget, simultaneous) and (ii) the iso-FLOP three-way frontier
   comparison. F2 (criterion vs schedule at equal growth events) is the delta-killer arm.
4. Residual risk, disclosed: per-paper "no iso-FLOP" readings beyond LAG are retrieval-grade,
   not verified-from-full-text. Mitigation: F2's design makes the claim self-defending — if any
   unswept work already ran that comparison, the novelty narrows but the receipt remains valid
   evidence; the class re-registers on discovery, per §6.

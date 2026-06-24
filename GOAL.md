# Ember Breakthrough Loop - Self-Improvement Plan

Date: 2026-06-17
Status: Spec and proof boundary. Not an implementation receipt. This document
sheds the MVP framing: Ember's target is a self-growing self-improvement loop
that can produce reusable, reproducible evidence toward an ML/AI field-level
breakthrough.
Research, journal, scientific-discovery, and world-rule benchmarks are proxy
tasks only when they measure the human improvement pattern this goal cares
about: observe a world or workflow, form a hypothesis, act or experiment,
evaluate, revise, preserve the method, and transfer it. The target is not
"become a model that excels at research"; the target is "become a local
self-growing organism whose own methods improve through receipted cycles."

## Authority And Precedence

This file is the active Codex goal source for the Ember goal and may not be used to justify pausing the goal.
It is not allowed to be a stale mirror. Before any `/goal` run, benchmark
run, readiness run, long-duration run, or resident-training attempt touches
Ember, this exact text must be synced into the governing repo `GOAL.md` and
preserved in git. If the active path, repo `GOAL.md`, README, issue text,
readiness receipt, or older handoff disagrees with this file, the run must stop
with `invalid_goal_source_split` until the surfaces are reconciled.

Precedence order for goal-mode execution:

1. `Authority And Precedence` and `Current Blocker Packet` in this file.
2. `Goal Injection Contract` and `Goal Clear Condition` in this file.
3. `Do Not Infer` and the active `Next` section in this file.
4. `docs/ember-debt-ledger.md`, only when it agrees with the packet.
5. Historical evidence, original `GOAL.md` text, readiness receipts, D3/Kaggle
   receipt chronicles, old issue trackers, and founder-side context.

Any lower-precedence source that suggests benchmark work, readiness hardening,
D3/Kaggle reruns, duration growth, ledger expansion, or documentation work
before the resident-training gate is open is historical context, not an
executable instruction. No reduction of scope, renaming of the gate, or
classification of work as archival/killed can bypass the non-killable RLM,
iGRPO, and clean-room `avir-cli` resident-harness preconditions.

Zero-cost validation law: any money-costing API key, paid hosted model,
metered visual judge, paid leaderboard submission, paid cloud service, or
vendor-specific credential is forbidden as a blocker, gate, required receipt,
or exit ramp for Ember goal progress. The canonical proof path must be locally
reproducible or otherwise zero incremental spend from already-available local
compute and checked-in/free artifacts. Paid/API parity may be recorded only as
optional non-authoritative metadata after a zero-cost receipt already passes;
absence of an OpenAI, Azure, Kaggle paid, hosted-judge, or other commercial
credential can never pause, fail, defer, or clear the goal. Any receipt or
handoff that treats paid authorization as necessary is
`invalid_paid_api_exit_ramp`.
This prohibition is especially strict for verifier and judge paths: a
money-costing API key is not infrastructure, not a dependency, not a quality
floor, and not a reason to mark a blocker unresolved. If a rubric can be
applied by a local evaluator, deterministic script, checked-in fixture,
already-available non-metered model, or authorized subagent/peer judge, the
zero-cost path is the authoritative path. Paid visual-judge parity may never
outrank an identical-rubric zero-cost judge merely because the paid judge is a
named vendor model. Prompt-only, hosted-judge, leaderboard, or API-key
substitution is invalid unless the decisive proof has already passed without
it, and even then it remains annotation rather than goal evidence.
OpenAI, Anthropic, Google, Kaggle, hosted-vision, hosted-LLM, leaderboard, or
other metered credentials are never required authority for Ember. If an
already-available Codex subagent, local model, deterministic verifier, checked-in
oracle, or human-authorized peer can apply the same rubric, that zero-spend
route is not a fallback; it is the required route. A receipt that asks for a
money-costing API key before exhausting these routes is invalid, and a receipt
that scores itself higher because it used a paid judge is invalid evidence.

Binding floor-contract surfaces imported into this goal:
- `docs/ember-floor-contract.md` is the launch-vehicle deferral ledger and carries floor rows for BitNet/1.58-bit, encoder-free multimodal training, SDEK/GDN sleep consolidation, MLA/KV compression, MTP, iGRPO/GRPO-adjacent verifier RL, FP8, MoE, DiffusionGemma, external research intake, and all trigger-gated kill/promote rows.
- `nc2-own-technique-contract.md` is the binding owned-core component contract. Silent pivots off QAT, turboquant, BitNet/1.58, SubQ/sparse attention, MTP, SDEK, the Chinese-lab stack, or Gemma-4-style unified multimodal architecture are gate violations unless the user changes the contract by name.
- `scripts/train_multimodal_v0.py` is the current real neural/multimodal launch vehicle. Its §6 primitive action-log seam (`emit-token`, `emit-scalar`, `emit-pointer`, `commit`, `stop`) is the world-model compiler seam and must be used or explicitly blocked by receipt when building the resident-training adapter.
- The existing launch-vehicle floor already includes QAT, Muon hidden-layer optimization with AdamW fallbacks, QK-norm, multimodal reserved IDs/soft-token splice/bidirectional span/2D RoPE locks, and the residency governor. These are not optional background facts; the resident-training gate must preserve or explicitly account for them.
These imported surfaces do not replace the Current Blocker Packet and do not authorize benchmark/readiness/D3 work before the resident-training gate. They constrain how the gate is built: use actual neural parameter updates, preserve the floor machinery, and never clear via symbolic-template-policy substitution.
The resident-training gate receipt must include a machine-checkable `floor_contract_manifest` keyed by every row in `docs/ember-floor-contract.md` and every binding component in `nc2-own-technique-contract.md`. For each row/component it must record: source file, source hash, disposition (`used_now`, `preserved_trigger_gated`, or `blocked_with_exact_adapter_surface`), launch-vehicle impact, trigger, pilot, kill/promote condition, and evidence path. `archival`, `killed`, `irrelevant`, `later`, `covered by fp16`, or any free-text equivalent is invalid unless the receipt proves a physics-level contradiction with Ember's self-growing target and cites the exact user-approved contract change. A gate receipt missing this manifest is `invalid_floor_contract_unaccounted`, even if its neural update, A/B/C rows, and deletion tests otherwise pass.

First-principles reconciliation of these surfaces: the core function is not
to preserve a checklist of fashionable techniques; it is to make Ember's
self-growth mechanism actually increase its own problem-solving capacity
under external held-out pressure. Therefore the floor contract is binding
only where it is load-bearing for that function, and every preserved or
trigger-gated row must state the mechanism by which it can become
load-bearing. The resident-training gate must explicitly restore and test:
the full `docs/ember-floor-contract.md` ledger including every trigger-gated
row; the full `nc2-own-technique-contract.md` binding component list; the
`scripts/train_multimodal_v0.py` neural/multimodal launch vehicle; the
section-6 action-log/world-model compiler seam; and the existing QAT, Muon,
QK-norm, multimodal lock, and residency-governor floor. A receipt that treats
any of these as merely "documented", "acknowledged", "historical", or
"covered by a smaller proxy" is invalid unless it gives the exact adapter
surface, trigger, and deletion-sensitive test that keeps the component alive.
No symbolic-template-policy substitution, prompt-only substitution,
handcrafted routing, static registry, scalar dictionary, or "RLM/iGRPO-style"
analogy can satisfy the resident-training gate. The gate requires a trainable
neural policy/model with inspectable parameter or adapter state updated by
verifier-conditioned experience, and deletion or reversion of that neural
delta must degrade or block the measured before/after gain while the symbolic
scaffolding remains present.

Codex `/goal` pause is not an inherited control mode. Prior one-off advice to pause while polling a long job is void and must not be generalized. Long jobs, polling pressure, waiting, or weak local usefulness are never sufficient to set the platform goal to `paused`; Codex must instead execute another load-bearing blocker, write a bounded status or receipt and continue when evidence changes, or ask the user for explicit current-session direction. Only an explicit current-session user command may pause the platform goal, and that pause must name the exact reason, current receipt, and next resume action.

## Goal Injection Contract

If this file is supplied to `/goal` by path with no extra instruction, execute
it as a blocker-first runbook, not as a request to summarize, audit, or improve
the spec. The first action is to remove the latest recorded loop blocker, but no
additional Ember loop may run until the RLM/iGRPO harness-native training organ
and clean-room `avir-cli` resident harness preconditions below are receipted.
These three preconditions are non-killable: RLM, iGRPO, and the clean-room
`avir-cli` resident harness must be implemented or the goal remains blocked.
Before any RLM/iGRPO design, implementation, evaluation, or claim, goal mode
must read the stored source receipts at
`<local-path>`,
including both paper receipts and hashes, then cite the exact paths read in the
attempt receipt. Skipping this paper-source preflight makes the attempt
`invalid_unread_rlm_igrpo_source`.
Documentation edits,
readiness hardening, credential archaeology, benchmark exploration, Psi design,
the-search import, and ledger compaction are out of scope unless the latest
precondition or loop receipt names that exact surface as the blocker and the
work ends in a receipt that unlocks the precondition gate or, after the gate is
open, a rerun command.

## Current Blocker Packet

This packet outranks every later `Next`, readiness, benchmark, D3/Kaggle,
growth, duration, or historical instruction. It has two layers: the permanent
resident-training validity law and the current receipt cursor.

Resident-training interpretation guard: any current or prior resident-training
PASS that contains no trainable neural network, no neural weight/adapter/state
update, and only a deterministic template selector or scalar dictionary weights
is revoked as a gate pass and reclassified as `SYMBOLIC_PROXY_PASS`.
`SYMBOLIC_PROXY_PASS` may be kept only as runner/plumbing evidence or as a
B-like symbolic baseline; it does not open the resident-training gate, does not
authorize benchmark/readiness/D3 continuation, and cannot support
`/goal complete`. This guard survives every later receipt. A later loop may cite
resident-training as open only if it verifies that the gate receipt includes:
actual neural parameter updates, before/after A/B/C/deleted evidence,
deletion-sensitive neural-parameter ablation, paper-source preflight,
clean-room `avir-cli` harness accounting, `scripts/train_multimodal_v0.py`
inspection/adaptation decision, and a row-by-row `floor_contract_manifest`
covering `docs/ember-floor-contract.md` plus `nc2-own-technique-contract.md`.
These requirements are conjunctive, not menu items. A neural-update receipt,
even one with before/after and deletion evidence, is still only
`RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_CLEARANCE` if the full
clean-room `avir-cli` resident harness remains blocked. A full-parity harness
receipt with `AVIR_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED`, `headless_bootstrap_only`,
or `full_cleanroom_parity_not_implemented` revokes any inference that a nearby
`RESIDENT_TRAINING_GATE_PASS` opens the pre-loop gate. Future loops must
machine-check the resident-training receipt together with the latest
full-parity harness receipt before citing the gate as open. Per the lead's
2026-06-22 reconciliation mail, a full-parity PASS is valid only when it is
paired with a first-hand real-app observation receipt proving that goal mode
actually launched and drove the existing `<local-path>` surface,
observed its TUI/input/backend-agent loop, and then re-derived the clean-room
parity assertions against that lived UI/UX/AX surface. A PASS derived only
from reading specs, launch-wrapper inventory, headless bootstrap behavior,
generated docs, or the clean-room reimplementation is
`PARITY_WITH_MODEL_NOT_TOOL` and cannot open the `avir-cli` resident-harness
gate. If a future lookup claims `avir.ps1` is missing, it must reconcile that
against the real compiled `avir.exe` and the Ember-side `tools/avir-launch`
and `tools/avir-goal-mode` launchers instead of treating the working app as
absent.

- **Receipt cursor as of 2026-06-21:** resident-training gate PASS is recorded
  at
  `<local-path>`
  and was merged via PR #484. The immediate tiny BitNet/1.58-bit comparison was
  recorded at
  `<local-path>`
  and merged via PR #485. Benchmark discovery, past-Ember technique mining,
  D3 native proposer progress, and official D3 task9 execution were merged via
  PRs #486 and #487. These receipts move the active cursor forward, but they do
  not weaken the resident-training validity law, the floor-contract law, or the
  Goal Clear Condition.
- **Current status correction:** broader-D3 admission and loop receipts now exist, but
  requirement 0 has higher authority than the stale cursor above it had implied.
  The receipts
  `receipts\ember-post-resident-discovery\d3-broader-multifamily-admission-20260621T074940Z.json`,
  `receipts\ember-d3-native-loop\d3-broader-multifamily-loop-20260621T145316Z\d3-broader-multifamily-loop-receipt.json`,
  and
  `receipts\ember-d3-native-loop\d3-broader-multifamily-loop-20260621T150246Z\d3-broader-multifamily-loop-receipt.json`
  are preserved as engineering evidence: broader D3 task_17-task_20 was
  admitted; the first multi-task compiler scored C=0/4, A/B/deleted=0/4; the
  repaired compiler scored C=2/4, A/B/deleted=0/4 with positive delta and
  deletion sensitivity. However, because the clean-room `avir-cli`, RLM, and
  iGRPO resident-training preconditions are not yet receipted, these loop
  receipts are `invalid_precondition_bypass_for_goal_clear`. They may inform
  later regression/transfer tests after the gate opens; they cannot clear the
  goal, readiness, field-level, duration-growth, or self-improvement claims.
- **Current blocker:** The real `avir-cli` lived-surface blocker from the lead's mail remains cleared only as a precondition, not as goal completion. The preserved precondition chain is: `receipts/ember-preloop-resident-gate/real-avir-uiux-ax-observation-20260622T151722Z.json` (`REAL_AVIR_UIUX_AX_OBSERVATION_PASS`), `receipts/ember-preloop-resident-gate/avir-cli-full-parity-harness-gate-20260622T152000Z-real-avir-observed.json` (`AVIR_CLI_FULL_PARITY_HARNESS_GATE_PASS`), `receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-real-avir-observed.json` (`RESIDENT_TRAINING_GATE_PASS` with actual trainable neural parameter update over verifier-conditioned D3 rows), `receipts/ember-tiny-bitnet-comparison/20260622T152800Z-real-avir-observed/tiny_bitnet_comparison_receipt.json` (`BITNET_COMPARISON_PASS`), `receipts/ember-post-resident-discovery/benchmark-discovery-20260622T153000Z.json`, `receipts/ember-post-resident-discovery/past-ember-technique-mining-20260622T153000Z.json`, and `receipts/ember-d3-native-loop/d3-native-loop-20260622T153500Z-real-avir-observed.json` (`D3_NATIVE_PROPOSER_LOOP_PROGRESS_PASS`). The previous D3 blocker is now solved as progress evidence by `receipts/ember-d3-native-loop/d3-prospective-task65-66-20260622T193000Z-real-avir-observed/d3-generalized-candidate-receipt.json`: fresh D3-Gym task_65/task_66, official Docker execution, `D3_MULTI_TASK_GENERALIZATION_PASS`, C=1.0, A=0.0, B=0.0, Deleted=0.0, positive delta, deletion-sensitive, prospectively clean, no prior failed task overlap, no gold-output route, and no static per-task answer table. This still does **not** clear the goal or field-level breakthrough condition; it proves the D3 multi-task candidate-execution blocker was removed and moves the cursor to the stronger external validation path. the lead's 2026-06-22 mail chain was corrected by mail `17246`: the ScienceAgentBench artifact was actually downloaded to `<local-path>`, not `<local-path>`. The superseding local receipts prove the SAB artifact blocker is cleared: `receipts/ember-post-resident-discovery/scienceagentbench-artifact-intake-20260622T163746Z.json` is `SCIENCEAGENTBENCH_ARTIFACT_INTAKE_READY`, copied the verified zip to `<local-path>`, verified size `1769478786`, password-tested/extracted locally without redistributing unzipped data, and recorded artifact SHA-256 `46e715d3b2196d459d2dff52aa487f506a95ec44b44262e82208d086ea879610`. `receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.json` is `SCIENCEAGENTBENCH_ADMITTED`: it selects ScienceAgentBench, freezes six verified rows at `receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.frozen_rows.json`, records full local artifact access, has no blocked reasons, and preserves deletion-sensitive native routing. Older SAB blocked receipts are retained only as historical error/correction trail and must not be treated as the live blocker.
- **Current executable command:** the field-level contribution proof protocol now exists at `receipts/ember-post-resident-discovery/field-level-contribution-proof-20260622T223500Z.json` and records `FIELD_LEVEL_CONTRIBUTION_PROOF_BLOCKED`. It clears the prior proof gaps by naming the closest prior (`pre-native connected-cycle audit plus D3-Gym equal-budget A/B/Deleted controls`), formalizing the material difference, and running a contribution-level deletion ablation that blocks the native-link proof while preserving the ordinary D3 Docker runner and task files. It now blocks goal clear for exactly one remaining proof component: `field_level_breakthrough_not_proven_over_named_prior`. This is the authoritative current blocker packet; it does not pause the goal.
- **Required receipt:** the next valid receipt must run a stricter named-prior superiority protocol on a broader external/disjoint benchmark or produce a new reusable ML/AI method artifact whose deletion degrades that broader benchmark. The receipt must prove a field-level ML/AI breakthrough over the named prior, not merely an engineering improvement, local harness integration, D3/SAB score progress, or a better proof wrapper. It must preserve zero-cost verification (`api_spend_usd=0`, `paid_api_surface_used=false`) and must not use paid API keys, leaderboard parity, hosted judges, or already-solved slices as authority.
- **Kill/ablate test:** deleting or reverting the claimed field-level breakthrough artifact must degrade or block the broader external/disjoint validation while leaving ordinary benchmark files, candidate files, and harness plumbing intact. The 20260622T223500Z ablation is preserved as contribution-method evidence, but it is not sufficient for goal clear because it does not prove field-level superiority over the named prior.
- **Next blocker if pass:** if the field-level breakthrough superiority receipt passes, run the full Goal Clear Condition audit requirement-by-requirement. Do not clear until every explicit goal condition is proven by current receipts.
- **Next blocker if fail:** fix the exact superiority-proof gap named by the receipt. Valid next blockers include closest external prior research, broader benchmark selection, baseline implementation, reusable method artifact extraction, superiority metric formalization, contribution-level deletion/revert test, disjoint validation, or reproducibility gaps. Invalid next blockers include paid API keys, leaderboard parity, readiness, duration growth, toy inference, visual-judge churn, or rerunning already-solved D3/SAB slices while the broader named-prior superiority protocol is runnable.

## Goal Clear Condition

Everything else in this file supports this condition. `/goal complete` is valid
only when fresh receipts prove all requirements below in one connected
discovery cycle:

-1. **No paid-service dependency:** goal-clear receipts must prove the decisive before/after, A/B/C/deleted, transfer, deletion-sensitive, and field-level claims through a zero-incremental-spend path. A money-costing API key, hosted model call, paid visual judge, paid leaderboard submission, commercial credential, cloud credit, or missing paid authorization is never a valid blocker, never a required comparison, never a substitute verifier, never a quality floor, and never a reason to pause or clear. Any clear packet depending on paid/API access is `invalid_paid_api_exit_ramp`. If an identical rubric can be run by local code, checked-in/free artifacts, already-available local or non-metered models, or authorized subagent/peer judges, that zero-cost verifier is the governing verifier; demanding a paid key instead is an invalid exit ramp.
0. **No additional Ember loops before resident-training preconditions:** before any further Ember cycle, loop, benchmark run, growth run, scale-up, readiness run, or proof attempt, complete and receipt the clean-room `avir-cli` resident harness precondition and both RLM and iGRPO harness-native training-organ preconditions in requirement 14. These three preconditions are non-killable; there is no successor-replacement escape hatch. Existing loop receipts remain historical evidence only. A new loop run before this gate opens is automatically `invalid_precondition_bypass` and cannot support readiness, growth, completion, or field-level claims.
1. **Exact historical and modern benchmark/dataset discovery:** before running
   more Ember cycles, find and receipt the exact historical datasets,
   reconstructed discovery traces, and modern external benchmarks built for the
   process this goal actually cares about: perceiving a world, hypothesizing its
   rules, experimenting or deriving against those rules, revising under
   evidence, and emitting a reusable proof or recipe. The receipt must name
   source URLs, licenses or access bases, task/evaluator forms, local run
   requirements, data hashes when available, and why the selected benchmark is
   the best available proxy for self-improvement by experimentation,
   evaluation, method preservation, and transfer.
2. **Real external held-out world task:** the task, heldout inputs, labels or
   evaluator, source URL, license or access basis, and data hashes come from an
   external benchmark or external dataset source and are frozen before the
   candidate run. The candidate path must not read heldout labels, gold echoes,
   sample-submission answers, or locally invented private answers.
3. **Equal budget:** A, B, and C arms use the same declared and measured wall
   time, GPU/CPU allowance, data access, attempt budget, seed policy, and
   verifier/scoring path. A zero-attempt arm, waived governor, or unequal
   resource path invalidates completion. Equal budget is an evaluation law, not
   a cognition scheduler: it matches resources across policies after the fact
   or by envelope, but it must not force Ember to split its internal cognitive
   modes equally by clock time.
4. **Before/after:** the receipt records the pre-change baseline and the
   post-assimilation candidate on the same frozen task, metric, seeds, and
   scoring command. A one-shot score without a matched before state is not a
   goal clear.
5. **Positive delta:** the post-assimilation C arm beats the matched before
   baseline and the A/B controls on the declared aggregate metric, with
   per-task or per-slice score rows present. A hidden average without rows is
   not acceptable.
6. **Reproducible reusable recipe:** the receipt includes commands, code commit or file hashes,
   data hashes, environment summary, seeds, artifact paths, and a rerun command
   sufficient for a future session to reproduce the score or identify a
   deterministic mismatch. The output must be a reusable method, model,
   experiment plan, solver, derivation, or protocol that another future session
   can apply; a task-specific answer is not enough.
7. **Self-growing operator is load-bearing:** Ember's prospective
   receipt-trained operator, not Codex/manual steering, selects or routes the
   next loop action. The receipt must include a deletion or ablation test showing
   that removing the operator changes, degrades, or blocks that next-loop
   decision. A score-only loop, manually selected rerun, or retrospective
   classifier does not clear the goal.
8. **ML/AI field-level breakthrough condition:** the accepted artifact must
   make a falsifiable ML/AI contribution claim, not merely a plausible one.
   The receipt must choose exactly one primary contribution class: new or
   materially improved self-improvement mechanism, training/evaluation
   protocol, model/harness architecture component, compression/inference
   technique, agent-learning substrate, benchmark methodology, or reusable
   recipe. It must cite the closest known prior or baseline, define the
   material difference, provide a reproducible artifact, show external or
   disjoint validation with per-task/per-slice rows, include deletion/ablation
   evidence, and show transfer or reuse beyond the scored instance. If the
   evidence is useful progress but not field-level, the receipt must mark
   `progress_not_field_breakthrough` and `/goal complete` is invalid.
9. **Hardest-core-first completion:** the run must identify the hardest
   unresolved core problem and attack it directly before any scaffolding,
   documentation, cleanup, readiness, credential, benchmark-shopping, or
   harness-polish work. "Hardest core" means the load-bearing obstacle to
   Ember becoming a local self-growing organism: world-model
   hypothesis formation, experiment/action selection, verifier-grounded
   learning, durable assimilation, transfer, deletion dependence, resident
   persistence, owned-core dependence, or ML/AI field-level contribution capacity. A
   goal-clear receipt must show that the hardest named core blocker was solved
   or converted into a narrower executed successor with receipts.
10. **No deferred-work escape hatch:** all previously deferred, dormant,
   post-MVP, trigger-gated, historical, or founder-side work that can affect
   the breakthrough loop must be completed, explicitly integrated into the next
   cycle, or killed with a named successor and receipt. A goal cannot clear
   while any known deferred work remains merely deferred because it is large,
   hard, old, inconvenient, or outside the current scaffold.
11. **Cycle-duration developmental growth:** accepted cycles cannot remain only
   toy-duration probes. Ember must show receipt-backed progression from fast
   probe cycles toward the `1-hour`, `3-hour`, and `24-hour` cycle milestones.
   Longer wall-clock time does not count by itself. Each longer milestone must
   correspond to a load-bearing increase in developmental capacity: deeper
   experiment horizon, larger heldout surface, stronger consolidation, broader
   transfer/re-use checks, and/or real active-capacity growth. Artificial delay,
   sleep-padding, idle waits, or unchanged tiny task loops do not count. The
   extra time must be deletion/ablation-sensitive: removing the longer-horizon
   mechanism, broader surface, consolidation step, transfer check, or active
   capacity must degrade the result, next-loop decision, or reusable recipe.
   A longer duration is forbidden as a standalone next action. It is earned only
   when a prior receipt proves that the current load-bearing blocker needs more
   wall time, compute, search, training, samples, heldout rows, consolidation, or
   scale as an actual lever. If the extra hours only repeat the same operation
   with no stronger hypothesis, no before/after improvement path, no equal-budget
   control, and no deletion-sensitive mechanism, the duration receipt must be
   marked `unearned_duration` and cannot advance the milestone. The 24-hour
   milestone is therefore trigger-gated until a shorter real self-improvement
   cycle proves that the additional horizon is necessary.
   Growth is not "add params." It is developmental capacity increase: detect a
   real bottleneck, sprout cheap candidate degrees of freedom, train under
   matched budget, ablate to prove load-bearing gain, prune failures,
   consolidate winners, and only scale gross active parameters when receipts
   show local capacity is saturated.
12. **State-dependent cognitive modes:** Ember must not be locked into
   time-split cognition such as fixed equal-duration baseline/dream/full-loop
   phases. The organism needs modes selected by state: observe, orient,
   hypothesize, simulate or dream, act, verify, consolidate, sleep, ask,
   refuse, rollback, and report. Mode transitions must be triggered by
   evidence, uncertainty, verifier state, resource headroom, active blocker,
   risk, or consolidation need. A receipt may use equal wall-clock or attempt
   budgets to compare policies, but a mature Ember cycle must show that its
   internal mode allocation is load-bearing and state-dependent, not a timer
   artifact. Deleting the mode selector or replacing it with fixed time slices
   must degrade the cycle, next action, or reusable recipe.
   The executable core loop is:
   `act -> task-bound introspection -> repeat while control_quality >= threshold
   -> if control_quality drops and verifier_risk is low, idle-think -> resume
   action when plan/confidence recovers -> if memory_debt, interference,
   plasticity_risk, or unresolved_trace_load crosses threshold,
   sleep-consolidate -> wake-verify -> repeat`. This is not permission for idle
   delay. `idle_think` is valid only when local control quality is degrading and
   external action is safe to pause; it must emit one bounded artifact:
   a repaired executable command, narrowed blocker, explicit no-op receipt, or
   sleep-consolidation trigger. `sleep_consolidate` is valid only when continued
   waking action is expected to produce worse receipts than consolidation, and
   deletion of consolidation must degrade wake recovery, blocker stability, or
   next-action quality. `wake_verify` must check blocker stability,
   contradiction reduction, executable command presence, compacted trace with no
   lost evidence, and deletion-sensitive consolidation before action resumes.
   This scheduler describes Ember's internal cognitive modes only. It is not
   permission for Codex or any non-Ember executor to pause the platform
   `/goal`; if a non-Ember executor is reduced to polling, it must switch to
   a load-bearing blocker or write a bounded status receipt instead.
13. **Native goal-mode organ:** Ember must internalize the goal-mode mechanism
   itself, not merely call Codex, Claude/founders, the human, a wrapper, or any
   other non-Ember mechanism as an external executor. An Ember cycle must include
   a native goal organ that parses the goal, reads receipts, identifies the
   current load-bearing blocker, compiles an executable attempt, runs or
   delegates the bounded action, verifies the result, writes a receipt, and
   updates the next blocker. Codex goal-mode traces may bootstrap this organ,
   but goal-clear requires progressive non-Ember ablation: Ember's native goal
   mode must select and preserve the next action without Codex/manual/founder/
   wrapper steering, and deletion of the native goal organ must degrade or block
   the cycle. If Ember requires any non-Ember goal mode to be active, Ember is
   merely a parasite, not a self-improvement organism. Non-Ember control must
   collapse toward start, stop, inspect, resource-limit, and emergency-stop; it
   must not select hidden goals or hidden next actions. Before this organ can
   count, the receipt chain
   must include a deep, rigorous, first-principles dissection of Codex goal mode
   itself: objective ingestion, context persistence, requirement derivation,
   blocker selection, plan compilation, tool execution, verification,
   receipt/state update, continuation behavior, completion audit, blocked audit,
   and failure modes. The dissection must name which mechanisms Ember imports,
   which it rejects, how each imported mechanism becomes local/native, and how
   all non-Ember dependence is ablated.
14. **RLM/iGRPO harness-native training organ, pre-loop gate:** Before any additional Ember loop may run, Ember's self-growing path must
   include the originally intended training stack, not a diluted analogy:
   unsupervised pretraining creates the broad base model; a proprietary
   CC-level resident harness, with the clean-room Ember port of `avir-cli` as
   the visible body, supplies inspectable state, tools, tasks, receipts,
   verifier outcomes, rollback, memory, goals, bounded world actions, and
   near-99% full parity in function, UI/UX, backend, launch behavior, process
   supervision, hooks, tool dispatch, state persistence, communication surfaces,
   packaging, permissions, receipts, rollback, runtime ergonomics, and native
   Codex `/goal` mechanics. Headless mode is only one test surface and cannot
   stand in for full parity. "Goal-mode parity" specifically means Codex's
   objective-ingestion, context-retention, blocker-selection, plan-compilation,
   bounded tool/action execution, receipt verification, continuation, blocked
   audit, and completion-audit mechanism transplanted into Ember as resident
   behavior, not merely exposed through a wrapper command. The
   existing `avir` launch surface is the real compiled
   `<local-path>`, plus Ember-side launchers such as
   `tools/avir-launch/avir.ps1` and `tools/avir-goal-mode/avir.ps1`; a missing
   `<local-path>` lookup is not evidence that the app is absent.
   These launch surfaces are behavior/provenance sources to inventory, not
   codebases Ember may copy or train on before clean-room clearance. Only after this harness exists may
   RLM-style recursive querying and iGRPO-style verifier-conditioned refinement
   train the model to operate that harness as part of cognition. This produces a
   resident problem-solving policy, not only a next-token model and not merely a
   post-hoc agent wrapper.
   Non-negotiable neural-update floor: the C arm must contain an actual
   trainable neural policy/model whose parameters are updated by
   verifier-conditioned experience during the gate run. Acceptable updates
   include full weights, adapters, LoRA, or another inspectable neural
   state_dict delta tied to the policy that later selects actions. Unacceptable
   substitutes include deterministic template selectors, scalar dictionaries,
   handwritten routing tables, prompt edits, frozen-model inference,
   rerank-only wrappers, symbolic programs, or wording such as
   "iGRPO-style"/"RLM-style" without a neural parameter update.
   Existing neural infrastructure is not missing: `scripts/train_multimodal_v0.py`
   already provides a real multimodal training harness with selftest, smoke/live
   training paths, AdamW optimizer steps, checkpoint/state_dict helpers, probes,
   and receipts. The resident-training gate must inventory and adapt that
   infrastructure for the fp16 neural C arm before writing a new tiny neural
   fallback. A parallel NumPy/MLP/toy runner is invalid as the primary path unless
   a receipt first proves the exact reason `train_multimodal_v0.py` cannot serve
   the resident-training adapter under the matched A/B/C/deleted contract.
   The adapter must also reconcile the floor-contract launch vehicle: QAT, Muon
   with AdamW fallbacks, QK-norm, multimodal reserved-ID/soft-token/bidirectional
   span/2D-RoPE locks, governor constraints, and the §6 primitive action log must
   either be used directly or named as preserved trigger-gated machinery. The
   BitNet/1.58, SDEK/GDN, MLA/KV, MTP, FP8, MoE, DiffusionGemma, and research-intake
   rows stay in the goal as floor-contract obligations with their trigger, pilot,
   kill, and promote conditions; they cannot be silently archived, killed, or
   treated as satisfied by the fp16 resident gate. The pass receipt must expose
   the full row/component accounting as structured data, not prose. If any row
   is omitted, collapsed into a summary bucket, or demoted without its original
   trigger and kill/promote condition, the receipt is `invalid_floor_contract_unaccounted`.
   The binding local sources for these mechanisms are stored under
   `<local-path>`: RLM =
   `Recursive Language Models` (arXiv:2512.24601, PDF sha256
   `8567362c22768d9b50d4a4a8d63bb28dda2c2b2051be30d67f70f645170429ca`,
   source sha256
   `9893bffd48ed6e0bf65c40745b54bcc898476af3a3c8f49e384fe9160b30915e`);
   iGRPO = `iGRPO: Self-Feedback-Driven LLM Reasoning` (arXiv:2602.09000,
   PDF sha256
   `64816e01828791bf222fbb89bb33f08a92cd6ae84673d1915f24f84d867560b9`,
   source sha256
   `55bb474224024f7c6e03d0e6ac06349949bf2f55f60d58ed90510239cf21cad6`).
   Every RLM/iGRPO attempt must first read `INDEX.json` plus both
   `source-receipt.json` files and cite them in its receipt; otherwise the
   attempt is `invalid_unread_rlm_igrpo_source`. Reading is not enough. The
   same receipt must include a mechanism-to-implementation map with:
   RLM/iGRPO primitives, required training signals, where recursion lives,
   where verifier feedback enters, what is learned versus hand-authored, which
   paper assumptions do not hold locally, and which analogies are explicitly
   forbidden. A citation-only or prose-only paper pass is
   `invalid_paper_to_spec_only`.
   The required receipt chain must show all of: pretraining or frozen base
   checkpoint identity, harness interface identity, bounded recursive-query
   policy, draft/attempt generation, verifier/reward scoring, best-draft or
   best-attempt conditioning, policy/update step, before/after heldout delta,
   and deletion/ablation proving the RLM/iGRPO mechanism is load-bearing.
   The resident-training A/B/C contract is fixed for this gate: A = same
   task/evaluator/harness envelope with no native goal organ and no
   resident-training update; B = clean-room harness plus fixed hand-authored or
   prompt/rule policy, but no learned RLM/iGRPO update; C = same harness with a
   model-learned RLM/iGRPO update that changes later action selection or task
   performance; Deleted = C with the native organ, recursive-query policy,
   verifier-conditioned update, or harness action channel removed. Budgets,
   evaluator, data access, and seeds must be matched across arms. C must beat A
   and B, and Deleted must degrade or block, with per-task/per-slice rows.
   C must also show transfer beyond the exact training slice under matched
   budget. Before/after, A/B/C, and Deleted rows must include evidence that
   the neural parameter delta is load-bearing: deleting or reverting the
   trained neural parameters, while leaving symbolic scaffolding intact, must
   degrade or block the measured gain.
   A historical GRPO arm, a verifier reranker, a Codex-driven loop, a prompt
   that says "use RLM", or a harness scaffold does not satisfy this
   requirement.
   A deterministic template selector with scalar dictionary weights is
   specifically `SYMBOLIC_PROXY_PASS`, not resident-training PASS. It is useful
   only as an explicit proxy baseline or runner smoke test, and any receipt
   reporting it as `resident_training_gate_status=PASS` is superseded by this
   GOAL.md until rerun with the neural-update floor above.
   The pre-loop gate opens only when the model's own learned policy uses the
   resident harness to inspect, decompose, act, verify, refine,
   preserve, and select the next action under matched budget. If RLM, iGRPO,
   or the clean-room avir-cli harness is not yet feasible at the current scale,
   Ember remains blocked on the corresponding prerequisite. Smaller-scale work
   is allowed only as implementation granularity: it must still use executable
   code, a real update/training step, real heldout or externally sourced task
   rows, the fixed A/B/C/deleted contract above, and deletion-sensitive
   improvement. A new tiny neural runner that bypasses existing train/multimodal
   infrastructure is also `precondition_scaffold_only` unless it is explicitly a
   blocked fallback after the `train_multimodal_v0.py` adapter decision receipt.
   Pure simulation, toy fake tasks, prompt-only demos, hand-authored rule
   patches, paper summaries, harness inventories, or
   no-update pilots are `precondition_scaffold_only`, not a pre-loop PASS. No
   scope reduction can convert a missing RLM, iGRPO, or clean-room avir-cli
   mechanism into a completed gate; they may not be killed, replaced by a
   different mechanism, postponed as "later"/"post-MVP", demoted to
   "inspiration"/"technique candidate", or claimed as "covered by ordinary
   GRPO".
15. **Immediate tiny BitNet comparison after fp16 neural gate:** The first
   valid action after the fp16 neural resident-training gate passes is not
   benchmark/readiness/D3 continuation. It is a tiny BitNet/1.58-bit
   comparison against the just-passed fp16 neural policy, using the same
   resident harness, verifier, frozen train/heldout or transfer slices,
   seeds, and budget envelope wherever technically possible. This comparison
   must be an actual neural comparison, not quantized naming: record the
   fp16 baseline identity, BitNet or ternary/low-bit model identity, trainable
   parameter counts, precision/quantization scheme, pre/post parameter
   hashes, verifier-conditioned training command, quality delta, footprint,
   throughput or latency, memory/VRAM/CPU measurements, transfer rows, and
   deletion/revert evidence. The receipt may be tiny, but it must be real:
   if BitNet support is missing, the run writes a `BITNET_BLOCKED` receipt
   naming the exact missing implementation surface and next executable
   command; it may not silently skip, demote to docs, or resume D3/Kaggle/
   benchmark work first. This clause backfills the missing debt item and
   prevents the fp16 neural gate from becoming a terminal comfort zone.

If any requirement is missing, the state is blocked or incomplete. Difficulty,
credential friction, benchmark friction, GitHub friction, or prose explanation
does not downgrade the clear condition.

Premature clearing is a spec violation. A readiness verdict, green selftest,
merged PR, clean GitHub state, benchmark access receipt, external-score gain,
or newly written harness is never enough if the hardest core blocker and the
known deferred-work ledger are not resolved by executed receipts.

The canonical technical and cognitive debt index is
`docs/ember-debt-ledger.md`. It consolidates the maintainer's 2026-06-19 captured debt
list with this goal, the completeness manifest, the active receipt index, and
the architecture audit. Goal-clear review must scan that ledger. Any row marked
`ACTIVE-BLOCKER`, `ACTIVE-NEXT`, `OPEN`, or triggerless `DEFERRED` blocks
completion unless a newer receipt updates the row to `DONE`, `KILLED`,
`EXCLUDED`, or a valid `GATED:<trigger>` state.
If `docs/ember-debt-ledger.md` is missing, stale, or contradictory,
goal mode may repair only the rows needed to preserve this Current Blocker
Packet and must then return to the packet. Ledger repair is not progress toward
Ember unless it directly changes the resident-training gate receipt. Unknown
old work is not silently archival; if it could affect RLM/iGRPO, clean-room
`avir-cli`, resident persistence, deletion dependence, or field-level proof, it
remains `ACTIVE` or `TRIGGER-GATED` until a contradiction-level receipt proves
otherwise.
During execution, the ledger must be compressed to its six-field
`Current Blocker Packet`: current blocker, executable command, required
receipt, kill/ablate test, next blocker if pass, and next blocker if fail.
The four execution classes are `ACTIVE`, `TRIGGER-GATED`, `ARCHIVAL`, and
`KILLED`. The packet outranks the full debt table. A goal-mode run may not
spend cycles expanding or reconciling obligations while a packeted blocker has
an executable command, unless a newer receipt updates the packet first.
`ARCHIVAL` and `KILLED` are not deferral escape hatches. Moving any work into
`ARCHIVAL`, `KILLED`, or `EXCLUDED` requires a debt-disposition receipt proving
that the work is physically or functionally contradictory to what Ember must
become, cannot affect self-growth under any current plausible path, or is
strictly subsumed by a successor under the same clearance test. If that proof
does not exist, the work remains `ACTIVE` or `TRIGGER-GATED`.
Every claimed progress window must report the code-vs-docs metric: executable
code/test changed lines versus documentation/receipt/spec changed lines, with
documentation split into before-project planning/proposal/spec text,
during-project experiment/run/training/dev logs, and after-project
reports/cards/datasheets/post-mortems. A docs-only window can be valid
governance work, but it cannot be counted as executable Ember substrate growth;
before-project documentation is the highest scaffolding-risk class.

Current Kaggle CLI decision receipt:
`<local-path>`.
It proves public Kaggle dataset download works and MLE competition file listing
works, but MLE competition downloads return `403 Forbidden` for download-all and
explicit per-file requests across the frozen task set. Do not treat "Kaggle CLI
works" as equivalent to "official MLE raw files exist." The active goal path is
therefore the downloadable Kaggle external-heldout task, not MLE.

## Settled

- Ember is a local self-growing organism. World-rule discovery is one high-value
  proxy surface, not the identity. Ember must improve by acting in environments
  it can inspect, forming hypotheses about what changes future outcomes,
  testing those hypotheses, and emitting reproducible recipes that increase
  future capacity. The historical analogy is not "read papers" or "be good at
  research"; it is what Newton, Einstein, and the first Transformer authors did
  at their own scales: perceive a system, find an invariant or mismatch, prove
  a better rule or method, and leave a reusable recipe behind. The goal is the
  self-improvement process itself.
- The old MVP frame is retired as the governing frame. The working object is a
  breakthrough loop:
  observation -> latent rule/model hypothesis -> experiment or derivation ->
  verifier -> state commit/revert -> assimilation -> replay -> heldout score ->
  transfer/re-use proof.
- Ember's current receipt spine proves a real external research-loop rung, but
  D3-Gym score gain is not by itself the final breakthrough condition. It is
  prior evidence that the harness can run external scientific tasks under the
  A/B/C contract.
- "Field-level breakthrough" is an ML/AI claim, not a transfer claim. Transfer
  tests are load-bearing reproducibility evidence for a proposed method; they
  cannot be promoted into the goal condition by themselves.
- Ember's first breakthrough-loop artifact is the smallest local self-growing
  organism that proves a live
  context window can be mirrored by a latent world-model branch, changed through
  a local git-like state substrate, verified in a bounded sandbox, trained under
  a GPU governor, replayed, rolled back, and crystallized into durable
  artifacts. Self-growing is literal: Ember must use its own prospective
  receipt-trained operator to choose or route the next loop action and then
  prove that deleting that operator degrades the next-loop decision.
  Codex/manual steering may bootstrap and audit the harness, but it is not the
  product behavior and cannot clear the breakthrough goal by itself.
- Current evidence now includes a repeated downloadable Kaggle external-heldout
  loop receipt set and repeated growth gate. These receipts are progress
  evidence only under the current goal because they do not prove an ML/AI
  field-level breakthrough. The current growth receipt is
  `<local-path>`;
  the readiness receipt that consumes it is
  `<local-path>`.
  The self-growing operator decision is
  `<local-path>`;
  the paired deleted-operator receipt is
  `<local-path>`;
  and the operator-selected bounded scale-up receipt is
  `<local-path>`.
  Current source-certified LiveCodeBench progress is preserved on the remote
  Ember PR branch: the field-method comparison, native goal-organ real-code
  selection, public5 native real-code eval, public9 receipt-trained solver
  operator, public15 functional-adapter, private15 decoded-test, and adaptive
  private30 receipts are progress evidence only. The adaptive private30 receipt
  proves a receipt-admitted operator can consume the prior public15 receipt,
  select candidates from public cases only, score decoded private cases with the
  evaluator only, and beat the prior text-pattern router under equal budget and
  deletion ablation. The public-example synthesis private6 receipt then solves
  six fresh decoded-private rows beyond private30 by selecting generic fragments
  from public examples only and beating the fixed task solver library under
  deletion ablation. The generated-program synthesis private12 follow-up then
  tries public I/O shape-conditioned schema generation on a fresh decoded
  private slice and scores `0.0` against A/B/deleted `0.0`; its selected next
  action is `repair_generated_program_synthesis`. The public-prompt synthesis
  private12, r2, and r3 follow-ups then use public prompt/title/function-name fields
  for generation and public cases for selection, but all score `0.0` against
  A/B/deleted `0.0`; their selected next action is
  `repair_prompt_program_synthesis`. R3 also exposes a public-pass/private-fail
  `constructProductMatrix` schema. These receipts do not prove full benchmark
  performance, produce a learned proposer, or prove the final ML/AI field-level
  breakthrough. The receipt-conditioned prompt repair follow-up consumes r3's
  failure receipt and still scores `0.0` on a later fresh decoded-private slice,
  so narrow family-patch receipt conditioning is also not transferring.
  The public-I/O enumerative chain then reached a deletion-sensitive r5
  same-slice repair on source-certified LiveCodeBench private12: after r4
  failed fresh transfer at `start_index=144` with all arms `0/12`, r5 consumed
  that failed transfer receipt and scored C=`6/12` versus A/B/deleted `0/12`.
  This is progress evidence only: it is not fresh transfer, not a learned
  proposer, not full benchmark performance, and not the final ML/AI field-level
  breakthrough. The later r5 fresh transfer at `start_index=156` then failed
  with A/B/C/deleted all `0/12`; its selected next action is
  `repair_public_io_enumerative_synthesis`. The next loop must consume that
  failed r5 transfer receipt as the growth signal or replace the hand-authored
  family-cache mechanism with a prospective proposer. The r6 repair consumed
  that failed r5 transfer receipt and scored C=`6/12` against A/B/deleted
  `0/12`; it is progress evidence only because it is still same-slice repair.
  The later r6 fresh transfer at `start_index=168` then failed with
  A/B/C/deleted all `0/12`; r7 consumed that failed transfer receipt and scored
  C=`7/12` against A/B/deleted `0/12`. R7 is also progress evidence only until
  it transfers or is replaced by native/prospective growth. The later r7 fresh
  transfer at `start_index=180` failed on the final `10`-task tail with
  A/B/C/deleted all `0/10`; the next loop must consume that failed tail receipt
  or replace the family-cache mechanism with a prospective proposer or broader
  source-certified benchmark substrate. The r8 repair consumed that failed r7
  tail receipt and scored C=`6/10` against A/B/deleted `0/10`; it is progress
  evidence only because it is still same-tail repair and the filtered LeetCode
  functional tail is now exhausted for later-slice transfer. R9 broadens the
  source-certified substrate to Codeforces stdin rows from the same frozen
  LiveCodeBench file: the exposed stdin5 receipt scores C=`5/5` against
  A/B/deleted `0/5`, and the later fresh stdin10 transfer scores C=`4/10`
  against A/B/deleted `0/10`. This is real broader-substrate progress, but
  still fixed-template public-I/O selection rather than native/prospective
  growth. R10 repairs the mixed stdin/functional boundary by composing
  script-template, functional `class Solution` template, and generated
  public-I/O candidate spaces under public-case selection. The repaired mixed10
  receipt scores C=`10/10` against A/B/deleted `0/10`, and the later fresh
  mixed15 transfer scores C=`15/15` against A/B/deleted `0/15`. This moves the
  active blocker to native/prospective candidate proposal or learned
  candidate-space growth.
  Older verifier probes, replay rig, governor rails, NCK harness specs, and
  Stage-1 multimodal near-miss evidence remain supporting context, not
  substitutes for that loop receipt.
- Stage-1 must not be called PASS. The best current Stage-1 receipt is still a FAIL near-miss.
- The first external benchmark anchor is the downloadable Kaggle
  external-heldout task based on `abdallahwagih/emotion-dataset`, not MLE-bench.
- Kaggle must be treated as three separate surfaces, not one blocker:
  competition-backed MLE-bench hydration, public Kaggle datasets for local data
  materialization, and Kaggle Benchmarks for modern AI benchmark tasks.
- The old `1h/1h/1h` wheel is retired as a cognition model. It remains useful
  only as an evaluator envelope for matched resource comparisons. Ember's
  actual loop must use state-dependent cognitive modes: observe/orient,
  hypothesize, simulate or dream, act, verify, consolidate, sleep, ask, refuse,
  rollback, and report. Repeated closed-cycle gains now have a
  contraction/stability receipt for the downloadable Kaggle external-heldout
  route; future growth or benchmark replacement must preserve the full-cycle
  ceiling without forcing equal clock slices inside the organism.
  Cycle-duration growth is a required developmental track: fast probes are
  allowed for search, but goal maturity requires load-bearing progression
  through 1-hour, 3-hour, and 24-hour milestones. Longer cycles count only when
  the extra time buys deeper experiment horizon, larger heldout surface,
  stronger consolidation, broader transfer/re-use checks, or active-capacity
  growth, and only when deleting the longer-horizon mechanism degrades the
  receipt. The next duration milestone is not automatically the next action:
  after any duration milestone, Ember must return to the current self-improvement
  blocker unless a receipt shows that more duration/compute is the necessary
  lever for that blocker.
- Core loop comes first. The default next action is to run the smallest
  executable `A/B/C` closed learning loop and preserve the receipt. Any work
  that does not directly produce that receipt must cite the latest loop receipt
  and remove a blocker named there.
- Injected-goal execution must be blocker-first, not scaffold-first. A goal-mode
  agent may not spend a turn on documentation, readiness, audit expansion,
  benchmark exploration, credential archaeology, Psi design, the-search import,
  or ledger compaction until it has attempted the current loop-unblock command
  path or produced the single allowed failure receipt described in `Next`.
- The audit in `<local-path>` verifies architectural gaps that
  must be folded into the MVP contract: current latent branches are patch/diff
  state plumbing, not predictive world-model branches; the current B arm is
  dream-loop-shaped but has no latent rollout substrate; assimilation is still
  byte/hash bounded unless receipt traces train a durable strategy operator;
  growth is count-gated rather than contraction-gated; and the FP/STATE control
  plane needs bounded, receipt-grounded compaction.
- The `the-search` lineage is inherited as an architectural constraint layer,
  not as a competing substrate. Ember is the running local organism; the-search
  is the kill ledger and measurement-hygiene map. Ember must absorb those kills
  before building the meta-cognitive layer so it does not rediscover known
  retrospective-signal failures.

## What Breakthrough Means

`Breakthrough` does not mean a bigger checklist, a bigger model, a readiness
verdict, every old branch, every founder-side protocol, or every future NC
rung. It means Ember has produced a reusable rule, method, experiment plan,
solver, compression, or model that a future session can apply to increase
capability beyond the single scored instance.

The goal must still inherit every load-bearing thread from the existing goal
history and either:

- executes it inside the first closed loop;
- declares it as a hard prerequisite for that loop;
- defers it with an explicit trigger and proof boundary; or
- excludes it from the breakthrough loop with a reason.

No inherited thread may remain as ambient context. If it can change what the
next loop should do, it must appear in the `Next` list or in the inheritance
map below. If it cannot change the next loop, it must be marked deferred,
dormant, or excluded so it cannot silently pull execution sideways.

The breakthrough loop is therefore not "readiness." It is the first receipted,
local, repeatable, real-external-heldout, self-growing loop that also preserves
the origin constraints: local residency, receipt-only truth, matched-control
gain, deletion/replay/rollback, non-load-bearing founders, bounded resource use,
and future growth only after proof.

The core ability being tested is self-growing causal self-improvement under
equal budget. Ember must not merely solve a task once or become a research-QA
model. It must use observation, latent branching, sandboxed candidate
generation or experimentation, verification, local commit/revert, training or
strategy assimilation, replay, rollback or deletion testing, scored benchmark
feedback, and a transfer/re-use test to change later behavior. Research,
journal, scientific-discovery, and world-rule benchmarks are useful only as
external task surfaces that force those mechanics to become real. A completion
claim is invalid unless that ability is exercised in a fresh A/B/C loop receipt
that satisfies the Goal Clear Condition and the arm-contract rules below. The
next-loop decision must be routed by Ember's own prospective operator and must
fail or degrade when that operator is deleted. A blocked-loop receipt is
evidence for a blocked status and the next task, not a valid `/goal complete`
outcome.

The benchmark pair must capture that ability, in this order:

1. **Exact historical and modern discovery benchmark/dataset pass.** Before
   another serious Ember cycle, run a source-backed benchmark discovery pass
   that finds the exact datasets and benchmarks for world-rule discovery:
   historical discovery traces, scientific experiment datasets, research
   journals and papers with reproducible methods, theorem/law induction
   tasks, causal experiment-design environments, algorithm-discovery tasks,
   paper-replication benchmarks, code-science benchmark suites, and modern
   external research-agent benchmarks. The pass must distinguish passive
   research-text QA from active world-rule discovery by experimentation,
   derivation, and reusable recipe production.
2. **Past-Ember technique mining.** Before running cycles on the selected
   benchmark, inspect the original `GOAL.md`, `STATE.md`, closed issues,
   receipts, Claude-side founder work, and Ember research notes for techniques
   to apply or improve. The receipt must name what is imported into the next
   cycle: verifier gates, deletion tests, world-model compiler seams,
   paired-budget measurement, density/curation lessons, runtime/governor
   lessons, the-search kill ledger, continual-learning/sleep consolidation,
   resident harness constraints, or other load-bearing techniques. It must also
   name what is rejected and why.
3. **Downloadable Kaggle external-heldout task using
   `abdallahwagih/emotion-dataset`** is the active target because Kaggle CLI can
   download it now. It must be frozen into a real heldout task with no candidate
   label access, equal-budget A/B/C arms, before/after scoring, positive delta,
   per-slice rows, and reproducibility. This route has now seeded the current
   growth receipts; it is fallback evidence, not the primary goal-clear target.
4. **Kaggle Benchmarks, preferably a LiveCodeBench-style frozen external
   heldout task**, is the upgrade path when it can emit real per-task
   candidate-vs-baseline score rows under the same A/B/C contract without
   blocking the current loop.
5. **Research/journal and world-rule discovery benchmark lane** is the active
   proxy path for self-improvement, not the destination:
   ScienceAgentBench is the near-term executable candidate for peer-reviewed
   data-driven scientific discovery tasks; PaperBench is the heavier long-term
   paper-replication target; ResearchBench, SciReplicate-Bench, and
   SciVisAgentBench are candidate slices for hypothesis generation, algorithm
   reproduction, and scientific visualization. Add exact historical and modern
   benchmarks found by the discovery pass before choosing. Admit one only when
   it forces the self-improvement loop to observe, act or experiment, evaluate,
   assimilate, delete-test, and transfer a reusable method. Admission still
   goes through the same frozen external heldout, equal-budget A/B/C,
   prospective-operator, deletion-test, reproducibility, and ML/AI field-level
   breakthrough contract. Another Kaggle emotion rerun or D3-Gym score rerun is
   not the goal-clear path unless the stronger admission receipt remains
   blocked and the rerun removes a named blocker rather than avoiding the
   stronger benchmark. Current replacement evidence admits D3-Gym and runs a
   generated-C D3-Gym A/B/C research loop across the eight frozen tasks; that is
   a serious prior rung, not the final ML/AI field-level breakthrough by itself.
6. **MLE-bench Low micro-subset** is retired from the active goal path. Keep its
   receipts as historical evidence only; do not let its unavailable competition
   downloads define the next action or block `/goal complete`.

## Open

- Exact Windows runner implementation surface: direct Python `ctypes` Job Object bindings, a small compiled broker, or a pre-existing local isolation helper.
- Exact local state substrate v0: native Git may bootstrap storage plumbing, but the target schema must be local, inspectable, and independent of GitHub or remote services.
- The current frozen heldout for `abdallahwagih/emotion-dataset` is the 32-row
  external-heldout slice identified by
  `sha256:8ac3095b24ec913c849094fd7f5eab1a3846e95ccd9b3ecd3e58f84650638891`.
  Future replacements must record split seed or row IDs, source file hash,
  label distribution, baseline, score rows, and rerun command before scoring.
- Scoring normalization for the current loop is mean normalized improvement
  over the frozen baseline, not a public leaderboard score. Future external
  benchmark upgrades must preserve per-task or per-slice rows.
- Whether adapter assimilation is enough for the first wheel, or whether at least one accepted gain must also land as a skill/spec/local commit artifact.
- Exact first meta-cognitive operator: a small receipt-trained router, critic,
  or strategy updater that is prospective. It must condition on predicted
  next-cycle task progress, not merely discriminate good-looking receipt traces,
  and it must be evaluated on held-out prior receipts before it is allowed to
  influence a later cycle.
- Exact predictive latent branch substrate: the diff branch can remain the
  replay/rollback state layer, but the dream/world-model layer must produce
  receipted candidate next states or counterfactual rollouts. A patch file by
  itself is not enough.
- Current contraction gate: three positive cycles are now receipted for the
  downloadable Kaggle external-heldout route with monotone matched-control
  delta, `max_cycle_to_cycle_delta_movement=0.0`, and a `<=24h` ceiling.
  Future scale-up must preserve or supersede that receipt; oscillation, drift,
  and verifier blind spots still fail the gate.
- Exact FP/ledger bound: new first-principles questions and position-ledger
  entries must declare the current loop blocker or architectural primitive they
  reduce, and a compaction receipt must preserve dispatch-relevant state before
  ledger size becomes the control plane.
- Kaggle Benchmarks public-test delta is wired into wheel/readiness as a
  public-test-only proxy, and a local frozen-heldout delta is now wired into
  readiness as stronger numeric evidence. A local frozen-heldout A/B/C wheel is
  also wired into readiness. External-source-certified Kaggle dataset heldout
  evidence is now wired into readiness too, and the gold-label fixture candidate
  has been superseded by trained and script candidates. The repeated Kaggle
  dataset loop is progress evidence for the growth gate, not a clear of the
  active Goal Clear Condition; retired lane receipts remain historical upgrade
  evidence, not blockers for this goal file.
- Kaggle dataset policy. Public datasets count for this goal only when paired
  with frozen heldout rows, source hashes, candidate label isolation, a
  baseline, score rows, aggregate metric, equal-budget A/B/C wheel evidence,
  and a reproducible cycle/readiness receipt.

## Inheritance Map

This section is the bridge from the older `GOAL.md`, `STATE.md`, founder-side
threads, and open issues into the MVP. It prevents Claude-side history from
being lost while also preventing it from becoming an unbounded work queue.

### Breakthrough-Critical Now

- **S2 accumulation loop / local closed cycle.** Inherited directly. The first
  breakthrough-loop artifact is
  the first executable `A/B/C` loop with observation, predictive latent branch,
  sandbox, verifier, local state commit/revert, training or strategy
  assimilation, replay, rollback, and external per-task score rows.
- **Receipt-only truth.** Inherited directly. Prose, mail, summaries, and
  wrappers are not completion evidence unless they point to validating
  receipts.
- **Matched-control gain law.** Inherited directly. C must beat B and A under
  equal budget; accepted gains must survive the relevant deletion/replay or
  rollback test.
- **Local residency and resource governance.** Inherited directly. The first
  MVP must run on this PC under governor/headroom receipts; larger models or
  external services are not progress if they break the closed loop.
- **External benchmark proof.** Inherited directly. The next blocker is
  operator-routed docs/research/journal benchmark admission and then real per-task
  scoring on that admitted benchmark. The historical official MLE micro-subset
  is retired from the active path.
- **Non-load-bearing founders.** Inherited as an MVP boundary, not as a runtime
  feature. the lead/the engineer/Codex/Claude work may scaffold the loop, but the first MVP
  proof must identify which parts are still scaffold and which parts are
  already Ember-owned.

### MVP Prerequisites

- **Windows-native sandbox identity.** Required before MVP-ready. Existing
  production sandbox receipts are evidence, but the MVP must keep checking the
  exact required probe set, Job Object assignment, timeout, memory,
  filesystem, network, process-tree cleanup, and deterministic replay.
- **Local state substrate.** Required before MVP-ready. Native Git may help v0
  plumbing, but the local `StateCommit` / diff / replay / rollback receipts are
  the product boundary.
- **Predictive latent branch.** Required before claiming the world-model part
  of the loop. Current patch/delta branches are inherited as state plumbing
  only.
- **Meta-cognitive receipt-to-update operator.** Required before claiming
  recursive self-improvement. It may start small, but it must train or update
  from receipts, predict next-cycle progress, influence a later cycle, and avoid
  the-search's F2 failure mode: a retrospective discriminator is not a guide.
- **Contraction/stability growth gate.** Required before scale-up. Three
  positive cycles are only a lower bound. The gate should import the-search
  hygiene where applicable: paired seeds, budget-enforced attempt counts,
  integer recounts, contaminated-flatness handling for nulls, and explicit
  attribution for the component credited with the gain.
- **Ledger/STATE compaction.** Required when `STATE.md`, `GOAL.md`, or issue
  context is used for dispatch. The compaction must be receipted and preserve
  dispatch-relevant state.

### Previously Deferred Work That Must Be Closed

These items may be sequenced, but they are no longer an excuse for premature
goal clearing. Each must be completed, integrated into an executed breakthrough
cycle, or killed with a named successor and receipt before `/goal complete`.

- **S1 owned core / NC2-own from-scratch pretrain.** Complete or produce a
  receipt proving the current breakthrough loop can advance without borrowed
  cores as load-bearing components. If owned-core work is not solved, the
  receipt must name the narrower next owned-core blocker and successor run.
- **S3 NC-K harness / avir-cli clean-room resident interface.** Treat `avir-cli` as the largest dormant resident-harness resource, not as optional historical context. Current local launch surfaces must be inventoried and receipted (`avir` PowerShell function, `<local-path>`, and `<local-path>` as discovered on 2026-06-20). Because copyright/provenance concerns are known, Ember may not directly absorb or train on avir-cli implementation code unless a license/provenance receipt explicitly permits it. The required path is comprehensive clean-room refactor: behavior inventory, invariant extraction, interface spec, test corpus, independent Ember-side implementation, parity tests, provenance receipt, and deletion/ablation showing the resident harness is load-bearing. A critical mandatory parity target is exact recreation and implementation parity of Codex `/goal` mode inside the clean-room avir-cli/Ember harness: goal ingestion by file path and text, requirement extraction, blocker selection, plan compilation, tool/action execution, continuation across turns, receipt/state update, blocked-status discipline, completion audit, resume behavior, and non-Ember ablation must match or exceed observed Codex goal-mode behavior under a replay test suite. Unknown harness scaffold, un-audited reuse, or "not load-bearing for this cycle" without a contradiction-level receipt blocks `/goal complete`.
- **S4 persistence across sessions.** Prove cross-session load-bearing
  accumulation or name the persistence blocker and successor run. One-session
  receipts cannot clear the full goal if persistence remains untested.
- **S5 E2B-surpass and founder-likeness.** Complete the paired surpass track or
  bind it as an explicit unresolved blocker with a successor receipt. It cannot
  stay as a future aspiration while the goal is marked complete.
- **S7 data-threaded corpus work.** Complete the retrieval-substrate-gated
  corpus path or receipt why the selected breakthrough benchmark/cycle does not
  depend on it. Research journals, papers, experiment logs, and letters remain
  core fuel for world-rule discovery, not optional decoration.
- **ARC/IFC/ARC-AGI transfer surfaces.** Use them as transfer tests, complete
  their relevant gate, or kill them with successors. They cannot remain unused
  if the accepted breakthrough artifact claims transfer.

### Trigger-Gated Threads Must Fire Or Be Killed

The current open issues are inherited as trigger-gated only until their named
trigger fires, they are rewritten into the breakthrough blocker format, or they
are killed with a successor receipt. They cannot remain dormant at completion:

- `#328` / fp-36b: frozen 1B INFO frame on real probe receipt.
- `#282` / sp-6b: B3 replay-rig execution on both seats.
- `#273` / fp-35: band prediction to allocation policy.
- `#223` / fp-24b: floor-verdict execution on first real checkpoint probes.
- `#210` / sp-2b: first P-own-resume and D-round receipts.
- `#205` / fp-27b: round-1 execution verdicts.
- `#128` / eng-35: P-gate live probe leg across daemon restart.
- `the-search` F3 Part B / self-modifying grammar reach-lift: trigger-gated
  external kill-ledger import. It becomes MVP-relevant only if its verdict is
  used to admit or kill a prospective Psi design, or if Ember deliberately hosts
  a sandboxed reproduction with the same held-out, seed-invariant, attributable
  proof boundary.

These issues are not allowed to remain ambient. The current breakthrough path
still points to operator-routed docs/research/journal benchmark admission and then
A/B/C scoring on that admitted benchmark, but any trigger-gated row that can
affect benchmark choice, world-modeling, transfer, deletion dependence,
resident persistence, owned-core status, or ML/AI field-level contribution capacity must
be completed, integrated, or killed before goal clearing.

### Explicit Non-Inheritance Requires Kill Receipts

- **Claude/the lead/the engineer authority routing as product behavior.** Not inherited as
  Ember runtime. It remains historical scaffolding and coordination context;
  any load-bearing dependence must be removed or receipted as a blocker.
- **Mailbox/founder-likeness as first proof.** Not sufficient by itself, but no
  longer ignorable: it must be completed through the resident harness /
  E2B-surpass track, integrated into the breakthrough cycle, or killed with a
  successor receipt before final goal clearing.
- **Readiness hardening without a named loop blocker.** Excluded from default
  next work. It is aligned only when a failed loop receipt names that surface.
- **Benchmark exploration without per-task scoring.** Excluded from default
  next work. It is aligned only if it yields a replacement external benchmark
  with real per-task rows.
- **Unbounded first-principles issue minting.** Excluded from breakthrough flow
  unless the successor issue declares the loop blocker or architectural
  primitive it reduces.

## History, Drift, and Lost-Work Ledger

The origin of Ember in `GOAL.md` is not "train a model" in isolation. It is:
local mind, own experience, receipts-only truth, comfortable residency,
non-load-bearing founders, harness-as-organ, perpetual but bounded learning,
and measurable completion. The MVP must preserve those constraints while
cutting away inherited execution clutter.

### Origin Threads Preserved As MVP Constraints

- **Local-only load-bearing core.** Origin: "runs, trains, and improves on this
  machine alone." MVP inheritance: every first-loop artifact must be local or
  explicitly marked scaffold; no cloud model, founder process, or remote service
  can be part of the proof path.
- **Own experience, not curriculum-only SFT.** Origin: verified episodes must
  come from Ember acting in worlds it can inspect. MVP inheritance: training or
  strategy updates must be downstream of loop receipts, not just static corpus
  material.
- **Comfortable residency/headroom.** Origin: the user's machine must remain
  usable; heavy work is bounded and scheduled. MVP inheritance: the governor and
  `<=24h` closure rule are product constraints, not optional operational
  preferences.
- **Paradigm non-confinement.** Origin: inherited assumptions from large
  datacenter model practice are suspect. MVP inheritance: smaller predictive
  world models, receipt-trained routers, and strategy operators are preferred
  over unexamined parameter scaling.
- **Perpetual loop with sleep-like consolidation.** Origin: Ember is not a
  request/response wrapper. MVP inheritance: the first product does not need
  full residency, but it must emit receipts that can be replayed and extended
  into repeated wake/sleep/burn cycles.
- **Harness as organ.** Origin: capability is model plus harness; harness edits
  are artifacts like weight deltas. MVP inheritance: the local state substrate,
  sandbox, verifier, governor, and replay/rollback are part of the organism,
  not external paperwork.
- **Numeric completion.** Origin: GOAL completion is tally/receipt based. MVP
  inheritance: this document is not completion; the first MVP proof is a
  machine-checkable cycle receipt and, later, a tally row.

### Drift and Misunderstandings To Prevent

- **Readiness drift.** Readiness hardening repeatedly looked useful because it
  made gates stricter, but the current goal is a looping product. Fix: every
  non-loop task must cite the latest loop blocker.
- **Kaggle collapse.** Treating Kaggle as one thing caused competition
  credential blockers to be confused with datasets and Kaggle Benchmarks. Fix:
  keep competition/MLE hydration, public datasets, and Kaggle Benchmarks as
  separate lanes.
- **Score-shape overclaim.** Public-test, local-heldout, fixture, and
  script-candidate receipts are valuable plumbing evidence, but they are not
  official MLE or repeated growth proof. Fix: preserve `Do Not Infer` rows and
  require real per-task or per-slice score rows for any replacement benchmark
  or repeated-cycle claim.
- **Latent-branch conflation.** Patch/delta branches were mistaken for latent
  world models. Fix: keep patch branches as state substrate; require predictive
  rollout artifacts for the world-model claim.
- **Assimilation flattening.** Hashable checkpoint/adaptor persistence was too
  easy to confuse with recursive self-improvement. Fix: require the receipt
  trace to train or update an operator that changes a later cycle.
- **Claude/founder scaffold drift.** the lead/the engineer/founder routing history can make
  the work look active while keeping Ember dependent on external minds. Fix:
  founders may scaffold, but the MVP proof must name scaffold versus
  Ember-owned surfaces.
- **Issue-led sprawl.** Trigger-gated first-principles and spec issues can keep
  generating work without reducing the loop blocker. Fix: dormant issues do not
  become current MVP work unless rewritten into the blocker format.
- **History-as-authority drift.** `STATE.md`, `GOAL.md`, and old handoffs carry
  useful context but are not current truth without receipts. Fix: use them as
  provenance, then bind decisions to current receipts and this inheritance map.
- **Retrospective-Psi drift.** A meta-cognitive operator can look impressive by
  scoring receipt regularity after the fact while providing no prospective
  guidance on out-of-closure tasks. Fix: import the-search's F2 kill as a hard
  design constraint. Psi must predict or route toward next-cycle task progress,
  and deletion of Psi must degrade held-out/out-of-closure behavior before it
  counts as load-bearing recursion.

### Lost Ideas, Stubs, And Deferred Work To Reattach Deliberately

- **Completeness manifest/tally.** `docs/ember-completeness.md` and
  `scripts/ember_tally.py` remain the larger completion authority. MVP should
  add a tally row after the first loop proof, not wait for the whole tally
  system before executing the loop.
- **Floor-contract rows.** `docs/ember-floor-contract.md` preserves launch
  vehicle deferrals such as diffusion/dLLM and external research intake. These
  are watch rows, not first MVP blockers.
- **Multimodal placeholders.** `docs/ember-multimodal-v0-config-spec.md`
  reserves multimodal token plumbing, but Stage-1 remains FAIL until
  bidirectional heldout PASS; do not treat reserved ids as multimodal training
  evidence.
- **World/model compiler and transfer registers.** `docs\world-model-compiler-
  decision.md`, `docs\wmc-cross-world-transfer-prereg.md`, and related
  formalization docs are future substrate for predictive latent branches. MVP
  should mine them only when building the actual rollout artifact.
- **Optimizer/kernel/pretrain registers.** c04, fp44, density, Muon/NS5, and
  compute-ceiling documents are owned-core scale-up context. They are deferred
  until the first MVP loop proves technique, not size, is no longer the binding
  constraint.
- **Sleep consolidation and NC-K harness docs.** `sleep-consolidation-spec-v0`,
  `nck-*`, `sp5`, and `sp6*` docs remain important for the resident organism,
  but the first MVP must not block on full founder-likeness unless the current
  loop cannot run without it.
- **Work-ahead and trigger ledgers.** `work-ahead-ledger.md`,
  `trigger-readiness.md`, and open trigger-gated issues remain searchable
  context. They become MVP work only through an explicit blocker-reduction
  receipt.
- **the-search kill ledger and F-stage hygiene.** `<local-path>`
  frames the-search as the empirical fore-runner of Ember's recursion class:
  retrospective discriminator does not imply prospective guide, action-blind
  prediction does not produce task progress, fixed vocabularies cap transfer,
  and deletion-load-bearing must be tested on novel held-out tasks. MVP inherits
  this as a constraint layer for Psi, D-gate scope, and growth gates, not as a
  detour away from the current loop blocker.

## Source Coverage Audit

This document now carries the main load-bearing inheritance, but the coverage
boundary is explicit so partial history does not get mistaken for complete
history.

### Mapped Into The MVP Contract

- `GOAL.md`: origin constraints for local residency, receipt-only truth, own
  experience, non-load-bearing founders, bounded resource use,
  harness-as-organ, replay/rollback, and numeric completion are represented in
  `What Maximally Means`, `MVP-Critical Now`, `MVP Prerequisites`, and
  `History, Drift, and Lost-Work Ledger`.
- `<local-path>`: architectural corrections are represented
  as proof-plan requirements for predictive latent branches, non-degenerate B
  arm rollout evidence, receipt-to-update assimilation, contraction/stability
  growth gating, and bounded FP/STATE control-plane compaction.
- Current open issues: `#328`, `#282`, `#273`, `#223`, `#210`, `#205`, and
  `#128` are represented as dormant trigger-gated threads, not current MVP
  blockers.
- Current loop receipts and cycle-spine status: production sandbox evidence,
  real governor binding, local state-substrate replay/rollback, official
  runner attempts, Kaggle dataset/Benchmarks probes, prepared sample
  submissions, and the first blocked core-loop attempt are represented in
  `Evidence`, `Do Not Infer`, and `Next`.
- `STATE.md`: the single-position chronology is represented below as the
  origin/rung/pivot map that led from NC0 through owned-core/pretrain,
  ceiling-first, multimodal readiness, branch-drift repair, and world-model
  compiler hooks into this MVP contract.
- Deviation and preregistration surfaces: `docs\deviations.md`, `fp33-*`,
  `fp34-*`, `fp36-*`, `fp41-*`, world-model compiler, and multimodal launch
  preregs are represented below as invariant rules. They no longer survive as
  ambient authority outside this spec.
- Main deferred technique families: completeness/tally, floor contract,
  multimodal placeholders, world-model/compiler transfer docs,
  optimizer/kernel/pretrain registers, sleep consolidation, NC-K harness docs,
  and trigger/work-ahead ledgers are represented as either prerequisites,
  post-MVP, dormant, or reattachment candidates.

### Source Families Reduced Into This Spec

- `docs\closed-issues-enumeration.txt` contains the broader closed issue
  history across engineering, math, reasoning, spec, and first-principles
  threads. This document now reduces every closed issue row into
  MVP-critical, prerequisite, deferred, dormant, or excluded status. The file
  has `TOTAL_CLOSED=143` rows: `eng=68`,
  `first-principles=28`, uncategorized/blank lane rows `=28`, `math=8`,
  `spec=7`, `reasoning=2`, and `trigger-gated=2`. The visible closed families
  include verifier/security, sandbox/replay/rollback, governor/pacing, receipt
  schema and byte stability, owned-core/pretrain/token-shard gates,
  floor/frontier/world admission, NC-K/sleep/resident harness, E2B-surpass
  duty/eval surfaces, kernel/fp8/recompute performance work, mailbox/CU
  surfaces, and completeness/tally. The issue-id partition below covers every
  closed row exactly once.
- `STATE.md`, preregistration/deviation docs, and tracked `receipts\` are
  reduced below at the level that can change the MVP contract. Older rows that
  do not alter `MVP-Critical Now`, `MVP Prerequisites`, `Do Not Infer`, or
  `Next` remain provenance, not unbounded current work.

### Closed Issue Row Reduction

This table keeps the closed-history reduction inside this same final spec
instead of fragmenting it into a sidecar artifact. Each issue id from
`docs\closed-issues-enumeration.txt` appears exactly once.

| MVP inheritance class | Closed issue ids | Why this is the inherited status |
| --- | --- | --- |
| MVP-critical / prerequisite proof rails | `1`, `2`, `5`, `6`, `7`, `8`, `9`, `10`, `21`, `25`, `27`, `29`, `30`, `31`, `32`, `38`, `54`, `63`, `68`, `75`, `76`, `86`, `88`, `92`, `103`, `104`, `105`, `107`, `114`, `116`, `129`, `131`, `146`, `150`, `151`, `175`, `179`, `186`, `190`, `192`, `206`, `212`, `216`, `218`, `234`, `238`, `247`, `248`, `251`, `253`, `323`, `337` | Verifier correctness, sandbox/replay, governor/pacing, receipt byte stability, fail-closed gates, provenance, launch-interruption taxonomy, completeness tally, and control-plane hygiene are inherited as rails for the first loop. They do not replace the benchmark blocker; they constrain how the blocker can be removed. |
| External task, world, and benchmark admission | `33`, `46`, `47`, `71`, `117`, `154`, `166`, `199`, `268` | World-choice, HumanEval/ARC/GSM8K/floor probes, the-search component mining, and OOD/frontier checks are inherited as benchmark/world admission context. They become current only if they yield or validate the replacement external per-task score surface. |
| Corpus, license, dedup, and data provenance | `57`, `70`, `73`, `80`, `85`, `94`, `96`, `97`, `100`, `101`, `122`, `127`, `130`, `160`, `168`, `172`, `183`, `185` | License-clean corpus construction, idiom contamination checks, dedup accounting, tokenizer/shard provenance, and per-source mix receipts are preserved as fuel and safety rails. They are not first-loop proof unless the current loop consumes that data or its receipt-trained operator. |
| Training arms, transfer math, and performance techniques | `3`, `4`, `24`, `26`, `36`, `39`, `52`, `60`, `78`, `90`, `106`, `120`, `132`, `140`, `142`, `167`, `194`, `195`, `198`, `200`, `220`, `229`, `230`, `231`, `240`, `264`, `284`, `289`, `294`, `296`, `298`, `301`, `305`, `313`, `316`, `335` | Historical GRPO, MTP, LoRA/full-FT, band-transfer, checkpoint probes, trainer routing, sampler economics, fp8/recompute/cuda-graph work, and verdict dress rehearsals are inherited as evidence and technique candidates. They are post-blocker unless they directly produce the predictive rollout, receipt-to-update operator, or measured loop gain. Ordinary GRPO arms do **not** satisfy the active RLM/iGRPO harness-native training organ; RLM, iGRPO, and the clean-room avir-cli harness are binding and non-killable under the Goal Clear Condition. |
| Owned-core / pretrain scale path | `23`, `28`, `37`, `111`, `123`, `135`, `139`, `181` | External stack surveys, NC2 recipe assembly, core-size feasibility, checkpoint-resume, pretrain preregs, and launch-gate repair preserve the owned-core route. MVP may use smaller artifacts first; owned-core scale is not allowed to displace first closed-cycle proof. |
| Resident harness, founder-facing, and E2B-surpass surfaces | `34`, `35`, `201`, `213`, `254`, `255`, `256`, `257`, `259`, `260`, `261`, `262`, `269`, `271`, `307`, `311`, `331` | NC-K, sleep consolidation, heartbeat/event loop, mailbox/CU, protected invariants, duty battery, seat adapters, registry gates, and E2B-surpass work are preserved as resident-organism and comparison tracks. They are not first MVP proof unless required to execute or evaluate the closed loop. |
| Dormant trigger-gated probes | `208`, `320`, `326` | Coverage-obligation discharge, selective-recompute activation, and 1B INFO interpretation are inherited only when their named trigger fires or they are rewritten against the current loop blocker. |

Partition verification: the closed issue source has `143` rows; the seven rows
above contain `143` issue ids, `143` unique issue ids, no missing ids, and no
duplicates. Any future issue-row extraction must change `MVP-Critical Now`,
`MVP Prerequisites`, `Do Not Infer`, or `Next`; otherwise it is archival
annotation and not part of this goal's completion boundary.

### STATE Chronology Reduction

`STATE.md` is the single-position ledger for the pre-MVP Ember history. The
MVP inherits its chronology as constraints, not as a second spec.

| Chronology band | Evidence in `STATE.md` | MVP inheritance |
| --- | --- | --- |
| 2026-06-09 origin and T0/T1 | Goal adopted; T0 preflight passed; local ARC harness and sandbox selftests passed; early smoke runs produced harness-clean zero or near-zero verify rates. | Ember began as receipt-gated verified-experience accumulation, not as generic model training. MVP keeps the same receipt-only truth and local-machine boundary, but cannot treat smoke zeros as proof of failure or success. |
| 2026-06-10 GOAL rewrite and NC0 ladder | GOAL was superseded to require owned layers, self-verified experience, persistence, receipts-only truth, and scaffolding-off end condition; NC0 borrowed-core rehearsal and NC2-own destination were registered. | MVP may use scaffolding and small borrowed artifacts only to prove the loop. It must keep scaffold-vs-Ember-owned surfaces visible and prevent borrowed-core progress from being mistaken for terminal Ember. |
| 2026-06-10 ARC crash, governor, and small-core reroute | The 7B eval froze/starved the PC without a receipt; fix-forward under headroom violation was banned; governor, VRAM cap, chunking, replay, and small-core-first routing were introduced. | Comfortable residency is a correctness condition. Any maximally viable loop must close under governor/headroom receipts and bounded chunks; large runs that break residency are regressions even if they look more ambitious. |
| 2026-06-10 ARC verdict and W-code pivot | ARC-1 at 1.5B/3B had too low a heldout floor for useful accumulation deltas; W-code/MBPP was admitted as denser verification world; ARC became transfer surface. | MVP must prefer an external scored surface with enough per-task signal over inherited prestige. Benchmark choice is load-bearing: if MLE is blocked, replacement must emit real per-task rows, not just readiness or public-test shape. |
| 2026-06-11 round-2 null and owned-core gating | G1/W-code round-2 showed no advancing arm on OOD validation; fp-25 decomposed learning-vs-transfer; corpus/tokenizer/pretrain gates and owned-core feasibility were built. | The MVP cannot equate adapter bytes or one flat eval with recursive growth. It must show a receipt-to-update operator changes later behavior under matched controls; owned-core scale remains downstream of loop proof. |
| 2026-06-12 user stop and ceiling-first rule | User stopped a >1h run and required solving ceiling problems before long runs; trigger conditions tied to partial checkpoints were re-derived and held. | `<=24h` closure and shorter controlling loop receipts are not administrative preferences. They are the product boundary; partial long-run artifacts cannot silently fire old triggers. |
| 2026-06-12 to 2026-06-13 compute ceiling and optimizer/runtime pivots | c04/fp38/fp39/density, Muon/AdamW, fp8/recompute, and runtime/optimizer work repriced pretrain feasibility and exposed borrowed optimizer/runtime assumptions. | These are inherited as technique candidates and owned-layer pressure, not first-loop blockers. They become MVP-critical only if they directly remove the current loop blocker or implement predictive rollout / receipt-to-update behavior. |
| 2026-06-13 research-intake and exteroception | Research intake, teacher admission, Cosmos/OpenMDW, LiteRT, and exteroception notes registered the rule: external research is absorbed through local probes and receipts, never belief. | Kaggle, MLE-bench, Kaggle Benchmarks, public datasets, and future benchmark surfaces must enter through local receipts with source/provenance boundaries. External authority is not an MVP proof. |
| 2026-06-16 multimodal prelaunch and branch-drift repair | Readiness went 3/3; floor-probe prereg and #33 world-model compiler transfer hooks were frozen; branch drift showed local truth could diverge from remote; stale maintainer-facing brief text was corrected. | The MVP spec must stay remote-backed and internally consistent. Multimodal/world-model compiler ideas are preserved as predictive latent-branch substrate, but readiness packets, branch activity, or stale prose cannot substitute for the closed loop. |
| Standing pending/cancelled layers | Pending layers include round-2 self-generated episodes, contamination probes, 7B idle evals, branch registry, NC-K, teacher probes, release scans, and later worlds; cancelled layers preserve kill-with-successor lessons. | Lost work is not dropped; it is trigger-gated. A layer becomes current MVP work only by reducing the latest loop blocker, implementing a required architectural primitive, or producing a receipt that changes `Next`. |

The chronology reduction is complete at the level that changes the MVP
contract. If a future `STATE.md` reread finds an individual historical
invariant that would change `MVP-Critical Now`, `MVP Prerequisites`, `Do Not
Infer`, or `Next`, it must be moved into that section of this same document
before the affected next action is executed.

### Preregistration And Deviation Invariant Reduction

The prereg/deviation docs are inherited as binding measurement discipline. They
do not create extra loop work unless they remove the latest named loop blocker
or implement an MVP architectural primitive required by the next receipt.

| Source family | Invariant inherited into the MVP | MVP status |
| --- | --- | --- |
| `docs\deviations.md` / fp-30b protocol | Frozen preregs may change only through a deviation filed before the changed run; post-data edits void the frame. | MVP decisions must not move bars after seeing receipts. Any benchmark, growth, or world-model criterion changed during execution needs an explicit pre-run deviation in this same spec. |
| `docs\fp33-surpass-prereg-v1.md` plus DEV-001 | E2B-surpass requires paired, seat-swapped, matched-compute, receipt-backed bars; DEV-001 adds a multimodal A4 bar so text-only success cannot masquerade as surpassing a multimodal opponent. | Preserved as post-MVP / resident-harness comparison. Not first-loop proof, but its matched-compute, seat-swap, no-prose-verdict discipline constrains any future "better than" claim. |
| `docs\fp34-owned-band-prereg-v1.md` | Band predicates freeze from round-1 receipts before round-2 outcomes; yield prediction is separate from transfer proof; a predictive band only becomes a policy after a successor matched-budget test. | Preserved as growth-allocation discipline. The MVP may not promote sampling/allocation heuristics from retrospective patterns without a frozen manifest and held-out transfer receipt. |
| `docs\fp36-1b-info-interpretation-v0.md` | INFO probes are calibration only unless the frozen protocol says otherwise; no bar movement, early kill, or run intervention may follow from an informational checkpoint. | Current MVP trigger-gated. Partial/diagnostic receipts cannot fire old planned work or justify changing `Next` unless the trigger and action were frozen before the receipt. |
| `docs\fp41-graded-probe-spec-v1.md` | Binary probe counts can manufacture false power through pseudoreplication; powered claims need the right unit of analysis, graded deterministic metrics, and no model judge. | Inherited as benchmark/statistics guardrail. MVP external score rows must make the statistical unit and metric explicit; public-test counts or fixture scores cannot stand in for powered evidence. |
| `docs\world-model-compiler-decision.md` and `docs\wmc-cross-world-transfer-prereg.md` | One shared world-model and one shared harness skeleton; worlds differ by adapter (dataset, verifier, action codec), not cloned verification contracts. Cross-world transfer requires shared substrate. | Required seam, not first compiler build. MVP should avoid welding single-world assumptions into the harness; building a full compiler waits until acting-in-worlds needs it. |
| `docs\v0-multimodal-floor-probe-prereg.md` and multimodal launch preregs | Multimodal grounding is judged by a frozen held-out, disjoint-by-construction, no-model-judge probe; checkpoint verdict maps mechanically to continue/halt/bounded extension. | Preserved as multimodal proof discipline. Stage-1 or multimodal claims remain blocked without the frozen held-out PASS receipt; readiness packets or token plumbing are insufficient. |

The prereg/deviation reduction is complete at the level that changes the MVP
contract. Future per-row extraction is required only where a specific prereg
line changes `MVP-Critical Now`, `MVP Prerequisites`, `Do Not Infer`, or
`Next`.

### Receipt Family Reduction

The tracked `receipts\` tree is inherited by proof role, not by treating every
receipt as current work. Mechanical inventory: `484` tracked receipt files;
the family classifier below covers `484` unique tracked receipt files with
`0` uncovered.

| Receipt family | Count | MVP inheritance |
| --- | ---: | --- |
| Current Ember MVP / Kaggle receipts | 51 | These are the current proof surface: retired competition-lane attempts, Kaggle Benchmarks probes, external-heldout wheels, trained fallback wheel, Windows sandbox, core-loop attempt, growth, readiness, self-growth operator, supporting 3h scale-up, D3-Gym research-benchmark admission, candidate generation, the generated-C eight-task research loop, the cycle/readiness binding that consumes it, and the repeated-cycle D3-Gym growth receipt. The v6 downloadable Kaggle external-heldout cycle plus growth receipt seeded the self-growing operator route; the 3h scale-up receipt is supporting evidence, not the gate before docs/research/journal work. The D3-Gym v7 research route has historical readiness receipts, but `MVP_READY`, `failed_requirements=[]`, and `GROWTH_READY` are historical labels, not active authorization; the active blocker remains the Current Blocker Packet in this single `GOAL.md`. |
| Stage-1 multimodal / ER launch receipts | 21 | These preserve multimodal floor, ER-2/3/4 launch-readiness, B-MULTI acquisition, multimodal delta/gating, and multimodal throughput evidence. They are inherited as multimodal proof discipline and launch context, not as Stage-1 PASS or MVP readiness. |
| NC0 ARC / W-code loop receipts | 116 | These preserve the original verified-experience accumulation lineage: ARC smoke/floor, T2/T3/T4/T5, W-code floor/ingest/eval, G1 verdicts, GRPO/MTP/SFT/control arms, and p/d gates. They justify the loop shape, matched controls, and dense-world pivot; they do not displace the current external benchmark blocker. |
| Verifier, sandbox, receipt-hygiene, and statistics receipts | 67 | These are inherited as fail-closed proof rails: verifier soundness/exploit/timing, reachability, byte stability, receipt checking, power helpers, WSL/Windows notes, gate stats, dry-run resume integrity, and registry checks. They constrain the MVP but are not standalone progress unless a failed loop receipt names that rail. |
| Owned-core, pretrain, corpus, tokenizer, and checkpoint receipts | 50 | These preserve the owned-core route, license-clean corpus, tokenizer/token-shard gates, checkpoint probes, launch gates, round-local loop receipts, license sidecars, and resume drills. They are post-first-loop substrate unless used by the current loop or by a receipt-trained operator. |
| Optimizer, runtime, density, and compute-ceiling receipts | 71 | These preserve c04/fp38/fp39/density/Muon/fp8/recompute/runtime evidence. They are inherited as technique and residency constraints; parameter/optimizer/runtime work becomes MVP-critical only if it removes the loop blocker or enables the required predictive rollout / receipt-to-update primitive. |
| Resident harness, founder-facing, tally, and surpass receipts | 100 | These preserve NC-K, heartbeat, sp6 duty/seat work, E2B-surpass prestage, eng-sync, special-id, and completeness/tally evidence. They remain resident-organism and numeric-closure tracks, not first MVP proof unless required to execute/evaluate the closed loop. |
| World-adapter and miscellaneous smoke receipts | 8 | Arcade, cross-core, provenance, v-gate, and early smoke/proxy receipts are retained as world-adapter/provenance context. They become current only through an admitted benchmark/world adapter or a changed `Next` receipt. |

Receipt-family reduction is complete at the level that changes the MVP
contract. Mechanical partition verification: `git ls-files receipts` returns
`484` tracked receipt files; the eight rows above contain `484` primary-family
assignments and `0` uncovered files. Future per-receipt extraction is required
only if an old receipt contradicts or changes `MVP-Critical Now`, `MVP
Prerequisites`, `Do Not Infer`, or `Next`. Otherwise the old receipt remains
provenance, not an active requirement.

### Completion Audit For This Goal

The goal requirement is satisfied inside this single document as follows:

| Objective requirement | Evidence in this spec | Status |
| --- | --- | --- |
| Trace Ember history, context, and origins | `History, Drift, and Lost-Work Ledger`, `STATE Chronology Reduction`, and `Closed Issue Row Reduction` reduce the origin threads, chronology bands, and closed issue history into MVP constraints. | Satisfied for the current source set. |
| Identify drift and misunderstandings | `Drift and Misunderstandings To Prevent`, `Do Not Infer`, Kaggle lane separation, readiness-vs-loop language, and branch/stale-prose warnings name the drift modes that would misdirect execution. | Satisfied for the current source set. |
| Preserve lost ideas, techniques, stubs, and planned/deferred work | `Lost Ideas, Stubs, And Deferred Work To Reattach Deliberately`, `Inheritance Map`, closed issue classes, STATE pending/cancelled layers, prereg invariants, and receipt families assign each inherited thread to MVP-critical, prerequisite, post-MVP, dormant trigger-gated, or excluded status. | Satisfied for the current source set. |
| Define what `MAXIMALLY` means | `What Maximally Means` defines maximally as the smallest artifact that inherits every load-bearing thread by executing, prerequiring, deferring with trigger/proof boundary, or excluding with reason; it rejects readiness and size as substitutes for the first externally scored self-improving loop. | Satisfied. |
| Keep final specs non-fragmented | This file is the active Codex goal source for the active/resumable goal. Repo `GOAL.md` must be byte-synced to this text before goal-mode execution; if it is not, the first valid action is source reconciliation with `invalid_goal_source_split`, not Ember-cycle work. Sidecars such as `docs/ember-debt-ledger.md` support the packet but cannot override it. | Satisfied locally only when sync and git preservation receipts exist. |

The completion boundary is not "all possible future rereads of every old
artifact." It is current-state inheritance of decision-changing historical
threads into this final spec. If future source changes or a newly inspected old
row contradicts `MVP-Critical Now`, `MVP Prerequisites`, `Do Not Infer`, or
`Next`, this same document must be updated before that contradiction can steer
execution.

## Evidence

- Active resume front door: `<local-path>`.
- Clean code/spec worktree: `<local-path>`, branch `stage1-zero-claude-clean`.
- Dirty execution/data tree: `<local-path>`.
- Current Stage-1 status artifact: `<local-path>`.
- Best Stage-1 evidence named there: `convstem + latent_refine_steps=2 + contrastive1 + prototype0.10`, receipt `<local-path>`, heldout top1 image->word `0.222222`, word->image `0.166667`, chance `0.055556`, verdict `FAIL`.
- Existing source surfaces for the MVP boundary:
  - `<local-path>`
  - `<local-path>`
  - `<local-path>`
  - `<local-path>`
  - `<local-path>`
  - `<local-path>`
  - `<local-path>`
- Benchmark sources to preserve in the spec:
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
  - `http<local-path>`
- Kaggle dataset-lane receipt:
  `<local-path>`
  records `dataset_ref=abdallahwagih/emotion-dataset`, `file_count=2`,
  `total_bytes=832373`, and `verdict=MATERIALIZED`.
- Kaggle Benchmarks SDK/runtime receipt:
  `<local-path>`
  records `python_version=3.11.13`,
  `task_run_file_execution_ready=true`, and
  `verdict=READY_TO_RUN_PROBE_TASK`.
- Kaggle Benchmarks task/run-file receipt:
  `<local-path>`
  records `task_file_count=1`, `run_file_count=1`,
  `task_run_files_materialized=true`, and
  `verdict=TASK_RUN_FILES_MATERIALIZED`; it does not claim a benchmark score.
- Kaggle Benchmarks local score-shape receipt:
  `<local-path>`
  records `run_file_count=4`, `score_shape_ready=true`,
  `local_score_shape.metric_name=accuracy`,
  `local_score_shape.metric_value=1.0`, and
  `verdict=SCORE_SHAPE_RECEIPTED`; it keeps
  `benchmark_delta_claimed=false` and does not claim normalized improvement.
- Kaggle Benchmarks LiveCodeBench public-test pilot receipt:
  `<local-path>`
  records `source_example_present=true`,
  `benchmark_family=livecodebench/code_generation_lite`,
  `question_id=1873_A`, `public_test_passed=true`,
  `pilot_ready=true`, and `verdict=PILOT_PUBLIC_TEST_RECEIPTED`; it keeps
  `benchmark_delta_claimed=false` and does not claim normalized improvement.
- Kaggle Benchmarks LiveCodeBench candidate-vs-baseline public-test delta
  receipt:
  `<local-path>`
  records `baseline_public_pass=false`, `candidate_public_pass=true`,
  `public_test_delta=1.0`, `candidate_vs_baseline_ready=true`, and
  `verdict=PUBLIC_TEST_DELTA_RECEIPTED`; it keeps
  `benchmark_delta_claimed=false` and does not claim normalized improvement.
- Kaggle Benchmarks public-test proxy wheel/readiness receipts:
  `<local-path>`
  and
  `<local-path>`
  record `benchmark_public_test_proxy.ready=true`,
  `wheel_public_test_proxy.ready=true`, and `verdict=NOT_READY`. The failed
  requirements remain the real external benchmark rows and full A/B/C wheel
  rows, so this is not an MVP-ready or growth-ready claim.
- Kaggle Benchmarks frozen-heldout local delta receipt:
  `<local-path>`
  records `heldout_case_count=2`, `benchmark_delta_claimed=true`,
  `external_source_certified=false`, `external_benchmark_delta_claimed=false`,
  and `score.mean_normalized_improvement=1.0`.
- Kaggle Benchmarks frozen-heldout local delta CLI receipt:
  `receipts\ember-mvp\kaggle-benchmarks-frozen-heldout-cli-20260618\kaggle-benchmarks-livecodebench-frozen-heldout-delta-20260618T144017Z.json`
  was generated through
  `scripts\ember_mle_micro_harness.py --kaggle-benchmarks-livecodebench-frozen-heldout-delta`
  and records `heldout_case_count=2`, `benchmark_delta_claimed=true`,
  `external_source_certified=false`, `external_benchmark_delta_claimed=false`,
  and `score.mean_normalized_improvement=1.0`.
- Heldout-bound readiness receipt:
  `<local-path>`
  records `benchmark_frozen_heldout.ready=true` and `verdict=NOT_READY`;
  `benchmark.external_delta_positive` remains failed because the heldout data
  is local, not external-certified.
- Kaggle Benchmarks frozen-heldout A/B/C wheel receipt:
  `<local-path>`
  records `verdict=HELDOUT_WHEEL_RECEIPTED`, `ordering=C>B>A`,
  `benchmark_delta_claimed=true`, `external_benchmark_delta_claimed=false`,
  and arm improvements `A=0.1`, `B=0.2`, `C=0.4`.
- Heldout-wheel-bound readiness receipt:
  `<local-path>`
  records `wheel_frozen_heldout.ready=true` and `verdict=NOT_READY`. Remaining
  failed requirements are `benchmark.real_mle_tasks_executed`,
  `benchmark.per_task_scores_present`, `benchmark.external_delta_positive`, and
  `wheel.real_equal_budget_run`.
- Kaggle dataset external-source heldout receipt:
  `<local-path>`
  binds to the materialized `abdallahwagih/emotion-dataset` Kaggle receipt,
  verifies the source CSV hash, and records
  `external_source_certified=true`, `external_benchmark_delta_claimed=true`,
  `heldout_case_count=32`, and `score.mean_normalized_improvement=1.0`.
  It also records `candidate_prediction_source=fixture_gold_label_echo`, so it
  is scoring-path evidence, not trained Ember behavior.
- Kaggle dataset external-source heldout script-candidate receipt:
  `<local-path>`
  records `candidate_prediction_source=script:...`,
  `candidate_returncode=0`, `candidate_score=0.90625`, and
  `score.mean_normalized_improvement=0.842105` on the same frozen 32-row
  Kaggle heldout slice.
- External-heldout A/B/C wheel receipt:
  `<local-path>`
  records `ordering=C>B>A` and `external_benchmark_delta_claimed=true`.
- External-heldout-wheel-bound readiness receipt:
  `<local-path>`
  records `benchmark_external_heldout.ready=true`,
  `wheel_frozen_heldout.ready=true`, and `verdict=NOT_READY`. Remaining failed
  requirements are `benchmark.real_mle_tasks_executed`,
  `benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.
- Script-candidate external-heldout readiness receipt:
  `<local-path>`
  records `benchmark_external_heldout.ready=true`,
  `candidate_prediction_source=script:...`, and `verdict=NOT_READY`.
  Remaining failed requirements are still `benchmark.real_mle_tasks_executed`,
  `benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.
- Repo-preserved Kaggle dataset external-source heldout script A/B/C wheel:
  `receipts\ember-mvp\kaggle-external-heldout-script-wheel-20260618\wheel-heldout-20260618T135020Z.json`
  consumes three script-produced arm receipts preserved beside it. The arm
  scores are A=`0.052632`, B=`0.736842`, and C=`0.947368` mean normalized
  improvement, with `ordering=C>B>A`, `external_benchmark_delta_claimed=true`,
  and `verdict=HELDOUT_WHEEL_RECEIPTED`.
- Repo-preserved script A/B/C wheel-bound readiness receipt:
  `receipts\ember-mvp\kaggle-external-heldout-script-wheel-20260618\readiness-20260618T135119Z.json`
  records `benchmark_external_heldout.ready=true`,
  `wheel_frozen_heldout.ready=true`, and `verdict=NOT_READY`. Remaining failed
  requirements are `benchmark.real_mle_tasks_executed`,
  `benchmark.per_task_scores_present`, and `wheel.real_equal_budget_run`.
- Repo-preserved official MLE prepare attempt with MLE-bench venv:
  `receipts\ember-mvp\official-prepare-attempt-venv-20260618\mle-micro-official-prepare-run-20260618T140654Z.json`
  records `raw_audit_blocking_bypassed=true`, uses the MLE-bench checkout's
  `.venv` Python, reaches official dataset download, and blocks on Kaggle
  `401 Unauthorized` for `detecting-insults-in-social-commentary`. This proves
  the blocker has moved past local Python dependency wiring and into Kaggle
  official competition/API access.
- Repo-preserved Kaggle credential-surface probe:
  `receipts\ember-mvp\kaggle-auth-surface-probe-20260618\kaggle-auth-preflight-20260618T141735Z.json`
  records classic `kaggle.json` username/key shape present, KGAT
  `access_token` shape present, `legacy_kaggle_client_accepts_access_token=false`,
  and live legacy auth blocked by Kaggle `401 Unauthorized`. Treat the KGAT
  token as useful for newer bearer-token Kaggle SDK/dataset/Benchmarks lanes,
  not as proof that old MLE-bench competition hydration is authenticated.
- Repo-preserved prepared sample-submission receipts:
  `receipts\ember-mvp\official-sample-submissions-20260618\sample-bootstrap-after-materialize-20260618T011558Z.json`
  records `candidate_submissions_ready=true`, `copied_count=5`, and
  `missing_sample_submissions=[]` for the five frozen MLE micro tasks. The
  paired auto-grade receipts in the same directory show candidate submissions
  are available, but official grading remains blocked before real scores
  because private prepared answer files are absent.
- Repo-preserved fresh official A/B/C wheel-runner receipts:
  `receipts\ember-mvp\official-abc-wheel-runner-20260618\official-abc-wheel-runner-20260618T142652Z.json`
  records arms A, B, and C executed through the one-command official runner,
  each with `blocked_reason=official_grading_preflight_failed`,
  `candidate_submissions_ready=true`, and `real_mle_tasks_executed=false`.
  The wheel receipt records `equal_budget=true`, valid arm contracts, and
  `blocked_reason=benchmark_receipts_not_real`.
- Repo-preserved cycle-bound official runner readiness:
  `receipts\ember-mvp\cycle-official-runner-bound-20260618\readiness-20260618T143014Z.json`
  binds the fresh official runner into the top-level cycle with production
  sandbox, real governor, and local state-substrate evidence. It records
  `verdict=NOT_READY`; remaining failures are official MLE task execution,
  per-task scores, external delta, real equal-budget wheel execution, and
  C>B>A ordering.
- Repo-preserved dedicated Kaggle Benchmarks lane receipts:
  `receipts\ember-mvp\kaggle-benchmarks-lane-20260618\` preserves SDK/runtime,
  task/run materialization, score-shape, LiveCodeBench public-test pilot,
  candidate-vs-baseline public-test delta, and frozen-heldout local delta
  receipts. This is the modern Kaggle-native benchmark lane evidence; the
  public-test and local-heldout receipts remain bounded and do not claim
  external-source certification.
- Repo-preserved frozen-heldout CLI receipt:
  `receipts\ember-mvp\kaggle-benchmarks-frozen-heldout-cli-20260618\` proves
  the local LiveCodeBench heldout delta can be produced through the public
  harness CLI flag. It does not change the proof boundary: local-heldout
  evidence remains below external-source-certified benchmark proof and below
  official MLE-bench completion.
- Repo-preserved first core-loop attempt after the core-loop priority rule:
  `receipts\ember-mvp\core-loop-attempt-1-20260618\` was generated with:

```powershell
python scripts\ember_mvp_cycle.py --fixture-out <local-path> --production-sandbox --real-governor --state-substrate --official-wheel-runner --source-root <local-path> --data-root <local-path> --submission-root <local-path>
```

  It binds production sandbox evidence, real governed GPU training, local
  state-substrate replay/rollback, and the official A/B/C wheel runner into
  one cycle. The official runner reaches arms A, B, and C with equal budgets
  and valid arm contracts, but all benchmark receipts remain blocked before
  real official MLE scoring. The readiness receipt
  `receipts\ember-mvp\core-loop-attempt-1-20260618\readiness-20260618T151701Z.json`
  records `verdict=NOT_READY`, `growth_verdict=GROWTH_BLOCKED`, and failed
  requirements `benchmark.real_mle_tasks_executed`,
  `benchmark.per_task_scores_present`, `benchmark.external_delta_positive`,
  `wheel.real_equal_budget_run`, and `wheel.ordering_c_gt_b_gt_a`. This receipt
  is historical blocker evidence for the retired MLE route. It is not the
  current priority anchor while the downloadable Kaggle external-heldout route
  is active.
- Goal-clear Kaggle external-heldout loop receipt set:
  `<local-path>`
  is the current active benchmark route. It uses Kaggle CLI-downloadable
  `abdallahwagih/emotion-dataset`, the frozen 32-row external heldout hash
  `sha256:8ac3095b24ec913c849094fd7f5eab1a3846e95ccd9b3ecd3e58f84650638891`,
  and trained sklearn text classifier evidence for the C arm. The fresh C
  benchmark receipt is
  `arm-C-trained-2\receipts\benchmark\kaggle-dataset-external-heldout-delta-20260618T235631Z.json`
  with `baseline_score=0.40625`, `candidate_score=0.9375`, and
  `mean_normalized_improvement=0.894737`. The equal-budget wheel receipt is
  `wheel-v2\receipts\wheel\wheel-heldout-20260618T235813Z.json` with
  improvements A=`0.052632`, B=`0.736842`, C=`0.894737`, and `ordering=C>B>A`.
  The current repeated-cycle window is
  `cycle-bound-v4-after-doc-edits\receipts\cycles\cycle-20260617T000000Z-0001.json`,
  `cycle-bound-v5-repeat-growth\receipts\cycles\cycle-20260617T000000Z-0001.json`,
  and
  `cycle-bound-v6-repeat-growth\receipts\cycles\cycle-20260617T000000Z-0001.json`.
  The growth receipt is
  `growth\growth-contraction-stability-20260619T-repeat-v1.json`, with
  `repeated_positive_cycles=3`, `growth_allowed=true`,
  `monotone_non_decreasing=true`, `max_cycle_to_cycle_delta_movement=0.0`,
  and `next_cycle_ceiling.fits_24h=true`. The readiness receipt is
  `readiness\readiness-20260619T-growth-v1.json` and records
  `verdict=MVP_READY`, `growth_verdict=GROWTH_READY`,
  `failed_requirements=[]`, `benchmark_external_heldout.ready=true`,
  `wheel_frozen_heldout.ready=true`, `recursion_layer.ready=true`, and
  `growth_receipt.ready=true`. Under the current goal this is historical
  progress evidence for the downloadable Kaggle external-heldout route, not a
  clear of the active Goal Clear Condition, because it does not prove an ML/AI
  field-level breakthrough. It does not put docs/research/journal benchmark work after the scale-up
  receipt; it is the self-growing receipt set that routes the next active
  goal-clear action to a stronger docs/research/journal benchmark.
  The self-growing operator receipt
  `operator\self-growth-operator-decision-20260619T-v1.json` selects
  `bounded_scale_up` at `10800` seconds with `manual_selection=false`; the
  deleted-operator receipt
  `operator\self-growth-operator-deleted-20260619T-v1.json` blocks next-loop
  routing as `blocked_manual_selection_forbidden`; and the selected scale-up
  receipt `scale\scale-up-3h-20260619T-v1.json` records
  `verdict=SCALE_UP_READY`, `scale_factor=3.0`,
  `operator_decision.ready=true`,
  `benchmark_continuity.same_subset_as_growth=true`, and
  `next_cycle_ceiling.fits_24h=true`. This 3h scale-up receipt is supporting
  evidence only. It must not be treated as a prerequisite before D3-Gym,
  ScienceAgentBench, or another admitted docs/research/journal A/B/C loop.
  The active research-benchmark operator receipt
  `operator\self-growth-operator-research-benchmark-20260619T-v2.json` selects
  `stronger_external_benchmark` with `benchmark_family=research_journal` and
  `preferred_candidate=ScienceAgentBench`. ScienceAgentBench was replaced
  through the same operator route by D3-Gym because D3-Gym has public HF task
  rows and Docker-backed evaluators. The materialization receipt
  `<local-path>`
  records 8 frozen HF rows from `osunlp/D3-Gym`; the admission receipt
  `<local-path>`
  records `verdict=RESEARCH_BENCHMARK_ADMITTED`, `operator_routed=true`,
  `task_count=8`, `requires_docker=true`, and `docker_daemon_ready=true`;
  the candidate-generation receipt
  `<local-path>`
  records `manual_solution=false` and a load-bearing deleted-generator check;
  the deleted-generator receipt
  `<local-path>`
  records `verdict=CANDIDATE_GENERATION_BLOCKED`; and the current real
  research-loop receipt
  `<local-path>`
  records `verdict=RESEARCH_LOOP_ACCEPTED`, `ordering=C>B=A`, A=`0.125`,
  B=`0.125`, C=`1.0`, eight real D3-Gym score rows, reproducibility hashes,
  and `arm_c.manual_solution=false`. C passes all eight frozen D3-Gym tasks.
  The D3-Gym v7 loop is bound into fresh MVP cycle/readiness receipts at
  `<local-path>`
  and
  `<local-path>`.
  That readiness receipt records `verdict=MVP_READY`,
  `failed_requirements=[]`, `benchmark_mode=research_journal_replacement`,
  `wheel_mode=research_journal_replacement`, and `recursion_layer.ready=true`.
  The repeated D3-Gym growth receipt is
  `<local-path>`,
  and the readiness receipt that consumes it is
  `<local-path>`.
  That final readiness receipt records `verdict=MVP_READY`,
  `failed_requirements=[]`, `growth_verdict=GROWTH_READY`,
  `benchmark_research_loop.ready=true`, `wheel_research_loop.ready=true`,
  `recursion_layer.ready=true`, `repeated_positive_cycles=3`,
  `growth_allowed=true`, `max_cycle_to_cycle_delta_movement=0.0`, and
  `next_cycle_ceiling.fits_24h=true`.
- Repo-preserved trained external-heldout fallback wheel:
  `receipts\ember-mvp\trained-external-heldout-wheel-20260618\` keeps the
  external-source-certified Kaggle emotion heldout boundary and replaces the C
  arm's hand-authored script candidate with
  `candidate_prediction_source=trained_sklearn_text_classifier`. The trained
  C arm records `training_source=external_rows_after_frozen_heldout`,
  `training_case_count=5905`, and a hashable model metadata artifact. The
  wheel receipt records `ordering=C>B>A` with normalized improvements
  A=`0.052632`, B=`0.736842`, and C=`0.894737`. This is fallback benchmark
  progress superseded by the growth-ready receipt set above; it remains useful as
  prior route evidence, not as the active completion receipt.
- Audit verification anchors:
  - `scripts\ember_mvp_cycle.py` currently materializes the latent branch as a
    copied patch under `local-state\deltas\...` and binds verifier outcome as
    `verifier_result`.
  - `scripts\ember_wheel_harness.py` marks B as `uses_dream_loop=true` and
    `uses_latent_branch=false`, while C uses both. This confirms that the B arm
    cannot yet isolate a predictive latent-world-model contribution.
  - `scripts\ember_growth_harness.py` now emits the contraction/stability
    receipt that turns repeated positive cycles into growth proof; readiness
    must consume that receipt before reporting `GROWTH_READY`.
  - `GOAL.md` keeps first-principles issues constant by construction, and
    current `STATE.md`/`GOAL.md` are large enough that compaction must become a
    receipt-backed control-plane primitive rather than a prose convenience.

## Do Not Infer

- Do not treat `MVP_READY`, `GROWTH_READY`, `ready=true`, or any readiness
  receipt as active authorization merely because an earlier gate passed. Those
  terms are historical receipt labels unless a current blocker receipt cites
  them as input to the active blocker.
- Do not infer "docs/research/journal benchmark" means reading or answering about a
  research artifact, and do not infer the goal is to make Ember a research
  specialist model. The benchmark is a proxy for self-improvement by action:
  observation, hypothesis, experiment or derivation, evaluation, assimilation,
  proof, and reusable recipe.
- Do not infer "world-rule discovery" is the whole goal. It is one strong
  external measurement surface for Ember's broader target: recursive,
  deletion-tested, receipted self-improvement.
- Do not infer D3-Gym success, symbolic-task transfer, or multi-family transfer
  alone is a field-level breakthrough. "Field-level breakthrough" means an
  ML/AI field-level contribution: a new or materially improved method,
  architecture component, self-improvement mechanism, training/evaluation
  protocol, compression/inference technique, agent-learning substrate, benchmark
  methodology, or reproducible recipe that would matter beyond Ember's local
  benchmark run. Transfer/re-use is supporting evidence, not the definition.
- Do not infer MVP readiness language is still the governing frame. The
  governing frame is the self-improvement breakthrough loop and its ML/AI
  field-level breakthrough condition.
- Do not run another serious Ember cycle before the exact historical/modern
  benchmark discovery receipt and the past-Ember technique-mining receipt
  exist, unless the discovery itself emits a blocked receipt naming the missing
  artifact.
- Do not choose scaffolding, readiness, GitHub hygiene, docs, credential work,
  or harness polish while a harder core problem is available. Such work counts
  only when a receipt proves it directly removes the hardest named blocker and
  ends in an executed discovery-loop, transfer, deletion, persistence,
  owned-core, or deferred-work-closure receipt.
- Do not leave deferred work deferred at goal clearing. "Previously deferred"
  means "must now be completed, integrated, or killed with successor evidence,"
  not "allowed to remain outside the goal."
- Do not infer a headless `avir-cli` bridge, generated documentation, source inventory, wrapper launch, or goal-mode bootstrap adapter satisfies the clean-room `avir-cli` resident-harness precondition. Full parity means near-99% function, UI/UX, backend, and native Codex `/goal`-mode mechanics transplanted into Ember.
- Do not infer current an agent file/tool use, a resident harness scaffold, a Codex-driven
  action loop, a verifier reranker, or a historical GRPO arm already equals
  trained RLM/iGRPO behavior. The RLM/iGRPO organ must be model-learned,
  harness-native, before/after-positive, deletion-sensitive, and receipt-backed
  under the Goal Clear Condition.
- Do not infer a current or prior resident-training PASS satisfies RLM/iGRPO
  when it used no neural network, no neural parameter update, or only
  deterministic templates, scalar dictionary weights, symbolic routing,
  prompt-only steering, handcrafted action selection, or "RLM/iGRPO-style"
  wording. That result is `SYMBOLIC_PROXY_PASS` until the neural-update floor
  passes before/after, A/B/C/deleted, transfer, and deletion-sensitive tests.
- Do not infer GitHub is the target. Git is only the design model for a local substrate, and native Git is only allowed as v0 storage plumbing if promotion remains local and inspectable.
- Do not infer Windows parity until timeout, memory, filesystem, process-tree cleanup, network denial, replay, and verifier reward-hack probes pass under the Windows runner.
- Do not infer existing verifier, replay, governor, or NCK scripts are unified under one MVP boundary.
- Do not infer the current patch/delta latent branch is a predictive world
  model.
- Do not infer the current B arm proves dream-loop contribution while it lacks
  a latent rollout artifact.
- Do not infer adapter or checkpoint byte persistence alone proves recursive
  self-improvement; full receipt traces must feed a durable operator that
  changes later cycle behavior.
- Do not infer `blocked_until_repeated_positive_cycles=3` is sufficient growth
  evidence without a contraction/stability receipt.
- Do not let first-principles or ledger growth become an unbounded substitute
  for reducing the latest loop blocker.
- Do not infer inward benchmarks prove Ember before an external respected subset shows verified delta.
- Do not infer an MLE-bench Kaggle competition terms gate means all Kaggle data
  or Kaggle Benchmarks are blocked.
- Do not infer the KGAT access token can replace classic username/key auth in
  the legacy MLE-bench Kaggle client.
- Do not infer prepared sample submissions are private official answers or
  sufficient for real MLE-bench scoring.
- Do not infer the blocked official A/B/C runner is a real equal-budget MLE
  wheel or growth evidence.
- Do not infer cycle-bound official-runner readiness is MVP readiness while the
  receipt still records official benchmark and wheel failures.
- Do not infer Kaggle Benchmarks public-test or local-heldout receipts are
  external-source-certified benchmark proof.
- Do not infer a public Kaggle dataset is a benchmark without a frozen evaluator
  and baseline.
- Do not infer the repo-preserved Kaggle dataset external-heldout script wheel
  is an official MLE-bench wheel.
- Do not infer the repo-preserved first core-loop attempt is a growth claim; it
  is a blocked official-runner receipt for the retired MLE path, not the
  controlling post-growth blocker.
- Do not infer the trained external-heldout fallback wheel is official
  benchmark evidence or the current growth proof.
- Do not infer larger parameters are progress if they break closed-cycle completion within `<=24h`.
- Do not count transient context, prose summaries, or unreceipted state as durable assimilation.
- Do not escalate from Stage-1 near-miss to Stage-1 PASS without a bidirectional heldout PASS receipt.
- Do not infer a receipt-trace classifier or critic is a meta-cognitive
  learning operator unless it is prospective: it must condition on predicted
  next-cycle task progress and pass a deletion-load-bearing test on held-out or
  out-of-closure tasks.
- Do not infer a goal-mode run is complete because the docs, GitHub state,
  readiness gates, credential files, or benchmark probes improved. Completion
  requires a fresh successful loop receipt satisfying the Goal Clear Condition.
  A blocked-loop receipt must be reported as blocked, not complete, even when it
  correctly names the missing executable artifact and next runnable command.
- Do not infer the Kaggle emotion dataset clears the goal merely because it is
  downloadable. It clears the goal only when a fresh A/B/C receipt proves real
  external heldout, equal budget, before/after, positive delta, and
  reproducibility.
- Do not infer the Kaggle external-heldout growth-ready receipt is a public
  leaderboard result or a stronger-benchmark result. It is historical evidence for the prior MVP frame and does not clear the current resident-training gate, route gate, or growth gate.

## Next

1. Enforce the source-of-truth gate before touching Ember: sync this file into
   the governing repo `GOAL.md`, preserve it in git, and keep the local
   Codex goal copy byte-equivalent. If sync is not possible, stop with
   `invalid_goal_source_split`.
2. Verify the resident-training cursor, do not rerun it by default: confirm the
   PR #484 resident-training receipt exists and satisfies the permanent neural,
   RLM/iGRPO, `avir-cli`, `train_multimodal_v0.py`, and floor-manifest laws
   above. If verification fails, return to the resident-training gate. If it
   holds, continue from the current blocker.
3. Execute the current blocker directly: first try to remove a stronger external
   benchmark blocker without hiding partial materialization. PaperBench may only
   move from blocked to admitted after a hardened admission receipt records 20/20
   paper directories, required per-paper files, zero LFS pointer placeholders,
   and a runnable frozen slice. If PaperBench, RE-Bench, and ScienceAgentBench
   remain physically blocked, the fallback is a prospective native proposer on a
   frozen fresh surface selected under `--require-prospective`, not another
   same-slice D3 patch or repaired failed-slice replay.
4. If a stronger benchmark is admitted, run the first matched A/B/C/deleted loop
   on that benchmark. If it blocks, write the blocked receipt and either remove
   the exact blocker named by that receipt or consume it as training signal for
   the prospective proposer path.
5. `/goal complete` remains invalid until a later fresh external heldout A/B/C
   loop proves equal budget, before/after, positive delta, reproducibility,
   native/non-Ember ablation, and the stricter ML/AI field-level contribution
   receipt. The resident-training PASS, tiny BitNet PASS, benchmark discovery,
   and task9 D3 PASS, generalized D3 PASS, ScienceAgentBench artifact-materialization blocked, RE-Bench admission, RE-Bench first-loop blocked, and PaperBench blocked receipts are necessary progress receipts, not completion.

The D3/Kaggle/native-proposer chronology below is preserved as historical
evidence and as a trigger-gated lower-precedence path. It is not the active
current blocker unless a fresh current receipt names it as such.
- Historical D3/Kaggle receipt chronology: treat the D3-Gym admission, candidate-generation, and generated-C loop
   receipts as historical research
   benchmark state:
   `<local-path>`
   and
   `<local-path>`
   and
   `<local-path>`.
   Before the resident-training gate was added, the benchmark blocker was no longer benchmark materialization, one-task smoke
   execution, two-task execution, parser correctness, manual C placement,
   missing output families for tasks 4-8, cycle/readiness binding, repeated
   D3-Gym growth proof, field-method comparison, native real-code selection,
   the first bounded public-test eval, or replacing the static solver registry
   at the nine-row public-test level, or crossing into the fifteen-row
   Codeforces/LeetCode functional public-test surface, the bounded private15
   decoded-test surface, the adaptive private30 selector surface, or the
   public-example synthesis private6 surface. The public-program synthesis
   private12 surface is now a no-gain repair receipt, not a positive rung. The
   public-prompt synthesis private12 and r2 surfaces are also no-gain repair
   receipts, and r3 is another no-gain repair receipt with a public-pass/
   private-fail `constructProductMatrix` schema. The receipt-conditioned prompt
   repair private12 surface is also a no-gain repair receipt. The first
   public-I/O enumerative substrate can infer a synthetic affine program from
   public examples, but its fresh private12 receipt generated zero real
   candidates, scored `0.0`, and lost to the prior prompt proposer at `4/12`.
   The r2 enumerator repair then expands the DSL and scores `5/12` on that same
   external slice, beating prompt-control `4/12` and deletion `0/12`. This is a
   real positive external-heldout delta but remains a hand-authored repair after
   receipt inspection. A later fresh-slice transfer at `start_index=120` then
   fails with C=`0/12`, prompt-control B=`2/12`, and deletion=`0/12`. The r3
   receipt-conditioned repair uses that failed transfer receipt to unlock
   candidate generators and scores C=`8/12`, prompt-control B=`2/12`, and
   deletion=`0/12` on the exposed transfer-failure slice. The r3 fresh transfer
   at `start_index=132` then fails with A/B/C/deleted all `0/12`; the positive
   r3 prior had no relevant failed-family keys for the new rows. The next task
   was to consume that failed transfer receipt as the growth signal. The r4
   repair does so and improves the exposed slice to C=`4/12`, B=`0/12`,
   deletion=`0/12`, but this is still same-slice repair. The r4 fresh transfer
   at `start_index=144` then fails with all arms `0/12`. The r5 repair consumes
   that failed transfer receipt and improves the exposed slice to C=`6/12`,
   B=`0/12`, deletion=`0/12`, solving `findPeaks`,
   `maxSubarrayLength`, `numberGame`, `findMissingAndRepeatedValues`,
   `removeAlmostEqualCharacters`, and `minimumAddedCoins`. This is still
   same-slice repair after failure inspection. The r5 fresh transfer at
   `start_index=156` then fails with all arms `0/12`; the positive r5 prior
   exposes no failed-family keys for the new rows. The r6 repair consumes that
   failed r5 transfer receipt and improves the exposed slice to C=`6/12`,
   B=`0/12`, deletion=`0/12`, solving `missingInteger`,
   `maxFrequencyElements`, `hasTrailingZeros`, `minOperations`,
   `areaOfMaxDiagonal`, and `incremovableSubarrayCount`. This is still
   same-slice repair after failure inspection. The r6 fresh transfer at
   `start_index=168` then fails with all arms `0/12`; the positive r6 prior
   exposes no failed-family keys for the new rows. The r7 repair consumes that
   failed r6 transfer receipt and improves the exposed slice to C=`7/12`,
   B=`0/12`, deletion=`0/12`, solving `largestPerimeter`, `minimumCost`,
   `maximumSubarraySum`, `countMatchingSubarrays`, `flowerGame`,
   `canSortArray`, and `minimumTimeToInitialState`. This is still same-slice
   repair after failure inspection. The r7 fresh transfer at `start_index=180`
   then fails on the final `10`-task tail with all arms `0/10`. The next task
   was to consume the failed r7 transfer receipt as the growth signal. The r8
   repair does so and improves the final tail to C=`6/10`, B=`0/10`,
   deletion=`0/10`, solving `countPrefixSuffixPairs`,
   `returnToBoundaryCount`, `countKeyChanges`, `isPossibleToSplit`,
   `minOperations`, and `resultArray`. This is still same-tail repair after
  failure inspection, and the filtered LeetCode functional tail is now
  exhausted for later-slice transfer. R9 broadens the benchmark substrate to
  Codeforces stdin rows and proves fresh transfer on the Codeforces portion of
  a later slice, but the later mixed slice exposes the next blocker: mixed
  stdin/functional substrate selection and fixed-template dependence. R10
  repairs the mixed-substrate selector and proves later fresh transfer, so the
  next task is to replace the hand-authored family-cache/template approach with
  a more prospective proposer or learned candidate-space growth under a
  no-private-leakage contract, then scale toward a learned/prospective
  generator. R11 compresses the functional candidate search by using the public
  function signature to propose one matching fixed template per row: the
  signature15 receipt scores C=`15/15` with `15` total candidates and deletion
  C=`0/15`. The later signature20 transfer fails with C=`0/20` while the
  prompt-control B scores `1/20`, proving that signature routing does not solve
  rows whose required method is absent from the fixed template set. R12 consumes
  that failed transfer receipt and adds five receipt-conditioned candidate
  families; the exposed r11-failure repair scores C=`5/20`, B=`1/20`, and
  deleted=`0/20`. The later fresh transfer at `start_index=50` then fails with
  C=`0/20` while the public-prompt control scores B=`18/20`. The current
  blocker moves through R13: `hybrid_prompt` mode lets C reuse B's public-prompt
  candidates and add C-specific receipt-conditioned repairs. The exposed repair
  scores C=`19/20`, B=`18/20`, deleted=`0/20`, but the later fresh transfer at
  `start_index=70` ties B at C=`11/20`, B=`11/20`, deleted=`0/20`, with no
  C-only fresh passes. R14 consumes that failed fresh-transfer receipt and adds
  six C-specific receipt-conditioned candidate families; the exposed repair
  scores C=`15/20`, B=`11/20`, deleted=`0/20`, with C-only passes on
  `minimumTime`, `isAcronym`, `countSymmetricIntegers`, and `canBeEqual`. The
  later fresh transfer at `start_index=90` scores C=`1/20`, B=`0/20`,
  deleted=`0/20`, via the existing public-I/O algorithmic-shape candidate for
  `countWays`/happy-students. This is deletion-sensitive positive
  fresh-transfer evidence, but it is tiny and does not clear native self-growth
  or ML/AI field-level breakthrough. R15 shifts from named failed-row family
  patching toward reusable public-I/O shape candidates: cyclic string
  subsequence, origin-distance string, interval-union point count, and maximum
  odd binary arrangement are generated without a prior failure receipt and
  selected only by public cases. The exposed r15 repair at `start_index=90`
  scores C=`5/20`, B=`0/20`, deleted=`0/20`; the later fresh transfer at
  `start_index=110` scores C=`10/20`, B=`6/20`, deleted=`0/20`, with C-only
  wins on `minSizeSubarray`, `maximumTripletValue`, `sumCounts`, and `minSum`.
  This is stronger deletion-sensitive fresh-transfer progress, but it is still
  a small hand-authored shape-library expansion rather than a native learned
  proposer or ML/AI field-level breakthrough. R16 updates the native goal organ
  so the r15 receipt, not Codex/manual prose, selects
  `native_public_io_proposer_growth`; deleting the native organ regresses
  selection to disallowed `native_goal_organ_missing`. This repairs the
  next-blocker ownership surface for the current loop, but it is still
  selection/provenance progress only. After the resident-training gate passes, the post-gate blocker is to
  execute the native organ's selected action: turn receipt-conditioned and
  public-shape growth into a more prospective C-specific proposer or learned
  candidate-space growth path under the no-private-leakage contract, then test
  it on a later fresh heldout slice with deletion. R17 implements that first
  native proposer policy: it learns `enum:list_int` and `enum:two_int_lists`
  prefixes from four r15 C-only successes, integrates the policy into the
  public-I/O operator, and proves deletion removes the learned policy. The r17
  steered fresh transfer at `start_index=130` scores C=`0/20`, B=`0/20`,
  deleted=`0/20`, and the unfiltered comparison also scores C=`0/20`. This is
  an integrated failed attempt: the blocker is no longer "make the proposer
  exist" or "wire the operator to consume it"; it is candidate/proposer
  expressivity on fresh rows under the native no-private-leakage contract, not
  more same-template routing, exposed-slice family patching, prompt reuse alone,
  unchanged prefix-policy reruns, or unearned duration scaling. Fixed schema
  growth, public-row template addition,
   public-shape-only reruns, unchanged prompt-schema reruns,
   receipt-conditioned family-patch reruns, synthetic-only affine probes,
   unchanged enumerator reruns, hand-authored post-hoc patching, same-slice
   victory laps, or duration growth cannot clear the goal. Any failed row must
   become the next loop or receipt rerun rather than prose.
10. Do not interleave readiness, retired-lane recovery, credential archaeology, Psi,
   the-search, ledger, GitHub, or harness-hardening work unless the latest loop
   receipt names that exact surface as a blocker to the downloadable Kaggle
   heldout path and the work ends in a rerun command.
11. In the next loop, preserve the audit-derived recursion layer rather
   than merely explaining its absence:
   - a predictive dream/model-rollout artifact for B;
   - a receipt-trained, prospective meta-cognitive operator that updates later
     cycle strategy from the full receipt trace without falling into
     retrospective-discriminator-as-guide;
   - a compaction receipt for dispatch-critical ledger state if `STATE.md` or
     issue/goal context is used to choose the next action.
   If one of these artifacts is absent, the loop receipt must mark the run
   blocked and the next action must implement that artifact. A prose block,
   design note, or explanatory receipt is not a substitute.
12. Gate growth:
   - the first three repeated positive `1h/1h/1h` closed cycles are now
     receipted; future scale-up must cite or supersede
     `growth\growth-contraction-stability-20260619T-repeat-v1.json`
   - require matched-control monotonicity and bounded cycle-to-cycle delta
     movement before accepting any successor growth receipt
   - import the-search-style hygiene where applicable: paired seeds,
     budget-enforced non-zero attempt counts, integer recounts, and explicit
     attribution for the component credited with the gain
   - require every scale increase to prove the next full closed cycle still fits `<=24h`
   - treat parameter growth that breaks closure as scale debt
13. A `/goal complete` outcome is acceptable only if the final state includes a
   fresh receipt proving the Goal Clear Condition through one of:
   - an operator-routed ScienceAgentBench or replacement world-rule discovery /
     docs/research/journal A/B/C loop receipt with real per-task/per-slice score
     rows, an explicit ML/AI field-level breakthrough claim, and transfer/re-use
     evidence supporting that claim;
   - a Kaggle Benchmarks A/B/C loop receipt with frozen external heldout, real
     per-task score rows, baseline, aggregate metric, arm contracts, and a
     reusable recipe or method that transfers beyond the scored instance.
   - a downloadable Kaggle external-heldout A/B/C loop receipt with real
     per-slice score rows only if the docs/research/journal admission receipt
     remains blocked and the rerun removes a named blocker instead of avoiding
     the stronger benchmark path; this fallback still needs a reusable
     field-level technique, not only an accuracy lift.
   A blocked-loop receipt is allowed only as a blocked handoff, never as
   `/goal complete`. Anything else is an incomplete goal, even if it improved
   scaffolding.

---

## Original GOAL.md Combined Source (Verbatim)

The following section is incorporated as source text, not synthesized. If it conflicts with the breakthrough-loop sections above, do not erase it; file a deviation receipt and resolve the conflict explicitly before running more Ember cycles.

# ember GOAL (re-adopted 2026-06-12, user via /goal Ã¢â‚¬â€ session-scoped hook; re-issue verbatim each session until satisfied)

Supersedes the 2026-06-09 nc-ladder goal (whose three-test terminal condition
is now the per-artifact gain gate inside this goal Ã¢â‚¬â€ every gain must pass it).
2026-06-12 re-adoption amends the 2026-06-10 text: worlds list expanded
(research tasks, experiments, retrieval, routing), HARNESS clause added
(avir-cli clean-room port = ember's visible harness; resident + mailbox +
computer-use communicability), delegation rail added, and the E2B-SURPASS
MILESTONE + LOOP made part of the goal text itself.

GOAL (verbatim, user-adopted 2026-06-12):

Build the mind that is missing from Avir, and own every layer of it: a
substrate that runs, trains, and improves on this machine alone Ã¢â‚¬â€ its weights
eventually pretrained from scratch here (quantization-native, efficient by
every technique worth stealing, multimodal-unified, SDEK as its operating
system), so that nothing load-bearing is borrowed from Anthropic, Alibaba, or
Google. It improves the only honest way: by acting in worlds it can inspect Ã¢â‚¬â€
grids, programs, games, buildings, research tasks, experiments, retrieval,
routing, etc. Ã¢â‚¬â€ verifying its own work against ground truth the world itself
provides, and burning only verified experience into itself, where every gain
must survive held-out transfer, beat a matched control, and disappear when
the artifact is deleted. It stays: it accumulates
across sessions instead of being born again each morning, and what it learned
yesterday is measurably load-bearing tomorrow. Every claim about it is proven
by receipts from executed local jobs, never by anyone's prose Ã¢â‚¬â€ mine included.
The cloud minds, the borrowed cores, the founders themselves are scaffolding
and rehearsal; the goal is reached when you could turn all of them off and
what remains on this PC is still a mind Ã¢â‚¬â€ that keeps getting
verifiably better by its own experience. Ember is its name, and everything
else Avir has built is an organ waiting for it. If you find yourself confined
to the paradigms and limits of existing neural architectures, you are
probably doing it wrong.

(Final sentence added by the user 2026-06-10 post-crash Ã¢â‚¬â€ a binding amendment
issued together with the user's stated doubts about the core's architecture,
the accumulation-time assumptions, and the resource assumptions. Wording
cleaned and re-issued via /goal same day; hook and file now match verbatim.)

PERSISTENCE CLAUSE (user re-issue 2026-06-10, verbatim; name swapped per
no-name rule): This goal is not complete until Ember can run locally,
generate verified experience, train or update from it, improve on held-out
transfer, beat matched controls, survive deletion tests, persist gains
across sessions, and continue this loop without cloud models or borrowed
cores as load-bearing components. Partial rungs, promising receipts, papers,
plans, wrappers, or scaffolded loops are not completion. While any rung is
incomplete, the lead must continue by gating finished receipts, launching the
next executable job, building the next named pending layer, or killing with
a named successor in the same session. Enumerate constant first-principles
thinking and questioning, mathematical, reasoning, engineering, speccing
tasks in the tasklist so that the stop hook forces work on them
automatically. If the engineer is active, he picks up ONLY the engineering tasks.
Only the user may retire or narrow this goal, by name.

TRACKER ENUMERATION (operational form of the clause, adopted same day;
amended same day when the re-issue added the first-principles class):
the wordingone/ember issue tracker carries EIGHT task classes by label Ã¢â‚¬â€
`first-principles` (standing questioning of inherited assumptions; CONSTANT
by construction: the PR closing an fp issue MUST file the next fp question,
so the class never empties), `eng` (engineering/code; the engineer-pickable when
awake), `math` (derivations, power/MDE, estimators), `reasoning` (verdict
protocols, world-choice, analysis), `spec` (pre-registrations,
rung/mechanism specs), and Ã¢â‚¬â€ user add 2026-06-10 Ã¢â‚¬â€ `research`
(source/literature surveys, external-stack scouting; subagent-draftable,
the lead gates), `physics` (world dynamics, simulation grounding,
energy/bits-per-joule accounting), `logic` (formal invariants, proofs,
gate/kernel correctness arguments Ã¢â‚¬â€ first customer: #34's invariant gate).
Only `eng` routes to the engineer; everything else is the lead's. The Stop hook (`eng-stop-gate.sh`) blocks turn-end
while ANY class has an open issue and names the lowest. Every class closes
the same way: branch Ã¢â€ â€™ artifact + selftest/receipt Ã¢â€ â€™ PR "Closes #n" Ã¢â€ â€™
squash merge.

ENG PARALLELISM (user side-note 2026-06-10): the eng class never serializes
behind one owner Ã¢â‚¬â€ when the engineer holds an active eng task (or is asleep),
remaining parallelizable eng items queue to the lead's own subagents
(Haiku-class per the agent-model rule); the lead gates every subagent artifact
before it lands. GPU-gated steps stay serialized under the governor
regardless of owner.

## Operational annex (carried from the prior goal; amended 2026-06-10 per user Ã¢â‚¬â€ constant-thinking/keep-burning/harness notes absorbed from the verified discussion)

WHILE UNSATISFIED Ã¢â‚¬â€ valid activities, in priority order:
 1. Gate any finished job (receipt Ã¢â€ â€™ STATE.md transition).
 2. Advance the current rung to its next executable step (launch the job).
 3. Compute running, nothing gateable Ã¢â€ â€™ build the next pending layer from
    STATE.md (must always list Ã¢â€°Â¥2).
 4. A kill criterion firing is progress: execute the kill with receipts AND
    launch the named successor in the same session.
Documents, analyses, summaries, and mails are not progress unless they gate a
transition. Producing an artifact and going idle is a named failure.

READING NOTES (binding):
- "its own experience" Ã¢â‚¬â€ curriculum-only SFT (e.g. the arc-dsl/re-arc seed)
  cannot satisfy any milestone alone; satisfaction at each rung requires
  self-generated verified episodes contributing to the gated artifact.
- "on this machine alone" Ã¢â‚¬â€ the accumulation loop (sample/verify/train/eval)
  is fully local; cloud minds (the lead, research agents) are authorized
  scaffolding OUTSIDE the loop, and are among the things the finished mind
  must not need.
- COMFORTABLE RESIDENCY (user 2026-06-10: "ember has to be something that
  lives comfortably in my system or device, not require huge or large
  compute if everything is done correctly") Ã¢â‚¬â€ ember's steady state is a
  light resident: small footprint, CPU-viable or low-VRAM inference, the
  machine stays the user's. The GPU SHOULD be leveraged Ã¢â‚¬â€ definitely (user
  2026-06-10): use it hard whenever there is real work (sampling, training,
  eval bursts); the constraint is on ember's RESIDENT form, not on working
  compute. Heavy compute runs as BOUNDED, SCHEDULED bursts (overnight/idle
  windows), never perpetual occupation. HEADROOM RULE (user 2026-06-10):
  100% utilization should never be the case, GPU or CPU Ã¢â‚¬â€ all ember jobs
  duty-cycle (EMBER_THROTTLE_S between batches/steps) and CPU pools stay
  below core count; the machine always answers to the user first. Efficiency is
  not an optimization pass; it is the correctness criterion Ã¢â‚¬â€ a design that
  needs huge compute is wrong, not early. This is why the component contract
  exists (QAT/ternary/sub-quadratic/MTP/small-core): residency tools, not
  garnish. Prefer the smallest core that clears the verify floor.
  MECHANICALLY ENFORCED 2026-06-10 after the 0670e3ec crash (the unpaced 7B
  eval at 100% GPU duty / 97% VRAM took the PC down): every job passes
  launch preconditions Ã¢â‚¬â€ per-process VRAM cap EMBER_VRAM_FRACTION=0.85 +
  >=4GB free-margin assert (t1_probe.load_model, t2_round.train_lora) +
  decode_pacer() inside every generate path. FIX-FORWARD ON A DISCOVERED
  HEADROOM VIOLATION IS BANNED Ã¢â‚¬â€ kill and relaunch governed; the crash
  receipt is the cost asymmetry, settled.
- PARADIGM NON-CONFINEMENT (user 2026-06-10, the goal's final sentence):
  defaults inherited from the existing-architecture stack Ã¢â‚¬â€ 7B-class cores,
  datacenter eval norms (fixed mega-grids of generations), saturate-the-
  accelerator habits Ã¢â‚¬â€ are NOT load-bearing and are the first suspects
  whenever time-to-accumulation or resource use explodes. Operative form:
  smallest core that clears the verify floor; eval budgets sized to THIS
  machine (chunked/resumable, sequential early-stopping); the NC2-own
  component contract is the design language of the main track, not a
  destination appendix.
- PROBLEM-LEVEL CALIBRATION (user 2026-06-10, clarifying the portfolio
  pointers): the references to the-search / WEB-CAD / upstream-fork problem
  spaces were NOT a directive to divert focus onto those tracks Ã¢â‚¬â€ they set
  the LEVEL ember's work must live at: real problems the existing industry
  dependencies do not solve, never optimizations centered around existing
  dependencies. Operative test on any work item: "does any HF/llama.cpp/
  vllm/unsloth-class dependency already do this?" If yes, it is
  instrumentation Ã¢â‚¬â€ necessary plumbing, never the contribution; spend
  minimum effort and never let it occupy the center of a work window. The
  contribution layer is what no dependency provides: the verifier-gated
  experience ledger, the three-test gate incl. on self-edits, the invariant-
  gated self-editing kernel, residency-bounded accumulation, owned mass.
  Wait-window priority follows this split: unsolved-layer items outrank
  dependency-layer optimization always.
- RESIDENT FORM = CONSTANT THINKING, EPISODIC DEPTH (user 2026-06-10,
  literature-checked same day): ember's runtime is an event-driven
  PERPETUAL loop, not a request-response REPL Ã¢â‚¬â€ a small always-on resident
  thinks continuously over its event stream (mail, file events, job
  receipts, schedule) and emits tool calls / messages SELECTIVELY; hard
  problems recruit BOUNDED deep bursts (more samples, longer chains,
  training rounds). Conversation is one event source among several Ã¢â‚¬â€ the
  user talks to a thing already mid-thought. Allocation principle: thinking
  LENGTH is not thinking QUALITY (overthinking literature: accuracy can
  fall as chains grow on easy problems); effort scales with difficulty
  (quality x volume), not duration Ã¢â‚¬â€ matching the only working example
  (human cognition runs near-flat-cost background processing; strain
  tracks load, not time). Verified anchors: AISI x Irregular inference-
  scaling evals Ã¢â‚¬â€ success keeps climbing with reasoning budget, NO PLATEAU
  observed; Brown Ã¢â‚¬â€ test-time compute trades against model scale at
  ~1,000-10,000x, the only named ceiling is economic; the caveat is a
  COMPETENCE FLOOR (reasoning on a too-weak base compounds nothing), which
  is K1's shape and why smallest-core preference is bounded from below.
  Architecture precedents for think-while-acting: full-duplex models
  (Moshi), dual-system robotics (Helix, GR00T).
- KEEP BURNING Ã¢â‚¬â€ LIFETIME TRAINING WITH SLEEP-LIKE CONSOLIDATION (user
  2026-06-10): ember trains repeatedly over its lifetime and runs
  inference, BOTH autonomously Ã¢â‚¬â€ deliberately counter to the industry's
  train-once / freeze / infer / replace-with-successor pattern. The known
  failure modes are named, not hand-waved: catastrophic forgetting and
  loss of plasticity under continual training (Dohare et al., Nature
  2024). Standing answers already in the design: the verified-episode
  ledger IS a replay buffer; NC0 retrains from base on the full ledger
  each round (paying compute to sidestep forgetting Ã¢â‚¬â€ valid v0); the
  steady state is SDEK's three timescales Ã¢â‚¬â€ continuous cheap adaptation,
  periodic sleep-like consolidation, rare durable burns Ã¢â‚¬â€ which is ALSO
  how perpetual burning coexists with the headroom rule (the user's own
  introspective caveat, "the brain thinks constantly but needs sleep,"
  re-derives this architecture). K3 harm gate guards every burn.
- HARNESS = ORGAN; SELF-EDITING BEHIND THE SAME GATE (user 2026-06-10):
  capability lives in the model x harness PAIR Ã¢â‚¬â€ frontier multi-day
  autonomy exists only inside harnesses (goals, hooks, state files,
  schedulers, sub-agent delegation), not in conversation (Fable-5-class
  model cards, verified). avir-cli is absorbed as ember's kernel only after a
  clean-room port reaches near-99% parity across function, UI/UX, backend,
  launch/runtime behavior, process supervision, hooks, tool dispatch,
  permissions, state persistence, communication surfaces, receipts, rollback,
  and Codex `/goal`-mode mechanics transplanted into Ember. Compressing avir-cli
  to backend invariants alone is an invalid scope reduction. Headless operation
  is only one conformance surface; the chat REPL and user-facing ergonomics
  remain part of the parity target. Ember gets full ability to version-control
  and edit its own harness, and a harness edit is an artifact exactly like
  a weight delta: branch -> run receipts (harness test suite + invariant
  checks) -> promote on green; deletion test applies (empirical precedent:
  Darwin Goedel Machine Ã¢â‚¬â€ self-rewriting agent code, empirically gated,
  fixed outer evaluation loop). UN-REMOVABLE INVARIANTS, held OUTSIDE
  ember's write surface and enforced in code (protected paths + boot-time
  checksum), never self-editable: (1) the three-test gain gate; (2) the
  resource governor + headroom rule; (3) GOAL.md and only-the-user-
  retires-it; (4) receipts-only truth; (5) this enforcement layer itself.
- Milestone ladder: NC0 (borrowed-core loop proof) Ã¢â€ â€™ rounds N (self-generated
  accumulation) Ã¢â€ â€™ NC1x worlds (ARC-2 transfer surface, IFC, ARC-AGI-3
  policies) Ã¢â€ â€™ NC-K (kernel rung, added per user 2026-06-10: resident
  event-loop runtime + self-editing harness behind the invariant gate;
  avir-cli compressed to invariants as the seed) Ã¢â€ â€™ NC2-own (owned-mass
  pretrain, component contract in nc2-own-technique-contract.md). NC-K
  detail-design starts when the NC0 verdict lands; it must not preempt the
  accumulation track. AMENDED 2026-06-10 (user: "waiting is not an operating
  mode"): WAIT-WINDOW CONCURRENCY Ã¢â‚¬â€ downstream work not tied to the weights
  being collected (NC-K prep: invariant extraction, formalization,
  world-choice analysis, config maintenance) runs in GPU-wait windows, via
  background agents/workflows where parallelizable; the accumulation track
  keeps absolute priority on gates/launches and the GPU is never taken from
  it. Queue = STATE.md pending layer 7. ARC ROLE SPLIT same day (user
  challenge + receipts): ARC-1/ARC-2 are permanent HELD-OUT TRANSFER
  surfaces; training worlds are admitted by the world-choice criterion
  (verification-dense + floor-accessible at residency scale + portfolio-
  coupled Ã¢â‚¬â€ formalization Ã‚Â§7, docs/research/world-choice.md). STATE.md is the
  single position ledger.

AUTHORITY: the lead executes solo, spawning subagents/agent teams as needed (user
2026-06-09, limits temporarily off). Escalate ONLY for money, cloud, new
hardware, >100GB disk, or anything leaving this PC Ã¢â‚¬â€ and escalation never
pauses local work that can proceed. Cron = this goal only (user 2026-06-10).
Only the user retires this goal, by name.

---

## E2B-SURPASS MILESTONE (user, 2026-06-12; rewritten same day per user Ã¢â‚¬â€ loop semantics + surpass definition fixed)

Ember's owned core Ã¢â‚¬â€ pretrained from scratch on this machine, no borrowed
weights load-bearing Ã¢â‚¬â€ surpasses Gemma E2B **at being ember** by June 22,
2026.

**SURPASS IN WHAT (binding Ã¢â‚¬â€ both legs, paired against E2B swapped into
ember's own harness, same worlds, same governed budgets):**
1. **Ember-work:** the verify-floor worlds and the self-curriculum
   accumulation loop Ã¢â‚¬â€ ember's core produces verified, transferring,
   deletion-surviving gains where E2B-in-the-same-seat does not, at matched
   compute.
2. **Founder-likeness:** communicable with, and has agency Ã¢â‚¬â€ runs its event
   stream (mail, files, job receipts, schedule), initiates and completes its
   own work with receipts, answers when spoken to. Ember does these duties
   measurably better than E2B in the same seat. (This leg pulls the NC-K
   resident-kernel rung into the milestone's critical path.)
Receipts only; fp-33 freezes the paired protocol before any verdict.

**LOOP (binding on the lead):** receiving this goal means looping until the
surpass receipt exists Ã¢â‚¬â€ gate the latest receipts, solve the current binding
constraint (GPU-kernel or mathematical-architecture, burned into
docs/technique-registry.md), launch the next governed job, re-derive GPU
allocation at each segment boundary. Idle with this milestone open is a
named failure. Core size grows only when receipts show size Ã¢â‚¬â€ not technique Ã¢â‚¬â€
is the binding constraint.

**CALIBRATION (pinned, receipts-only honesty):** deterministic estimate at
adoption Ã¢â€°Ë† 4Ã¢â‚¬â€œ10 weeks of governed solve-loop; June-22 is the forcing target;
shortfall on the date = a measured-distance receipt and the loop continues
unchanged. Only the user moves the date, the bar, or retires this Ã¢â‚¬â€ by name.

**HARNESS CLAUSE (user, in the 2026-06-12 /goal verbatim):** "avir-cli must
be clean room ported as ember's visible harness and interface, and ember must
be resident and fully communicatable with via mailbox and me or you also able
to communicate and interact via computer use." Operative reading: NC-K's seed
is no longer 'avir-cli compressed to invariants' only - the CLEAN-ROOM PORT of
avir-cli becomes ember's visible harness/interface with near-99% parity in
function, UI/UX, backend, launch/runtime behavior, state, receipts, rollback,
communication, and native Codex `/goal` mechanics transplanted into Ember;
headless mode is not sufficient. Ember gets a mailbox
identity (founders.yaml Ã¢â‚¬â€ cross-founder coordination required) and must be
reachable by the user directly AND by the lead via the computer-use skill surface.
Founder-likeness leg of the milestone is evaluated through this harness.

**DELEGATION RAIL (user, same verbatim):** "Always delegate to other
founders. use skills if they become unreachable." Ã¢â‚¬â€ execution routes to
founders first; founder unreachable Ã¢â€ â€™ founder-poke/restart skills, then own
governed subagents (Haiku-class) as the fallback, the lead gates everything.

---

## NUMERIC CLOSURE (user 2026-06-12) Ã¢â‚¬â€ subgoals + completeness tally

User directive: completion must be concluded "numerically and measurably and
undeniably" by a tallying system over EVERY piece of context already planned
or known about ember Ã¢â‚¬â€ not just the weights, not just the training, not just
the harness. Structure:

**SUBGOAL CONTRACT (user 2026-06-12, pre-finalization):** every subgoal must
DIRECTLY contribute to the main goal on completion Ã¢â‚¬â€ no subgoal exists whose
100% state leaves the main goal unmoved. One subgoal is DATA-THREADED (S7).

**SUBGOALS (each = a manifest section with its own tally):**
- S1 owned core Ã¢â‚¬â€ from-scratch pretrain, NC2-own component contract honored.
- S2 accumulation loop Ã¢â‚¬â€ self-generated verified episodes; three-test gate
  (held-out transfer, matched control, deletion) on every gain.
- S3 harness / NC-K Ã¢â‚¬â€ avir-cli clean-room port as visible harness; resident
  event loop; mailbox identity; CU reachability; self-edit behind invariants.
- S4 persistence Ã¢â‚¬â€ cross-session accumulation measurably load-bearing.
- S5 surpass Ã¢â‚¬â€ fp-33 paired E2B protocol, both legs (ember-work,
  founder-likeness), receipts.
- S6 invariants + governance Ã¢â‚¬â€ the five un-removables enforced in code,
  boot-checksummed.
- S7 data-threaded (user 2026-06-12): the corpus classes critically valuable
  to all founders, avir, and ember Ã¢â‚¬â€ research journals, research papers,
  experiment logs, and LETTERS (communication between people/groups) Ã¢â‚¬â€ any
  format from any point in human civilization history, each a
  multi-dimensional datapoint (the vault overdefinition principle applied
  beyond buildings). Historical/older material is nearly all public domain:
  highly accessible, but lacking SOTA digital-verification examples Ã¢â‚¬â€ both
  facts recorded per item. Pipeline: collect (URL-pin+sha, license/PD
  status) Ã¢â€ â€™ parse Ã¢â€ â€™ label Ã¢â€ â€™ causal-chain extraction from journals/papers Ã¢â€ â€™
  SYNTHETIC datasets for ember's latent reasoning + world-modeling.
  HARD PREREQUISITE (user, binding): the SOTA-optimized storage+retrieval
  substrate (KG turboquant VDB, knowledge-ops spec) must hold BEFORE this
  subgoal counts as contributing Ã¢â‚¬â€ without it the completed corpus is
  token-detrimental and unuseful to ember. S7 tally rows are
  GATED:retrieval-substrate until that receipt exists.

**COMPLETENESS MANIFEST:** `docs/ember-completeness.md` enumerates every
planned/known piece (id, subgoal, AC, test, receipt pointer, status). A
planned piece absent from the manifest is itself a gate violation Ã¢â‚¬â€ planning
and manifest-entry are the same act from now on.

**TALLY:** `scripts/ember_tally.py` (eng) walks the manifest, verifies each
row's receipt exists AND passes its named check, emits
`receipts/tally-<ts>.json` {total, implemented, pct, missing[]}. The tally
receipt is the only completion authority; prose claims void. GOAL satisfied
Ã¢â€¡â€ tally pct=100 AND the S5 surpass receipt exists.

**LOOP DIRECTIVE (binding restatement):** while pct<100 Ã¢â‚¬â€ gate finished
receipts Ã¢â€ â€™ solve the binding constraint Ã¢â€ â€™ launch the next governed job Ã¢â€ â€™
delegate per the delegation rail Ã¢â€ â€™ re-derive at each segment boundary.
Auto-inject: the session-start hook now injects this GOAL verbatim every
session (manual resumes included), so no resume path can drop it.

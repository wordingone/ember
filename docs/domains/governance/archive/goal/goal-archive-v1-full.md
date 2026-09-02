Full historical context: docs/domains/governance/archive/goal/goal-archive.md

# Ember Breakthrough Loop - Self-Improvement Plan

Date: 2026-06-17. Re-founded 2026-07-06 (operator mandate restored to top precedence).
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

## The Mandate (top precedence - outranks every section below)

Operator, standing since 2026-06-25, restored here 2026-07-06 after three
documented pushes of the same directive:

> "Discover the computation primitive that could lower the barrier to
> foundation model creation."

Concretely: break the bottlenecks that make FULL local foundation-model
creation - pretraining included - impossible on one consumer GPU (the single
local 4090). This is what the energy law was commissioned to encapsulate. A
model reachable by standard-stack arithmetic on this hardware (Chinchilla
scaling, dense states, 6ND compute) is NOT a foundation model and is never the
goal; the FM bar is the capability-per-local-resource frontier BENDING past
what the standard stack yields at the same budget, receipted.

Binding consequences:

1. The BOTTLENECK LEDGER (issue #207) enumerates the walls (B1 data, B2
   training-state memory, B3 compute, B4 inference-to-training transfer,
   B5 the capability bar) and is the standing dispatch authority for all
   goal work. The highest-priority open ledger row outranks every other
   work class, machinery and surface work included.
2. No ledger row, and no track named non-killable anywhere in this file, can
   be killed, archived, deferred, or descoped by any self-verdict. Only the
   operator kills a track. A self-kill is void, auto-revived, and disclosed.
   (Receipt of need: RLM/iGRPO were declared non-killable below and were
   still self-killed on 2026-07-05. The clause failed as prose; this section
   plus ledger row-state is the mechanism.)
3. `docs/contracts/ember-floor-contract.md` is re-designated from deferral ledger to
   REVIVAL QUEUE: its rows (BitNet/1.58-bit, MLA/KV compression, FP8, MoE,
   MTP, iGRPO/GRPO verifier RL, sleep consolidation, encoder-free multimodal,
   external research intake) map onto ledger walls and queue behind live
   falsifiable legs - parked-with-a-path, never parked-as-disposal.
4. Any capability or ceiling statement about Ember that contains only
   standard-stack terms is the named FAILURE STATE of this goal, not an
   answer to it.
5. Live bend-claims and their pre-registered verdicts (current: G-arm
   token_bill_collapse_ratio, generalize <=0.5 / revoke >=1.0, issues
   #121/#113) are the only currency that closes ledger rows.

## Authority And Precedence

This file is the active Codex goal source for the Ember goal and may not be used to justify pausing the goal.
It is not allowed to be a stale mirror. Before any `/goal` run, benchmark
run, readiness run, long-duration run, or resident-training attempt touches
Ember, this exact text must be synced into the governing repo `GOAL.md` and
preserved in git. If the active path, repo `GOAL.md`, README, issue text,
readiness receipt, or older handoff disagrees with this file, the run must stop
with `invalid_goal_source_split` until the surfaces are reconciled.

Precedence order for goal-mode execution:

0. `The Mandate` in this file, and the Bottleneck Ledger (issue #207) it binds.
1. `Authority And Precedence` and `Current Blocker Packet` in this file.
2. `Goal Injection Contract` and `Goal Clear Condition` in this file.
3. `Do Not Infer` and the active `Next` section in this file.
4. `docs/domains/governance/ledgers/ember-debt-ledger.md`, only when it agrees with the packet.
5. Historical evidence, original `GOAL.md` text, readiness receipts, D3/Kaggle
   receipt chronicles, old issue trackers, and founder-side context.

Any lower-precedence source that suggests benchmark work, readiness hardening,
D3/Kaggle reruns, duration growth, ledger expansion, or documentation work
before the resident-training gate is open is historical context, not an
executable instruction. No reduction of scope, renaming of the gate, or
classification of work as archival/killed can bypass the non-killable RLM,
iGRPO, and clean-room `the predecessor CLI` resident-harness preconditions.

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
OpenAI, the model vendor, Google, Kaggle, hosted-vision, hosted-LLM, leaderboard, or
other metered credentials are never required authority for Ember. If an
already-available Codex subagent, local model, deterministic verifier, checked-in
oracle, or human-authorized peer can apply the same rubric, that zero-spend
route is not a fallback; it is the required route. A receipt that asks for a
money-costing API key before exhausting these routes is invalid, and a receipt
that scores itself higher because it used a paid judge is invalid evidence.

Binding floor-contract surfaces imported into this goal:
- `docs/contracts/ember-floor-contract.md` is the launch-vehicle deferral ledger and carries floor rows for BitNet/1.58-bit, encoder-free multimodal training, SDEK/GDN sleep consolidation, MLA/KV compression, MTP, iGRPO/GRPO-adjacent verifier RL, FP8, MoE, DiffusionGemma, external research intake, and all trigger-gated kill/promote rows.
- `nc2-own-technique-contract.md` is the binding owned-core component contract. Silent pivots off QAT, turboquant, BitNet/1.58, SubQ/sparse attention, MTP, SDEK, the Chinese-lab stack, or Gemma-4-style unified multimodal architecture are gate violations unless the user changes the contract by name.
- `src/ember/governance/scripts/train_multimodal_v0.py` is the current real neural/multimodal launch vehicle. Its §6 primitive action-log seam (`emit-token`, `emit-scalar`, `emit-pointer`, `commit`, `stop`) is the world-model compiler seam and must be used or explicitly blocked by receipt when building the resident-training adapter.
- The existing launch-vehicle floor already includes QAT, Muon hidden-layer optimization with AdamW fallbacks, QK-norm, multimodal reserved IDs/soft-token splice/bidirectional span/2D RoPE locks, and the residency governor. These are not optional background facts; the resident-training gate must preserve or explicitly account for them.
These imported surfaces do not replace the Current Blocker Packet and do not authorize benchmark/readiness/D3 work before the resident-training gate. They constrain how the gate is built: use actual neural parameter updates, preserve the floor machinery, and never clear via symbolic-template-policy substitution.
The resident-training gate receipt must include a machine-checkable `floor_contract_manifest` keyed by every row in `docs/contracts/ember-floor-contract.md` and every binding component in `nc2-own-technique-contract.md`. For each row/component it must record: source file, source hash, disposition (`used_now`, `preserved_trigger_gated`, or `blocked_with_exact_adapter_surface`), launch-vehicle impact, trigger, pilot, kill/promote condition, and evidence path. `archival`, `killed`, `irrelevant`, `later`, `covered by fp16`, or any free-text equivalent is invalid unless the receipt proves a physics-level contradiction with Ember's self-growing target and cites the exact user-approved contract change. A gate receipt missing this manifest is `invalid_floor_contract_unaccounted`, even if its neural update, A/B/C rows, and deletion tests otherwise pass.

First-principles reconciliation of these surfaces: the core function is not
to preserve a checklist of fashionable techniques; it is to make Ember's
self-growth mechanism actually increase its own problem-solving capacity
under external held-out pressure. Therefore the floor contract is binding
only where it is load-bearing for that function, and every preserved or
trigger-gated row must state the mechanism by which it can become
load-bearing. The resident-training gate must explicitly restore and test:
the full `docs/contracts/ember-floor-contract.md` ledger including every trigger-gated
row; the full `nc2-own-technique-contract.md` binding component list; the
`src/ember/governance/scripts/train_multimodal_v0.py` neural/multimodal launch vehicle; the
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
and clean-room `the predecessor CLI` resident harness preconditions below are receipted.
These three preconditions are non-killable: RLM, iGRPO, and the clean-room
`the predecessor CLI` resident harness must be implemented or the goal remains blocked.
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
clean-room `the predecessor CLI` harness accounting, `src/ember/governance/scripts/train_multimodal_v0.py`
inspection/adaptation decision, and a row-by-row `floor_contract_manifest`
covering `docs/contracts/ember-floor-contract.md` plus `nc2-own-technique-contract.md`.
These requirements are conjunctive, not menu items. A neural-update receipt,
even one with before/after and deletion evidence, is still only
`RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_CLEARANCE` if the full
clean-room `the predecessor CLI` resident harness remains blocked. A full-parity harness
receipt with `reference_CLI_FULL_PARITY_HARNESS_GATE_BLOCKED`, `headless_bootstrap_only`,
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
`PARITY_WITH_MODEL_NOT_TOOL` and cannot open the `the predecessor CLI` resident-harness
gate. If a future lookup claims `launch.ps1` is missing, it must reconcile that
against the real compiled `the predecessor CLI executable` and the Ember-side `tools/reference-launch`
and `src/ember/infrastructure/tools/reference-goal-mode` launchers instead of treating the working app as
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
  deletion sensitivity. However, because the clean-room `the predecessor CLI`, RLM, and
  iGRPO resident-training preconditions are not yet receipted, these loop
  receipts are `invalid_precondition_bypass_for_goal_clear`. They may inform
  later regression/transfer tests after the gate opens; they cannot clear the
  goal, readiness, field-level, duration-growth, or self-improvement claims.
- **Current blocker:** The real `the predecessor CLI` lived-surface blocker from the lead's mail remains cleared only as a precondition, not as goal completion. The preserved precondition chain is: `receipts/ember-preloop-resident-gate/real-reference-uiux-ax-observation-20260622T151722Z.json` (`REAL_reference_UIUX_AX_OBSERVATION_PASS`), `receipts/ember-preloop-resident-gate/full-parity-harness-gate-20260622T152000Z-final.json` (`reference_CLI_FULL_PARITY_HARNESS_GATE_PASS`), `receipts/ember-resident-training-gate/resident-training-gate-20260622T152500Z-final.json` (`RESIDENT_TRAINING_GATE_PASS` with actual trainable neural parameter update over verifier-conditioned D3 rows), `receipts/ember-tiny-bitnet-comparison/20260622T152800Z-final/tiny_bitnet_comparison_receipt.json` (`BITNET_COMPARISON_PASS`), `receipts/ember-post-resident-discovery/benchmark-discovery-20260622T153000Z.json`, `receipts/ember-post-resident-discovery/past-ember-technique-mining-20260622T153000Z.json`, and [deleted] (`D3_NATIVE_PROPOSER_LOOP_PROGRESS_PASS`). The previous D3 blocker is now solved as progress evidence by [deleted]: fresh D3-Gym task_65/task_66, official Docker execution, `D3_MULTI_TASK_GENERALIZATION_PASS`, C=1.0, A=0.0, B=0.0, Deleted=0.0, positive delta, deletion-sensitive, prospectively clean, no prior failed task overlap, no gold-output route, and no static per-task answer table. This still does **not** clear the goal or field-level breakthrough condition; it proves the D3 multi-task candidate-execution blocker was removed and moves the cursor to the stronger external validation path. the lead's 2026-06-22 mail chain was corrected by mail `17246`: the ScienceAgentBench artifact was actually downloaded to `<local-path>`, not `<local-path>`. The superseding local receipts prove the SAB artifact blocker is cleared: `receipts/ember-post-resident-discovery/scienceagentbench-artifact-intake-20260622T163746Z.json` is `SCIENCEAGENTBENCH_ARTIFACT_INTAKE_READY`, copied the verified zip to `<local-path>`, verified size `1769478786`, password-tested/extracted locally without redistributing unzipped data, and recorded artifact SHA-256 `46e715d3b2196d459d2dff52aa487f506a95ec44b44262e82208d086ea879610`. `receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.json` is `SCIENCEAGENTBENCH_ADMITTED`: it selects ScienceAgentBench, freezes six verified rows at `receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.frozen_rows.json`, records full local artifact access, has no blocked reasons, and preserves deletion-sensitive native routing. Older SAB blocked receipts are retained only as historical error/correction trail and must not be treated as the live blocker.
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
0. **No additional Ember loops before resident-training preconditions:** before any further Ember cycle, loop, benchmark run, growth run, scale-up, readiness run, or proof attempt, complete and receipt the clean-room `the predecessor CLI` resident harness precondition and both RLM and iGRPO harness-native training-organ preconditions in requirement 14. These three preconditions are non-killable; there is no successor-replacement escape hatch. Existing loop receipts remain historical evidence only. A new loop run before this gate opens is automatically `invalid_precondition_bypass` and cannot support readiness, growth, completion, or field-level claims.
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
   itself, not merely call Codex, the assistant model/founders, the human, a wrapper, or any
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
   CC-level resident harness, with the clean-room Ember port of `the predecessor CLI` as
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
   existing `the predecessor CLI` launch surface is the real compiled
   `<local-path>`, plus Ember-side launchers such as
   the former reference launcher and `src/ember/infrastructure/tools/reference-goal-mode/goal-mode.ps1`; a missing
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
   Existing neural infrastructure is not missing: `src/ember/governance/scripts/train_multimodal_v0.py`
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
   or the clean-room the predecessor CLI harness is not yet feasible at the current scale,
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
   scope reduction can convert a missing RLM, iGRPO, or clean-room the predecessor CLI
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
`docs/domains/governance/ledgers/ember-debt-ledger.md`. It consolidates the maintainer's 2026-06-19 captured debt
list with this goal, the completeness manifest, the active receipt index, and
the architecture audit. Goal-clear review must scan that ledger. Any row marked
`ACTIVE-BLOCKER`, `ACTIVE-NEXT`, `OPEN`, or triggerless `DEFERRED` blocks
completion unless a newer receipt updates the row to `DONE`, `KILLED`,
`EXCLUDED`, or a valid `GATED:<trigger>` state.
If `docs/domains/governance/ledgers/ember-debt-ledger.md` is missing, stale, or contradictory,
goal mode may repair only the rows needed to preserve this Current Blocker
Packet and must then return to the packet. Ledger repair is not progress toward
Ember unless it directly changes the resident-training gate receipt. Unknown
old work is not silently archival; if it could affect RLM/iGRPO, clean-room
`the predecessor CLI`, resident persistence, deletion dependence, or field-level proof, it
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

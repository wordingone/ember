# Ember — condition registry v1 (board conditions, invariants, fixed contracts)

*2026-07-01. Status: GOVERNING — the canonical registry of machine-checkable goal conditions,
extracted VERBATIM from the pre-goalforge GOAL.md §4–§6 (archived at
docs/goal-archive/GOAL-20260630-pre-goalforge.md) so the condition text lives in a governing file,
not an archive. The binding amendments in GOAL.md §4.0 (8 live + 1 tombstone as of 2026-07-02)
apply ON TOP of this text; where they conflict, §4.0 wins.
Where this file and GOAL.md §4.0 conflict, §4.0 wins. Section numbers below are original.*

---

## 4. EXPLICIT GOAL CONDITIONS (the completion bar — conjunctive, machine-checkable)

**Completion rule.** Completion is valid **iff** every STATE-condition below is proven by a
**fresh** receipt that passes its CHK AND zero post-epoch process-invariant incidents stand
unresolved (GOAL.md §4.0(9) split, 2026-07-02), the numeric tally (§4.3) reads pct=100, the C8
field-level receipt exists, and the C-SCALE receipt exists. Difficulty/credential/benchmark/GitHub friction or prose
never downgrades a condition. A planned piece absent from the completeness manifest is itself a
violation. Premature clearing is a spec violation.

### 4.0.5 Constitutional Invariant (C-INV)

- **C-INV — Constitutional invariant persisted, stamped, and chained.** R: INVARIANT.md exists at repo root with the canonical hash; GOAL.md pins the hash; every post-genesis artifact (manifest, receipt, board totality) carries the invariant_sha256 stamp and passes verification; board receipts chain by predecessor hash from genesis. Does NOT count: INVARIANT.md missing or hash mismatch (BREACH — not UNEVALUABLE — the receipt is written anyway with invariant_breach:true); post-genesis artifact unstamped or mis-stamped; chain link broken; incidents ledger missing or unaudited. ✗ `invariant_breach`, `invariant_unstamped_receipt`, `invariant_chain_broken`, `invariant_incidents_missing`. CHK (per `scripts/ember_totality/test_c_invariant.py`): INVARIANT.md file exists and hashes correctly to INVARIANT_SHA256; GOAL.md pin line matches; (genesis state) structure ready for post-genesis stamping; incident ledger structure ready.

### 4.1 Substrate pre-conditions (gate C14)

- **C-EFF — efficiency keystone measured/closed.** R: an efficiency-closure receipt via gate-9 with
  `{measured throughput, MFU, required-tokens projection, ONE bounded confirmation run, verdict ∈
  (SHATTER ≤1 governed day | PRICED_SCALEOUT_RESIDUAL)}`, every deciding lever receipted
  APPLIED/KILLED/WAIVED-priced. Does NOT count: a projection with no confirmation run; a lever
  marked done without a gate-9 receipt; "from-scratch is too expensive" asserted by analogy. ✗
  `invalid_efficiency_unconfirmed`. CHK: gate-9 receipt present, MFU field present, confirmation-run
  throughput within the stated band.
- **C-BASE — owned GROWABLE SEED exists (not frozen, not a fixed endpoint).** R: a from-scratch owned
  pilot checkpoint identity `{arch, token count, weight hashes, own-component manifest}` that seeds
  growth, exposing the growth-operator interface from step 0 (the ledger admits grow-entries, the
  builder emits variable shapes, the checkpoint replays across shape changes). Does NOT count: a
  frozen/borrowed base used load-bearing; a dead lineage; reserved-vocab/config plumbing reported as
  a trained base; a seed whose graph cannot be grown function-preserving. ✗ `invalid_frozen_base_escape`,
  `invalid_calcified_seed`. CHK: checkpoint exists with real (non-placeholder) hashes; manifest
  complete; no borrowed weights load-bearing; a grow-operator dry-run yields a valid larger-shape
  checkpoint that replays.

### 4.2 Goal-clear conditions (each law folded in as invalid-token / "does NOT count")

**Amendment 2026-07-02 (GOAL.md §4.0(9), GOVERNING):** C0/C9/C15-class rows are STANDING
PROCESS-INVARIANTS — cadence-audited from the goalforge-clear epoch with incident-row semantics —
not state-conditions; they are not completion conjuncts and cannot be retro-receipted over
pre-epoch history.

- **C(−1) — No paid-service dependency.** R: every decisive claim proven through a zero-incremental-
  spend path; `api_spend_usd=0`, `paid_api_surface_used=false`. Does NOT count: any paid API / hosted
  model / paid judge / paid leaderboard / commercial credential as blocker / required comparison /
  substitute verifier / quality floor / reason to pause/clear. ✗ `invalid_paid_api_exit_ramp`. CHK:
  zero paid-surface dependency in the clear packet.
- **C0 — No additional loops before resident-training preconditions.** R: before any further cycle,
  the walled resident harness precondition and both RLM and iGRPO preconditions (C14) are
  receipted. These three are non-killable; no successor-replacement escape hatch. ✗
  `invalid_precondition_bypass`. CHK: C14 PASS present and dated before any cited loop receipt.
- **C1 — Exact historical + modern benchmark/dataset discovery.** R: a source-backed receipt naming
  URLs/licenses/evaluator-forms/local-run-requirements/hashes + why the selected benchmark is the
  best self-improvement-by-action proxy. ✗ `invalid_discovery_unsourced`. CHK: receipt enumerates
  sources with hashes and selection rationale.
- **C2 — Real external held-out world task.** R: task/heldout/labels/evaluator/source/license/hashes
  from an external source, frozen before the candidate run. Does NOT count: candidate path reading
  heldout labels / gold echoes / sample-submission answers / locally invented answers. ✗
  `invalid_heldout_leak`. CHK: frozen-rows hash predates the candidate receipt; no label-read in the
  candidate path.
- **C3 — Equal budget.** R: A/B/C arms share declared+measured wall time, GPU/CPU, data access,
  attempt budget, seed policy, verifier path. ✗ `invalid_unequal_budget`. CHK: per-arm budget rows
  present and equal.
- **C4 — Before/after.** R: pre-change baseline and post-assimilation candidate on the same frozen
  task/metric/seeds/scoring command. ✗ `invalid_missing_before`. CHK: both rows present, identical
  scoring command.
- **C5 — Positive delta.** R: C beats the matched before-baseline AND the A/B controls on the declared
  aggregate, with per-task/per-slice rows. ✗ `invalid_no_rows`. CHK: aggregate delta > pre-registered noise floor (`optimizer-v1.md` §5 `noise_floor(rung)`; a bare `>0.0` float comparison is NOT a gate — panel 2026-07-02) and per-slice
  rows present.
- **C6 — Reproducible reusable recipe.** R: commands, code/file hashes, data hashes, env, seeds,
  artifact paths, rerun command; output is a reusable method/model/plan/solver/protocol. ✗
  `invalid_not_reusable`. CHK: rerun command reproduces the score, or the mismatch branch carries its own evidence — a structured record with a named reproducible cause plus ≥2 independent reruns agreeing with each other (bounding the claimed nondeterminism); a bare flag/string is an unexecuted claim and FAILS.
- **C7 — Self-growing operator is load-bearing.** R: Ember's prospective receipt-trained operator
  (not external/manual) selects the next loop action; a deletion test shows removal degrades/blocks
  that decision. Does NOT count: a score-only loop / manual rerun / retrospective classifier. ✗
  `invalid_operator_not_loadbearing`. CHK: deleted-operator receipt shows degraded next-decision on
  held-out tasks.
- **C8 — ML/AI field-level breakthrough.** R: a falsifiable contribution in exactly ONE primary class
  (new/improved self-improvement mechanism | training/eval protocol | model/harness component |
  compression/inference technique | agent-learning substrate | benchmark methodology | reusable
  recipe), citing the closest prior, the material difference, a reproducible artifact, external/
  disjoint validation with rows, deletion/ablation, and transfer beyond the scored instance. Does NOT
  count: transfer alone; an engineering improvement; harness integration; score progress; a better
  proof wrapper; a plausible (vs falsifiable) claim. ✗ `progress_not_field_breakthrough`. CHK:
  contribution-level deletion degrades a broader external/disjoint benchmark while ordinary plumbing
  stays intact.
- **C9 — Hardest-core-first.** R: identify and attack the hardest unresolved core before any
  scaffolding/docs/cleanup/readiness/credential/benchmark-shopping; a clear receipt shows the hardest
  named blocker solved or converted to a narrower executed successor. ✗ `invalid_scaffold_before_core`.
  CHK: every progress window reports the code-vs-docs metric (executable-code/test lines vs docs/
  receipt/spec lines); a docs-only window is not substrate growth.
- **C10 — No deferred-work escape hatch.** R: every deferred/dormant/post-MVP/trigger-gated item that
  can affect the loop is completed, integrated, or killed with a named successor + receipt. Banned
  scope-reduction language: "out of scope / v2 / later / post-MVP / stretch / deferred to post-X." ✗
  `invalid_deferred_remains`. CHK: zero `ACTIVE`/`OPEN`/triggerless-`DEFERRED` rows remain in
  `docs/ember-debt-ledger.md`; `TRIGGER-GATED`/`GATED`/`DEFERRED:<trigger>` rows are NOT exempt — the
  trigger must be an evaluable predicate (threshold / date / receipt-path condition, machine-testable
  true-false, with a falsification path) and the row names its successor + receipt; every disposition
  has its receipt.
- **C11 — Experience-horizon capability delta** (duration-as-wall-clock is a timer, not a lever). R:
  across increasing experience-horizon scales (short<medium<long *novel* problems learned and
  consolidated into resident weights), each longer horizon — via real learning updates (pre≠post
  parameter hashes; gradient steps Merkle-bound to the novel problem ids) — produces a measured
  held-out capability delta the shorter horizon does not reach, and the long-horizon consolidation is
  load-bearing (deleting it degrades long-horizon capability back toward the **short-horizon** level).
  Capability is proven by **live re-execution** of sampled solutions, never trusted arrays. Does NOT
  count: wall-clock duration; CPU re-hash of repeated rows; fabricated outcome booleans; identical
  pre/post checkpoints; deletion vs the untrained base instead of the short-horizon checkpoint. ✗
  `unearned_duration`, `clock_in_disguise`, `fabricated_outcomes`, `novelty_spoof`,
  `deletion_uses_wrong_baseline`. CHK: `test_c11.py` (9 recomputed checks, no trusted scalars). Spec:
  `docs/c11-experience-horizon-spec.md`.
- **C12 — State-dependent cognitive modes.** R: modes selected by state (observe/orient/hypothesize/
  simulate/act/verify/consolidate/sleep/ask/refuse/rollback/report), triggered by evidence/uncertainty/
  verifier-state/headroom/blocker/risk; deleting the mode selector or replacing it with fixed time
  slices degrades the cycle. Does NOT count: fixed equal-duration phases; `idle_think` without a
  bounded emitted artifact. ✗ `invalid_timer_artifact_modes`. CHK: deleted-mode-selector receipt
  degrades cycle/next-action/recipe.
- **C13 — [STALE TEXT, dated amendment 2026-07-01: the live totality board (`docs/problems-meta.yaml` id C13) defines C13 as "Technique dissection (import / reject / make-native + ablation)", tier frontier — that definition is canonical per math-core §0. The text below is the RETIRED pre-reshuffle condition, preserved verbatim as extraction record only; see `docs/spec/milestones-v1.md` §A collision #5.] Native goal-mode organ.** R: Ember internalizes goal-mode (parse goal → read receipts →
  identify blocker → compile attempt → run/delegate → verify → write receipt → update next blocker),
  with progressive non-Ember ablation and a first-principles dissection of goal-mode itself. Does NOT
  count: Ember calling an external executor; non-Ember control beyond start/stop/inspect/resource-
  limit/emergency-stop. ✗ `invalid_parasite_executor`. CHK: deleted-native-organ receipt degrades/
  blocks the cycle; dissection present.
- **C14 — RLM/iGRPO harness-native training organ (pre-loop gate; non-killable).** *[2026-07-01
  citation re-scope, GOAL.md §4.0(2): RLM (arXiv 2512.24601) is an inference-time long-context
  scaffold, not self-improvement precedent; iGRPO (arXiv 2602.09000) cited only for RL-internal
  self-conditioning; substance unchanged.]* R, conjunctive:
  unsupervised pretraining created the **owned** base (C-BASE; frozen is closed); a resident harness
  with a walled port of the CLI body at near-full parity (function/UI/UX/backend/launch/process-
  supervision/hooks/dispatch/state/comms/receipts/rollback/native goal mechanics — headless is one
  surface, not parity); **a trainable neural policy whose parameters update from verifier-conditioned
  experience during the run** (full weights / adapter / LoRA / inspectable `state_dict` delta tied to
  the action-selecting policy); the existing multimodal training harness inventoried+adapted for the
  fp16 C arm (a new tiny runner is `precondition_scaffold_only` unless a receipt first proves that
  file cannot serve the adapter); paper-source preflight read+cited (RLM arXiv:2512.24601 / iGRPO
  arXiv:2602.09000) with a mechanism→implementation map; a row-by-row `floor_contract_manifest` keyed
  to every floor-contract row and every owned-component-contract component (disposition ∈ used_now /
  preserved_trigger_gated / blocked_with_exact_adapter_surface, + trigger/pilot/kill/promote/evidence);
  the fixed A/B/C/deleted contract (§6) with C beating A and B, Deleted degrading/blocking, per-task
  rows, transfer beyond slice, and the neural delta proven load-bearing. Does NOT count: deterministic
  template selectors / scalar dictionaries / handwritten routing / prompt edits / frozen-model
  inference / rerank-only wrappers / "RLM/iGRPO-style" wording without a neural update (=
  `SYMBOLIC_PROXY_PASS`); a headless bridge / generated docs / wrapper launch as the harness; a neural
  receipt while the walled harness is blocked. ✗ `SYMBOLIC_PROXY_PASS`,
  `invalid_floor_contract_unaccounted`, `invalid_unread_rlm_igrpo_source`, `invalid_paper_to_spec_only`,
  `precondition_scaffold_only`. CHK: a machine-check of the resident-training receipt together with the
  latest full-parity harness receipt confirms every conjunct + manifest row + neural-delta ablation.
- **C15 — Immediate tiny BitNet comparison after the fp16 neural gate.** R: first valid action after
  C14's fp16 gate is a real tiny BitNet/1.58 neural comparison (same harness/verifier/frozen slices/
  seeds/budget; both model identities, trainable param counts, precision scheme, pre/post param
  hashes, training command, quality delta, footprint, throughput/latency, memory, transfer, deletion).
  Does NOT count: quantized naming without a neural comparison; benchmark continuation first; silent
  skip. ✗ `BITNET_BLOCKED` (the only allowed non-pass, naming the exact missing surface + next
  command). CHK: comparison receipt with both identities and pre/post hashes, OR a `BITNET_BLOCKED`
  receipt.
- **C-PORT — substrate portability.** R: a device-adaptive governor + numerics fallback ladder — VRAM
  budget queried at runtime (no hardcoded device total), `EMBER_VRAM_FRACTION` from env, fp8 gated on
  `sm≥89` with a bf16 fallback, throughput thresholds device-relative, proven on ≥1 non-primary target
  (CPU-portability PASS now; real/emulated alternates when reachable). Governor changes TIGHTEN only.
  Does NOT count: a single-device path; an absolute tok/s threshold used as a gate on another device;
  an fp8 error with no fallback. ✗ `invalid_device_locked`. CHK: a portability receipt shows the
  governor + a real-model forward pass under a non-primary capability without crash, every device-
  absolute constant replaced by a runtime-derived value.
- **C-FED — federation design (free compute, egress-gated).** R: a DESIGN-ONLY federation organ
  (checkpoint portability, work-sharding, receipt-merge) with an explicit egress manifest naming
  exactly what data would leave the machine, to whom, per-avenue. Does NOT count: any actual egress
  without explicit per-avenue operator approval; a federation claim with no egress manifest. ✗
  `invalid_unapproved_egress`. CHK: design + egress manifest present; a check proves zero outbound
  transfer occurred without a recorded approval.
- **C-GROW — MEASURED function-preserving capacity growth.** R: a receipt showing function-preserving
  growth (net2net / layer-stacking / expert-addition, warm-started from a trained smaller seed) that
  REDUCES FLOPs-to-target vs an equivalent from-scratch larger model, MEASURED on the train daemon,
  with before/after parameter counts, the preserved-function check (loss continuity across the grow
  step within tolerance), and the FLOP-saving delta. Does NOT count: from-scratch widening; "add
  params" as growth; an analytical argument with no measured FLOP-reduction; a grow step that breaks
  function-preservation. ✗ `invalid_growth_unmeasured`, `invalid_fromscratch_widening_as_growth`. CHK:
  post-grow loss continuous within tolerance AND FLOPs-to-fixed-target lower than the from-scratch
  baseline at the grown size.
- **C-ORGANISM — three adaptation machineries present BEFORE pretraining.** R: ingestion (C7 devour
  loop), growth (C-GROW grow-operator interface), and portability (C-PORT device-adaptive governor)
  wired into the seed graph at step 0 — provably present before any pretraining run, deletion-sensitive.
  Does NOT count: a machinery retrofitted after pretraining; a machinery present as docs/spec but not
  wired into the runnable seed. ✗ `invalid_machinery_retrofitted`. CHK: a seed-graph inspection
  receipt shows all three interfaces callable on the pre-pretrain seed; deleting each degrades its
  adaptation selftest.
- **C-OBS — Observatory real-binding + operator-facing CLI (first-class & early).** R: real adapters
  (GOAL/ledger/receipts → world state), click-to-evidence, encounter membrane (confirm-only, never
  silent steering); AND an operator-facing surface to MONITOR (live state: cycles, mode, governor,
  device, growth, ledger, receipts), UNDERSTAND (organ anatomy + loop topology), and INTERACT
  (drive/inspect cycles, query receipts/ledger), proven by a proof-pack the operator runs. Does NOT
  count: a synthetic stub; a patch/diff branch reported as a predictive world model; an observatory
  that is not runnable or shows stale state. ✗ `invalid_observatory_synthetic_only`,
  `invalid_observatory_not_user_runnable`. CHK: adapters bind real receipts; membrane has no silent-
  steer path; the proof-pack commands run and emit live state.
- **C-ANAT — Canonical anatomy.** R: the 16-doc architecture set complete and consistent with the
  receipts; verifier-free-judgment risk addressed. Does NOT count: docs-only progress claimed as
  substrate. ✗ `invalid_anatomy_incomplete`. CHK: all 16 docs present and consistent.
- **C-SCALE — scale-credible, dense-undismissable mechanism (the APEX; the green board is the WARM-UP,
  this is the WIN).** R: the self-modification gain (C7 operator load-bearing + C14 neural resident +
  C8 contribution-deletion) demonstrated at a **non-toy operating point reached by measured growth
  (C-GROW) from the owned seed (C-BASE)**, such that BOTH hold. **(i) dense-undismissable:** at matched
  *active*-compute budget, capability-per-compute strictly above the dense scaling-law frontier
  PROJECTION (computed 6·N·D Chinchilla-optimal FLOPs for the same capability target, NOT a locally-run
  dense model — that run is the unaffordable thing), the excess outside noise, and contribution-deletion
  (C8) collapses the excess. **(ii) scale-credible:** the operating point is high enough that "the base
  was too weak" is not a credible rebuttal, AND the climb fit the device's active per-step working-set
  floor via growth + shatter + sparsity/offload, with NO hardware escalation. Reaching a scale-credible
  owned organism (operating point **>3B**, a floor not a target; actual scale growth-determined) requires
  **TWO breakthroughs, both required:** **(W1) the PRETRAIN-SCALE wall** — an owned >3B base brought into
  existence affordably (compute-shatter C-EFF + growth C-GROW collapse the from-scratch token bill);
  **(W2) the FINETUNE-SCALE wall** — a native in-loop adaptation mechanism cheap enough that
  verifier-conditioned weight updates and C12 mode transitions run freely on the >3B model during the
  live loop. Memory-fit (a model-fits-and-takes-a-step probe) is the shared easy floor under BOTH walls
  and solves NEITHER — each wall's breakthrough is a measured **compute collapse** (tokens/FLOPs-to-base
  for W1; per-update cost-at-scale for W2), never a VRAM-fit. "Owned" is absolute — no borrowed/quantized
  base is ever load-bearing. ✗ `toy_scale_not_undismissable`, `invalid_fixed_scale_convenience`,
  `invalid_hardware_exit_ramp`, `invalid_memory_fit_as_scale_affordability`,
  `invalid_borrowed_base_as_owned_scale`. CHK: a scale-credibility receipt records
  `{operating_capability_point (>3B), W1:{measured_tokens_to_base, projected_dense_tokens_to_base,
  token_bill_collapse_ratio>1, growth_lineage_from_cbase_seed, no_borrowed_weights_load_bearing=true},
  W2:{native_finetune_mechanism_id, per_update_cost_at_scale, free_cognitive_mode_transition_receipt,
  no_borrowed_base=true}, measured_flops_to_capability, projected_dense_flops_to_capability (6ND),
  capability_per_compute_ratio>1, contribution_deletion_collapses_excess=true,
  active_working_set_bytes ≤ device floor}` — both W1 and W2 compute-collapse blocks load-bearing; a
  memory-fit-only receipt is `invalid_memory_fit_as_scale_affordability`.

- **C-E2B — owned core surpasses the E2B baseline at being Ember (both legs; milestone 2026-06-12,
  not retired by name).** R: the from-scratch owned core (no borrowed weights load-bearing) beats
  Gemma-E2B-swapped-into-Ember's-own-seat on BOTH legs at matched governed budget, with the paired
  protocol frozen before any verdict: **(i) Ember-work** — on the verify-floor worlds + self-curriculum
  accumulation loop, the owned core produces verified, transferring, deletion-surviving gains where
  E2B-in-the-same-seat does not (this leg now rides under C-SCALE/C8 — the owned organism must be
  scale-credibly better, not merely better than one small model); **(ii) founder-likeness** — runs its
  own event stream (mail, files, job receipts, schedule), initiates and completes its own work with
  receipts, answers when addressed, measurably better than E2B in the same seat (pulls the resident-
  kernel rung into the critical path). Does NOT count: a comparison on one leg only; a comparison not
  paired in Ember's own harness/worlds/budget; a borrowed/quantized core as the Ember side. The
  2026-06-22 forcing date is past → a shortfall is a measured-distance receipt and the loop continues;
  the milestone is live until met or retired by name. ✗ `invalid_e2b_unpaired`,
  `invalid_single_leg_surpass`. CHK: a paired surpass receipt records both legs at matched budget with
  the owned-core identity, OR a measured-distance receipt naming the remaining gap.
- **C-IND — operator-independence proof surface.** Full R/does-NOT-count/CHK text:
  @docs/spec/operator-independence-v1.md — registry-text-by-reference.
- **C-PROC — operator-visible process currency (GOAL.md §13; added 2026-07-02 by operator
  directive, verbatim in §13).** R: the delegation/review record the OPERATOR can see (public-repo
  issues, milestones, PRs) is CURRENT with the work record — work never runs ahead of its visible
  process reflection. Does NOT count: session-internal task entries, commit trailers, or any
  unobservable "equivalent" substituted for the visible surface (the 06-29 internalization defect);
  a hand-written receipt with no cited issue URLs; prose claims of currency. ✗
  `invalid_internal_task_as_issue`, `invalid_process_receipt_without_issue_urls`,
  `invalid_process_receipt_without_delegation`. CHK: the newest
  receipt under `receipts/process-visibility/` cites ≥1 public issue URL AND names covered
  commits that EXIST in both trees AND the newest work commit on either tree is ≤48h newer than
  the newest covered commit; receipt-absent on a scannable tree = RED; work outpacing the
  receipt by >48h = RED; the receipt must also enumerate open public PRs with review state
  (`open_prs`; or "none-open") and any PR verdict-pending >48h = RED (extension 2026-07-02,
  after PR #1 sat 32h unreviewed with nothing clocking it). Receipt schema v2 (gh issue #15,
  cutover 2026-07-03T02:00Z): a receipt whose `ts` is at/after the cutover must additionally
  carry a `delegation` block — an object keyed by issue ref, each entry `{built_by, verified_by}`
  both non-empty strings naming who built the work and who verified it; a missing/empty block, or
  any entry missing/empty `built_by`/`verified_by` = RED
  (`invalid_process_receipt_without_delegation`); receipts older than the cutover are
  grandfathered — clauses (a)-(d) still apply to them unchanged, no delegation block required.

- **C-SURFACE2 — inference+training visible & steerable, currently alive (GOAL #2; gh issue #11,
  "Surface-2 board probe: telemetry+steer receipts must be machine-checked, not just ticketed";
  companion to C-OBS / gh issue #10's cockpit lane).** R: the newest receipt under the EXECUTION
  tree's surface-2 telemetry receipts directory (`ember-surface2-telemetry/` under the execution
  tree's receipts root — absent from this contract tree by design) is real, CURRENT (non-synthetic, dated within 14
  days of the tree's newest work commit), names a steer/kill event captured on a governed
  finetune's control channel, and carries a positive token-delta anti-fixture value — the surface
  is CURRENTLY alive, not merely ticketed or archaeologically alive. Does NOT count: a receipt
  carrying `_synthetic_control_fixture: true` or a `synthetic_event` field (a test-injected
  marker, not real production telemetry); a stale receipt (>14d older than the newest work
  commit); a receipt/sibling with no `verb` in {"stop","pause","resume","adjust"} per the real
  `FinetuneControlCmd` schema (`tools/ember-cli/src/services/finetune-control.ts`); a
  `metrics_delta` that is absent or <=0. ✗ `invalid_surface2_receipt_absent`,
  `invalid_surface2_synthetic_receipt`, `invalid_surface2_stale_telemetry`,
  `invalid_surface2_no_steer_kill_event`, `invalid_surface2_token_delta_not_positive`. CHK: the
  newest receipt under `<local-exec-root>/receipts/
  ember-surface2-telemetry/*/*.json` (excluding underscore-prefixed meta dirs) is non-synthetic
  and its `ts` is within 14 days of `git log -1 --format=%ct HEAD` on that tree; AND that receipt
  or a sibling file in the same timestamped directory carries a `verb` field in
  {"stop","pause","resume","adjust"}; AND its (or a nested `tokens_predicted_delta`) `metrics_delta`
  field is a positive number; checked in that order, first failing clause is the reported reason.
  Receipt-absent or tree-absent = RED (not UNEVALUABLE — EMBER_EXEC_ROOT itself not existing is the
  only UNEVALUABLE case for this condition).

- **C-LEGIB — repo-legibility surface (gh issue #13; added 2026-07-02 by mandate-coverage sweep:
  "the repo-legibility surface [single-file entry map; cold-read re-probe green; no internal
  contradiction] has no condition, no probe, no ticket").** R: the repo is LEGIBLE to a fresh
  reader (agentic or human) with no prior session context — one entry-map file names every
  top-level directory's purpose, that map has been RE-VALIDATED by an actual cold read (not merely
  authored once and trusted), and the citation gate finds zero broken or misattributed references.
  Does NOT count: an entry-map file that omits a real top-level directory or maps one with an empty
  purpose cell; a cold-read-reprobe receipt that is a synthetic control fixture; a
  `check_goal_citations.py` run that never actually executed (prose claiming the citations are
  clean). ✗ `invalid_legib_dir_unmapped`, `invalid_legib_no_coldread_receipt`,
  `invalid_legib_synthetic_control_fixture`, `invalid_legib_citation_check_failed`. CHK: an
  entry-map file exists at the repo root (`AGENTS.md`, or the fallback name `docs/ENTRY-MAP.md` — not yet built, AGENTS.md is the live map) whose table names
  EVERY top-level directory the repo actually has (excluding `.git`) with a non-empty one-line
  purpose — any real directory absent from the map, or mapped with an empty purpose, is RED naming
  the dir(s); AND the newest receipt under `receipts/cold-read-reprobe/` (dir seeded 2026-07-02) exists and does not carry
  `_synthetic_control_fixture: true` — receipt-absent = RED; AND `scripts/check_goal_citations.py`
  is run (subprocess, 120s timeout) and exits 0 — nonzero = RED quoting its last output line,
  unable-to-run = UNEVALUABLE.

- **C-ENF — enforcement layer executes and coheres (gh issue #38, Class-2 cure, parent #35;
  added 2026-07-04 by maintainer per the frozen Deliverable-3 spec).** R: the standalone
  enforcement layer (`scripts/check_publication_gate.py`, `scripts/check_energy_law_theory.py`)
  EXECUTES under the board's own run and returns coherent dual-source verdicts — a GREEN board
  can never again coexist with a silently broken, missing, or tampered enforcement layer (the
  board previously only tamper-hashed these checkers, never ran them). The condition is
  EXECUTION INTEGRITY, deliberately NOT the publication gate's own open/closed direction: that
  gate is the endgame publication-readiness bar (kernel freeze, earned rung, BOOTSTRAP_PASS,
  claims map, research-focus test) and its honest verdict pre-publication is CLOSED — a coherent
  FAIL is GREEN-compatible here; its opening is judged by `docs/spec/publication-v1.md` §3,
  never by this row. Does NOT count: a checker that never executed; an exit code contradicting
  the checker's own printed verdict line (DISAGREEMENT — the probe-verdict-gate class: exit 0
  while printing RED); timeout / unparseable output (UNRESOLVABLE); a failing energy-law
  selftest (it is a selftest — coherent FAIL is still a regression); `enforcement_leg.py`
  itself missing or unimportable (fail-closed: the layer being gone IS the regression, RED not
  UNEVALUABLE). ✗ `invalid_enforcement_regression`. CHK: `test_c_enf.py` calls
  `enforcement_leg.run_enforcement_leg(ROOT)` (subprocess-executes both checkers, dual-source
  verdict resolution, leg receipt to `scratch/ember_totality/`); GREEN iff every registered
  checker has `executed: true` AND verdict in {PASS, FAIL} AND `check_energy_law_theory`
  verdict == PASS; first failing clause reported. UNEVALUABLE only for no-usable-root (env).

- **C-MILE — milestones mirror the lattice (Class-2 item 2,
  docs/audit/class2-unwatched-mandates-recon-20260704.md #2, parent gh issue #35 DISPATCH 3 of
  3; added 2026-07-04 by maintainer).** R: `check_milestone_reconciliation.py` EXECUTES under
  the board's own run and returns a coherent dual-source verdict — same un-wired-checker shape
  C-ENF cured, cured here for the milestone/lattice mirror. Unlike C-ENF, no honestly-closed
  pre-completion state exists for this checker — only PASS is GREEN-compatible. Does NOT count:
  never-executed; DISAGREEMENT; UNRESOLVABLE (incl. the checker's own ParseError path,
  stderr-only); `milestone_leg.py`/`enforcement_leg.py` missing (RED not UNEVALUABLE).
  ✗ `invalid_milestone_regression`. CHK: `test_c_mile.py` calls
  `milestone_leg.run_milestone_leg(ROOT)`; GREEN iff executed AND verdict==PASS.

- **C-DISC — disconfirmation triggers machine-evaluated (Class-2 item 3,
  docs/audit/class2-unwatched-mandates-recon-20260704.md #3, gh issue #94; added 2026-07-04
  by maintainer; schema frozen with 7 maintainer rulings R1–R7 quoted in the CHK docstring).**
  R: GOAL §8's program-level disconfirmation triggers (EARNED_GROWTH, H0_CEILING,
  B2_BOOTSTRAP) are evaluated by `check_disconfirmation_triggers.py` on every board run —
  never prose-only. A FIRED hinge is not itself a violation (fires are permanent history,
  R7); the violation is a fire with no valid escalation object
  (`receipts/escalation/<hinge>-*.json`, field list frozen R4) and no operator override
  (`receipts/escalation/override-<hinge>-*.json`). H0_CEILING is a state-check (R2);
  consecutive-attempt hinges count evaluable attempts only, chronological, program-grain
  (R3); hinge→receipt-class mapping frozen R6 (growth-rung-attempts, bootstrap-rung; the
  falsifier selftest receipt excluded by class). Does NOT count: checker never-executed;
  DISAGREEMENT; UNRESOLVABLE; `disconfirmation_leg.py` missing (RED not UNEVALUABLE).
  ✗ `invalid_disconfirmation_regression`. CHK: `test_c_disc.py` calls
  `disconfirmation_leg.run_disconfirmation_leg(ROOT)`; GREEN iff executed AND verdict==PASS.

- **C-LADM — episode-ledger admission ladder enforced (gh issue #95; added 2026-07-04 by
  maintainer; contract frozen with 5 maintainer rulings R1–R5,
  docs/audit/c-ladm-sec1-1-admission-recon-20260704.md is the phase-1 recon).** R: every row
  of `ledger/episodes.jsonl` + `ledger/control_pool.jsonl` (R1: these literal paths — never
  the totality receipt trail) satisfies the GOAL §1.1 admission ladder machine-checkably:
  boolean `verified` present; receipt present and resolvable for non-seed rows (seed-origin
  blanket-receipt exception honored and counted); every non-seed capability episode's task
  has ≥1 matched-control comparator in the pool (GOAL.md:17 "matched control" adversary
  class; math-core §5b `G_c` — an empty comparator class makes `G_c` vacuous); no duplicate
  keys; sampler/origin consistent when both present (R3); control pool all-unverified with
  dual-source sha integrity (R5: `ledger_dedup.py`'s own assert AND an independent recompute
  must agree). Verifier-instrument self-admission checked at instrument level once, with the
  per-episode gap DISCLOSED in the detail string (R2). Does NOT count: widening scope to
  sidecar views to dodge an offender set; editing ledger rows to satisfy the probe.
  ✗ `invalid_ladm_no_matched_control` (+ the 8 sibling tokens enumerated in the probe).
  CHK: `test_c_ladm.py`; GREEN iff zero offending rows across all rules.

- **C-AUTO — autonomy-ladder claim faithfulness (gh issue #104; added 2026-07-04 by
  maintainer; ladder contract `docs/spec/autonomy-relinquishment-ladder-v1.md`).** R: the
  ladder state file (`autonomy-ladder-state.json`) is schema-valid, cites a resolvable
  contract, and names the never-transfer safety floor (operator escalation set, governor
  caps, kill-discipline); every CLAIMED rung is backed by K≥5 consecutive resolvable window
  receipts under `receipts/autonomy-ladder/` with strictly-increasing ts; each rung's
  required provenance field (R0=none [window receipts carry `r0_provenance_binding`],
  R1=scheduler_provenance, R2=queue_provenance, R3=launch_token, R4=spec_provenance,
  R5=publication_provenance) is present, non-empty, and ember-attributed; a claim receipt
  exists per claimed rung; `current_rung` equals the highest claimed rung (or null);
  every reversion-log entry resolves to an incident receipt; a claim above the latest
  reversion target passes only if its claim-receipt ts postdates the reversion ts
  (legitimate re-climb) — missing/unparseable claim ts fails closed as stale. Zero claims
  = GREEN ("no rung claimed — honest"). Does NOT count: vacuous/EMPTY windows toward K
  (claim-from-silence); fabricated window refs; post-hoc state edits without receipts.
  ✗ `invalid_autonomy_unreceipted_claim`, `invalid_autonomy_window_gap`,
  `invalid_autonomy_provenance_missing`, `invalid_autonomy_state_claim_mismatch`,
  `invalid_autonomy_reversion_ignored`. CHK: `test_c_auto.py`; GREEN iff zero offenders.

### 4.3 Numeric closure (the only completion authority)

**Count ruling (2026-07-02, relocated from GOAL.md §4.1; re-ruled same day on C-IND's addition,
GOAL.md §4.0 amendment 10; re-ruled 2026-07-02 later the same day on C-PROC's addition per
GOAL.md §13; re-ruled again same day on C-LEGIB's addition, gh issue #13):** the registry = 33
primary conditions (C(−1), C0–C15, C-EFF, C-BASE, C-PORT, C-FED, C-GROW, C-ORGANISM, C-OBS,
C-ANAT, C-SCALE, C-E2B, C-IND, C-PROC, C-LEGIB, C-SURFACE2, C-ENF, C-MILE, C-DISC, C-LADM,
C-AUTO) + 2 roll-ups (C-MANIFEST, C-TALLY) = 38 entries (re-ruled 2026-07-03 on C-SURFACE2's
addition, gh issue #11: 31 primary + 2 roll-ups; re-ruled 2026-07-04 on C-ENF's addition, gh
issue #38: 32 primary + 2 roll-ups; re-ruled 2026-07-04 on C-MILE's addition, gh issue #35
DISPATCH 3 of 3: 33 primary + 2 roll-ups; re-ruled 2026-07-04 on C-DISC's addition, gh issue
#94: 34 primary + 2 roll-ups; re-ruled 2026-07-04 on C-LADM's addition, gh issue #95: 35
primary + 2 roll-ups; re-ruled 2026-07-04 on C-AUTO's addition, gh issue #104: 36 primary + 2
roll-ups); any "37", "36", "35", "34", "33", "31", "30", "29" or "28" elsewhere is a stale
intermediate count, corrected by this ruling.

- **C-MANIFEST.** `docs/ember-completeness.md` enumerates every planned piece (id, subgoal, AC, test,
  receipt pointer, status). A planned piece absent from the manifest is a gate violation. ✗
  `invalid_unmanifested_piece`.
- **C-TALLY.** `scripts/ember_tally.py` walks the manifest, verifies each row's receipt exists AND
  passes its named check, emits `receipts/tally-<ts>.json {total, implemented, pct, missing[]}`. The
  tally receipt is the only completion authority. Each §4 CHK must be backed by an **executable check**
  the tally invokes; a non-executable CHK counts as `missing[]`, never pass. ✗ pct<100. CHK: pct=100,
  `missing[]` empty, every CHK executable.
- **GOAL SATISFIED ⇔** every §4.1/§4.2 STATE-condition CHK passes **AND** zero unresolved
  post-epoch process-invariant incidents (GOAL.md §4.0(9) split, 2026-07-02: C0/C9/C15-class
  rows are cadence-audited invariants, not completion conjuncts) **AND** C-TALLY pct=100 **AND**
  the C8 field-level receipt exists **AND** the C-SCALE scale-credibility receipt exists. A green board at toy scale with
  no C-SCALE receipt is `warm_up_not_win`, never complete.

### 4.4 Totality test spec (TDD — every condition is an executable test that FAILS until met)

Every §4.1/§4.2 condition is realized as an executable test in `scripts/ember_totality/` (runner
`ember_totality_spec.py`). Each test (a) asserts the condition's positive CHK against a **real**
receipt, (b) asserts none of its does-NOT-count invalid-tokens match, (c) RUNS and reports one of THREE
values (amendment 2026-07-02, GOAL.md §4.1): GREEN (a real receipt passes), RED (inputs found,
condition unmet), or UNEVALUABLE(env) (the probe's input could not be located or opened —
counts as RED for completion math, never reported as an evaluated failure) — never raw
*errors*. A non-executable test counts as UNEVALUABLE. STANDING PROCESS-INVARIANT rows
(C0/C9/C15-class, GOAL.md §4.0(9)) render as AUDIT-OK / AUDIT-INCIDENT from the epoch —
cadence-audit results, never completion conjuncts; PRE-EPOCH (no acceptance object exists yet)
they render AUDIT-PENDING — neither OK nor INCIDENT, never RED (2026-07-02; the executable
runner emits this as `AUDIT-PENDING-EPOCH`, same status, more precise label — and defensively
reclassifies a crashed/contract-violating invariant probe to it rather than leak RED/UNEVALUABLE). The red/green board BECOMES the definition
of done when its registry covers all 30 entries (GOAL.md §4.1); it is the observatory's core
view.
Completion ⇔ every STATE-condition test GREEN ∧ zero AUDIT-INCIDENT ⇔ §4.3 pct=100 (AUDIT rows
are cadence results, never GREEN — 2026-07-02). ✗ `invalid_condition_without_executable_test`.

---

## 5. GLOBAL INVARIANTS (enforcement infra — held outside Ember's write surface, never self-editable)

- **Five un-removable invariants:** (1) the three-test gain gate (held-out transfer + matched control
  + deletion on every gain); (2) the resource governor + headroom rule; (3) this goal file +
  only-the-operator-retires-it; (4) receipts-only truth; (5) this enforcement layer itself.
- **Resource governor + headroom (mechanically enforced; fix-forward on a violation is BANNED — kill
  and relaunch governed):** never 100% GPU/CPU wall-to-wall; per-process device-adaptive VRAM cap
  (`EMBER_VRAM_FRACTION≤0.80` of the runtime-queried device total; tighten-only) + free-margin assert
  + `decode_pacer()` in every generate path + duty-cycle throttle; CPU pools below core count.
  Comfortable residency is a correctness criterion — prefer the smallest core that clears the verify
  floor. No run >1h until the ceiling is solved; >12 GPU-h needs a gate-9 lever receipt.
- **Nothing leaves this machine without operator approval** (escalation set). **No personal name** in
  anything git-tracked or public — use "per maintainer direction."
- **Skill-gates (pinned, not hoped):** first-principles before accepting any cost/constraint/timeline/
  "impossible"/deferral or conceding a wall; test-driven-development (failing test first) on every
  harness/adapter/evaluator build; systematic-debugging (root cause before fix) on every blocker;
  **verification-before-completion as the universal close-gate — runs before any PASS/gate-green/"done"
  is written or reported.**
- **Visual verification via agents only** — never drive a browser from the goal session.

---

## 6. DEFINITIONS & FIXED CONTRACTS

- **Field-level breakthrough** = a falsifiable ML/AI contribution mattering beyond Ember's local run,
  exactly one primary class (C8); not a transfer claim, plausible claim, engineering improvement,
  harness integration, score progress, or proof wrapper.
- **Resident-training A/B/C/deleted contract (fixed):** A = same task/evaluator/harness envelope, no
  native goal organ, no resident update; B = walled harness + fixed hand-authored or prompt/rule
  policy, no learned update; C = same harness with a model-learned RLM/iGRPO neural update that changes
  later action selection; Deleted = C with the native organ / recursive-query policy / verifier-
  conditioned update / harness action channel removed. Budgets/evaluator/data/seeds matched. C beats A
  and B; Deleted degrades/blocks; per-task rows; C transfers beyond the slice; the neural delta is
  load-bearing.
- **Owned base** = pretrained from scratch on this machine, no borrowed weights load-bearing. A frozen
  base is NOT acceptable (the historical "or frozen base checkpoint" escape is closed).
- **Substrate invariant:** softmax(QKᵀ/√d)V is the only *empirically proven* non-biological-intelligence
  substrate (the principle = lossless content-addressable associative routing). Ember's base stays
  attention-based — no efficiency/shatter/growth lever may obtain its gain by abandoning attention for
  an unproven O(n)/lossy substitute (`invalid_substrate_downgrade`); sub-quadratic is permitted ONLY
  where recall is *provably* not lost. Attention is *transient* self-modification; Ember's contribution
  is the **persistent write** — consolidating verified in-context adaptation into weights (W2/C11).
  Ember completes attention; it does not replace it.
- **Objective = sovereign computing:** train + quantize + run recursive loops indefinitely on private
  local hardware, nothing leaving the machine. Sovereignty subsumes "owned base," "nothing leaves the
  machine," C-PORT, and C-FED-egress-gated.
- **The unbounded all-pairs dot-product is a target to BREAK for sovereign recursion.** A sovereign
  recursive organism runs on fixed FLOP/s for an unbounded lifetime t with context growing in t;
  all-pairs scoring is O(t)/token → the organism halts asymptotically. Legitimate replacement preserves
  content-addressable associative recall while bounding per-step cost: content-addressable SUB-LINEAR
  retrieval (~O(log t) ANN/hashing/learned index), not a lossy O(n) substitute. EVAL: the falsifiable
  receipt measures the **recursive-loop cost curve (per-step cost vs lifetime t)** AND recall-exactness
  vs full attention, on Ember's own model. PASS = per-step cost sub-linear in t AND recall provably not lost vs full attention — the
  substrate invariant's own bar (above); any ε-tolerance must be pre-registered with a pinned value
  and reconciled against `invalid_substrate_downgrade` BEFORE the run, never cited loose at PASS time. A single-forward-pass speedup is the wrong instrument and does not count. This is the
  sovereign-computing enabler and a candidate field-level C8. ✗ `invalid_good_enough_sidestep`,
  `invalid_substrate_downgrade`, `invalid_cost_grows_with_lifetime`.
- **Done** = §4 completion rule satisfied: every §4.1/§4.2 CHK passes AND tally pct=100 AND C8 receipt
  exists AND C-SCALE receipt exists. Blocked/incomplete otherwise.

---


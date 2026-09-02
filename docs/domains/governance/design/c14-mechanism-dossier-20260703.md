# C14 Mechanism Design Dossier — issue #41

Sources: `src/ember/governance/scripts/ember_c14_owned_run.py`, `scripts/ember_c14_contract_rig.py`,
`scripts/ember_resident_igrpo.py`, `src/ember/governance/scripts/ember_phase3_c14/igrpo_trainer.py`,
`src/ember/governance/scripts/ember_phase3_c14/resident_adapter.py`, `src/ember/governance/scripts/ember_c14_owned_core.py`,
`receipts/ember-c14-owned-run/live-20260703T215130Z.json` (fire-4, verdict
`C14-LIVE-NOT-CLEARED`, `clearance: false`, `elapsed_s: 12768.56`).

All facts below are sourced to file:line or to the named receipt field. No
design proposals or recommendations are included.

---

## (a) TASK SEMANTICS

**State/action space.** The state domain is the 8 integers `{0..7}`
(`STATE_DOMAIN = list(range(8))`, `ember_c14_owned_run.py:324`). The action
space used for reward scoring is also `{0..7}` (the increment-mod-8 target),
but the real owned core's raw sampling space is the full ~32000-token
vocabulary; a wrapper (`_ActionBandPolicy`, `ember_c14_owned_run.py:587-893`)
restricts SAMPLING (never gradient flow) to a 10-token band: tokens 0-7 are
valid actions, 8=`ACTION_FINAL`, 9=`ACTION_RECURSE` (`VOCAB_SIZE = 10`,
`ember_resident_igrpo.py:51-54`). This band restriction was added after an
empirically-observed defect: without it, at true 32000-token vocab scale the
RLM episode's fallback (`_no_action_fallback`, see (b) below) fires on
~99% of episodes and saturates every arm's reward to a trivial 1.0
(`ember_c14_owned_run.py:592-609`).

**Target rule.** `correct_action = (state_val + 1) % 8`, executed fresh by the
verifier every call, never looked up from a stored table
(`_executing_verifier`, `ember_c14_owned_run.py:555-584`; base definition
`executing_verifier`, `ember_resident_igrpo.py:67-80`).

**Train/heldout split construction.** `generate_corpus()`
(`ember_c14_owned_run.py:327-459`) builds a `random.Random(seed)` instance,
shuffles the 8-element `STATE_DOMAIN`, and takes the first `heldout_size`
values (3, in the receipted run) as `heldout_state_vals`, the rest as
`train_state_vals` (`ember_c14_owned_run.py:388-392`). This is a disjoint
split over the state_val FAMILY PARAMETER itself — no state_val appears in
both splits — which the file's own docstring (`ember_c14_owned_run.py:343-356`)
contrasts with the older stub rig's built-in corpus
(`_make_stub_corpus`, `ember_c14_contract_rig.py:210-229`), whose held-out
state_vals (5,6,7,3) are a subset of the value range train already covers
(different task IDs, same value range — not a genuinely held-out parameter
range).

From the fire-4 receipt (`corpus.seed=20260702`):
`train_state_vals=[0,2,5,6,7]` (5 tasks), `heldout_state_vals=[1,3,4]`
(3 tasks).

**Interpolation vs. extrapolation.** The domain is the finite cyclic set
`{0,...,7}`; train already spans the full range's endpoints (min=0, max=7).
The 3 held-out values (1, 3, 4) all lie strictly inside `[0,7]`, i.e.
inside the range already spanned by train. By construction this split is
an interpolation-style split (missing categorical values within an
already-spanned range), never an extrapolation split (no held-out value
falls outside train's min/max) — this is a structural fact of an 8-value
cyclic domain with only 3 held out, not a property that could differ run to
run under this generator.

**Corpus-v2 exemplars.** Each task additionally carries `k_exemplars=3`
in-context `(exemplar_state, exemplar_action)` pairs, drawn ONLY from
`train_state_vals`, for BOTH train and heldout tasks
(`ember_c14_owned_run.py:394-431`; echo-proof assertions at
`ember_c14_contract_rig.py:180-203` forbid an exemplar's state/action
equalling the task's own queried state/answer, and forbid exemplar states
outside `train_state_vals`). From the receipt, `corpus_version: "v2"`,
`k_exemplars: 3`, and the full `exemplar_assignment` map is recorded (e.g.
`held_s01: [5,6,7]`, `held_s03: [0,5,7]`, `held_s04: [0,2,5]`). This makes
heldout solvability a genuine "apply the rule demonstrated via exemplars
to an unseen state" test, never won by construction.

---

## (b) REWARD PATHWAY

**Model output → verifier.** `rlm_generate`/`_rlm_generate_batch`
(`ember_resident_igrpo.py:286-416`, `633-819`) produce an `RLMEpisode` whose
`final_action` is the last in-band (`<8`) token emitted before an
`ACTION_FINAL`/loop-exhaustion termination. If no in-band token was ever
emitted, `final_action` falls back to `_no_action_fallback(state_val) =
(state_val + 2) % 8` — an in-band but DETERMINISTICALLY WRONG token (never
accidentally the correct `(state_val+1)%8` answer), and
`episode.fallback_fired = True` is set (`ember_resident_igrpo.py:83-96`).
`_executing_verifier(task, emitted_action)` then recomputes
`correct = (task.state_val + 1) % 8` and returns `1.0 if (emitted_action %
8) == correct else 0.0` (`ember_c14_owned_run.py:555-584`).

**Binary, no partial credit.** Every code path that produces a reward
returns exactly `0.0` or `1.0`; `compute_advantages` and
`compute_advantages_per_state` (`ember_resident_igrpo.py:825-904`) only ever
consume this binary signal — there is no continuous or partial-credit
reward anywhere in this pipeline. The reward IS computed for every single
rollout (never withheld/sparse-in-time); what is sparse is the PASS RATE
(2/5 = 0.4 on train, 0/3 = 0.0 on heldout in the fire-4 receipt's final
arm_scores), not the scoring frequency.

**Zero-reward trajectories.** Within one Stage-2 group of `G` rollouts for a
single state_val: if `compute_advantages` sees `std(rewards) == 0` (every
rollout in the group scored identically, including all-zero), it returns
`A_j = 0` for every sample in that group (`ember_resident_igrpo.py:825-850`).
Under `--degenerate-resample` (`degenerate_resample=true` in this receipt's
`envelope_v1_7`), a degenerate group is resampled ONCE at
`resample_temperature=2.0` before accepting `A_j=0`
(`ember_resident_igrpo.py:1186-1193`; knob defined `igrpo_stage2`
docstring, `ember_resident_igrpo.py:1117-1146`). A zero advantage
contributes exactly `0` to the scalar loss term for that sample
(`per_tok[credited_idx]` with `A=0`), so the step still runs a real
forward/backward pass but with a mathematically-zero gradient contribution
— this exact property is asserted directly by test suites in both
`ember_resident_igrpo.py` (T9, `~line 1704-1750`) and `igrpo_trainer.py`
(`test_name = "degenerate_zero_reward_no_weight_change"`, lines 409-493).
Individual zero-reward samples inside a MIXED (non-degenerate) group are NOT
dropped — they receive a real (negative, below-mean) advantage and
contribute gradient that pushes the policy away from that behavior.

---

## (c) UPDATE PATH

**Which parameters get gradients — depends on mode.** In `--owned-smoke` and
`--live` (the REAL owned-core paths, and the path the fire-4 receipt is
from), a `LoRAAdapter` wraps the frozen owned core
(`ember_c14_owned_core.py`, docstring lines 22-28; `LoRAAdapter.__init__`,
`resident_adapter.py:147-187`). `freeze_base=True` calls
`param.requires_grad_(False)` on every base parameter
(`resident_adapter.py:182-184`), so the frozen base (backbone_model,
mtp_heads, and the `head` linear itself, which is architecturally tied to
the input embedding per `cbase_grow_dryrun.build_model`) receives NO
gradient. Only `lora_A` (`[in_features, rank]`) and `lora_B`
(`[rank, out_features]`), injected at the `"head"` linear via a forward
hook, are trainable (`LoRALayer.__init__`, `resident_adapter.py:93-119`;
`trainable_params = [p for p in base_adapter.parameters() if
p.requires_grad]`, `ember_c14_owned_run.py:1168`). LoRA rank defaults to 8
(`--lora-rank` CLI default, `ember_c14_owned_run.py:1984`); the fire-4
receipt does not itself record the rank used (see gap noted below).
In `--dry-run` (the CPU toy path, NOT what fire-4 ran), by contrast, the
FULL `TinyPolicyTransformer` core is optimized directly — `torch.optim.Adam
(core.parameters(), lr=lr)` with no adapter at all
(`ember_c14_contract_rig.py:534`).

**Loss expression.** iGRPO Eq. 5, clipped importance-ratio policy gradient
minus an optional `beta * KL` term (`beta=0.0` throughout this run — no KL
term contributes), scored at ONE "credited" token position per episode
rather than averaged over the full sampled sequence (the "D6 fix",
`ember_resident_igrpo.py:1212-1413`). For refinement `j`: `ratio_jt =
exp(log pi_theta(o_jt) - log pi_theta_old(o_jt))` at the credited position
`t` (the last occurrence of the episode's `final_action` in its verbatim
sampled-token sequence, `ember_resident_igrpo.py:1326-1353`); `surr1 =
ratio*A_j`, `surr2 = clip(ratio, 1-eps, 1+eps)*A_j`; `per_tok =
min(surr1,surr2) - beta*KL_hat`; the scalar `per_tok[credited_idx]` is
collected per refinement and `loss = -mean(scalars)` over the group
(`ember_resident_igrpo.py:1404-1413`). `loss.backward(); optimizer.step()`
(`igrpo_step`, `ember_resident_igrpo.py:1512-1524`; equivalently
`train_one_step`, `igrpo_trainer.py:279-294`, which is the actual function
`--owned-smoke`/`--live` call).

**Verifier-conditioning (iGRPO's two stages).** Stage-1
(`igrpo_stage1`, `ember_resident_igrpo.py:1029-1075`) samples `N` exploratory
drafts with NO gradient, verifier-scores each, and selects `d-hat = argmax
reward`. Stage-2 (`igrpo_stage2`, `ember_resident_igrpo.py:1078-1209`)
conditions on the augmented prefix `q' = concat(obs, d-hat)`, samples `G`
refinements from THAT prefix, and verifier-scores each refinement — these
`G` scored refinements are the actual gradient-bearing rollouts. So the
verifier enters twice per step: once to pick `d-hat`, once to produce the
rewards that become the Stage-2 advantages.

**Batch construction.** One training step = one `state_val`, cycled
round-robin over the 5 train tasks (`task = train_tasks[step_idx %
len(train_tasks)]`, `ember_c14_contract_rig.py:543`). The rig's C-arm loop
hard-codes `N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5` on every
`train_resident_fn` call (`ember_c14_contract_rig.py:567-577`) — `--live`'s
`--igrpo-n`/`--igrpo-m` CLI flags (defaults 2/4) are consumed only as a
`kwargs.pop(..., args.igrpo_n)` fallback inside `_train_fn`
(`ember_c14_owned_run.py:1710-1711`), and since the rig always supplies
`N`/`G` explicitly, those CLI flags have NO effect on `--live`/`--dry-run` —
they only matter for `--owned-smoke`'s separate one-task smoke path.
`temperature=1.5` is likewise the rig's hard-coded value UNLESS
`--temp-schedule` is set (it was, in this run: `"1.5:1.0:384"`, linear decay
from 1.5 to 1.0 by step 384 — `_resolve_rollout_temperature`,
`ember_c14_owned_run.py:249-281`).

**Baseline/advantage computation.** Group-relative `(r_j - mean(r)) /
std(r)` (population std, divide by `n` not `n-1`) over the `G=4` Stage-2
rollouts for the ONE state_val trained this step
(`compute_advantages`, `ember_resident_igrpo.py:825-850`). This run's
`envelope_v1_7.per_state_reward_norm = false`, so the v1.9 per-state
normalization lever (`compute_advantages_per_state`,
`ember_resident_igrpo.py:864-904`) was NOT engaged — though the code's own
docstring notes this lever would be a structural no-op at this call site
regardless, since each Stage-2 group is already single-state
(`ember_resident_igrpo.py:1148-1167`). `entropy_beta=0.02` (nonzero in this
run) adds a UNIFORM bonus `entropy_beta * H(pi(.|s))` to every advantage in
the group, independent of each sample's own reward
(`ember_resident_igrpo.py:1195-1201`).

**Receipt gap (fact, not interpretation).** The fire-4 `--live` receipt's
final payload (`C14-LIVE-PASS`/`C14-LIVE-NOT-CLEARED` branch,
`ember_c14_owned_run.py:1879-1893`) does NOT include a `config` block with
`lora_rank`/`lr`/`igrpo_n`/`igrpo_m`/`temperature` — unlike the
`--dry-run`/`--owned-smoke` payloads, which do carry such a block
(`ember_c14_owned_run.py:1061-1068`, `1273-1281`). Only the
`envelope_v1_7` anti-collapse/v1.9/v2.0/v2.1 knob block and the
`candidate_manifest`/`resident_training_candidate` (seed-checkpoint path,
trained-adapter checkpoint path) are recorded for `--live`. The seed
checkpoint used was an A20 override (`models/cbase-grow-rung/rung1-
20260703T155447Z/stabilize/checkpoints/step-00000766/model.pt`), NOT the
module's default `cbase-v0` seed (`SEED_CKPT_DEFAULT =
models/cbase-smoke-run/checkpoints/step-00000610`, `ember_c14_owned_core.py:97`).

---

## (d) TRAIN-TASK EVOLUTION

Per-checkpoint TASK IDENTITY IS recorded, not just counts. The fire-4
receipt's `checkpoint_evals` array carries, at every one of the 16
checkpoints (steps 64, 128, ..., 1024), a full `train_rows` list with
`{id, state_val, action, reward}` for each of the 5 train tasks — this is
an additive fact beyond `train_pass_count`, which is only a derived
summary of those same rows (`_make_checkpoint_eval_callback`,
`ember_c14_owned_run.py:183-223`).

Reconstructed pass membership per checkpoint (which of the 5 train tasks
scored `reward=1.0`), read directly from `checkpoint_evals[i].train_rows`:

| step | passing train tasks | train_pass_count |
|---|---|---|
| 64  | (none) | 0 |
| 128 | train_s07 | 1 |
| 192 | train_s07 | 1 |
| 256 | train_s07 | 1 |
| 320 | train_s07 | 1 |
| 384 | train_s07 | 1 |
| 448 | train_s02, train_s07 | 2 |
| 512 | train_s02, train_s07 | 2 |
| 576 | train_s02, train_s07 | 2 |
| 640 | train_s02, train_s07 | 2 |
| 704 | train_s02, train_s07 | 2 |
| 768 | train_s02, train_s07 | 2 |
| 832 | train_s02, train_s07 | 2 |
| 896 | train_s02, train_s07 | 2 |
| 960 | train_s02, train_s07 | 2 |
| 1024 | train_s02, train_s07 | 2 |

Membership does NOT oscillate from step 448 onward: the same two tasks
(`train_s02`, `train_s07`) pass at every one of the last 10 checkpoints,
confirming the working assumption "the same 2 train tasks pass from step
448" as TRUE against this receipt. `train_s00`, `train_s05`, `train_s06`
never pass at any checkpoint from step 64 through 1024 (0/16 each) — this
matches the final `arm_scores.C.train` rows exactly (`train_s00`/`train_s05`
/`train_s06` all `reward: 0.0`; `train_s02`/`train_s07` both `reward: 1.0`,
`pass_rate: 0.4`).

`train_s07`'s correct action is `(7+1)%8 = 0`; `train_s02`'s correct action
is `(2+1)%8 = 3`. Both tasks pass with `action: 0` and `action: 3`
respectively at every checkpoint from their first pass onward. At the SAME
checkpoints, the model's emitted action for the OTHER, non-passing train
tasks is also frequently `0` or `3` (e.g. step 128: `train_s00`, `train_s02`,
`train_s05`, `train_s06` all emit `action: 0`; step 448 onward: `train_s05`,
`train_s06` both emit `action: 3`, which is wrong for their own states —
correct for state 5 is 6, for state 6 is 7). This is a directly-observed
fact from the receipt's per-checkpoint rows: the two actions (`0`, `3`)
that happen to satisfy `train_s07` and `train_s02` respectively recur
across most OTHER train tasks' outputs as well, where they are wrong.

---

## (e) HELDOUT FAILURE MODE

**Final arm_scores, C arm (trained), heldout split:** `held_s01` (state=1,
correct=2) → emitted `action: 3`, reward 0.0. `held_s03` (state=3,
correct=4) → emitted `action: 3`, reward 0.0. `held_s04` (state=4,
correct=5) → emitted `action: 3`, reward 0.0. All three heldout tasks
converge to emitting the SAME action, `3` — which is `train_s02`'s own
correct answer, not any function of the heldout task's own state, and not
the correct answer for any of the three heldout states.

**A-arm (untrained baseline), heldout split, for comparison:** `held_s01`
→ `action: 3`. `held_s03` → `action: 5`. `held_s04` → `action: 6`. These
values are EXACTLY `(state_val + 2) % 8` for each state (1+2=3, 3+2=5,
4+2=6) — i.e. the A-arm's outputs are exactly `_no_action_fallback`'s
signature (`ember_resident_igrpo.py:83-96`), confirming the working
assumption "the untrained core emits state+2" as TRUE for the untrained
baseline's heldout behavior in this receipt. This means the untrained
core's greedy decode is hitting the deterministic-wrong fallback on every
heldout episode (never producing a valid in-band action of its own accord
on these tasks).

**Deleted arm exactly matches A-arm.** `Deleted.heldout` rows are
byte-identical to `A.heldout` (`held_s01: action 3`, `held_s03: action 5`,
`held_s04: action 6`), consistent with `guard_a_deleted_restores_core:
true` and the matching `pre_c_hash`/`deleted_hash` in `guard_results`.

**Did training move heldout behavior at all?** Yes, but not toward the
target rule and not toward each heldout state's own correct answer.
Comparing the trained C-arm (`3, 3, 3`) against the untrained/deleted
baseline (`3, 5, 6`): `held_s01` is UNCHANGED (3 in both — same digit, but
for different underlying reasons: A-arm reaches 3 via the fallback formula
`state+2`; C-arm reaches 3 as its trained/collapsed output). `held_s03`
moved from `5` (state+2 fallback) to `3` (train_s02's memorized answer;
correct would be `4`). `held_s04` moved from `6` (state+2 fallback) to `3`
(same memorized answer; correct would be `5`). So training moved 2 of the
3 heldout tasks AWAY from the untrained state+2 fallback pattern and TOWARD
the constant action (`3`) that satisfies one specific TRAIN task
(`train_s02`), rather than toward either the general increment rule or the
heldout task's own individually-correct action. The checkpoint series
confirms this is a late-training-stage convergence, not a from-the-start
constant: `held_s03`/`held_s04` still showed state+2-pattern values (`5`,
`6`) at checkpoint step 320, and only both settle to the constant `3`
by step 448 onward (matching exactly the checkpoint step at which
`train_s02` itself first passes, per section (d)'s table) — i.e. the same
weight change that first satisfies `train_s02` on train is the one that
carries the `action=3` output onto the heldout states as well.

**Gate predicates on this receipt (for context, not proposal).**
`c_beats_a_heldout: false`, `c_beats_b_heldout: false`,
`deletion_drops_heldout_c_tasks: false` (with `c_new_passes_heldout: 0`,
`deleted_drops_count: 0` — predicate (4) reads `false` because C never
newly-passed ANY heldout task relative to A, so there was nothing for
deletion to drop, not because deletion failed to remove a real gain).
`clearance: false`, `verdict: "C14-LIVE-NOT-CLEARED"`. All 8
does-NOT-count guards pass (`guard_results.*: true`), including guard (h)
reward-dependence (`c_train_rate: 0.4`, `c_scrambled_train_rate: 0.2`,
`a_train_rate: 0.0` — 0.2 does not exceed `0.0 + 0.20` tolerance, so the
scrambled-reward arm does not "beat" A, meaning the trainer IS
reward-dependent, not a reward-ignoring weight-setter).

---

## Assumption check (explicit, as requested)

1. **"Reward is sparse binary"** — CONFIRMED as binary (`{0.0, 1.0}`
   exclusively, no partial credit anywhere in `compute_advantages`/
   `compute_advantages_per_state`/`_executing_verifier`). "Sparse" is
   imprecise if read as "infrequently scored" — every rollout is scored
   every time; what is sparse is the PASS RATE (0.4 train, 0.0 heldout).
2. **"The untrained core emits state+2"** — CONFIRMED, exactly, for the
   A-arm's heldout rows in this receipt (`held_s01→3, held_s03→5,
   held_s04→6` = `(state_val+2)%8` for each), and this is not a
   coincidence: it is precisely `_no_action_fallback`'s hard-coded formula
   (`ember_resident_igrpo.py:96`), meaning the untrained core's greedy
   decode never emits a valid in-band action on these heldout episodes and
   always falls through to this deterministic-wrong default.
3. **"The same 2 train tasks pass from step 448"** — CONFIRMED against the
   receipt's `checkpoint_evals[*].train_rows` (per-task identity IS
   recorded per checkpoint, contrary to any assumption that only
   aggregate counts exist): `train_s02` and `train_s07` pass at every
   checkpoint from step 448 through the final step 1024, with no
   oscillation in between.

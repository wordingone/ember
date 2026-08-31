# Registered deviations — frozen-prereg changes (fp-30b deviation protocol)

Frozen preregs may only change via a deviation note filed **BEFORE** the changed
run, never after. One entry per deviation, newest first. Each names: the frozen
artifact + its freeze SHA/date, what changes, why, and who owns the call.

---

## DEV-008 — EMBER-02 R1-E8: charged-budget projection remains external authority

**Date filed:** 2026-08-18, before any A1 liveness receipt or R1-E8 verdict.
**Frozen artifacts:** `docs/domains/governance/spec/ember02-preregistration-v1.md` and
`docs/spec/ember02-preregistration-thresholds-v1.json`.

**Gap recorded, no formula amendment:** the preregistration freezes T-08 as
`A1 equal-budget tokens / A3 tokens >= 0.33` and requires tokens/second plus
proxy-joules/token measurements, but it does not freeze a rule that converts
those two measurements into one projected R2 charged-budget token count. The
R1-E8 source carrier therefore does not invent that rule. It requires an
external canonical `ember02-r2-charged-budget-contract-v1` receipt, reopens and
hash-binds it to both matched run receipts, and remains `EVIDENCE_MISSING`
forever when it is absent. This entry grants no liveness, parity, execution,
compute, capability, or issue-closure credit.

**Why / owner:** fail-closed implementation ruling for issue #1464 Packet A,
independently reviewed on 2026-08-18. The future charged-budget authority owns
the projection definition; Packet A owns only byte and arithmetic validation.

---

## DEV-007 — eval-suite-freeze-v1 (battery-14): HellaSwag scored split bound to revision-pinned validation; contamination gate remains pending

**Date filed:** 2026-08-18, before any #1433 WARM-100 evaluation or capability
claim consumes this amendment. **Frozen artifact:**
`docs/spec/eval-suite-freeze-v1.md`.

**What changes:** the HellaSwag scoring instrument moves from the upstream
unlabelled `test` split to the labelled `validation` split that the installed
`lm_eval` task actually scores. The governed override pins dataset revision
`218ec52e09a7e7462a5400043bb9a69a41d06b76`; the exact scored file is
`data/validation-00000-of-00001.parquet`, 10,042 rows, SHA-256
`899813071e1e95efafec90f856e1987d2150fa4d020fc005df6962c259f660cd`.
The scorer reopens that revision, row count, and cached parquet hash at runtime
and binds per-row `doc_hash`, `prompt_hash`, and `target_hash` values into raw
prediction evidence.

**Contamination boundary:** the historical 8/10,003 HellaSwag exclusions remain
valid only for the old unlabelled `test` split against historical `shards-v0`.
They are not copied to `validation`. The amended HellaSwag instrument is
`PENDING_FINAL_CORPUS_CONTAMINATION_SCAN`, and every receipt says
`ready_for_compute=false`, until the exact 10,042-row validation split is scanned
against the final tokenized training corpus consumed by WARM-100. The current
canonical scanner is deliberately bound to historical `shards-v0`; the #1719
corpus is still growing and is not yet that final tokenized corpus. Any later
corpus admission also invalidates an earlier scan and requires recensus at run
entry.

**Why:** the upstream HellaSwag `test` split has no labels, while the installed
harness scores `validation`. Pretending the old test hash or exclusion count
describes the scored rows would create a plausible but false receipt. This
amendment corrects only the split/revision/file identity and keeps the unresolved
contamination gate visible; it grants no READY_FOR_COMPUTE, result, capability,
GPU, or issue-closure credit. **Who owns the call:** the 2026-08-18 independent
#1433 review ruling. Relates to #1433 and #1498.

---

## DEV-006 — A1 freeze declaration (battery-14): consumer rule (3) amended — ancestry binding → declaration-content-in-master binding

**Date filed:** 2026-07-10 (the A1 machinery-cure lane, issue #631, executing the
coordinator ruling R3 posted on PR #645). **Filed before any governed launch consumes
the freeze.** **Frozen artifact:**
`receipts/eval-suite-freeze/a1-freeze-declaration-20260709T233050Z.json` (byte-law
immutable; its bytes are NOT edited — this entry amends the consumer-verification
rule its `eval_freeze_hash_rule` clause (3) states).

**What changes:** the declaration's consumer rule (3) — "the pointer commit is an
ancestor of the ref they build from" — is amended to **declaration-content-in-master
binding**: a consumer verifies (1) the pointer file
`receipts/eval-suite-freeze/EVAL-FREEZE-HASH` names commit `ccde4a67` and that commit
contains the declaration byte-identical (unchanged), (2) `freeze_ts` predates the
consumer's `launch_ts` (unchanged), and (3-amended) **the declaration file is present
byte-identical in the build-ref's tree** (master lineage), failing CLOSED on any
content mismatch or absence. Ancestry of the pointer commit is recorded and disclosed
by the consumer, no longer required.

**Why:** PR #603 was squash-merged, so the freeze-content commit `ccde4a67` the
pointer names is dangling — reachable as an object, byte-identical declaration
verified at it, but **not an ancestor of master**. Rule (3) as written is therefore
unsatisfiable from master forever, through no property of any launch. Re-anchoring
the pointer to a master-reachable commit is NOT done: the pointer value fed AC4's
held-out derivation, and an amendment never re-rolls AC4 (DEV-005 / the amendment's
`ac4_anchoring`). Content binding preserves the rule's substance — the launch builds
from a tree carrying the exact frozen declaration — while removing only the
squash-merge-broken ancestry mechanics. The binding remains fail-closed on content
mismatch (`scripts/a1_freeze_consumer.py` REFUSE[DECL_ABSENT_IN_BUILD_REF] /
REFUSE[DECL_ALTERED_IN_BUILD_REF]; negative-tested).

**Who owns the call:** the coordinator (ruling R3, PR #645, dated 2026-07-10); this
entry executes it. **Receipts:**
`receipts/eval-suite-freeze/a1-freeze-admission-example-*.json` (the consumer's
admission receipt discloses `pointer_is_ancestor_of_build_ref` plus the declaration
sha256 at pointer / on disk / at build-ref), `scripts/a1_freeze_consumer.py` +
`tests/test_a1_freeze_consumer.py` (PR #645). Relates to issues #631, #593, #487.

---

## DEV-005 — eval-suite-freeze-v1 (battery-14): #193-v2 contamination convention ADOPTED AS SPEC + 147-item exclusion amendment

**Date filed:** 2026-07-09 (the A1 eval-freeze execution lane, issue #593, executing
the coordinator ruling: issue #593 comment 4930531475 — the binding text). **Filed
before any capability claim cites the suite.** **Frozen artifact:**
`docs/spec/eval-suite-freeze-v1.md`.

**What changes:** (1) the freeze doc gains a "Contamination counting convention"
section adopting the issue-#193 pre-registered v2 convention as SPEC for external
suites (item contaminated iff contiguous matched run >= 50 tokens OR > 10% of
13-gram windows matched; per-dataset; both statistics published per item; gate =
0 contaminated items post-exclusion; raw any-match totals recorded, not gated) —
the counting convention was previously unstated for external suites. (2) The first
application excludes 147 items from suite (b) (HumanEval+ 58, MMLU-Pro 69, MBPP 12,
HellaSwag 8) via a dated amendment receipt chained by sha256 to the freeze
declaration (`receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-*.json`);
the declaration is NEVER retro-edited — frozen suite = declaration + amendment.
AC4's held-out selection stays anchored to the v1 declaration hash (no re-roll,
ruling point 3).

**Who owns the call:** the coordinator (ruling comment, dated); this entry and the
spec text execute it verbatim. **Receipts:** the amendment receipt above; scan
receipt `receipts/a1-predicate-scan/a1-predicate-scan-20260709T231932Z.json` +
per-item JSONL. Relates to issues #593, #193, #440, #591.

---

## DEV-004 — eval-suite-freeze-v1 (battery-14): GPQA-diamond EXCLUDED from v1

**Date filed:** 2026-07-09 (the A1 eval-freeze execution lane, issue #593). **Filed
before any capability claim cites the suite** (no eval-reference leg has run; the A1
declaration receipt lands in the same PR as this entry). **Frozen artifact:**
`docs/spec/eval-suite-freeze-v1.md` (Status: Frozen, effective 2026-07-08); this entry
uses that doc's own amendment mechanism ("Amendments to this frozen specification
require entries in `docs/domains/governance/ledgers/deviations.md` under the battery-14 section").

**What changes:** GPQA-diamond's status moves from PIN-PENDING ("queued for when the
operator is next active") to **EXCLUDED from suite v1**. Suite (b) of the A1 freeze
declaration is the SEVEN successfully pinned datasets (MMLU-Pro, GSM8K, MATH-500,
ARC-Challenge, HumanEval+, MBPP, HellaSwag) — exactly the rows the freeze doc's own
pinning-status table marks "Pinned", with their recorded test-split sha256 values
unchanged.

**Why:** a frozen suite cannot carry an open-ended pending member — every downstream
admissibility check ("is this receipt's suite exactly the frozen one?") needs a closed
set. GPQA-diamond's pin is blocked on a HuggingFace license-consent gate that the
automated pin process correctly refuses to accept on the operator's behalf; waiting
converts a license gate into an indefinite freeze-blocker for every governed C8 arm
(execution queue rows 3, 5, 6, 8, 9 gate on A1 — refs #591). Per the A1 issue's own
rule: **a dataset pinned later joins a future suite VERSION; it is never appended to a
frozen one.** GPQA-diamond, once its consent gate clears, is a suite-v2 candidate.

**Who owns the call:** the exclusion rule is stated verbatim in the #593 dispatch
(coordinator-authored, frozen spec); this entry executes it. Re-inclusion (as part of
a versioned v2) is a coordinator/operator call when the license consent is granted in
an operator session.

**Receipts:** `receipts/eval-suite-freeze/a1-freeze-declaration-*.json` (this PR;
suite (b) = seven datasets, GPQA-diamond absent with this entry cited),
`receipts/eval-suite-freeze/eval-suite-freeze-v1.json` (the original pin receipt whose
GPQA row carries the PIN-PENDING blocker text, unchanged). Relates to issues #593,
#487, #591.

---

## DEV-003 — p1-envelope-sweep-prereg-v1: point-numbering clarification, E0 operational formula, warmup-rule implementation

**Date filed:** 2026-07-08 (the lead, ruling on findings from the P1 envelope-sweep runner
build, issue #118). **Filed pre-run** (no live gate-probe run has executed clean against
this prereg; the point-3 attempt failed on unrelated environmental blockers -- see PR #434
-- before reaching the schedule/numbering surfaces this deviation touches). **Frozen
artifact:** `docs/spec/p1-envelope-sweep-prereg-v1.md` (FROZEN 2026-07-05).

**What changes:** three clerical/operational clarifications to section 2's frozen run
protocol and section 1/4's point inventory. No threshold is relaxed; no run's acceptance
bar changes.

### 1. H-MLI point-numbering clarification

Section 4 states "points 4 (1.0x) and 6 (1.0x replicate) ARE the two control replicates"
for the H-MLI lever-arm design. This is arithmetically impossible against section 1's own
inventory table, which lists only six sweep values in order for points 3-8 (0.1x, 0.2x,
0.5x, 1.0x(replicate), 2.0x, 4.0x) -- one 1.0x entry, not two. Section 4's indices are
RULED clerical errors. The authoritative point-value mapping is the section 1 table read
positionally: point3=0.1x, point4=0.2x, point5=0.5x, point6=1.0x(replicate), point7=2.0x,
point8=4.0x. The H-MLI null-control trio (section 4) is: row 1's W1 control (1.0x, already
banked), the sweep's own point 6 (1.0x replicate, fresh seed), and one additional
lever-arm run at 1.0x WITH L1 enabled. "Points 4 and 6" as written in section 4 is void as
numbering; "points 4-8" elsewhere in the doc still means the sweep's six from-scratch runs.

### 2. E0-to-token-budget operational formula

Section 5 states E0 = 0.067478 gpu-h ("derived retrofit, banked") with no operational
formula for converting a multiplier x E0 into a token/step budget for a NEW from-scratch
run -- and no receipt anywhere in the repo carries that field literally. The BINDING
operational reading (ruled): `REFERENCE_THROUGHPUT_TOK_S` = the only real measured
throughput on record for the exact matched recipe (muon-split + AdamW + MTP aux, governor
pacing 0.80) on the pinned RTX4090 -- the banked W1 control-arm's own real run,
`receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json`
(`control_arm.tokens_to_match=819200` tokens / `control_arm.wall_s=126.484s` = 6476.24
tok/s). `tokens(point) = multiplier * E0_GPU_HOURS * 3600 * REFERENCE_THROUGHPUT_TOK_S`;
`steps = round(tokens / (batch*seq))`. Sanity: point 3 (0.1x) lands at ~24.3s of intended
GPU time, matching the P1 sweep-runner build spec's own stated "~24s GPU" almost exactly --
the strongest evidence this is the reading the program intended.

### 3. Warmup rule -- now implementable

Section 2's "warmup = min(2% of budget, the c03 recipe's absolute warmup)" referenced an
"absolute warmup" constant that does not exist anywhere in the repo (grepped for
`warmup_steps`, zero hits outside worktrees/fixtures). RULED: implement the rule properly
rather than disclose-and-diverge. `src/ember/governance/scripts/w1_collapse_control_run.py`'s
`cosine_warmup_frac` / `apply_cosine_warmup` / `run_phase2_live` now accept an OPTIONAL
`warmup_steps` override (default `None`, byte-identical prior behavior for every
pre-existing caller -- additive reuse, unit-tested regression, never a fork). The absolute
cap is 153 steps (10% of the banked W1 control's own 1533-step ceiling -- the only concrete
number on record for "the c03 recipe's" warmup allocation). `p1_envelope_sweep.py` computes
`intended_warmup = min(round(0.02*budget_steps), 153)` and passes it as `warmup_steps`, so
the prereg-intended figure and the actually-applied one are identical by construction, both
quoted in the point receipt (`lr_schedule.prereg_intended_warmup_steps` /
`lr_schedule.effective_warmup_steps`).

**Who owns the call:** all three rulings are the lead's, given verbatim in response to the
P1 envelope-sweep runner build lane's disclosed findings (PR #434); the runner's disclosure
text and this deviation note describe the SAME three items from the two sides (finding vs
ruling).

**Receipts:** PR #434 (`feat/p1-envelope-sweep-runner`, `src/ember/governance/scripts/p1_envelope_sweep.py` +
`scripts/test_p1_envelope_sweep.py` + this warmup-override commit); no run receipt yet --
point 3's gate probe has not completed clean (two unrelated environmental blockers,
reported in the same PR: a 13GiB contiguous-allocation failure in the reused corpus loader,
and a missing sha-pinned decontam receipt the banked W1 control run cites). Relates to
issue #118.

---

## DEV-002 — rung2-grow-spec-v1 production stabilization: VRAM-resident-AdamW config infeasible on L1

**Date filed:** 2026-07-08 (the lead). **Filed pre-run** (no full-param production training
run has executed under this config; only the #402 dry-run estimate has run, receipted).
**Frozen artifact:** `docs/domains/governance/spec/rung2-grow-spec-v1.md` (FROZEN, decision gated 2026-07-04, #76 /
#113).

**What changes:** the production stabilization memory strategy. The frozen spec's config —
batch=16, seq=1024, full-param 2.2B, VRAM-resident AdamW — is replaced by a host-RAM-offloaded
optimizer-state strategy (candidate 3/4 below). Training semantics are UNCHANGED: same tokens,
same effective batch, same optimizer math. The deviation is a memory-strategy substitution,
not a change to the stabilization run itself.

### Deviation

docs/domains/governance/spec/rung2-grow-spec-v1.md specifies production stabilization at batch=16, seq=1024,
full-param 2.2B, VRAM-resident AdamW. The #402 honest dry-run receipts this config at an
estimated **30.903 GiB required vs 23.988 GiB total** on the L1 card — infeasible outright,
independent of co-residency. FLOPs are NOT the wall (6.571e15 vs 2.431e16 ceiling, 0.5%).

### Why (the gap) — what the wall teaches

The spec smuggled a strategy-class assumption: "production config" was written as if
VRAM-resident-everything is the only shape. The bill decomposes (first-principles, rank-2):
weights 2N (bf16 ~4.4GiB) + grads 2N (~4.4GiB) + AdamW states 8N (~17.6GiB) + activations
(batch-dependent) + fragmentation. The 8N optimizer term dominates — the wall binds the
VRAM-resident-AdamW strategy class only, not the training semantics.

### Candidate cures priced against the receipt (MEASURE slots REGISTERED-PENDING)

1. **Gradient checkpointing** — trades activation memory for ~30–35% step-time. Does NOT
   touch the 8N term. Insufficient ALONE (saves only the activation slice); composable term.
   MEASURE: activation slice at batch=16/seq=1024 — REGISTERED-PENDING (cure PR).
2. **Batch reduction + grad accumulation** (e.g. micro-batch 2 × accum 8 = identical effective
   16) — shrinks activations ~8×; does NOT touch 8N. Composable, near-free in wall-clock at
   CPU-bound micro-batches. MEASURE: per-micro-batch activation footprint —
   REGISTERED-PENDING.
3. **CPU-offloaded optimizer states** (8N in host RAM, step on CPU or paged) — removes the
   dominant term from VRAM entirely: leaves ~2N+2N+activations ≈ 9–10GiB + margin — FITS even
   with margin floor 2GiB, possibly alongside a paused-server window only. Cost: step-time
   impact bounded by PCIe/host-RAM bandwidth; the box has 64GiB host RAM and the scan lane
   proved ~34GiB free is routine. Primary candidate.
4. **Combination 2+3** — micro-batch accumulation + host-RAM optimizer: the fit case with the
   largest margin; baseline recommendation pending MEASURE receipts — REGISTERED-PENDING.

The cure PR fills the REGISTERED-PENDING measurements under the kill/promote criteria below
(measuring activation footprints now would contend with the resident serving model for no
decision value — the 8N-term arithmetic already picks candidate 3/4).

### Residency ruling (acceptance #2 of #411)

Declared: the serving model (llama-server, ~18.3GiB resident) does NOT coexist with ANY
full-param training config on 24GiB — every cure above assumes a **serving-pause window**
(cockpit renders model-offline honestly; operator-visible line announces the window). The
alternative (residency budget carved out of VRAM) is arithmetic-infeasible for 2.2B full-param
under any candidate. This is a **dated acting-operator ruling**; reversible if a future config
change alters the arithmetic.

### Preflight change (acceptance #3)

The dry-run harness preflight asserts the CHOSEN config's estimate against nvidia-smi free
VRAM (authoritative under WDDM; torch.cuda.mem_get_info diverged twice, receipted) with the
2GiB margin floor, refusing to launch otherwise. No fix-forward on a failed assert.

**Named successor (→ cure PR):** fills the REGISTERED-PENDING MEASURE slots (1, 2, 4) and
executes the measured dry-run under the kill/promote criteria below.

**Who owns the call:** the wall diagnosis, candidate ranking, and residency ruling are the
lead's (drafted + adopted here, per the deviation mechanism). The cure PR's chosen config and
measured verdict are gated against the criteria below before promotion.

### Kill/promote criteria for the cure PR

Promote: a measured dry-run pass (same clause-d harness) showing the chosen config's REAL
peak (torch profiler or nvidia-smi sampling) fitting total-VRAM minus margin, with
function-preservation PASS unchanged. Kill: measured peak exceeds estimate by >15% (the
estimator is then the defect; fix estimator before config).

**Revision criterion:** if a future config change alters the 8N-term arithmetic (e.g. an
optimizer swap or parameter-count change), this ruling is revisited — not treated as
permanent.

**Receipts:** `receipts/grow-operator-dryrun-20260708T060841Z.json`,
`receipts/grow-op-verify-20260708T060841Z.json` (merged to public/master via PR #402, commit
e4a3e05). Relates to issues #411, #406.

---

## DEV-001 — fp-33 surpass contract: add A4 (multimodal paired bar)

**Date filed:** 2026-06-14 (the lead). **Filed pre-run** (no surpass run has executed;
the multimodal v0 is pre-launch). **Frozen artifact:** `docs/domains/governance/archive/pre-restart/fp33-surpass-prereg-v1.md`
(FROZEN 2026-06-12).

**What changes:** add a binding **A4 — multimodal paired bar** to Leg A, and
update the verdict to `SURPASS = A1 ∧ A2 ∧ A3 ∧ A4 ∧ B1 ∧ B2 ∧ B3 ∧ B4`.

**Why (the gap):** the v1 contract was frozen 2026-06-12, BEFORE the maintainer's 2026-06-14
reactivation set the active goal to a **multimodal-unified** v0. Every v1 bar
(A1 floor-world, A2 accumulation-loop, A3 MBPP/GSM8K, B1–B4 founder-likeness) tests
**text/code/duty only**. The opponent — Gemma E2B — is **multimodal-capable**.
So as frozen, "surpass E2B" is claimable while neither side's multimodal capability
is ever tested: a multimodal v0 could win the contest on text bars alone against a
multimodal opponent. That is an incomplete-measurement honesty hole, not a real
surpass. The goal centers the modality the contract does not test.

This is a TIGHTENING (surpass becomes harder, one more binding bar), not a scope
reduction — it aligns the success criterion with the goal the maintainer already set.

**A4 spec (drafted, same rigor as A1–A3):**
- **Paired, seat-swapped:** ember-multimodal vs E2B-multimodal, both seated in
  ember's own harness/worlds, same harness commit, prompt-template adaptation only
  (template in receipt). Identical to the common protocol's seat-swap rule.
- **Task distribution:** a **held-out image-text** split — the B-MULTI-1 corpus's
  frozen heldout bucket (image-text pairs in the 48×48 patch format), split by
  index BEFORE any training use (same split discipline as world-choice K3). Public
  VL slices admitted only if they clear the local-rights bar (the LiveCodeBench
  no-LICENSE rejection precedent applies — no license at repo root → not admitted
  without sign-off).
- **Metric:** per-task correctness on the VL task (exact-match / graded per the
  task's own ground truth, never a model judge). **Statistics:** the common block —
  paired bootstrap, 10,000 resamples, 95% CI on per-task delta (ember − E2B). Bar:
  **CI excludes 0 in ember's favor** (same as A1). E2B failing the VL floor while
  ember clears it also satisfies A4 (mirrors A2's asymmetry clause).
- **Matched compute** + governor/headroom rails, identical to every other bar.

**Named successor (eng, → the engineer):** the A4 VL eval harness leg + the B-MULTI-1
heldout-split manifest (rides the engineer's B-MULTI corpus build #27; the eval harness is
its A4 counterpart, analogous to the GSM8K-200 harness minted for A3-ii).

**Who owns the call:** the A4 *spec* is the lead's (drafted + adopted into the contract
here, per the deviation mechanism — not bounced). The surpass *verdict definition*
(whether SURPASS formally includes A4) is **goal-level = the maintainer's** — adopted by
default on this honesty argument; the maintainer confirms or scopes-out A4 on return. Until he
moves it, A4 is in the contract.

**Revision criterion:** if the maintainer rules that v0's multimodal capability is proven
separately by the verify-floor (the pilot's own kill-criteria forgetting-watch +
floor-probe) and the surpass *contest* stays text/code/duty, A4 is retired from the
verdict and recorded as proven-elsewhere — not silently dropped.

Per user direction.

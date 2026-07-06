# Ember Genesis Audit — Report

Auditor: genesisaudit (read-only). Scope: every live training lineage under
`models/` in the repository working tree, graded against clause 3 (CREATION) of
the INVARIANT.md candidate text (v2 draft). Repo state audited: `public/master`
(HEAD `15e467e9279222a4da5bc21925289ffe7d5150cb`, fetched from
`https://github.com/wordingone/ember.git` 2026-07-06) for tracked
scripts/docs/receipts, plus the on-disk `models/` and `receipts/` trees (which
are `.gitignore`d for the weight files, `.gitignore:19` = `models/`) as they
exist locally. No files were mutated; all reads were via `git show
public/master:<path>` or direct `Read`/`Grep`/`Bash` read-only calls.

**Headline finding: no checkpoint currently in the repo qualifies to start the
protected lineage.** Every from-scratch pretrain checkpoint (the entire "cbase"
/ c03 family, including `cbase-grow-rung` step-00000730/step-00000766) is
trained on a corpus whose largest prose component (FineWeb-Edu, ~29% of corpus
bytes) was curated by a classifier trained on Llama-3-70B-Instruct annotations
— a documented external-model contribution to the training data's
inclusion/exclusion decision, which clause 3 enumerates by name as a protected
path element. This is not an "unknown provenance" gap; it is an affirmatively
known external-model contribution, disclosed in ember's own design docs.

---

## 1. Per-lineage table

| Lineage | Data provenance | Tokenizer | Prompts/synthetic-data | Other path elements | VERDICT |
|---|---|---|---|---|---|
| **cbase / c03 / c04 timeshare family** — `models/cbase-smoke-run/*`, `models/cbase-grow-dryrun/*`, `models/cbase-grow-live/*`, `models/cbase-grow-rung/rung1-20260703T155447Z/{checkpoints/step-00000730, stabilize/checkpoints/step-00000766}`, `models/ceff-confirm-bf16ns5-*`, `models/conv-*-seed42` | **TAINTED.** All draw on the single pinned v0 corpus, `receipts/eng36-assembly-20260611T052337Z.json` (sha256 `a29d2e567f1853966cc72a4890eadc963164265e4f24a89cadea24d9ff5b80c2`, pinned verbatim in `config/v0-pretrain-config.json:68` and in `scripts/tokenizer_freeze.py:75-76`). Source 2 of 5 in that receipt is `HuggingFaceFW/fineweb-edu` (`receipts/eng36-fineweb_edu-20260611T044544Z.json`, 1,549,860 docs / 7.4GB, ~29% of the 25.3GB corpus). Ember's own frozen design doc `docs/research/fp22-corpus-world.md:27` tags this row **"EXTERNAL-CITED"** and cites the mechanism directly in `docs/technique-registry.jsonl:11` ("edge-grade filtering... source: FineWeb-Edu; SmolLM2 2502.02737"). Public record (FineWeb paper 2406.17557 + `HuggingFaceFW/fineweb-edu-classifier` card, verified via web search) confirms the filter is a linear-regression classifier trained on 410k annotations from **Llama-3-70B-Instruct**, retaining only docs scoring ≥3/5 educational value. That is an inclusion/exclusion decision over training data made by a chain rooted in an external model — enumerated verbatim in clause 3. Other 4 sources (`wikipedia_en`, `gutenberg_en`, `code_github_clean`, `ledger_mit`) show no comparable ML-classifier filtering in their receipts (Wikipedia/Gutenberg = deterministic extraction of human text; code_github_clean = deterministic per-file license-field filter, `receipts/eng36-code_github_clean-20260611T051128Z.json:16`; ledger_mit = ember's own MIT-clean slice, tagged RECEIPTED). | **CLEAN** on the ember-side question, but moot given the corpus verdict (see §2). | Deterministic, receipted, clean in isolation: exact-hash contamination decontam (`scripts/w2_heldout/build_decontam_batch_mp.py`, deterministic rolling-hash exclusion), net2net FF-widening growth surgery (`scripts/cbase_grow_rung.py`, function-preservation checked mechanically, spec pre-registered — the clause-3 "deterministic tool" exception applies cleanly here), WSD schedule, Muon optimizer (self-contained, no external dep) — all deterministic, all pre-registered. Stopping/floor-bar decisions (`docs/research/fp22-corpus-world.md` §3) use EXACT L1/L2/MBPP verification, never an LLM judge. Model architecture is a `transformers.LlamaConfig`/`LlamaModel` wrapper **randomly initialized** (`scripts/timeshare_pretrain.py:523-531,1108-1123` — no `.from_pretrained()` call found anywhere in the runner); architecture-as-published-idea is permitted under clause 3's "published ideas are not artifacts" line. | **TAINTED** — clause 3: *"free of contribution originating in any external model... through any chain of intermediaries"* is violated by the FineWeb-Edu inclusion decision. |
| **cbase-sft-toolagent, v1–v6** — `models/cbase-sft-toolagent{,-v2,-v3-turnwise,-v4-copy-contract,-v5-compositional-copy,-v6-observation-copy}/model.pt` | Base weights = a `cbase-smoke-run` checkpoint (step ~610/650, "near-untrained", per `scratch/seed-export-v5/dryrun-20260704T211712Z/.../receipts/owned-engine-sft-tool-loop-2026-06-30.json`) — inherits the cbase taint above. SFT itself trains 700–900 steps on "2000 held-out tool-use traces" per-run (same receipt, `training_run.synthetic_trace_count`). **No manifest.json, no receipt, and no generator script for these traces exists anywhere in the tracked repo or on disk** — repo-wide grep for `toolagent`, `copy-contract`, `compositional-copy`, `observation-copy`, `turnwise` returns zero hits outside the 3 scratch receipts found, and none of those name the actual trace-generation script (redacted as `<owned-engine-sft-runner>`). | N/A (SFT stage; inherits base tokenizer) | **UNKNOWN.** Whether the "synthetic traces" were templated/procedural (clean) or LLM-generated (tainted) cannot be determined — the generator is absent from the repo. Per clause 3: *"Unknown provenance is not violation; it is exclusion, fail-closed."* | Same base-checkpoint inheritance as row 1. | **EXCLUDED (fail-closed, unknown)** on the SFT data; **TAINTED** via inherited base weights regardless. |
| **Adaptation-loop / "borrowed-core" episodes** — `receipts/ledger/episodes.jsonl` (qwen-research-class rows, `receipts/fp6-provenance-20260610T235623Z.json`) | Episodes sampled from `Qwen2.5-Coder-3B-Instruct` (a third-party pretrained model) under a fine-tuned adapter on a borrowed core, not a from-scratch checkpoint. `fp6-provenance` itself: 956 "qwen-research" episodes with "sampler-stamp" basis. Ember's own `docs/research/fp22-corpus-world.md:32-34` already **excludes** qwen-research-class rows from the v0 pretraining corpus for licensing reasons. | N/A — uses the borrowed model's own tokenizer, not ember's. | N/A | The base weights themselves are an external model (Qwen) with an adapter; this is definitionally outside clause 3's "creation" scope regardless of episode provenance — clause 4 covers it explicitly ("what fails clause 3 may exist and may run in ember's body; it is not ember's creation"). | **OUT OF SCOPE for clause-3 CREATION claims** — already correctly excluded by ember's own team; not a candidate lineage. No board GREEN condition should ever attribute this track's capability to "ember's creation." |
| **"Dynamic teacher system" design** — `docs/research/teacher-system-2026-06-10.md` | Not executed. Repo-wide search for `sampler_id`, `teacher_pool`, `admit_teacher`, `TEACHER-ADMIT` returns zero receipts. | N/A | Proposed design would inject teacher-model-generated episode **text** into the training-signal path, gated only by a deterministic world-verifier before "burning" episodes into the ledger. | The doc's own framing treats deterministic verification as sufficient to keep the loop clean ("teachers propose, the world disposes... never a model"), and argues from GOAL.md's older "nothing load-bearing is borrowed" language, not from the INVARIANT (the note predates INVARIANT-draft-v2 by ~26 days). | **NOT YET EXECUTED — flagged as a standing risk, not a current violation.** If implemented as designed, it would fail clause 3: gate-verification decides *inclusion*, but the episode text's *origin* remains an external model, and clause 3 protects origin, not just post-hoc verification. This must be re-ruled against the entrenched invariant, not the older GOAL.md framing, before any execution. |
| **c04-design-bench-*** — `models/c04-design-bench-out/` (train.log + train_config.json only, no weights) | N/A — this is a compile/throughput benchmark harness (`receipts/c04-design-bench-*.json`), run on random/synthetic token ids to measure step time and compile behavior across candidate shapes (h2048-d12, h2304-d12, etc.). No persisted checkpoint weights. | N/A | N/A | N/A | **NOT A LINEAGE** — no persisted weights; excluded from lineage scope on that basis alone. |

## 2. The named checkpoint

**NO CURRENT CHECKPOINT QUALIFIES** to begin the protected lineage under the
strictest defensible reading of clause 3.

The disqualifying fact is structural, not incidental: every from-scratch
pretrain checkpoint in the repo — smoke runs, growth-chain rungs (including
the two named in the mission, `step-00000730` and `step-00000766`), the
`ceff-confirm` and `conv-*` optimizer-comparison seeds — draws on the *same*
single pinned corpus assembly (`eng36-assembly-20260611T052337Z.json`,
sha256 `a29d2e5...`), because `config/v0-pretrain-config.json` and
`scripts/tokenizer_freeze.py` both hard-pin that one sha as the only valid
corpus input, and every checkpoint-producing script (`timeshare_pretrain.py`,
`cbase_grow_rung.py`, `cbase_grow_live.py`, `cbase_grow_dryrun.py`) reads
through that same contract. There is no checkpoint anywhere on disk trained on
a corpus that excludes FineWeb-Edu. The one corpus source that IS fully
ember-receipted and external-model-free — `ledger_mit` — is 780 documents /
521KB, roughly 0.002% of the pinned corpus's byte budget: nowhere near
sufficient to have produced any existing checkpoint on its own, and no
checkpoint trained on it in isolation exists.

**What must exist first, for a future checkpoint to qualify:**

1. A v0 corpus assembly that either (a) drops FineWeb-Edu entirely and
   replaces its share with a source whose inclusion criterion is deterministic
   and non-ML (e.g., a fixed heuristic quality filter, or a larger own-ledger /
   public-domain / permissively-licensed-only mix), or (b) re-derives an
   "edu-quality" filter using a classifier trained end-to-end inside ember's
   own receipted chain (no Llama-3, no other external annotator anywhere in
   its training history) — a nontrivial rebuild, not a relabeling.
2. A fresh `tokenizer_freeze.py` run against that new assembly receipt (the
   *mechanism* is already clean — ByteLevel BPE trained via the HF
   `tokenizers` library's deterministic trainer on a stratified sample of
   ember's own corpus, `scripts/tokenizer_freeze.py:226-237` — it only needs
   to be re-run against a clean corpus pin).
3. A fresh pretrain launch through the existing `timeshare_pretrain.py` /
   `v0_pretrain_launch_gate.py` harness against that new tokenizer + corpus,
   producing a step-0 checkpoint that becomes the actual genesis candidate.
4. For the SFT-toolagent family specifically: either locate/reconstruct the
   actual trace-generation script and receipt it (resolving UNKNOWN to
   RECEIPTED-clean or TAINTED), or treat that entire sub-lineage as starting
   fresh after step 1-3 land.

This is a legitimate outcome, not a hedge: clause 3's own text anticipates it
("Unknown provenance is not violation; it is exclusion, fail-closed") and
clause 7 explicitly separates "history" from "lineage" for exactly this case
("earlier artifacts are history, not lineage, and no completion claim may
rest on them").

## 3. Fuse list — every finding that must land in the incidents ledger at genesis

1. **FineWeb-Edu external-model taint (primary fuse).** The entire cbase/c03
   pretrain corpus includes a source whose document-inclusion decision was
   made by a classifier trained on Llama-3-70B-Instruct annotations. Receipts:
   `receipts/eng36-assembly-20260611T052337Z.json`,
   `receipts/eng36-fineweb_edu-20260611T044544Z.json`,
   `docs/research/fp22-corpus-world.md:27`, `docs/technique-registry.jsonl:11`.
   External corroboration: FineWeb paper arXiv:2406.17557 and
   `huggingface.co/HuggingFaceFW/fineweb-edu-classifier` (web-verified
   2026-07-06). This affects every existing from-scratch checkpoint without
   exception.
2. **SFT-toolagent lineage has no receipted generator.** `models/cbase-sft-toolagent{,-v2..v6}/model.pt` exist on disk with zero manifest, zero
   production receipt, and zero generator script anywhere in the tracked repo
   or working tree. Only 3 heavily-redacted scratch receipts
   (`scratch/seed-export-v5/dryrun-20260704T211712Z/stage/ember_main/baseline/receipts/owned-engine-sft-{tool-loop,v2-tool-loop,v3-turnwise-tool-loop}-2026-06-30.json`)
   confirm the training EVENT happened (real loss curves, real step counts)
   without disclosing the trace-generation mechanism.
3. **Frozen-design-doc deviation, disclosed but worth carrying forward.**
   `fp22-corpus-world.md` row 1 specified `the-stack-v2` as the code source;
   the actual pinned assembly used `codeparrot/github-code-clean` instead
   (`receipts/eng36-code_github_clean-20260611T051128Z.json`, field
   `"deviation"`). This substitution was disclosed and acked (mail 14530) at
   the time — it is not itself a clause-3 violation (the applied filter is a
   deterministic per-file license check) — but it establishes that the
   pinned corpus already diverged once from its frozen design under
   time pressure, which is the same shape of risk as the FineWeb-Edu gap.
4. **The C-BASE board-GREEN status does not audit clause-3 data provenance.**
   `scripts/ember_totality/receipts-totality/ember-totality-20260624T142553Z.json`
   marks condition `C-BASE` GREEN on the basis of "owned from-scratch
   checkpoint... no borrowed/frozen base" plus a receipted net2net
   growth-rule check — i.e., it verifies the *weights* were not copied from a
   pretrained model, and says nothing about the *corpus* the from-scratch
   weights were trained on. A steward reading "C-BASE: GREEN" without this
   audit would reasonably but incorrectly infer clause-3 cleanliness.
5. **"Dynamic teacher system" design note is a live risk for future work,**
   not yet executed but written by the same team that will build the next
   pretrain generation (`docs/research/teacher-system-2026-06-10.md`). It
   pre-dates the invariant draft and reasons from GOAL.md's older framing.
   Flagging here so a steward rules on it before, not after, any
   `sampler_id`/`admit_teacher` receipt appears.

## 4. Open questions for a human steward

1. **Does "affirmatively shown to be free of" require zero external-model
   contribution to a *classifier used for filtering*, or only to the
   *literal token content* of retained documents?** This audit reads clause
   3's "inclusion, exclusion, weighting" language as covering the filtering
   decision itself (the stricter reading, which the invariant's own preamble
   commands when ambiguous), not merely the surviving text's authorship. A
   steward could in principle argue the surviving FineWeb-Edu documents are
   themselves human-authored web text, and only the *selection* touched an
   external model — but clause 3 lists "inclusion, exclusion, weighting" as
   protected path elements in their own right, independent of and alongside
   "training data," which reads as deliberately closing exactly this gap.
2. **Is a full corpus rebuild (dropping or re-deriving FineWeb-Edu) the
   intended remedy, or would the steward prefer a declared-fork /
   public-succession path (clause 7's "Public succession... is always
   available") that starts a new genesis explicitly acknowledging the prior
   work as history?** Both are compliant; they have very different cost and
   timeline implications the steward should weigh, not this audit.
3. **What should happen to the SFT-toolagent checkpoints and the underlying
   `<owned-engine-sft-runner>` script** — should the missing generator be
   located (it may exist in a private/untracked location outside this repo
   clone) and receipted retroactively, or should this entire sub-lineage be
   treated as disposable scaffolding per clause 4 ("may exist and may run in
   ember's body; it is not ember's creation")?
4. **Should the qwen-adapter "borrowed-core" track be given an explicit
   board condition of its own** (distinct from C-BASE) so its GREEN/RED
   status can never be conflated with a from-scratch clause-3 claim, given it
   is definitionally excluded from "ember's creation" by clause 4?
5. **Does the disclosed the-stack-v2 → codeparrot substitution (fuse #3)
   need its own incidents-ledger row at genesis**, given it was disclosed and
   acked at the time but represents the same class of risk (frozen-design
   deviation under schedule pressure) as the fuse that was NOT caught in
   time (FineWeb-Edu)?

---

## Amendment: v2 → v3 Draft Delta (2026-07-06)

This audit was conducted against the INVARIANT.md v2 candidate text. Between v2 and v3, only one substantive change was applied: clause 7's lineage-start sentence was refined to clarify the genesis-audit-names-none path (see issue #281 comment). That clause 7 amendment does not alter the verdicts in this report with respect to clause 3 (CREATION). All five findings (FineWeb-Edu taint, SFT-generator-missing, design-deviation, C-BASE-gap, teacher-system-risk) are pre-registered and stand unchanged under v3.

---

*Every claim above cites a file path and, where applicable, a sha256 or exact
line range from the ember repo as read on 2026-07-06, or an external source
verified by web search on the same date (FineWeb-Edu classifier mechanism).
No claim in this report rests on the auditor's unverified prior knowledge
alone where a repo receipt was available to check it.*

# Stage1 First Words Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the zero-assistant-active Stage-1 first-words lane: curate existing B-MULTI-1 assets into local noun manifests, freeze heldout, and make the multimodal launch gate accept local image-path manifests.

**Architecture:** Keep code/spec edits in `<local-path>`; keep `<local-path>` as the execution/data tree. The curation script copies selected images into a compact stage-1 corpus with single-word captions and receipt JSON, while `v0_pretrain_launch_gate.py` validates either URL-backed or local-image matched pairs.

**Tech Stack:** Python standard library, existing Ember scripts, existing tokenizer file, PowerShell verification commands.

---

### Task 1: Stage-1 Curation Tool

**Files:**
- Create: `scripts/stage1_first_words.py`

- [ ] **Step 1: Add deterministic curation script**

Create a script that reads `B-MULTI-1/raw/manifest.jsonl`, matches a fixed 20-noun stage-1 list, copies selected image files into `stage-1-first-words/train/raw` and `stage-1-first-words/holdout/raw`, writes single-word `.txt` captions, and writes manifest plus receipt files.

- [ ] **Step 2: Run script selftest**

Run: `python scripts/stage1_first_words.py --selftest`

Expected: `STAGE1_FIRST_WORDS_SELFTEST_PASS`.

- [ ] **Step 3: Curate from live execution data**

Run from the clean worktree, targeting `<local-path>` data:

```powershell
python <local-path> --source-manifest <local-path> --out-root <local-path> --receipt-dir <local-path>
```

Expected: receipt reports 20 nouns, at least 20 train pairs, exactly 20 heldout pairs, and `manual_review_required=true`.

### Task 2: Local Manifest Launch Gate

**Files:**
- Modify: `src/ember/governance/scripts/v0_pretrain_launch_gate.py`

- [ ] **Step 1: Accept local `image_path` matched-pair manifests**

Change `g_shards_mm()` so item 4 accepts records with either `url` or `image_path`, plus `caption`.

- [ ] **Step 2: Accept local holdout manifests**

Change the holdout check so records may carry `url` or `image_path`, plus `sha256` and `caption`.

- [ ] **Step 3: Run gate selftest**

Run: `python src/ember/governance/scripts/v0_pretrain_launch_gate.py --selftest`

Expected: `V0_LAUNCH_GATE_SELFTEST_PASS`.

### Task 3: Stage-1 Encoding and Rung-0 Validation

**Files:**
- Existing: `scripts/corpus_patch_encode.py`
- Existing: `scripts/train_multimodal_v0.py`

- [ ] **Step 1: Encode the curated training raw dir**

Run:

```powershell
python <local-path> --raw-dir <local-path> --encoded-dir <local-path>
```

Expected: encoded count equals the train manifest count.

- [ ] **Step 2: Run CPU selftests**

Run:

```powershell
python <local-path> --selftest
python <local-path> --selftest
```

Expected: both pass.

- [ ] **Step 3: Gate-check Stage-1 manifest without live training**

Run:

```powershell
python <local-path> --emit
```

Expected: no local-manifest format error. Any remaining block is recorded explicitly and must not be hand-waved.

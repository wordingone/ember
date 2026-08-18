# External Eval Suite Freeze v1

**Status**: Frozen | **Issue**: #487 | **Battery gap**: 14 | **Effective date**: 2026-07-08

## Selection Criteria

The external eval suite is selected under these constraints:
- **External**: test splits originate from public sources, not internal data
- **Revision-pinned**: each dataset frozen by commit/revision SHA for reproducibility
- **Locally runnable**: executable on one-GPU budget within hours
- **Zero-cost**: no paid APIs in any scoring path (L5 classification)
- **Contamination-auditable**: each test split hashed deterministically; predicate #440 (corpus leakage scan) must verify training data against these hashes BEFORE any capability claim cites this suite (battery Q5 interlock). Counting convention for the predicate: the adopted #193-v2 convention below ("Contamination counting convention", adopted 2026-07-09 via the #593 coordinator ruling).

## v1 Composition

**Knowledge**: MMLU-Pro  
**Reasoning**: GSM8K, MATH-500 subset  
**Science**: ARC-Challenge  
**Code**: HumanEval+, MBPP  
**Commonsense**: HellaSwag  
**Graduate-hard anchor**: GPQA-diamond  

## Harness

Standard open eval harness, pinned by commit SHA. The harness is external **code** evaluating the model — not an external model touching training tokens, so L3 is not implicated. The commit SHA freezes with the suite. Prompt templates and scoring configs freeze in the receipt; no post-hoc template tuning is permitted after freeze.

## Contamination counting convention (adopted 2026-07-09 — #193 v2 as spec)

Adopted as SPEC via the #593 coordinator ruling (issue #593, comment 4930531475,
dated 2026-07-09) after the first-ever predicate execution (PR #603); this section
supersedes the previously unstated counting convention for external suites. The
issue-#193 pre-registered v2 convention, exactly as applied by the executed scan:

- **Unit**: the ITEM (one eval row). Matching runs at **W = 13-token windows**
  over the item's tokenized text (every string leaf of the row's JSON, joined by
  newlines), encoded with the frozen tokenizer (`tokenizer/tokenizer.json`,
  sha256 `6923a52304637f48eb4cc421b58e6cdce29c1f5da860abaea5d57baa6ad6d97d`,
  added-token-matching-disabled-v1 semantics; the 21/31,755 vocab-absent-merge
  in-memory workaround is disclosed in the scan receipt).
- **An item is CONTAMINATED iff** (a) its longest contiguous matched run is
  **>= 50 tokens** (measured as the longest consecutive matched-window run
  + W-1 — the upper-bound proxy defined in the scan receipt; it cannot miss a
  true >=50-token shared substring), **OR** (b) **> 10%** of its 13-gram windows
  match training text.
- **Applied per-dataset**; both statistics are computed and PUBLISHED for every
  item (per-item JSONL beside the scan receipt), never only the verdict.
- **Gate**: suite (b) passes iff contaminated items = **0** after any ruled
  exclusion amendment. Cure for a nonzero finding = **exclusion with
  disclosure** (dated amendment receipt chained by sha256 to the freeze
  declaration; the declaration is never retro-edited; frozen suite definition =
  declaration + amendment). Raw any-13-gram match totals are recorded as
  transparency figures, not gated.
- **Suite (a)** (the corpus-drawn held-out batch) keeps its own stricter
  RESOLVED convention: strict any-match non-self at W=13 must be 0
  (w2-scale-preregistration-v1 §4).

First application (2026-07-09, PR #603): suite (b) pre-exclusion = 147
contaminated items (HumanEval+ 58/164, MMLU-Pro 69, MBPP 12, HellaSwag 8,
GSM8K/MATH-500/ARC-Challenge 0); post-exclusion = 0. Amendment receipt:
`receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-*.json`.

HellaSwag scored-split amendment (2026-08-18, DEV-007): the 8/10,003 result
above is historical evidence for the unlabelled `test` split only. The governed
#1433 scorer instead pins the labelled `validation` split at revision
`218ec52e09a7e7462a5400043bb9a69a41d06b76`, file
`data/validation-00000-of-00001.parquet`, 10,042 rows, SHA-256
`899813071e1e95efafec90f856e1987d2150fa4d020fc005df6962c259f660cd`.
That split is `PENDING_FINAL_CORPUS_CONTAMINATION_SCAN`; it is not
READY_FOR_COMPUTE until scanned against the final tokenized corpus consumed by
WARM-100. No old exclusion count transfers between splits.

## Binding Clauses

### Clause 1: Text-only, C1 insufficient
v1 covers text+code modalities only and is **explicitly insufficient for C1 parity claims**. The multimodal extension (versioned v2, operator-scoped per L8) is required before any C1 parity claim. v1 serves C5's no-dense-control-reaches-it clause and interim capability tracking.

### Clause 2: Reference scores locally reproduced
Reference scores are **locally reproduced, never paper-quoted**. The 27B-class comparison models must be run on this frozen suite on this machine. The first such run (against the currently-served 27B-class model) doubles as suite validation and lands the reference half of battery Q14; it rides the next free GPU window after re-measure.

## Freeze Receipt Schema

```json
{
  "suite_version": "v1",
  "datasets": [
    {
      "name": "dataset_name",
      "source": "huggingface",
      "canonical_url": "https://huggingface.co/datasets/...",
      "revision": "commit_sha",
      "test_split_name": "test",
      "test_split_sha256": "hex_hash",
      "row_count": 12345,
      "size_bytes": 1000000
    }
  ],
  "harness": {
    "name": "EleutherAI/lm-evaluation-harness",
    "commit": "harness_commit_sha",
    "install_recipe": "pip install lm_eval @ git+https://github.com/EleutherAI/lm-evaluation-harness.git@{commit}"
  },
  "templates_sha256": "templates_config_hash",
  "scoring_config_sha256": "scoring_config_hash",
  "total_size_bytes": 5000000,
  "storage_root": "../data/eval-suite-v1",
  "timestamp": "2026-07-08T00:00:00Z",
  "pin_notes": "Any dataset requiring account/consent to download is marked PIN-PENDING with blocker reason. Storage root path is relative to repo root."
}
```

## Pinning Status

As of 2026-07-08, the following datasets have been successfully pinned and verified:

| Dataset | Rows | Test Split Hash | Status |
|---------|------|-----------------|--------|
| MMLU-Pro | 12032 | 5fdd1b7583302292... | Pinned |
| GSM8K | 1319 | fb581f0270b25988... | Pinned |
| MATH-500 | 500 | 200806fb17234213... | Pinned |
| ARC-Challenge | 1172 | c0e7635ee91b9ca4... | Pinned |
| HumanEval+ | 164 | 4e8dbe9885c253ae... | Pinned |
| MBPP | 500 | 88d690200dbe7f37... | Pinned |
| HellaSwag | 10042 | 899813071e1e95ef... | Scored split pinned; contamination scan pending (DEV-007) |
| GPQA-diamond | — | — | PIN-PENDING (license gate) |

**PIN-PENDING Status Note**: GPQA-diamond requires operator-session authorization via HuggingFace. The automated pin process refuses to accept consent on behalf of the operator. This pin is queued for when the operator is next active.

## Amendments

Amendments to this frozen specification require entries in `docs/ledgers/deviations.md` under the battery-14 section. The deviation rule is: only deviations from this freeze are documented in that file; the document itself is immutable except via that mechanism.

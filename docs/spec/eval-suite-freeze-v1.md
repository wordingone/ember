# External Eval Suite Freeze v1

**Status**: Frozen | **Issue**: #487 | **Battery gap**: 14 | **Effective date**: 2026-07-08

## Selection Criteria

The external eval suite is selected under these constraints:
- **External**: test splits originate from public sources, not internal data
- **Revision-pinned**: each dataset frozen by commit/revision SHA for reproducibility
- **Locally runnable**: executable on one-GPU budget within hours
- **Zero-cost**: no paid APIs in any scoring path (L5 classification)
- **Contamination-auditable**: each test split hashed deterministically; predicate #440 (corpus leakage scan) must verify training data against these hashes BEFORE any capability claim cites this suite (battery Q5 interlock)

## v1 Composition

**Knowledge**: MMLU-Pro  
**Reasoning**: GSM8K, MATH-500 subset  
**Science**: ARC-Challenge  
**Code**: HumanEval+, MBPP  
**Commonsense**: HellaSwag  
**Graduate-hard anchor**: GPQA-diamond  

## Harness

Standard open eval harness, pinned by commit SHA. The harness is external **code** evaluating the model — not an external model touching training tokens, so L3 is not implicated. The commit SHA freezes with the suite. Prompt templates and scoring configs freeze in the receipt; no post-hoc template tuning is permitted after freeze.

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
| HellaSwag | 10003 | 6a78734fc71263f4... | Pinned |
| GPQA-diamond | — | — | PIN-PENDING (license gate) |

**PIN-PENDING Status Note**: GPQA-diamond requires operator-session authorization via HuggingFace. The automated pin process refuses to accept consent on behalf of the operator. This pin is queued for when the operator is next active.

## Amendments

Amendments to this frozen specification require entries in `docs/deviations.md` under the battery-14 section. The deviation rule is: only deviations from this freeze are documented in that file; the document itself is immutable except via that mechanism.

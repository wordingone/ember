# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "scripts" / "legb_live_candidate_v5_scorer.py"


def _load():
    # These tests exercise the scorer's byte-authority seam only. Keep the
    # fixture independent of a 3.84B model runtime and lm_eval installation.
    stubs = {
        "torch": types.ModuleType("torch"),
        "legb_inprocess_scorer": types.ModuleType("legb_inprocess_scorer"),
        "receipt_write": types.ModuleType("receipt_write"),
        "receipt_check": types.ModuleType("receipt_check"),
    }
    stubs["torch"].Tensor = object
    stubs["legb_inprocess_scorer"].LegBLM = object
    stubs["legb_inprocess_scorer"].load_verified_tokenizer = object
    stubs["legb_inprocess_scorer"].device_lease = object
    stubs["legb_inprocess_scorer"].TOKENIZER_EXPECTED_SHA256 = "f" * 64
    stubs["legb_inprocess_scorer"].SHA_CONVENTION = "fixture"
    stubs["receipt_write"].checked_write = object
    stubs["receipt_check"].INVARIANT_SHA256 = "e" * 64
    missing = object()
    prior = {name: sys.modules.get(name, missing) for name in stubs}
    try:
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location("legb_live_candidate_v5_scorer", SCORER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in prior.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _checkpoint(module, root: Path, *, step: int = 100, tag: bytes = b"a") -> tuple[Path, dict]:
    root.mkdir()
    records = []
    shard_sha = {}
    for index, name in enumerate((*module.MODEL_SHARDS, "optimizer-state.pt", "replay-state.pt")):
        path = root / name
        path.write_bytes(tag + bytes([index]))
        digest = _sha(path)
        shard_sha[name] = digest
        records.append({"path": name, "sha256": digest, "bytes": path.stat().st_size})
    cursor = {
        "shard": "semantic-fixture",
        "record_index": step,
        "receipt_sha256": "c" * 64,
        "tokenizer_sha256": "d" * 64,
        "shard_index": 0,
        "token_offset": step * 1024,
        "global_step": step,
        "tokens_seen": step * 1024,
        "governor": {"schema_version": "ember-runtime-governor-v1"},
    }
    manifest = {
        "schema_version": module.SUPPORTED_CHECKPOINT_SCHEMA,
        "shards": records,
        "shared_model_shard_sha256": shard_sha["shared-model.pt"],
        "optimizer_state_shard_sha256": shard_sha["optimizer-state.pt"],
        "expert_checkpoint_sha256": {
            name: shard_sha[f"expert-{name}.pt"] for name in module.EXPERTS
        },
        "model_config_sha256": _sha(ROOT / module.MODEL_CONFIG_REL),
        "data_cursor": cursor,
        "active_expert_ids": ["tool"],
        "architecture_revision": "ember-sparse-3b-v2",
        "contract_version": 5,
        "launch_seed": 830013,
    }
    _write_json(root / "checkpoint-manifest.json", manifest)
    published = {
        **manifest,
        "checkpoint_manifest_sha256": _sha(root / "checkpoint-manifest.json"),
        "checkpoint": {"byte_sha256": _sha(root / "checkpoint-manifest.json")},
    }
    return root, published


def _run_receipt(path: Path, published: dict) -> str:
    cursor = published["data_cursor"]
    segment_cursor = {
        key: value for key, value in cursor.items()
        if key not in {"governor", "resume_authority"}
    }
    step = cursor["global_step"]
    _write_json(
        path,
        {
            "post_step_checkpoint": published,
            "resume_authority": None,
            "segment": {
                "steps": step,
                "global_step": step,
                "tokens_seen": cursor["tokens_seen"],
                "data_cursor": segment_cursor,
                "losses": [1.0] * step,
            },
        },
    )
    return _sha(path)


def test_exact_warm100_receipt_reopened_and_boundary_derived(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(module, tmp_path / "warm100")
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    verified = module.load_verified_warm100_checkpoint(
        str(checkpoint), str(receipt), receipt_sha
    )

    assert verified["run_receipt_sha256"] == receipt_sha
    assert verified["global_step"] == 100
    assert verified["tokens_seen"] == 102400
    assert "global_step=100" in module.claim_boundary(verified)
    assert "tokens_seen=102400" in module.claim_boundary(verified)


@pytest.mark.parametrize("failure", ["subscale", "stale", "swap"])
def test_warm100_receipt_refuses_subscale_stale_and_swap(
    tmp_path: Path, failure: str
) -> None:
    module = _load()
    step = 99 if failure == "subscale" else 100
    checkpoint, published = _checkpoint(module, tmp_path / "subject", step=step)
    receipt_checkpoint = checkpoint
    if failure == "swap":
        receipt_checkpoint, published = _checkpoint(
            module, tmp_path / "other", tag=b"b"
        )
        assert receipt_checkpoint != checkpoint
    if failure == "stale":
        published["checkpoint_manifest_sha256"] = "0" * 64
        published["checkpoint"] = {"byte_sha256": "0" * 64}
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    expected = {
        "subscale": "WARM100_BOUNDARY_REQUIRED",
        "stale": "RUN_RECEIPT_CHECKPOINT_MISMATCH",
        "swap": "RUN_RECEIPT_CHECKPOINT_MISMATCH",
    }[failure]
    with pytest.raises(module.LiveCandidateRefusal, match=expected):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


def test_score_binding_requires_predictions_and_hashes_canonical_scores() -> None:
    module = _load()
    evaluation = {
        "raw_predictions": {
            "path": "predictions.jsonl",
            "rows": 2,
            "sha256": "a" * 64,
            "format": "jsonl; one row per scored eval item",
        },
        "results": {"arc_challenge": {"acc,none": 0.5}},
    }
    bound = module.bind_evaluation_artifacts(evaluation)
    assert bound["raw_predictions_sha256"] == "a" * 64
    assert bound["scores_sha256"] == hashlib.sha256(
        json.dumps(
            evaluation["results"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert bound["prediction_score_binding_sha256"] == hashlib.sha256(
        json.dumps(
            {
                "raw_predictions_sha256": bound["raw_predictions_sha256"],
                "scores_sha256": bound["scores_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    evaluation["raw_predictions"] = None
    with pytest.raises(module.LiveCandidateRefusal, match="RAW_PREDICTIONS_REQUIRED"):
        module.bind_evaluation_artifacts(evaluation)


def test_score_binding_refuses_missing_scores() -> None:
    module = _load()
    with pytest.raises(module.LiveCandidateRefusal, match="SCORES_REQUIRED"):
        module.bind_evaluation_artifacts({
            "raw_predictions": {
                "path": "predictions.jsonl",
                "rows": 1,
                "sha256": "a" * 64,
                "format": "jsonl; one row per scored eval item",
            },
            "results": {},
        })

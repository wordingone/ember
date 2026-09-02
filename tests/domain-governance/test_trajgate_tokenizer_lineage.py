# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SPEC = importlib.util.spec_from_file_location(
    "trajgate_tokenizer_lineage",
    ROOT / "scripts" / "trajgate_tokenizer_lineage.py",
)
assert SPEC and SPEC.loader
LINEAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINEAGE)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _row(
    step: int,
    manifest_sha256: str,
    model_pt_sha256: str,
    parent_evidence: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "step": step,
        "manifest_sha256": manifest_sha256,
        "model_pt_sha256": model_pt_sha256,
        "parent_evidence": parent_evidence,
    }


def test_intact_parent_evidence_chain_passes() -> None:
    rows = [
        _row(10, SHA_A, SHA_B, []),
        _row(
            20,
            SHA_C,
            SHA_D,
            [
                {
                    "step": 10,
                    "manifest_sha256": SHA_A,
                    "model_pt_sha256": SHA_B,
                }
            ],
        ),
    ]

    assert LINEAGE.verify_parent_evidence_chain(rows) == {
        "root_step": 10,
        "terminal_step": 20,
        "verified_edge_count": 1,
    }


def test_forged_parent_evidence_hash_breaches() -> None:
    rows = [
        _row(10, SHA_A, SHA_B, []),
        _row(
            20,
            SHA_C,
            SHA_D,
            [
                {
                    "step": 10,
                    "manifest_sha256": "f" * 64,
                    "model_pt_sha256": SHA_B,
                }
            ],
        ),
    ]

    with pytest.raises(LINEAGE.LineageError, match="parent evidence mismatch"):
        LINEAGE.verify_parent_evidence_chain(rows)


def test_missing_parent_row_breaches() -> None:
    rows = [
        _row(
            20,
            SHA_C,
            SHA_D,
            [
                {
                    "step": 10,
                    "manifest_sha256": SHA_A,
                    "model_pt_sha256": SHA_B,
                }
            ],
        )
    ]

    with pytest.raises(LINEAGE.LineageError, match="root row.*parent_evidence"):
        LINEAGE.verify_parent_evidence_chain(rows)


def test_parent_identity_is_hashed_from_actual_parent_artifacts(tmp_path: Path) -> None:
    parent_dir = tmp_path / "models" / "parent"
    parent_dir.mkdir(parents=True)
    parent_manifest = {
        "extra": {"segment_id": "parent-segment"},
        "declared_child_parent_manifest_sha256": "f" * 64,
        "declared_child_parent_model_pt_sha256": "e" * 64,
    }
    manifest_bytes = json.dumps(parent_manifest, sort_keys=True).encode("utf-8")
    model_bytes = b"actual-parent-model-bytes"
    (parent_dir / "manifest.json").write_bytes(manifest_bytes)
    (parent_dir / "model.pt").write_bytes(model_bytes)

    assert LINEAGE.checkpoint_identity_from_artifacts(10, "parent", tmp_path) == {
        "step": 10,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "model_pt_sha256": hashlib.sha256(model_bytes).hexdigest(),
    }


def test_generated_child_receipt_embeds_actual_parent_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "freeze.json").write_text("{}", encoding="utf-8")
    for rel_path, segment, model_bytes in (
        ("parent", "parent-segment", b"parent-model"),
        ("child", "child-segment", b"child-model"),
    ):
        checkpoint = tmp_path / "models" / rel_path
        checkpoint.mkdir(parents=True)
        (checkpoint / "manifest.json").write_text(
            json.dumps({"extra": {"segment_id": segment, "total_steps": 2}}),
            encoding="utf-8",
        )
        (checkpoint / "model.pt").write_bytes(model_bytes)
    monkeypatch.setattr(
        LINEAGE,
        "_load_checkpoint_tensor_dims",
        lambda _path: {"vocab_size": 32, "embedding_rows": 32},
    )

    receipt = LINEAGE._generate_lineage_receipt(
        20,
        "child-block",
        "child",
        tmp_path,
        SHA_A,
        "freeze.json",
        parent_step=10,
        parent_rel_path="parent",
    )

    assert receipt["parent_evidence"] == [
        LINEAGE.checkpoint_identity_from_artifacts(10, "parent", tmp_path)
    ]

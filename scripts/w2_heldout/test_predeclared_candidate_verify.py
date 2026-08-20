# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Two-sided tests for #1433's predeclared-candidate verify-only carrier."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import build_decontam_batch_mp as subject


def _candidate(tmp_path: Path, *, duplicate: bool = False) -> tuple[Path, Path, str, list[int]]:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    tokens = list(range(10, 50))
    if duplicate:
        tokens[20:22] = tokens[0:2]
    shard_path = shard_dir / "v0-00000.bin"
    np.asarray(tokens, dtype="<u2").tofile(shard_path)

    indices = list(range(16))
    windows = [
        {
            "window_index": index,
            "shard_name": "v0-00000.bin",
            "shard_token_start": index,
            "shard_token_end_exclusive": index + 2,
            "source_shard_token_end_exclusive": index + 2,
            "global_token_start": index,
            "global_token_end_exclusive": index + 2,
            "source_global_token_end_exclusive": index + 2,
        }
        for index in indices
    ]
    manifest = {
        "schema": "cbase-heldout-slice/v1",
        "issue": "#760",
        "captured_public_master": "a" * 40,
        "source_corpus": {
            "combined_sha256": "b" * 64,
            "receipt_path": "receipts/token-shards-v0-fixture.json",
            "receipt_sha256": "c" * 64,
            "shards": [{
                "name": "v0-00000.bin",
                "sha256": hashlib.sha256(shard_path.read_bytes()).hexdigest(),
                "n_tokens": len(tokens),
                "global_token_start": 0,
                "global_token_end_exclusive": len(tokens),
            }],
        },
        "selection_evidence": {
            "path": "receipts/cbase-heldout-eval/issue-760-slice-regeneration-finding.json",
            "sha256": "d" * 64,
            "batch_sha256": "d" * 64,
            "verdict": "DECONTAMINATION_NOT_PERFORMED",
        },
        "sequence": {
            "dtype": "<u2",
            "seq": 1,
            "n_mtp": 0,
            "separator_id": 0,
            "packed_bytes_per_token": 2,
            "scoring": "primary_next_token_only",
        },
        "training_consumption": [{
            "source": "fixture",
            "global_token_start": 30,
            "global_token_end_exclusive": 31,
        }],
        "windows": windows,
        "expected_scored_token_count": 16,
        "scale": "W1_FROM_SCRATCH_PILOT_BASELINE",
        "availability": {"status": "AVAILABLE", "missing": [], "note": "fixture"},
        "claim_boundary": "fixture candidate; no measurement claim",
    }
    manifest_path = tmp_path / "candidate.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest_path, shard_dir, hashlib.sha256(manifest_path.read_bytes()).hexdigest(), indices


def test_loader_requires_exact_candidate_sha(tmp_path: Path) -> None:
    manifest_path, _shard_dir, _manifest_sha, _indices = _candidate(tmp_path)

    with pytest.raises(SystemExit, match="PREDECLARED_CANDIDATE_SHA_MISMATCH"):
        subject.load_predeclared_candidate(manifest_path, "0" * 64)


@pytest.mark.parametrize("mutation", ["reordered", "extra"])
def test_loader_refuses_any_order_or_count_change_even_with_matching_new_sha(
    tmp_path: Path, mutation: str
) -> None:
    manifest_path, _shard_dir, _manifest_sha, _indices = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "reordered":
        manifest["windows"][0], manifest["windows"][1] = (
            manifest["windows"][1], manifest["windows"][0])
    else:
        manifest["windows"].append(dict(manifest["windows"][-1], window_index=16,
                                         shard_token_start=16, shard_token_end_exclusive=18,
                                         source_shard_token_end_exclusive=18,
                                         global_token_start=16, global_token_end_exclusive=18,
                                         source_global_token_end_exclusive=18))
        manifest["expected_scored_token_count"] = 17
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    changed_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(SystemExit, match="PREDECLARED_CANDIDATE_(ORDER|COUNT)_INVALID"):
        subject.load_predeclared_candidate(manifest_path, changed_sha)


def test_verify_only_preserves_exact_order_and_accepts_self_matches_only(tmp_path: Path) -> None:
    manifest_path, shard_dir, manifest_sha, indices = _candidate(tmp_path)
    manifest = subject.load_predeclared_candidate(manifest_path, manifest_sha)

    receipt = subject.verify_predeclared_candidate(
        manifest,
        candidate_manifest_path=manifest_path,
        candidate_manifest_sha256=manifest_sha,
        shard_dir=shard_dir,
        use_mp=False,
        n_workers=1,
        contamination_window=2,
    )

    assert receipt["status"] == "CLEAN"
    assert receipt["pass"] is True
    assert receipt["selected_window_indices"] == indices
    assert receipt["candidate_manifest_sha256"] == manifest_sha
    assert receipt["reselection_or_substitution"] is False
    assert receipt["contamination_recheck"]["confirmed_non_self_matches"] == 0


def test_one_non_self_hit_refuses_the_whole_predeclared_candidate(tmp_path: Path) -> None:
    manifest_path, shard_dir, manifest_sha, _indices = _candidate(tmp_path, duplicate=True)
    manifest = subject.load_predeclared_candidate(manifest_path, manifest_sha)

    with pytest.raises(SystemExit, match="PREDECLARED_CANDIDATE_CONTAMINATED"):
        subject.verify_predeclared_candidate(
            manifest,
            candidate_manifest_path=manifest_path,
            candidate_manifest_sha256=manifest_sha,
            shard_dir=shard_dir,
            use_mp=False,
            n_workers=1,
            contamination_window=2,
        )


def test_receipt_writer_is_no_overwrite(tmp_path: Path) -> None:
    manifest_path, shard_dir, manifest_sha, _indices = _candidate(tmp_path)
    receipt = subject.verify_predeclared_candidate(
        subject.load_predeclared_candidate(manifest_path, manifest_sha),
        candidate_manifest_path=manifest_path,
        candidate_manifest_sha256=manifest_sha,
        shard_dir=shard_dir,
        use_mp=False,
        n_workers=1,
        contamination_window=2,
    )
    out = tmp_path / "verification.json"
    subject.write_predeclared_verification_receipt(receipt, out)
    original = out.read_bytes()

    with pytest.raises(SystemExit, match="PREDECLARED_RECEIPT_EXISTS"):
        subject.write_predeclared_verification_receipt(receipt, out)

    assert out.read_bytes() == original

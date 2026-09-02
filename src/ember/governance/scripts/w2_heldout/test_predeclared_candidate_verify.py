# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Two-sided tests for #1433's predeclared-candidate verify-only carrier."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

# issue2015 exact-local-import:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py
import importlib.util as _ember_9c92008c8512cb00_importlib
import sys as _ember_9c92008c8512cb00_sys
from pathlib import Path as _ember_9c92008c8512cb00_Path
_ember_9c92008c8512cb00_path = _ember_9c92008c8512cb00_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'w2_heldout', 'build_decontam_batch_mp.py')
if not _ember_9c92008c8512cb00_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
_ember_9c92008c8512cb00_aliases = ('_ember_issue2015_9c92008c8512cb00', 'build_decontam_batch_mp', 'src.ember.governance.scripts.w2_heldout.build_decontam_batch_mp')
_ember_9c92008c8512cb00_existing = []
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_candidate = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_candidate is not None and all(_ember_9c92008c8512cb00_candidate is not item for item in _ember_9c92008c8512cb00_existing):
        _ember_9c92008c8512cb00_existing.append(_ember_9c92008c8512cb00_candidate)
if len(_ember_9c92008c8512cb00_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
if _ember_9c92008c8512cb00_existing:
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_existing[0]
    _ember_9c92008c8512cb00_observed = getattr(_ember_9c92008c8512cb00_module, '__file__', None)
    if _ember_9c92008c8512cb00_observed is None or _ember_9c92008c8512cb00_Path(_ember_9c92008c8512cb00_observed).resolve() != _ember_9c92008c8512cb00_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
else:
    _ember_9c92008c8512cb00_spec = _ember_9c92008c8512cb00_importlib.spec_from_file_location('_ember_issue2015_9c92008c8512cb00', _ember_9c92008c8512cb00_path)
    if _ember_9c92008c8512cb00_spec is None or _ember_9c92008c8512cb00_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_importlib.module_from_spec(_ember_9c92008c8512cb00_spec)
    for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
        _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
        if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
        _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
    try:
        _ember_9c92008c8512cb00_spec.loader.exec_module(_ember_9c92008c8512cb00_module)
    except BaseException:
        for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
            if _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias) is _ember_9c92008c8512cb00_module:
                _ember_9c92008c8512cb00_sys.modules.pop(_ember_9c92008c8512cb00_alias, None)
        raise
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
subject = _ember_9c92008c8512cb00_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py


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


def _scoped_candidate(tmp_path: Path, *, contaminated: bool = False):
    shard_dir = tmp_path / "scoped-shards"
    shard_dir.mkdir()
    consumed = [1000 + (index % 30000) for index in range(51216)]
    candidate = [40000 + index for index in range(16 * 16 + 1)]
    if contaminated:
        consumed[100:113] = candidate[:13]
    consumed_path = shard_dir / "v0-00000.bin"
    candidate_path = shard_dir / "v0-00001.bin"
    np.asarray(consumed, dtype="<u2").tofile(consumed_path)
    np.asarray(candidate, dtype="<u2").tofile(candidate_path)
    windows = []
    for offset in range(16):
        shard_start = offset * 16
        global_start = 51216 + shard_start
        windows.append({
            "window_index": global_start // 16,
            "shard_name": "v0-00001.bin",
            "shard_token_start": shard_start,
            "shard_token_end_exclusive": shard_start + 17,
            "source_shard_token_end_exclusive": shard_start + 17,
            "global_token_start": global_start,
            "global_token_end_exclusive": global_start + 17,
            "source_global_token_end_exclusive": global_start + 17,
        })
    manifest = {
        "schema": "cbase-heldout-slice/v1", "issue": "#760",
        "captured_public_master": "a" * 40,
        "source_corpus": {
            "combined_sha256": "b" * 64,
            "receipt_path": "receipts/token-shards-v0-fixture.json",
            "receipt_sha256": "c" * 64,
            "shards": [{
                "name": "v0-00001.bin",
                "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "n_tokens": len(candidate),
                "global_token_start": 51216,
                "global_token_end_exclusive": 51216 + len(candidate),
            }],
        },
        "selection_evidence": {
            "path": "receipts/cbase-heldout-eval/issue-760-slice-regeneration-finding.json",
            "sha256": "d" * 64, "batch_sha256": "d" * 64,
            "verdict": "DECONTAMINATION_NOT_PERFORMED",
        },
        "sequence": {"dtype": "<u2", "seq": 16, "n_mtp": 0, "separator_id": 0,
                     "packed_bytes_per_token": 2, "scoring": "primary_next_token_only"},
        "training_consumption": [{"source": "fixture", "global_token_start": 0,
                                  "global_token_end_exclusive": 51201}],
        "windows": windows, "expected_scored_token_count": 256,
        "scale": "W1_FROM_SCRATCH_PILOT_BASELINE",
        "availability": {"status": "AVAILABLE", "missing": [], "note": "fixture"},
        "claim_boundary": "fixture candidate; no measurement claim",
    }
    manifest_path = tmp_path / "scoped-candidate.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    proof = {
        "schema": "issue1433-warm100-trained-range-match-intersection/v1",
        "issue": 1433, "status": "PASS", "answer": "NO", "question": "fixture",
        "trained_run": {
            "run_id": "issue1296-warm100-run-20260819T203314Z",
            "source_commit": "b" * 40,
            "run_spec_path": "B:/fixture/run-spec.json", "run_spec_sha256": "1" * 64,
            "checkpoint_manifest_path": "B:/fixture/checkpoint-manifest.json",
            "checkpoint_manifest_sha256": "2" * 64,
            "stream_receipt_path": "A:/fixture/token-shards.json",
            "stream_receipt_sha256": "3" * 64,
            "sequence_length": 512, "steps": 100,
            "start_cursor": {"shard_index": 0, "token_offset": 0},
            "terminal_cursor": {"shard_index": 0, "token_offset": 51200,
                                "record_index": 100, "global_step": 100,
                                "tokens_seen": 51200},
            "consumed_physical_range": {
                "shard": "v0-00000.bin",
                "input_and_target_token_positions_inclusive": [0, 51200],
                "derivation": "fixture",
            },
            "producer_source": {},
        },
        "scan_evidence": {"refusal_packet_sha256": "5ffd38dca7d8cd10b1133a44c703c2468deb0d4f08f31053678eb9dc873d6aa2",
                          "confirmed_non_self_matches": 20777},
        "intersection": {"confirmed_non_self_matches_inside_trained_range": 0,
                         "any": False, "confidence": "fixture"},
        "claim_boundary": "fixture",
    }
    proof_path = tmp_path / "consumption-proof.json"
    proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
    proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()
    return manifest_path, manifest_sha, shard_dir, proof_path, proof_sha


def test_scoped_loader_refuses_wrong_consumption_set_hash(tmp_path: Path) -> None:
    _manifest_path, _manifest_sha, _shard_dir, proof_path, _proof_sha = _scoped_candidate(tmp_path)
    with pytest.raises(SystemExit, match="TRAINING_CONSUMPTION_SET_SHA_MISMATCH"):
        subject.load_training_consumption_set(proof_path, "0" * 64)


def test_scoped_scan_binds_candidate_consumption_and_checkpoint(tmp_path: Path) -> None:
    manifest_path, manifest_sha, shard_dir, proof_path, proof_sha = _scoped_candidate(tmp_path)
    receipt = subject.verify_predeclared_candidate_against_training_consumption(
        subject.load_predeclared_candidate(manifest_path, manifest_sha),
        candidate_manifest_path=manifest_path,
        candidate_manifest_sha256=manifest_sha,
        shard_dir=shard_dir,
        consumption_set=subject.load_training_consumption_set(proof_path, proof_sha),
        training_consumption_set_sha256=proof_sha,
        contamination_window=13,
    )
    assert receipt["status"] == "CLEAN_VS_TRAINED_CONSUMPTION"
    assert receipt["candidate_manifest_sha256"] == manifest_sha
    assert len(receipt["candidate_batch_sha256"]) == 64
    assert receipt["training_consumption_set_sha256"] == proof_sha
    assert receipt["checkpoint_identity"]["manifest_sha256"] == "2" * 64
    assert receipt["contamination_recheck"]["confirmed_matches"] == 0
    assert receipt["whole_corpus_refusal"]["confirmed_non_self_matches"] == 20777
    assert receipt["zero_intersection_proof"]["sha256"] == proof_sha


def test_scoped_scan_refuses_whole_candidate_on_consumed_range_match(tmp_path: Path) -> None:
    manifest_path, manifest_sha, shard_dir, proof_path, proof_sha = _scoped_candidate(
        tmp_path, contaminated=True)
    with pytest.raises(SystemExit, match="TRAINED_CONSUMPTION_MATCH_REFUSED"):
        subject.verify_predeclared_candidate_against_training_consumption(
            subject.load_predeclared_candidate(manifest_path, manifest_sha),
            candidate_manifest_path=manifest_path,
            candidate_manifest_sha256=manifest_sha,
            shard_dir=shard_dir,
            consumption_set=subject.load_training_consumption_set(proof_path, proof_sha),
            training_consumption_set_sha256=proof_sha,
            contamination_window=13,
        )


def test_scoped_verify_cli_writes_closed_receipt_without_selection_controls(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path, manifest_sha, shard_dir, proof_path, proof_sha = _scoped_candidate(tmp_path)
    receipt_path = tmp_path / "scoped-verification.json"
    monkeypatch.setattr(subject, "_check_singleton_lock", lambda **_kwargs: None)
    monkeypatch.setattr(subject, "_preflight_check_commit", lambda: (64.0, 32.0))
    monkeypatch.setattr(subject, "_validate_predeclared_corpus", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", [
        "build_decontam_batch_mp.py",
        "--verify-predeclared-trained-consumption",
        "--candidate-manifest", str(manifest_path),
        "--expected-candidate-sha256", manifest_sha,
        "--training-consumption-set", str(proof_path),
        "--expected-training-consumption-set-sha256", proof_sha,
        "--shard-dir", str(shard_dir),
        "--verification-out", str(receipt_path),
    ])

    subject.main()

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["verdict"] == "CLEAN_VS_TRAINED_CONSUMPTION"
    assert receipt["training_consumption_set_sha256"] == proof_sha

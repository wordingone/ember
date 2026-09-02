# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import hashlib
import json
import re
from pathlib import Path


EXECUTION_RECEIPT = Path(__file__).parents[1] / "receipts" / "lifecycle-census" / "ember-inherited-drawdown-002-execution-v1.json"
MANIFEST = Path(__file__).parents[1] / "receipts" / "lifecycle-census" / "ember-inherited-drawdown-002-keep-manifest-v2.json"


def _load() -> dict:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical = dict(payload)
    recorded = canonical.pop("manifest_sha256")
    assert recorded == hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


def _rehashed(payload: dict) -> dict:
    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return payload


def _valid_delete_row(payload: dict) -> dict:
    row = copy.deepcopy(payload["candidates"][0])
    row["verdict"] = "DELETE_VERIFIED"
    row["protection"] = False
    row["open_head_prs"] = []
    row["path_diff_blob_equivalence"] = {
        "status": "PROVEN_EXACT",
        "paths": ["receipts/example.json"],
        "terminal_blobs": {"receipts/example.json": "a" * 40},
    }
    return row


def test_manifest_has_no_delete_rows_and_preserves_divergent_edge_case() -> None:
    payload = _load()
    assert payload["deletion_authority"] == "NOT_GRANTED"
    assert payload["mutation_performed"] is False
    assert payload["candidate_count"] == len(payload["candidates"]) == 15
    assert all(row["verdict"].startswith("KEEP_") for row in payload["candidates"])
    edge = payload["independent_custody_edge_case"]
    assert edge["pr_state"] == "MERGED"
    assert edge["open_head_prs"] == []
    assert edge["protection"] is False
    assert edge["path_diff_blob_equivalence"] == "NOT_PROVEN"
    assert edge["verdict"] == "KEEP_UNCERTAIN_BRANCH_UNIQUE_OR_DIVERGED"
    assert edge["master_compare"]["status"] == "diverged"


def test_manifest_registered_worktrees_are_path_free_and_typed() -> None:
    registered = _load()["registered_worktrees"]
    assert registered["count"] == len(registered["entries"]) == 2
    assert registered["deletion_authority"] == "NOT_GRANTED"
    assert re.fullmatch(r"[0-9a-f]{64}", registered["porcelain_sha256"])
    for entry in registered["entries"]:
        assert re.fullmatch(r"[0-9a-f]{40}", entry["head_sha"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["path_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["common_repo_path_sha256"])
        assert entry["dirty"] is False
        assert entry["verdict"] == "KEEP_ACTIVE_OR_BASE"


def test_manifest_verifier_selects_no_uncertain_delete_rows() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import verified_delete_rows, verify_manifest

    payload = _load()
    verify_manifest(payload)
    assert verified_delete_rows(payload) == []


def test_manifest_verifier_rejects_uncertain_row_marked_for_deletion() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verified_delete_rows

    payload = _load()
    tampered = copy.deepcopy(payload)
    tampered["candidates"][0]["verdict"] = "DELETE_VERIFIED"
    canonical = dict(tampered)
    canonical.pop("manifest_sha256")
    tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with __import__("pytest").raises(ManifestError, match="DELETE_VERIFIED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_delete_row_under_not_granted_authority() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verified_delete_rows

    tampered = copy.deepcopy(_load())
    tampered["candidates"][0] = _valid_delete_row(tampered)
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="DELETE_VERIFIED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_granted_authority_in_structural_verifier() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verified_delete_rows

    tampered = copy.deepcopy(_load())
    tampered["deletion_authority"] = "GRANTED_EXACT_ROWS"
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="NOT_GRANTED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_duplicate_candidate_refs() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verify_manifest

    for duplicate in ("KEEP_KEEP", "KEEP_DELETE"):
        tampered = copy.deepcopy(_load())
        duplicate_row = copy.deepcopy(tampered["candidates"][0])
        if duplicate == "KEEP_DELETE":
            duplicate_row = _valid_delete_row(tampered)
        tampered["candidates"].append(duplicate_row)
        tampered["candidate_count"] = len(tampered["candidates"])
        tampered = _rehashed(tampered)
        with __import__("pytest").raises(ManifestError, match="duplicate candidate ref"):
            verify_manifest(tampered)


def test_manifest_verifier_rejects_more_than_25_candidates() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verify_manifest

    tampered = copy.deepcopy(_load())
    for index in range(11):
        row = copy.deepcopy(tampered["candidates"][0])
        row["ref"] = f"refs/heads/synthetic-wave003-{index}"
        tampered["candidates"].append(row)
    tampered["candidate_count"] = len(tampered["candidates"])
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="at most 25"):
        verify_manifest(tampered)


def test_execution_receipt_is_canonical_noop_and_binds_manifest() -> None:
    receipt = json.loads(EXECUTION_RECEIPT.read_text(encoding="utf-8"))
    canonical = dict(receipt)
    recorded = canonical.pop("receipt_sha256")
    assert recorded == hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert receipt["decision"] == {
        "candidate_count": 15,
        "deletion_authority": "NOT_GRANTED",
        "mutation_performed": False,
        "verified_delete_count": 0,
    }
    assert receipt["manifest"]["manifest_sha256"] == _load()["manifest_sha256"]
    assert receipt["before"]["remote_branch_count"] == 77
    assert receipt["after"]["remote_branch_count"] == 78
    assert "not attributed" in receipt["interpretation"]


def test_manifest_verifier_rejects_path_traversal_ref() -> None:
    from src.ember.governance.scripts.verify_lifecycle_drawdown_manifest import ManifestError, verify_manifest

    tampered = copy.deepcopy(_load())
    tampered["candidates"][0]["ref"] = "refs/heads/../unsafe"
    canonical = dict(tampered)
    canonical.pop("manifest_sha256")
    tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with __import__("pytest").raises(ManifestError, match="safe full head ref"):
        verify_manifest(tampered)

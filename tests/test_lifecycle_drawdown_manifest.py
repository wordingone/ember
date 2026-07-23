# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import json
import re
from pathlib import Path


MANIFEST = Path(__file__).parents[1] / "receipts" / "lifecycle-census" / "ember-inherited-drawdown-002-keep-manifest-v2.json"


def _load() -> dict:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical = dict(payload)
    recorded = canonical.pop("manifest_sha256")
    assert recorded == hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


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

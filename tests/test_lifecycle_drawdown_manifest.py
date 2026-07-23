import hashlib
import json
import subprocess
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

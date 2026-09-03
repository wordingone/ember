# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import tempfile
from pathlib import Path

from src.ember.governance.scripts import architecture_map


def test_manifest_json_path_literals_are_in_consumer_repoint_census() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = root / "manifests" / "custody" / "ledger.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            '{"guard_ref":"tests/legacy/test_guard.py:test_load_bearing"}\n',
            encoding="utf-8",
        )
        rows = [
            {
                "path": "manifests/custody/ledger.json",
                "owner": "Governance",
                "disposition": "KEEP",
                "touch_set_id": "manifest-census",
            }
        ]

        result = architecture_map.discover_consumers(root, rows)

    assert len(result["rows"]) == 1
    assert result["rows"][0]["consumer_path"] == "manifests/custody/ledger.json"
    assert result["rows"][0]["target"] == "tests/legacy/test_guard.py"
    assert result["rows"][0]["discovery_class"] == "manifest-reference"

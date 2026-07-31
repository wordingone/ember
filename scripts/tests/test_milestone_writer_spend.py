# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "check_milestone_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("check_milestone_reconciliation", MODULE_PATH)
assert SPEC and SPEC.loader
milestone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(milestone)


def test_authority_crosswalk_receipt_declares_zero_paid_spend(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ember-authority-matrix.md").write_text("fixture", encoding="utf-8")

    fake_gate = types.ModuleType("authority_supersession_gate")
    fake_gate.CROSSWALK_PATH = Path("docs/ember-authority-crosswalk.json")
    fake_gate.validate_current_authority_crosswalk = lambda _root: {
        "status": "PASS",
        "row_count": 1,
        "custody_gap_count": 0,
    }
    monkeypatch.setitem(sys.modules, "authority_supersession_gate", fake_gate)
    monkeypatch.setattr(milestone, "ROOT", str(tmp_path))

    captured = {}

    def capture(receipt, _timestamp):
        captured.update(receipt)
        return tmp_path / "receipt.json"

    monkeypatch.setattr(milestone, "_emit", capture)

    assert milestone.run() == 0
    assert captured["api_spend_usd"] == 0
    assert captured["paid_api_surface_used"] is False

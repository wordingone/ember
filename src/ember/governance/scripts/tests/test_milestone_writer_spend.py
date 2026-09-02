# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "ember" / "governance" / "scripts" / "check_milestone_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("check_milestone_reconciliation", MODULE_PATH)
assert SPEC and SPEC.loader
milestone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(milestone)

# [C-MILE cure] milestone_leg.py's MILESTONE_CHECKER.verdict_regex / test_c_mile.py's
# MILESTONE_VERDICT_LINE_RE -- re-derived here (not imported) so this test independently
# proves the writer's stdout satisfies the real dual-source-leg contract, the same
# discipline test_c_mile.py itself uses against milestone_leg.py.
VERDICT_LINE_RE = re.compile(
    r"^mapped=\d+/\d+\s+unmapped=\d+\s+lattice_diff=\d+\s+floor_contract_gaps=\d+\s+exit=(PASS|FAIL)\b")


def _patch_crosswalk(monkeypatch, tmp_path, *, status="PASS", row_count=1, custody_gap_count=0):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "ember-authority-matrix.md").write_text("fixture", encoding="utf-8")

    fake_gate = types.ModuleType("authority_supersession_gate")
    fake_gate.CROSSWALK_PATH = Path("docs/ember-authority-crosswalk.json")
    fake_gate.validate_current_authority_crosswalk = lambda _root: {
        "status": status,
        "row_count": row_count,
        "custody_gap_count": custody_gap_count,
    }
    monkeypatch.setitem(sys.modules, "authority_supersession_gate", fake_gate)
    monkeypatch.setattr(milestone, "ROOT", str(tmp_path))


def test_authority_crosswalk_receipt_declares_zero_paid_spend(monkeypatch, tmp_path):
    _patch_crosswalk(monkeypatch, tmp_path)

    captured = {}

    def capture(receipt, _timestamp):
        captured.update(receipt)
        return tmp_path / "receipt.json"

    monkeypatch.setattr(milestone, "_emit", capture)

    assert milestone.run() == 0
    assert captured["api_spend_usd"] == 0
    assert captured["paid_api_surface_used"] is False


def test_authority_crosswalk_path_prints_dual_source_verdict_line(monkeypatch, tmp_path, capsys):
    """C-MILE regression: the supersession branch used to print only the human-readable
    'PASS: legacy milestone reconciliation is preserved...' message, with no line matching
    the leg reader's verdict_regex -- every run resolved to UNRESOLVABLE (board row C-MILE
    RED) regardless of the crosswalk's real, validated PASS state. The fix must emit a
    verdict line here, derived from the same fields just persisted in the receipt."""
    _patch_crosswalk(monkeypatch, tmp_path, row_count=251, custody_gap_count=0)
    monkeypatch.setattr(milestone, "_emit", lambda receipt, _timestamp: tmp_path / "receipt.json")

    assert milestone.run() == 0

    stdout = capsys.readouterr().out
    matches = [line for line in stdout.splitlines() if VERDICT_LINE_RE.match(line.strip())]
    assert matches, f"no stdout line matched the dual-source verdict_regex; got: {stdout!r}"
    assert matches[0].strip() == "mapped=55/55  unmapped=0  lattice_diff=0  floor_contract_gaps=0  exit=PASS"

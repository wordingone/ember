# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for deterministic, non-authorizing derived claims-index outputs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_authority_conservation",
    REPO / "scripts" / "verify_authority_conservation.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BUILDER = r"""def build_index(receipts_dir):
    return ([{"path": "receipts/a.json", "ticket": "A"}], {"indexed": 1})
def render_index_jsonl(rows):
    return '{"path": "receipts/a.json", "ticket": "A"}\n'
def render_claims_md(rows):
    return '# Claims index\n'
"""

def fixture(tmp_path: Path) -> Path:
    (tmp_path / "src" / "ember" / "governance" / "scripts").mkdir(parents=True)
    (tmp_path / "receipts").mkdir()
    (tmp_path / "src" / "ember" / "governance" / "scripts" / "build_claims_index.py").write_text(BUILDER, encoding="utf-8")
    (tmp_path / "receipts" / "INDEX.jsonl").write_text(
        '{"path": "receipts/a.json", "ticket": "A"}\n', encoding="utf-8"
    )
    (tmp_path / "receipts" / "CLAIMS.md").write_text("# Claims index\n", encoding="utf-8")
    return tmp_path

def test_exact_deterministic_outputs_are_the_only_exempt_paths(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    errors: list[dict] = []
    allowed = MODULE.verified_derived_receipt_index_paths(
        root, {"receipts/INDEX.jsonl", "receipts/CLAIMS.md", "scripts/example.py"}, errors
    )
    assert errors == []
    assert allowed == {"receipts/INDEX.jsonl", "receipts/CLAIMS.md"}

def test_tampered_derived_output_fails_closed(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / "receipts" / "INDEX.jsonl").write_text("tampered\n", encoding="utf-8")
    errors: list[dict] = []
    allowed = MODULE.verified_derived_receipt_index_paths(
        root, {"receipts/INDEX.jsonl"}, errors
    )
    assert allowed == set()
    assert [item["code"] for item in errors] == ["artifact.derived_index_invalid"]

def test_unrelated_change_does_not_load_or_exempt_outputs(tmp_path: Path) -> None:
    errors: list[dict] = []
    assert MODULE.verified_derived_receipt_index_paths(
        tmp_path, {"scripts/example.py"}, errors
    ) == set()
    assert errors == []

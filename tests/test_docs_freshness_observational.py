# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Observational docs-freshness tests for EMBER-02A.

goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_docs_freshness",
    REPO / "scripts" / "check_docs_freshness.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


BUILDER = r"""from pathlib import Path
def build_index(receipts_dir):
    return ([{"path": "receipts/a.json", "ticket": "A"}], {"indexed": 1})
def render_index_jsonl(rows):
    return '{"path": "receipts/a.json", "ticket": "A"}\n'
def render_claims_md(rows):
    return '# Claims index\n'
"""


def fixture(tmp_path: Path, *, stale: bool = False) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "receipts").mkdir()
    (tmp_path / "scripts" / "build_claims_index.py").write_text(
        BUILDER,
        encoding="utf-8",
    )
    (tmp_path / "receipts" / "INDEX.jsonl").write_text(
        "stale\n" if stale else '{"path": "receipts/a.json", "ticket": "A"}\n',
        encoding="utf-8",
    )
    (tmp_path / "receipts" / "CLAIMS.md").write_text(
        "stale\n" if stale else "# Claims index\n",
        encoding="utf-8",
    )
    return tmp_path


def test_claims_freshness_is_observational(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    index_path = root / "receipts" / "INDEX.jsonl"
    claims_path = root / "receipts" / "CLAIMS.md"
    before = (index_path.read_bytes(), claims_path.read_bytes())

    checker = MODULE.DocsFreshnessChecker(root)
    checker.check_claims_index_freshness()

    assert checker.defects == []
    assert (index_path.read_bytes(), claims_path.read_bytes()) == before


def test_claims_freshness_reports_both_stale_outputs_without_rewriting(
    tmp_path: Path,
) -> None:
    root = fixture(tmp_path, stale=True)
    index_path = root / "receipts" / "INDEX.jsonl"
    claims_path = root / "receipts" / "CLAIMS.md"
    before = (index_path.read_bytes(), claims_path.read_bytes())

    checker = MODULE.DocsFreshnessChecker(root)
    checker.check_claims_index_freshness()

    assert [item["file"] for item in checker.defects] == [
        "receipts/INDEX.jsonl",
        "receipts/CLAIMS.md",
    ]
    assert (index_path.read_bytes(), claims_path.read_bytes()) == before

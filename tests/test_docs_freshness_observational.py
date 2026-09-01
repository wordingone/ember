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
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_docs_freshness",
    REPO / "src" / "ember" / "governance" / "scripts" / "check_docs_freshness.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_direct_cli_entrypoint_imports_shared_spec_policy() -> None:
    result = subprocess.run(
        [sys.executable, "-B", str(REPO / "src" / "ember" / "governance" / "scripts" / "check_docs_freshness.py"), "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--repo" in result.stdout


BUILDER = r"""from pathlib import Path
def build_index(receipts_dir):
    return ([{"path": "receipts/a.json", "ticket": "A"}], {"indexed": 1})
def render_index_jsonl(rows):
    return '{"path": "receipts/a.json", "ticket": "A"}\n'
def render_claims_md(rows):
    return '# Claims index\n'
"""


def fixture(tmp_path: Path, *, stale: bool = False) -> Path:
    (tmp_path / "src" / "ember" / "governance" / "scripts").mkdir(parents=True)
    (tmp_path / "receipts").mkdir()
    (tmp_path / "src" / "ember" / "governance" / "scripts" / "build_claims_index.py").write_text(
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


def test_ember_cli_specs_report_missing_current_consumer(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    specs = root / "tools" / "ember-cli" / "specs"
    specs.mkdir(parents=True)
    (specs / "current.md").write_text(
        "# Current spec\n\nStatus: SHIPPED\n",
        encoding="utf-8",
    )

    checker = MODULE.DocsFreshnessChecker(root)
    checker.check_ember_cli_specs()

    assert checker.defects == [
        {
            "file": "tools/ember-cli/specs/",
            "defect_class": "invalid_ember_cli_spec",
            "description": (
                "tools/ember-cli/specs/current.md:consumer-required"
            ),
        }
    ]


def test_ember_cli_specs_accept_existing_bound_consumer(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    specs = root / "tools" / "ember-cli" / "specs"
    service = root / "tools" / "ember-cli" / "src" / "services"
    specs.mkdir(parents=True)
    service.mkdir(parents=True)
    (service / "current.ts").write_text("export {};\n", encoding="utf-8")
    (specs / "current.md").write_text(
        "# Current spec\n\n"
        "Status: SHIPPED\n"
        "Consumer: `tools/ember-cli/src/services/current.ts`\n",
        encoding="utf-8",
    )

    checker = MODULE.DocsFreshnessChecker(root)
    checker.check_ember_cli_specs()

    assert checker.defects == []

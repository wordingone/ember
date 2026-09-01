#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_self_location_roots.py"
SPEC = importlib.util.spec_from_file_location("check_self_location_roots", SCRIPT)
assert SPEC and SPEC.loader
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def baseline(rows: list[dict[str, object]], expires: str = "2026-09-02") -> dict[str, object]:
    return subject.mint_baseline(
        rows,
        minted_on=dt.date(2026, 9, 1),
        expires_on=dt.date.fromisoformat(expires),
    )


def test_correct_root_and_local_directory_emit_match_denominator(tmp_path: Path) -> None:
    source = write(
        tmp_path / "scripts" / "probe.py",
        "from pathlib import Path\nHERE = Path(__file__).resolve().parent\nROOT = HERE.parent\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("HERE", "MATCH"), ("ROOT", "MATCH")]


def test_byte_identical_move_flips_root_match_to_mismatch(tmp_path: Path) -> None:
    text = "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
    original = write(tmp_path / "scripts" / "probe.py", text)
    assert subject.scan_files(tmp_path, [original])[0]["status"] == "MATCH"
    moved = write(tmp_path / "src" / "nested" / "probe.py", text)
    assert subject.scan_files(tmp_path, [moved])[0]["status"] == "MISMATCH"


def test_path_escaping_root_is_portable_and_never_serializes_checkout(tmp_path: Path) -> None:
    source = write(
        tmp_path / "scripts" / "probe.py",
        "import os\nROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n",
    )
    row = subject.scan_files(tmp_path, [source])[0]
    assert row["status"] == "MISMATCH"
    assert row["evaluated_path"] == "<root>/.."
    assert str(tmp_path.resolve()) not in str(row["evaluated_path"])


def test_dynamic_root_and_inline_sys_path_are_never_silent(tmp_path: Path) -> None:
    source = write(
        tmp_path / "probe.py",
        "import sys\nROOT = discover(__file__)\nsys.path.insert(0, discover(__file__))\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [row["status"] for row in rows] == ["UNEVALUABLE", "UNEVALUABLE"]


def test_root_like_assignment_outside_grammar_is_unevaluable_without_file_reference(tmp_path: Path) -> None:
    source = write(
        tmp_path / "probe.py",
        "import os\nCACHE_DIR = os.environ.get('CACHE_DIR')\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [
        ("CACHE_DIR", "UNEVALUABLE")
    ]


def test_exact_baseline_passes_but_expression_drift_and_growth_refuse(tmp_path: Path) -> None:
    source = write(tmp_path / "src" / "nested" / "probe.py", "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n")
    rows = subject.scan_files(tmp_path, [source])
    frozen = baseline(rows)
    assert subject.enforce_baseline(rows, frozen, dt.date(2026, 9, 1)) == []
    source.write_text("from pathlib import Path\nROOT = Path(__file__).resolve().parents[0]\n", encoding="utf-8")
    drifted = subject.scan_files(tmp_path, [source])
    errors = subject.enforce_baseline(drifted, frozen, dt.date(2026, 9, 1))
    assert "NEW_OR_DRIFTED_SELF_LOCATION_ROW" in errors

    second = write(
        tmp_path / "src" / "nested" / "second.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )
    grown = subject.scan_files(tmp_path, [source, second])
    errors = subject.enforce_baseline(grown, frozen, dt.date(2026, 9, 1))
    assert "BASELINE_COUNT_GROWTH" in errors


def test_row_identity_set_refuses_count_neutral_substitution_and_line_drift(tmp_path: Path) -> None:
    first = write(
        tmp_path / "first" / "nested" / "probe.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )
    second = write(
        tmp_path / "second" / "probe.py",
        "from pathlib import Path\nHERE = Path(__file__).resolve().parent\n",
    )
    original = subject.scan_files(tmp_path, [first, second])
    frozen = baseline(original)
    assert len([row for row in original if row["status"] != "MATCH"]) == 1

    first.write_text(
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\n",
        encoding="utf-8",
    )
    second.write_text(
        "from pathlib import Path\nHERE = Path(__file__).resolve().parent\n"
        "ROOT = Path(__file__).resolve().parents[0]\n",
        encoding="utf-8",
    )
    substituted = subject.scan_files(tmp_path, [first, second])
    assert len([row for row in substituted if row["status"] != "MATCH"]) == 1
    assert "NEW_OR_DRIFTED_SELF_LOCATION_ROW" in subject.enforce_baseline(
        substituted, frozen, dt.date(2026, 9, 1)
    )

    line_shifted = write(
        tmp_path / "first" / "nested" / "probe.py",
        "# inserted line\nfrom pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )
    shifted = subject.scan_files(tmp_path, [line_shifted])
    original_first = subject.scan_files(tmp_path, [write(
        tmp_path / "first" / "nested" / "baseline.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )])
    line_baseline = baseline([{**original_first[0], "path": "first/nested/probe.py"}])
    assert "NEW_OR_DRIFTED_SELF_LOCATION_ROW" in subject.enforce_baseline(
        shifted, line_baseline, dt.date(2026, 9, 1)
    )


def test_expired_baseline_refuses_any_remaining_debt(tmp_path: Path) -> None:
    source = write(tmp_path / "src" / "nested" / "probe.py", "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n")
    rows = subject.scan_files(tmp_path, [source])
    assert subject.enforce_baseline(rows, baseline(rows), dt.date(2026, 9, 3)) == [
        "BASELINE_EXPIRED_WITH_REMAINING_ROWS"
    ]


def test_baseline_manifest_binds_operator_expiry_policy_and_exact_count(tmp_path: Path) -> None:
    source = write(
        tmp_path / "src" / "nested" / "probe.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    frozen = baseline(rows)
    assert frozen["minted_on"] == "2026-09-01"
    assert frozen["baselined_row_count"] == len(frozen["rows"]) == frozen["maximum_rows"]
    assert frozen["expiry_change_authority"] == "OPERATOR_ONLY"
    assert frozen["expiry_consequence"] == (
        "after this date the gate fails on every baselined row, blocking all pull requests"
    )

    frozen["baselined_row_count"] = 0
    unsigned = dict(frozen)
    unsigned.pop("self_sha256")
    frozen["self_sha256"] = subject.hashlib.sha256(
        subject.json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert subject.enforce_baseline(rows, frozen, dt.date(2026, 9, 1)) == [
        "BASELINE_POLICY_INVALID"
    ]


def test_ci_runs_regressions_before_enforcing_the_checked_in_baseline() -> None:
    workflow = (SCRIPT.parents[1] / ".github/workflows/ci-pr.yml").read_text(encoding="utf-8")
    regression = "python -B -m pytest -q scripts/tests/test_self_location_roots.py"
    gate = (
        "python -B scripts/check_self_location_roots.py --root . "
        "--baseline scripts/self-location-baseline.json"
    )
    assert workflow.count(regression) == 1
    assert workflow.count(gate) == 1
    assert workflow.index(regression) < workflow.index(gate)

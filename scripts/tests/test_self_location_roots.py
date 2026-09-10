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
    # Every baselined row carries a reason, because after this leg a baseline without one is
    # refused at mint. The fixture reflects the contract rather than exempting itself from it.
    failures = [row for row in rows if row.get("status") != "MATCH"]
    return subject.mint_baseline(
        rows,
        minted_on=dt.date(2026, 9, 1),
        expires_on=dt.date.fromisoformat(expires),
        justifications={subject._justification_key(row): "fixture row under test"
                        for row in failures},
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


NL = chr(10)
MARKER_WALK = (
    "next(parent for parent in Path(__file__).resolve().parents "
    "if (parent / 'pyproject.toml').is_file())"
)


def _marker_tree(tmp_path: Path, body: str) -> Path:
    """A two-deep source under a directory that carries the marker file."""

    write(tmp_path / "pyproject.toml", "[project]" + NL + "name = 'probe'" + NL)
    return write(tmp_path / "pkg" / "probe.py", "from pathlib import Path" + NL + body)


def test_repo_marker_walk_resolves_to_the_directory_carrying_the_marker(tmp_path: Path) -> None:
    source = _marker_tree(tmp_path, "ROOT = " + MARKER_WALK + NL)
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "MATCH")]


def test_repo_marker_walk_reports_mismatch_when_a_nearer_parent_carries_the_marker(
    tmp_path: Path,
) -> None:
    """The rule produces verdicts, not blanket approval: a nested marker is a real MISMATCH."""

    write(tmp_path / "pyproject.toml", "[project]" + NL + "name = 'outer'" + NL)
    write(tmp_path / "nested" / "pyproject.toml", "[project]" + NL + "name = 'inner'" + NL)
    source = write(
        tmp_path / "nested" / "pkg" / "probe.py",
        "from pathlib import Path" + NL + "ROOT = " + MARKER_WALK + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "MISMATCH")]


def test_a_walk_that_does_not_start_at_file_stays_unevaluable(tmp_path: Path) -> None:
    """The refusal that matters most: resolving this against the checkout would report a verdict
    for an expression the checker never actually evaluated."""

    source = _marker_tree(
        tmp_path,
        "import os" + NL
        + "ROOT = next(parent for parent in Path(os.environ['X']).parents "
        + "if (parent / 'pyproject.toml').is_file())" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_no_parent_carrying_the_marker_is_unevaluable_never_the_filesystem_root(
    tmp_path: Path,
) -> None:
    source = write(
        tmp_path / "pkg" / "probe.py",
        "from pathlib import Path" + NL + "ROOT = " + MARKER_WALK + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_two_argument_next_with_a_fallback_stays_unevaluable(tmp_path: Path) -> None:
    source = _marker_tree(
        tmp_path,
        "ROOT = next((parent for parent in Path(__file__).resolve().parents "
        + "if (parent / 'pyproject.toml').is_file()), Path('/'))" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_a_walk_yielding_something_other_than_the_parent_stays_unevaluable(
    tmp_path: Path,
) -> None:
    source = _marker_tree(
        tmp_path,
        "ROOT = next(parent.parent for parent in Path(__file__).resolve().parents "
        + "if (parent / 'pyproject.toml').is_file())" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_a_non_literal_marker_name_stays_unevaluable(tmp_path: Path) -> None:
    source = _marker_tree(
        tmp_path,
        "MARKER = 'pyproject.toml'" + NL
        + "ROOT = next(parent for parent in Path(__file__).resolve().parents "
        + "if (parent / MARKER).is_file())" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert ("ROOT", "UNEVALUABLE") in [(row["target"], row["status"]) for row in rows]


def test_a_condition_that_is_not_an_existence_predicate_stays_unevaluable(
    tmp_path: Path,
) -> None:
    source = _marker_tree(
        tmp_path,
        "ROOT = next(parent for parent in Path(__file__).resolve().parents "
        + "if (parent / 'pyproject.toml').name.startswith('py'))" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_a_walk_over_something_other_than_parents_stays_unevaluable(tmp_path: Path) -> None:
    source = _marker_tree(
        tmp_path,
        "ROOT = next(parent for parent in Path(__file__).resolve().parent.iterdir() "
        + "if (parent / 'pyproject.toml').is_file())" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT", "UNEVALUABLE")]


def test_a_marker_joined_to_something_other_than_the_walk_target_stays_unevaluable(
    tmp_path: Path,
) -> None:
    source = _marker_tree(
        tmp_path,
        "OTHER = Path(__file__).resolve().parent" + NL
        + "ROOT = next(parent for parent in Path(__file__).resolve().parents "
        + "if (OTHER / 'pyproject.toml').is_file())" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert ("ROOT", "UNEVALUABLE") in [(row["target"], row["status"]) for row in rows]


def test_a_root_named_binding_that_appends_segments_is_a_derived_location(
    tmp_path: Path,
) -> None:
    """PRODUCER_ROOT = REPO_ROOT / "src" names a subdirectory, whatever it is called. Demanding
    that it equal the repository root reports a defect against a claim nobody made."""

    source = _marker_tree(
        tmp_path,
        "REPO_ROOT = " + MARKER_WALK + NL + "PRODUCER_ROOT = REPO_ROOT / 'src' / 'ember'" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    by_target = {row["target"]: row for row in rows}
    assert by_target["REPO_ROOT"]["expectation"] == "repo_root"
    assert by_target["REPO_ROOT"]["status"] == "MATCH"
    assert by_target["PRODUCER_ROOT"]["expectation"] == "derived_location_only"
    assert by_target["PRODUCER_ROOT"]["status"] == "MATCH"


def test_a_root_named_binding_with_no_join_still_owes_the_repository_root(
    tmp_path: Path,
) -> None:
    """The joined-expression carve-out is not a licence for every name ending in ROOT."""

    source = write(
        tmp_path / "pkg" / "deep" / "probe.py",
        "from pathlib import Path" + NL + "ROOT = Path(__file__).resolve().parent" + NL,
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [(row["target"], row["expectation"], row["status"]) for row in rows] == [
        ("ROOT", "repo_root", "MISMATCH")
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
    assert {key: frozen[key] for key in subject.BASELINE_GOAL_BINDING} == (
        subject.BASELINE_GOAL_BINDING
    )
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


def test_baseline_manifest_self_hash_binds_goal_metadata(tmp_path: Path) -> None:
    source = write(
        tmp_path / "src" / "nested" / "probe.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    frozen = baseline(rows)
    frozen["goal_id"] = "EMBER-OTHER"
    assert subject.enforce_baseline(rows, frozen, dt.date(2026, 9, 1)) == [
        "BASELINE_SELF_HASH_INVALID"
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


NOT_A_PATH_SOURCE = """\
import re
_DRIVE_ROOT_RE = re.compile('[A-Za-z]:')
ROOT_FIELDS = {'schema_version', 'seat'}
ROOT_EXCEPTIONS = {'.gitignore': 'lives at the repository root'}
DYNAMIC_CALL_ROOTS = frozenset({'runpy'})
_SIDECAR_ROOTS = set(['a', 'b'])
"""

COULD_BE_PATH_SOURCE = """\
import os
from pathlib import Path
HERE = Path(__file__).resolve().parent
EXTERNAL_ROOT = os.environ.get('EMBER_EXTERNAL_ROOT')
FIXTURE_ROOTS = [HERE / 'a', HERE / 'b']
SPEC_ROOTS = (HERE / 'c',)
"""


def test_root_named_bindings_that_cannot_be_paths_leave_the_census(tmp_path: Path) -> None:
    """The root-like predicate is name-based, so it admits regexes, sets and dicts by coincidence
    of naming. They leave rather than sit in the baseline as rows no justification can describe
    more truthfully than "this was never a path"."""
    source = write(tmp_path / "scripts" / "probe.py", NOT_A_PATH_SOURCE)
    assert subject.scan_files(tmp_path, [source]) == []


def test_the_reduction_does_not_reach_bindings_that_could_be_paths(tmp_path: Path) -> None:
    """The narrowness is the whole point. A root-named binding that refuses for a REAL reason --
    an environment read, an ordered collection whose elements reach __file__ -- keeps its row, so
    the census keeps watching exactly what it was built to watch."""
    source = write(tmp_path / "scripts" / "probe.py", COULD_BE_PATH_SOURCE)
    unevaluable = {
        row["target"]
        for row in subject.scan_files(tmp_path, [source])
        if row["status"] == "UNEVALUABLE"
    }
    assert unevaluable == {"EXTERNAL_ROOT", "FIXTURE_ROOTS", "SPEC_ROOTS"}


def test_a_dropped_name_repointed_at_a_path_comes_back_as_a_fresh_row(tmp_path: Path) -> None:
    """Why the reduction loses no watch: the census is recomputed from source on every run, so a
    dropped binding returns the moment it becomes a path again -- as an unbaselined row, which is
    the failure this gate exists to raise."""
    probe = tmp_path / "scripts" / "probe.py"
    assert subject.scan_files(tmp_path, [write(probe, "ROOT_FIELDS = {'schema_version'}\n")]) == []
    rows = subject.scan_files(
        tmp_path,
        [write(probe, "from pathlib import Path\nROOT_FIELDS = Path(__file__).resolve().parent\n")],
    )
    assert [(row["target"], row["status"]) for row in rows] == [("ROOT_FIELDS", "MISMATCH")]


NORMPATH_SIBLING_SOURCE = """\
import os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SIBLING_ROOT = os.path.normpath(os.path.join(ROOT, '..', 'other'))
"""


def test_normpath_makes_a_sibling_root_evaluable_and_it_mismatches(tmp_path: Path) -> None:
    """The point of admitting normpath is that the row stays EMITTED and gains the capacity to
    FAIL. scan_files appends a successful derivation only when depends_on_file is true, so a cure
    that severed that flag would delete the row rather than arm it -- which is exactly why the
    other residual bindings are left alone."""
    source = write(tmp_path / "scripts" / "probe.py", NORMPATH_SIBLING_SOURCE)
    rows = {row["target"]: row for row in subject.scan_files(tmp_path, [source])}
    assert rows["SIBLING_ROOT"]["status"] == "MISMATCH"
    assert rows["SIBLING_ROOT"]["expectation"] == "repo_root"
    assert rows["SIBLING_ROOT"]["error"] is None


def test_normpath_carries_the_file_dependence_through(tmp_path: Path) -> None:
    """A normpath over something that does not reach __file__ must not start being recorded: the
    grammar's job is to measure self-location, and a literal path normalised is still a literal."""
    source = write(
        tmp_path / "scripts" / "probe.py",
        "import os\nCONFIG_ROOT = os.path.normpath('a/../b')\n",
    )
    assert subject.scan_files(tmp_path, [source]) == []


def _failing_rows(tmp_path: Path) -> list[dict[str, object]]:
    source = write(
        tmp_path / "scripts" / "probe.py",
        "from pathlib import Path\nROOT = Path(__file__).resolve().parent\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    assert [row["status"] for row in rows] == ["MISMATCH"]
    return rows


def test_the_mint_refuses_a_partial_justification_set_and_names_the_rows(tmp_path: Path) -> None:
    """A baseline half-carrying reasons is worse than one carrying none: the empty entries read as
    'checked, nothing to say'. The refusal carries the ROWS rather than a count, because the
    caller's next action is to write those justifications and a count does not say which."""
    rows = _failing_rows(tmp_path)
    try:
        subject.mint_baseline(
            rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
            justifications={},
        )
    except subject.UnjustifiedRows as refused:
        assert [row["target"] for row in refused.rows] == ["ROOT"]
    else:
        raise AssertionError("the mint accepted a row for which no reason was supplied")


def test_a_whitespace_justification_is_not_a_justification(tmp_path: Path) -> None:
    """The field exists to carry a reason. A space satisfies 'non-empty' and satisfies nothing
    else, so the check is on the stripped value rather than on presence."""
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    try:
        subject.mint_baseline(
            rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
            justifications={key: "   "},
        )
    except subject.UnjustifiedRows as refused:
        assert refused.rows == rows
    else:
        raise AssertionError("whitespace was accepted as a reason")


def test_a_complete_set_mints_and_every_baselined_row_carries_its_reason(tmp_path: Path) -> None:
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    minted = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
        justifications={key: "correct as emitted: this root is component-scoped"},
    )
    assert [row["justification"] for row in minted["rows"]] == [
        "correct as emitted: this root is component-scoped"
    ]
    assert minted["maximum_rows"] == 1


def test_the_justification_survives_a_status_change_because_its_key_excludes_status(
    tmp_path: Path,
) -> None:
    """Deliberately NOT `_baseline_key`. That key includes status and evaluated_path, so a row whose
    status changes -- exactly what a grammar cure does -- would silently lose the reason someone
    wrote for it. The reason belongs to the binding at a location, and that is what a person read
    when they wrote it."""
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    drifted = dict(rows[0], status="UNEVALUABLE", evaluated_path=None)
    assert subject._justification_key(drifted) == key
    assert subject._baseline_key(drifted) != subject._baseline_key(rows[0])
    minted = subject.mint_baseline(
        [drifted], minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
        justifications={key: "still the same binding, still the same reason"},
    )
    assert minted["rows"][0]["justification"] == "still the same binding, still the same reason"


def test_an_added_justification_does_not_change_any_row_identity(tmp_path: Path) -> None:
    """The whole reason the field can live inside the baseline: `_baseline_key` reads six NAMED
    fields, so the allowed/current comparison is blind to it and no baselined row is invalidated by
    gaining a reason."""
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    plain = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
        justifications={key: "a different reason"})
    justified = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
        justifications={key: "a reason"})
    assert [subject._baseline_key(row) for row in plain["rows"]] == [
        subject._baseline_key(row) for row in justified["rows"]
    ]
    assert subject.enforce_baseline(rows, justified, dt.date(2026, 9, 2)) == []


def test_a_baselined_row_without_a_reason_refuses_the_gate(tmp_path: Path) -> None:
    """The deliberate red this leg owes. A gate whose exit code gates nothing is the receipted
    failure class, so the refusal is proven to FAIL the pipeline when its condition fails, not only
    to pass when it is satisfied."""
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    minted = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30),
        justifications={key: "a reason"})
    stripped = dict(minted)
    stripped["rows"] = [dict(row, justification="") for row in minted["rows"]]
    stripped.pop("self_sha256")
    stripped["self_sha256"] = subject.hashlib.sha256(
        subject.json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert subject.enforce_baseline(rows, stripped, dt.date(2026, 9, 2)) == [
        "BASELINE_ROW_UNJUSTIFIED"
    ]


def test_the_unjustified_refusal_does_not_mask_the_other_findings(tmp_path: Path) -> None:
    """Appended rather than returned early. A gate that stops at its first finding hands the reader
    one layer per run and every report looks like a first report -- the masked-failure treadmill,
    which this repository has already paid for at a different gate."""
    rows = _failing_rows(tmp_path)
    key = subject._justification_key(rows[0])
    minted = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 2),
        justifications={key: "a reason"})
    stripped = dict(minted)
    stripped["rows"] = [dict(row, justification="  ") for row in minted["rows"]]
    stripped.pop("self_sha256")
    stripped["self_sha256"] = subject.hashlib.sha256(
        subject.json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert subject.enforce_baseline(rows, stripped, dt.date(2026, 9, 3)) == [
        "BASELINE_ROW_UNJUSTIFIED",
        "BASELINE_EXPIRED_WITH_REMAINING_ROWS",
    ]


def test_the_mint_refuses_when_reasons_are_omitted_entirely(tmp_path: Path) -> None:
    """Otherwise the tool writes a baseline its own gate rejects. The refusal carries the rows, so
    the caller is handed a work list at the moment it still has them."""
    rows = _failing_rows(tmp_path)
    try:
        subject.mint_baseline(rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30))
    except subject.UnjustifiedRows as refused:
        assert refused.rows == rows
    else:
        raise AssertionError("the mint wrote a baseline that the checker refuses")


def test_a_baseline_with_no_rows_at_all_still_mints_without_reasons(tmp_path: Path) -> None:
    """The refusal is about rows that were accepted with no reason. A tree with nothing to accept
    has nothing to justify, and refusing it would make a clean repository unmintable."""
    source = write(
        tmp_path / "scripts" / "probe.py",
        "from pathlib import Path\nHERE = Path(__file__).resolve().parent\nROOT = HERE.parent\n",
    )
    rows = subject.scan_files(tmp_path, [source])
    assert all(row["status"] == "MATCH" for row in rows)
    minted = subject.mint_baseline(
        rows, minted_on=dt.date(2026, 9, 1), expires_on=dt.date(2026, 9, 30))
    assert minted["maximum_rows"] == 0
    assert subject.enforce_baseline(rows, minted, dt.date(2026, 9, 2)) == []

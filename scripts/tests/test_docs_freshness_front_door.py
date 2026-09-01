# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "check_docs_freshness.py"
FIXTURE = Path(__file__).parent / "fixtures" / "docs_freshness_front_door.md"


def load_checker():
    spec = importlib.util.spec_from_file_location("docs_freshness_front_door", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_prose_grammar_detects_and_excludes_exact_fixture_rows() -> None:
    module = load_checker()

    result = module.extract_path_candidates(FIXTURE.read_text(encoding="utf-8"))

    assert result.paths == {
        "fixtures/dead-mid.md",
        "fixtures/dead-end.json",
        "fixtures/dead-paren.py",
        "readme.md",
        "README.md",
    }
    assert result.pragma_lines == [15]


def test_resolution_is_git_tracked_and_case_sensitive(tmp_path: Path) -> None:
    module = load_checker()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "README.md").write_text("# tracked\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("local bytes cannot mask a defect\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)

    checker = module.DocsFreshnessChecker(tmp_path)

    assert checker.tracked_paths() == {"README.md"}
    assert checker.unresolved_paths({"README.md", "readme.md", "untracked.md"}) == {
        "readme.md",
        "untracked.md",
    }


def test_front_door_marker_coherence_requires_single_continuity_owner(
    tmp_path: Path,
) -> None:
    module = load_checker()
    (tmp_path / "docs" / "authority").mkdir(parents=True)
    (tmp_path / "README.md").write_text("# evergreen\n", encoding="utf-8")
    (tmp_path / "docs" / "authority" / "CONTINUITY.md").write_text(
        "<!-- state-as-of: 2026-08-01 -->\n"
        f"{module.BOARD_BEGIN_MARKER}\n{module.BOARD_END_MARKER}\n"
        f"{module.SUBJECT_BEGIN_MARKER}\n{module.SUBJECT_END_MARKER}\n",
        encoding="utf-8",
    )
    checker = module.DocsFreshnessChecker(tmp_path)

    checker.check_front_door_marker_coherence()

    assert checker.defects == []
    (tmp_path / "README.md").write_text(
        f"{module.SUBJECT_BEGIN_MARKER}\n{module.SUBJECT_END_MARKER}\n",
        encoding="utf-8",
    )
    checker = module.DocsFreshnessChecker(tmp_path)
    checker.check_front_door_marker_coherence()
    assert any(row["defect_class"] == "mutable_marker_misplaced" for row in checker.defects)


def test_both_workflows_wire_both_scoped_gates_by_exact_name() -> None:
    for relative in (".github/workflows/ci-pr.yml", ".github/workflows/ci-main.yml"):
        workflow = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert workflow.count("name: Verify evergreen front-door references") == 1
        assert workflow.count("python -B src/ember/governance/scripts/check_docs_freshness.py --front-door") == 1
        assert workflow.count("name: Verify generated continuity status") == 1
        assert workflow.count(
            "python -B src/ember/governance/scripts/gen_readme_status.py --check --generated-status"
        ) == 1

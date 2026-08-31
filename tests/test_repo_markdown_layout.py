# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_NAMES = {
    "GOAL.md",
    "INVARIANT.md",
    "GOVERNANCE.md",
    "CONTINUITY.md",
    "REDACTIONS.md",
    "STATE.md",
}

APPROVED_DOC_PATHS = {
    "docs/authority/ember-authority-matrix.md",
    "docs/contracts/ember-completeness.md",
    "docs/contracts/ember-floor-contract.md",
    "docs/contracts/goal-clear-protocol.md",
    "docs/guides/goal-live-session.md",
    "docs/contracts/goal-mode-mechanism.md",
    "docs/contracts/nc2-own-technique-contract.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md",
    "docs/custody/custody-disposition-20260708.md",
    "docs/custody/r1-exit-evidence-inventory-20260805.md",
    "docs/domains/governance/guides/START-HERE.md",
    "docs/roadmap/PROBLEMS.md",
}


def test_root_markdown_has_only_readme_and_mandatory_agent_control() -> None:
    assert {path.name for path in ROOT.glob("*.md")} == {"README.md", "AGENTS.md"}


def test_docs_root_markdown_has_only_docs_readme() -> None:
    assert {path.name for path in (ROOT / "docs").glob("*.md")} == {
        "DOCS-README.md"
    }


def test_every_authority_document_has_only_its_approved_path() -> None:
    for name in AUTHORITY_NAMES:
        assert not (ROOT / name).exists()
        if name == "GOAL.md":
            assert (
                ROOT / "docs" / "domains" / "governance" / "authority" / name
            ).is_file()
        else:
            assert (ROOT / "docs" / "authority" / name).is_file()


def test_loose_docs_use_the_approved_labeled_destinations() -> None:
    missing = sorted(path for path in APPROVED_DOC_PATHS if not (ROOT / path).is_file())
    assert missing == []


def test_docs_map_links_every_top_level_directory() -> None:
    text = (ROOT / "docs" / "DOCS-README.md").read_text(encoding="utf-8")
    missing = sorted(
        path.name
        for path in (ROOT / "docs").iterdir()
        if path.is_dir() and f"]({path.name}/)" not in text
    )
    assert missing == []


def test_moved_markdown_documents_have_no_dangling_relative_links() -> None:
    moved = {
        "docs/DOCS-README.md",
        "docs/domains/governance/authority/GOAL.md",
        *(f"docs/authority/{name}" for name in AUTHORITY_NAMES if name != "GOAL.md"),
        *APPROVED_DOC_PATHS,
    }
    failures = []
    for relative in sorted(moved):
        document = ROOT / relative
        if not document.is_file() or document.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (document.parent / target).resolve().exists():
                failures.append(f"{relative} -> {target}")
    assert failures == [], failures

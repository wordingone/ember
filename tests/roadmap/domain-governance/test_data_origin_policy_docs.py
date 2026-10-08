# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The training-data origin policy lives in the original documents, never in an override file.

Before the first consumption of AI-generated data, the reliability gate requires that
README.md and EMBER-02.md state the current policy in place, that the governing
documents link to that text, and that no docs/authority/operator-override-* file exists.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pytest


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
EMBER_02 = Path("docs/domains/governance/roadmap/milestones/EMBER-02.md")
POLICY_HEADING = "## Training-data origin policy\n"
POLICY_ANCHOR = "EMBER-02.md#training-data-origin-policy"
LINKING_DOCUMENTS = (
    Path("README.md"),
    Path("docs/domains/governance/design/the-actual-stack.md"),
)
README_POLICY_SENTENCE = "Training data is human-sourced first."
# Operative qualifiers carried over from the deleted override file; dropping one would let an
# incomplete denominator, a prospective exception or a first-hour reading count as compliance.
PRESERVED_POLICY_TERMS = (
    "stays unknown until the text\n  loss-bearing targets are counted",
    "No retroactive compliance is claimed.",
    "The reliability seat runs this check in the first hour after consumption\n  stops; a first-hour reading is interim only",
    "is never a completed\n  3-hour retention result.",
)
GOAL = Path("docs/domains/governance/authority/GOAL.md")
# GOAL.md may change only in its governing_surfaces_sha256 hash values (the repository's
# re-pin chain), never in prose: this is the sha256 of GOAL.md with those values blanked.
GOAL_PROSE_SHA256 = "048f696cd3512571b103732315c2fec77eef9610b7758ebd78ec6be990ba3682"
SURFACE_HASH_LINE = re.compile(r'^(\s*"[^"]+": ")[0-9A-Fa-f]{64}(",?)$', re.MULTILINE)


def goal_prose_sha256(text: str) -> str:
    start = text.index('"governing_surfaces_sha256": {')
    end = text.index("}", start)
    block = SURFACE_HASH_LINE.sub(r"\1\2", text[start:end])
    return hashlib.sha256((text[:start] + block + text[end:]).encode("utf-8")).hexdigest()


def policy_document_findings(root: Path) -> list[str]:
    findings: list[str] = []
    overrides = sorted((root / "docs" / "authority").glob("operator-override-*"))
    for path in overrides:
        findings.append(f"override file exists: {path.relative_to(root).as_posix()}")
    ember_02 = (root / EMBER_02).read_text(encoding="utf-8")
    if ember_02.count(POLICY_HEADING) != 1:
        findings.append("EMBER-02.md must carry exactly one training-data origin policy heading")
    if "operator-override" in ember_02:
        findings.append("EMBER-02.md still points at an override file")
    if "Superseded in part, 2026-10-03" in ember_02:
        findings.append("EMBER-02.md still carries a dated supersession note instead of edited text")
    for term in PRESERVED_POLICY_TERMS:
        if term not in ember_02:
            findings.append(f"EMBER-02.md drops a policy qualifier: {term.split()[0]} {term.split()[1]}")
    readme = (root / "README.md").read_text(encoding="utf-8")
    if README_POLICY_SENTENCE not in readme:
        findings.append("README.md does not state the training-data policy")
    if goal_prose_sha256((root / GOAL).read_text(encoding="utf-8")) != GOAL_PROSE_SHA256:
        findings.append("GOAL.md changed outside its governing_surfaces_sha256 hash values")
    for relative in LINKING_DOCUMENTS:
        text = (root / relative).read_text(encoding="utf-8")
        if POLICY_ANCHOR not in text:
            findings.append(f"{relative.as_posix()} does not link to the policy text")
        if "operator-override" in text:
            findings.append(f"{relative.as_posix()} still points at an override file")
    return findings


def _copy_documents(destination: Path) -> None:
    for relative in (EMBER_02, GOAL, *LINKING_DOCUMENTS):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    (destination / "docs" / "authority").mkdir(parents=True, exist_ok=True)


def test_policy_is_stated_in_place_and_no_override_file_exists() -> None:
    assert policy_document_findings(REPO) == []


def test_restored_override_file_refuses(tmp_path: Path) -> None:
    _copy_documents(tmp_path)
    assert policy_document_findings(tmp_path) == []
    (tmp_path / "docs" / "authority" / "operator-override-20261003.md").write_text(
        "# OPERATOR OVERRIDE\n", encoding="utf-8"
    )
    assert policy_document_findings(tmp_path) == [
        "override file exists: docs/authority/operator-override-20261003.md"
    ]


@pytest.mark.parametrize("relative", LINKING_DOCUMENTS, ids=lambda path: path.name)
def test_missing_policy_link_refuses(tmp_path: Path, relative: Path) -> None:
    _copy_documents(tmp_path)
    target = tmp_path / relative
    target.write_text(
        target.read_text(encoding="utf-8").replace(POLICY_ANCHOR, "EMBER-02.md"), encoding="utf-8"
    )
    assert f"{relative.as_posix()} does not link to the policy text" in policy_document_findings(tmp_path)


def test_goal_prose_change_refuses(tmp_path: Path) -> None:
    _copy_documents(tmp_path)
    target = tmp_path / GOAL
    text = target.read_text(encoding="utf-8")
    target.write_text(
        text.replace("deterministic tools are allowed research inputs.",
                     "deterministic tools are allowed research inputs. See the override.", 1),
        encoding="utf-8",
    )
    assert "GOAL.md changed outside its governing_surfaces_sha256 hash values" in policy_document_findings(tmp_path)


def test_goal_surface_hash_change_is_allowed(tmp_path: Path) -> None:
    _copy_documents(tmp_path)
    target = tmp_path / GOAL
    text = target.read_text(encoding="utf-8")
    start = text.index('"README.md": "') + len('"README.md": "')
    target.write_text(text[:start] + "0" * 64 + text[start + 64:], encoding="utf-8")
    assert policy_document_findings(tmp_path) == []


@pytest.mark.parametrize("term", PRESERVED_POLICY_TERMS, ids=("unknown-share", "no-retroactive", "interim-first-hour", "not-a-3-hour-result"))
def test_dropped_policy_qualifier_refuses(tmp_path: Path, term: str) -> None:
    _copy_documents(tmp_path)
    target = tmp_path / EMBER_02
    target.write_text(target.read_text(encoding="utf-8").replace(term, ""), encoding="utf-8")
    assert f"EMBER-02.md drops a policy qualifier: {term.split()[0]} {term.split()[1]}" in policy_document_findings(tmp_path)


def test_restored_dated_note_refuses(tmp_path: Path) -> None:
    _copy_documents(tmp_path)
    target = tmp_path / EMBER_02
    target.write_text(
        target.read_text(encoding="utf-8") + "\n> Superseded in part, 2026-10-03: see policy.\n",
        encoding="utf-8",
    )
    assert (
        "EMBER-02.md still carries a dated supersession note instead of edited text"
        in policy_document_findings(tmp_path)
    )

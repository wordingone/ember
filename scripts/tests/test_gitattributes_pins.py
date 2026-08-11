# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Every exact-path byte-pin in .gitattributes must still name a tracked file.

.gitattributes pins bytes for sha-bearing artifacts, so an orphaned pin is silent:
the pattern matches nothing, the file it was meant to protect quietly falls back to
LF normalization, and the sha it anchors drifts on the next Windows checkout. That
has already happened twice -- the eng-47 pin was anchored to a `research/**`
directory that never existed, and #219's config/ -> configs/ rename orphaned three
pins -- and both were caught by hand after the fact. This test makes a rename that
strands a pin fail loudly instead.

Glob patterns are deliberately out of scope: a `receipts/**` pin that currently
matches nothing is a legitimate forward declaration, whereas an exact path is a
claim that a specific file exists right now.
"""
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES = REPO_ROOT / ".gitattributes"
GLOB_CHARS = set("*?[]")


def exact_path_pins(text: str) -> list[str]:
    """Patterns from .gitattributes that name one literal path (no glob metacharacters)."""
    pins = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern = line.split()[0]
        if GLOB_CHARS & set(pattern):
            continue
        pins.append(pattern)
    return pins


def orphaned_pins(pins, exists) -> list[str]:
    return [pin for pin in pins if not exists(pin)]


def tracked_paths() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {entry for entry in out.split("\0") if entry}


def test_every_exact_path_gitattributes_pin_resolves() -> None:
    pins = exact_path_pins(GITATTRIBUTES.read_text(encoding="utf-8"))
    assert pins, "expected .gitattributes to carry at least one exact-path pin"
    tracked = tracked_paths()

    orphans = orphaned_pins(pins, lambda pin: pin.lstrip("/") in tracked)

    assert not orphans, (
        "these .gitattributes pins name paths that are not tracked; a rename has "
        f"stranded them and their bytes are no longer protected: {orphans}"
    )


def test_orphaned_pin_is_detected() -> None:
    """The checker has teeth: a pin to a path that does not exist must be reported."""
    fixture = "\n".join(
        [
            "# comment line",
            "* text=auto eol=lf",
            "receipts/** -text",
            "docs/authority/GOAL.md -text",
            "config/v0-pretrain-config.json -text",  # the #219 orphan, pre-rename
            "",
        ]
    )
    tracked = {"docs/authority/GOAL.md", "configs/v0-pretrain-config.json"}

    pins = exact_path_pins(fixture)
    orphans = orphaned_pins(pins, lambda pin: pin in tracked)

    assert pins == ["docs/authority/GOAL.md", "config/v0-pretrain-config.json"]
    assert orphans == ["config/v0-pretrain-config.json"]


@pytest.mark.parametrize(
    "pattern", ["*", "receipts/**", "*.sh", "configs/nck-baseline/**", "baseline/**/*.py"]
)
def test_glob_patterns_are_not_treated_as_exact_paths(pattern: str) -> None:
    assert exact_path_pins(f"{pattern} -text") == []

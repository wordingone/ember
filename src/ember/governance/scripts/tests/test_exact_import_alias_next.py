# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Planted regression: no tracked Python file calls an undefined rendered ``_next`` alias.

The exact-local-import renderer rewrote ``next(`` call sites inside rendered root
resolvers into ``_ember_<hash>_next(`` without emitting a binding for that name.
Twenty-one call sites across five modules failed at collection or at first call
(NameError). The builtin ``next`` is the only correct target; this test keeps the
rendered alias from reappearing anywhere in the tracked tree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
ALIAS_NEXT = re.compile(r"_ember_[0-9a-f]{16}_next\(")


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.py"],
        check=True, capture_output=True,
    ).stdout
    return [ROOT / p.decode("utf-8") for p in out.split(b"\0") if p]


def test_no_tracked_python_file_calls_a_rendered_next_alias() -> None:
    offenders = []
    for path in _tracked_python_files():
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALIAS_NEXT.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert offenders == [], f"undefined rendered next aliases: {offenders}"

# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep sibling test-helper imports deterministic under per-file collection."""

from __future__ import annotations

import ast
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parent


def test_sibling_modules_use_package_relative_imports() -> None:
    sibling_modules = {
        path.stem
        for path in TEST_ROOT.glob("*.py")
        if path.name not in {"__init__.py", Path(__file__).name}
    }
    bare_imports: list[str] = []

    for source_path in sorted(TEST_ROOT.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if node.level == 0 and root in sibling_modules:
                    bare_imports.append(f"{source_path.name}:{node.lineno}:{root}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in sibling_modules:
                        bare_imports.append(f"{source_path.name}:{node.lineno}:{root}")

    assert not bare_imports, (
        "bare sibling imports depend on invocation order or sys.path mutation: "
        + ", ".join(bare_imports)
    )

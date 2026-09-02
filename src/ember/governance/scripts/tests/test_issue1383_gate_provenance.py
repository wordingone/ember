#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Behavioral self-provenance regressions for issue #1383."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
TOOLS = (
    ROOT / "src" / "ember" / "governance" / "scripts" / "worktree_lifecycle.py",
    ROOT / "scripts" / "verify_authority_conservation.py",
    ROOT / "scripts" / "check_changed_receipts.py",
)
PROVENANCE = re.compile(
    r"^EMBER_GATE_PROVENANCE path=(?P<path>\S+) sha256=(?P<sha>[0-9a-f]{64}) head=(?P<head>\S+)$"
)
# worktree_lifecycle.py's own banner additionally carries dirty=true/false (#1696):
# whether ITS OWN on-disk bytes are modified vs the committed HEAD version. That field
# is composed onto the banner by worktree_lifecycle.py itself, not by
# gate_provenance.py's shared render_gate_provenance() -- so the other two direct gate
# entrypoints below are unaffected and keep matching the plain PROVENANCE form.
SELF_INTEGRITY_PROVENANCE = re.compile(
    r"^EMBER_GATE_PROVENANCE path=(?P<path>\S+) sha256=(?P<sha>[0-9a-f]{64}) "
    r"head=(?P<head>\S+) dirty=(?P<dirty>true|false)$"
)


def _banner(tool: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-B", str(tool), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stderr.splitlines()[0] if result.stderr else ""


def test_direct_gate_entrypoints_emit_matching_self_provenance() -> None:
    expected_head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    for tool in TOOLS:
        banner = _banner(tool)
        pattern = (
            SELF_INTEGRITY_PROVENANCE if tool.name == "worktree_lifecycle.py" else PROVENANCE
        )
        match = pattern.fullmatch(banner)
        assert match, (tool, banner)
        assert match.group("path") == tool.relative_to(ROOT).as_posix()
        assert match.group("sha") == hashlib.sha256(tool.read_bytes()).hexdigest()
        assert match.group("head") == expected_head
        if tool.name == "worktree_lifecycle.py":
            assert match.group("dirty") == "false", (
                "the checked-out worktree_lifecycle.py must match its own committed "
                "HEAD in a clean test/CI run"
            )


def test_different_tool_bytes_have_visibly_different_first_line(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    # issue2015 exact-local-import:src/ember/governance/scripts/gate_provenance.py
    import importlib.util as _ember_a3c9c2790e3cf404_importlib
    import sys as _ember_a3c9c2790e3cf404_sys
    from pathlib import Path as _ember_a3c9c2790e3cf404_Path
    _ember_a3c9c2790e3cf404_path = _ember_a3c9c2790e3cf404_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'gate_provenance.py')
    if not _ember_a3c9c2790e3cf404_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/gate_provenance.py')
    _ember_a3c9c2790e3cf404_aliases = ('_ember_issue2015_a3c9c2790e3cf404', 'gate_provenance', 'scripts.gate_provenance', 'src.ember.governance.scripts.gate_provenance')
    _ember_a3c9c2790e3cf404_existing = []
    for _ember_a3c9c2790e3cf404_alias in _ember_a3c9c2790e3cf404_aliases:
        _ember_a3c9c2790e3cf404_candidate = _ember_a3c9c2790e3cf404_sys.modules.get(_ember_a3c9c2790e3cf404_alias)
        if _ember_a3c9c2790e3cf404_candidate is not None and all(_ember_a3c9c2790e3cf404_candidate is not item for item in _ember_a3c9c2790e3cf404_existing):
            _ember_a3c9c2790e3cf404_existing.append(_ember_a3c9c2790e3cf404_candidate)
    if len(_ember_a3c9c2790e3cf404_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/gate_provenance.py')
    if _ember_a3c9c2790e3cf404_existing:
        _ember_a3c9c2790e3cf404_module = _ember_a3c9c2790e3cf404_existing[0]
        _ember_a3c9c2790e3cf404_observed = getattr(_ember_a3c9c2790e3cf404_module, '__file__', None)
        if _ember_a3c9c2790e3cf404_observed is None or _ember_a3c9c2790e3cf404_Path(_ember_a3c9c2790e3cf404_observed).resolve() != _ember_a3c9c2790e3cf404_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/gate_provenance.py')
    else:
        _ember_a3c9c2790e3cf404_spec = _ember_a3c9c2790e3cf404_importlib.spec_from_file_location('_ember_issue2015_a3c9c2790e3cf404', _ember_a3c9c2790e3cf404_path)
        if _ember_a3c9c2790e3cf404_spec is None or _ember_a3c9c2790e3cf404_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/gate_provenance.py')
        _ember_a3c9c2790e3cf404_module = _ember_a3c9c2790e3cf404_importlib.module_from_spec(_ember_a3c9c2790e3cf404_spec)
        for _ember_a3c9c2790e3cf404_alias in _ember_a3c9c2790e3cf404_aliases:
            _ember_a3c9c2790e3cf404_prior = _ember_a3c9c2790e3cf404_sys.modules.get(_ember_a3c9c2790e3cf404_alias)
            if _ember_a3c9c2790e3cf404_prior is not None and _ember_a3c9c2790e3cf404_prior is not _ember_a3c9c2790e3cf404_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/gate_provenance.py')
            _ember_a3c9c2790e3cf404_sys.modules[_ember_a3c9c2790e3cf404_alias] = _ember_a3c9c2790e3cf404_module
        try:
            _ember_a3c9c2790e3cf404_spec.loader.exec_module(_ember_a3c9c2790e3cf404_module)
        except BaseException:
            for _ember_a3c9c2790e3cf404_alias in _ember_a3c9c2790e3cf404_aliases:
                if _ember_a3c9c2790e3cf404_sys.modules.get(_ember_a3c9c2790e3cf404_alias) is _ember_a3c9c2790e3cf404_module:
                    _ember_a3c9c2790e3cf404_sys.modules.pop(_ember_a3c9c2790e3cf404_alias, None)
            raise
    for _ember_a3c9c2790e3cf404_alias in _ember_a3c9c2790e3cf404_aliases:
        _ember_a3c9c2790e3cf404_prior = _ember_a3c9c2790e3cf404_sys.modules.get(_ember_a3c9c2790e3cf404_alias)
        if _ember_a3c9c2790e3cf404_prior is not None and _ember_a3c9c2790e3cf404_prior is not _ember_a3c9c2790e3cf404_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/gate_provenance.py')
        _ember_a3c9c2790e3cf404_sys.modules[_ember_a3c9c2790e3cf404_alias] = _ember_a3c9c2790e3cf404_module
    render_gate_provenance = getattr(_ember_a3c9c2790e3cf404_module, 'render_gate_provenance')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/gate_provenance.py

    first = tmp_path / "gate-a.py"
    second = tmp_path / "gate-b.py"
    first.write_bytes(b"print('a')\n")
    second.write_bytes(b"print('b')\n")

    first_line = render_gate_provenance(first, repo_root=tmp_path)
    second_line = render_gate_provenance(second, repo_root=tmp_path)
    assert first_line != second_line
    assert "path=gate-a.py" in first_line
    assert "path=gate-b.py" in second_line
    assert hashlib.sha256(first.read_bytes()).hexdigest() in first_line
    assert hashlib.sha256(second.read_bytes()).hexdigest() in second_line
    assert first_line.endswith(" head=UNAVAILABLE")
    assert second_line.endswith(" head=UNAVAILABLE")

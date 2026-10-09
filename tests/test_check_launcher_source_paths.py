# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds and greens for check_launcher_source_paths.py (#1116 stale launcher paths)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "check_launcher_source_paths", ROOT / "src/ember/infrastructure/tools/check_launcher_source_paths.py")
lint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lint)


def _hits(name: str, text: str) -> list[str]:
    return lint.scan_text(name, text)


def test_red_powershell_launcher_old_source_root():
    # The exact line that made a clean checkout of master unable to start Ember.
    assert _hits("prepare.ps1", '    $sourceRoot = Join-Path $repositoryRoot "tools\\ember-cli\\src"\n')


def test_red_installer_old_marker_directory():
    assert _hits("install.ps1", 'New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools\\ember-cli") | Out-Null\n')


def test_red_ts_join_old_cli_source():
    assert _hits("a.ts", 'const sourceRoot = join(repoRoot, "tools", "ember-cli", "src");\n')


def test_red_ts_multiline_join_old_governance_script():
    assert _hits("a.ts", 'resolve(\n  root,\n  "scripts",\n  "ember_restart",\n  "cli_seat.py",\n);\n')


def test_red_ts_old_launch_packet():
    assert _hits("a.ts", 'join(repoRoot, "tools", "ember-restart-3b", "launch_packet.py")\n')


def test_green_canonical_paths():
    text = (
        'join(repoRoot, "src", "ember", "infrastructure", "tools", "ember-cli", "src")\n'
        'resolve(\n  root,\n  "src",\n  "ember",\n  "governance",\n  "scripts",\n  "ember_restart",\n)\n'
        '$s = Join-Path $r "src\\ember\\infrastructure\\tools\\ember-cli\\src"\n'
    )
    assert not _hits("a.ts", text.split("$s")[0]) and not _hits("a.ps1", "$s" + text.split("$s")[1])


def test_green_runtime_state_path_is_not_a_source_path():
    assert not _hits("a.ts", 'join(repoRoot, "tools", "ember-cli", "state", "planned-outage.json")\n')


def test_green_comment_and_exempt_fallback():
    assert not _hits("a.ts", '// Reads tools/ember-cli/state and join("tools", "ember-cli")\n')
    assert not _hits("a.py", 'legacy = os.path.join(root, "tools", "ember-restart-3b")  # launcher-paths: legacy-fallback\n')


def test_green_backslash_prose_outside_windows_shell_files():
    assert not _hits("a.py", '    "tools\\ember-cli\\src\\main.ts"` (round 4 probe)\n')


def test_repository_is_clean():
    assert lint.main([str(ROOT)]) == 0

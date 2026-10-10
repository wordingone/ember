# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds and greens for check_launcher_source_paths.py (#1116 stale launcher paths)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
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


STALE = 'const sourceRoot = join(repoRoot, "tools", "ember-cli", "src");\n'
CANONICAL = 'const sourceRoot = join(repoRoot, "src", "ember", "infrastructure", "tools", "ember-cli", "src");\n'


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                   **lint._hidden())


def _subject(tmp_path: Path, staged: str, working: str) -> Path:
    """A separate subject repository whose index and working tree carry different launcher bytes."""
    root = tmp_path / "subject"
    root.mkdir()
    _git(root, "init", "-q")
    launcher = root / "launcher.ts"
    launcher.write_text(staged, encoding="utf-8", newline="\n")
    _git(root, "add", "launcher.ts")
    launcher.write_text(working, encoding="utf-8", newline="\n")
    return root


def test_staged_scope_reads_the_index_not_the_working_tree(tmp_path):
    # Vera 76863 R3: stale bytes staged, canonical bytes in the working tree. The staged gate must refuse.
    subject = _subject(tmp_path, staged=STALE, working=CANONICAL)
    assert lint.main(["--staged", str(subject)]) == 1
    assert lint.main([str(subject)]) == 0  # the working tree alone would have passed


def test_working_scope_reads_the_working_tree_not_the_index(tmp_path):
    # Reciprocal control: canonical staged, stale working: only the working-tree gate refuses.
    subject = _subject(tmp_path, staged=CANONICAL, working=STALE)
    assert lint.main([str(subject)]) == 1
    assert lint.main(["--staged", str(subject)]) == 0


def test_the_kernel_checker_judges_the_subject_root_it_is_given(tmp_path):
    # The checker lives in this (clean) kernel tree; a stale subject must still be refused, and
    # the clean kernel tree itself passes: the verdict follows the bytes passed, never the kernel.
    subject = _subject(tmp_path, staged=STALE, working=STALE)
    assert lint.main([str(subject)]) == 1 and lint.main(["--staged", str(subject)]) == 1
    assert lint.main([str(ROOT)]) == 0


def test_repo_guard_passes_the_subject_root_and_the_staged_scope():
    guard = (ROOT / "tools" / "repo-guard.sh").read_text(encoding="utf-8")
    block = guard[guard.index("3c2. launcher source paths"):guard.index("LAUNCHER_PATHS_RC=$?")]
    assert '"${LAUNCHER_PATHS_SCOPE[@]}" "$SUBJECT_ROOT"' in block
    assert 'LAUNCHER_PATHS_SCOPE=(--staged)' in block and '"$KERNEL_ROOT" 2>&1' not in block


def test_every_git_child_is_created_without_a_console_window(monkeypatch, tmp_path):
    # Vera 76863 R2: the lint's own git children carry CREATE_NO_WINDOW and a hidden STARTUPINFO.
    seen = []
    real = subprocess.run

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(lint.subprocess, "run", spy)
    subject = _subject(tmp_path, staged=CANONICAL, working=CANONICAL)
    seen.clear()
    assert lint.main(["--staged", str(subject)]) == 0
    assert len(seen) == 2  # ls-files and one cat-file --batch
    for kwargs in seen:
        assert kwargs["capture_output"] is True
        if sys.platform == "win32":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
            assert kwargs["startupinfo"].wShowWindow == 0


def test_a_failed_git_query_is_an_error_never_a_clean_pass(tmp_path):
    # Fail-closed: a root that is not a repository must not read as zero files and pass.
    assert lint.main([str(tmp_path)]) == 2
    assert lint.main(["--staged", str(tmp_path)]) == 2

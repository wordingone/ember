# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression: a hook's Git environment must not select a probe's repository.

Only disposable repositories beneath pytest's temporary directory are written.
No operator worktree, branch, registry, or hook configuration is changed.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "worktree_lifecycle.py"
_SPEC = importlib.util.spec_from_file_location("worktree_hook_context_subject", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
subject = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = subject
_SPEC.loader.exec_module(subject)


def fixture_git(root, *args):
    """Fixture construction is explicitly isolated from the calling shell."""
    env = dict(os.environ)
    for key in subject._GIT_DISCOVERY_ENV_VARS:
        env.pop(key, None)
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
        timeout=10, check=True, env=env,
    )


@pytest.fixture
def repositories(tmp_path, monkeypatch):
    for key in subject._GIT_DISCOVERY_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    # Empty config/template keep user filters and default hooks out of fixtures.
    config = tmp_path / "empty-config"
    config.write_text("", encoding="utf-8")
    template = tmp_path / "empty-template"
    template.mkdir()
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))
    source, target = tmp_path / "hook-source", tmp_path / "probe-target"
    for root, name in ((source, "source-only.txt"), (target, "target-only.txt")):
        root.mkdir()
        fixture_git(root, "init", "--quiet")
        (root / name).write_text(name + "\n", encoding="utf-8")
        fixture_git(root, "add", "--", name)
    return source, target


def hook_context(monkeypatch, source, *, work_tree=False):
    monkeypatch.setenv("GIT_DIR", str(source / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(source / ".git" / "index"))
    if work_tree:
        monkeypatch.setenv("GIT_WORK_TREE", str(source))


def test_probe_reads_target_index_not_hook_index(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    result = subject.run_git(target, ["ls-files", "--cached"])
    assert result.stdout.splitlines() == ["target-only.txt"]


def test_probe_reads_target_staged_changes(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    result = subject.run_git(target, ["diff", "--cached", "--name-only"])
    assert result.stdout.splitlines() == ["target-only.txt"]


def test_probe_worktree_is_the_explicit_target(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source, work_tree=True)
    result = subject.run_git(target, ["rev-parse", "--show-toplevel"])
    assert Path(result.stdout.strip()).resolve() == target.resolve()


def test_probe_does_not_report_hook_files_as_missing(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    result = subject.run_git(target, ["ls-files", "--modified"])
    assert result.stdout == ""


def test_target_addition_is_not_hidden_by_hook_index(repositories, monkeypatch):
    source, target = repositories
    # Source and target give a deliberately contradictory answer for this path.
    (source / "new-in-target.txt").write_text("already tracked at source\n", encoding="utf-8")
    fixture_git(source, "add", "--", "new-in-target.txt")
    (target / "new-in-target.txt").write_text("not tracked at target\n", encoding="utf-8")
    hook_context(monkeypatch, source)
    result = subject.run_git(target, ["ls-files", "--others", "--exclude-standard"])
    assert "new-in-target.txt" in result.stdout.splitlines()


def test_parent_environment_and_source_index_remain_untouched(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    before_env = dict(os.environ)
    before_index = (source / ".git" / "index").read_bytes()
    subject.run_git(target, ["ls-files", "--cached"])
    assert dict(os.environ) == before_env
    assert (source / ".git" / "index").read_bytes() == before_index


def test_clean_target_is_still_readable(repositories):
    _, target = repositories
    assert subject.run_git(target, ["ls-files"]).stdout.splitlines() == ["target-only.txt"]


def test_check_false_preserves_git_failure(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    result = subject.run_git(target, ["show", ":not-present.txt"], check=False)
    assert result.returncode != 0
    assert result.stderr.strip()


def test_check_true_still_refuses_git_failure(repositories, monkeypatch):
    source, target = repositories
    hook_context(monkeypatch, source)
    with pytest.raises(subject.LifecycleError) as caught:
        subject.run_git(target, ["show", ":not-present.txt"])
    assert caught.value.code == "GIT_ERROR"


def test_subprocess_only_loses_repository_discovery_variables(monkeypatch, tmp_path):
    for name in subject._GIT_DISCOVERY_ENV_VARS:
        monkeypatch.setenv(name, "inherited-hook-setting")
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("EMBER_GPU_LOCK_PATH", "preserved-lock-setting")
    original_env = dict(os.environ)
    seen = {}

    def capture_run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    monkeypatch.setattr(subject.subprocess, "run", capture_run)
    subject.run_git(tmp_path, ["status", "--short"])
    assert "env" in seen, "run_git must pass a cleaned child environment"
    expected = {k: v for k, v in original_env.items() if k not in subject._GIT_DISCOVERY_ENV_VARS}
    assert seen["env"] == expected
    assert dict(os.environ) == original_env


def test_actual_git_hook_inspects_target_without_changing_source(repositories):
    """Exercise Git's real hook launcher, not just an injected Python environment."""
    import shlex

    source, target = repositories
    hooks = source / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    witness = source.parent / "hook-probe-output.txt"
    program = (
        "import os,sys;from pathlib import Path;"
        f"sys.path.insert(0,{str(SCRIPT.parent)!r});"
        "import worktree_lifecycle as m;"
        "assert os.environ.get('GIT_DIR');"
        f"Path({str(witness)!r}).write_text(m.run_git(Path({str(target)!r}),['ls-files']).stdout,encoding='utf-8')"
    )
    command = " ".join(shlex.quote(x) for x in (str(Path(sys.executable).as_posix()), "-B", "-c", program))
    hook = hooks / "pre-commit"
    hook.write_bytes(("#!/bin/sh\nexec " + command + "\n").encode("utf-8"))
    hook.chmod(0o755)
    before = (source / ".git" / "index").read_bytes()
    env = dict(os.environ)
    env["GIT_DIR"] = str(source / ".git")
    env["GIT_INDEX_FILE"] = str(source / ".git" / "index")
    result = subprocess.run(
        ["git", "-C", str(source), "-c", "core.hooksPath=" + hooks.as_posix(),
         "hook", "run", "pre-commit"],
        capture_output=True, text=True, encoding="utf-8", timeout=10, check=True, env=env,
    )
    assert witness.read_text(encoding="utf-8").splitlines() == ["target-only.txt"]
    assert (source / ".git" / "index").read_bytes() == before

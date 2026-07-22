# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*args], cwd=cwd, text=True, capture_output=True, encoding="utf-8"
    )
    if check and result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, cwd=repo, check=check)


def lifecycle(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(SCRIPT), "--repo", str(repo), *args, cwd=repo, check=check)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.name", "Ember Test")
    git(repo, "config", "user.email", "ember@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-m", "seed")
    return repo


def state_path(repo: Path) -> Path:
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common) / "ember-worktree-lifecycle.json"


def test_install_snapshots_legacy_worktrees_and_sets_target_floor(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    legacy = tmp_path / "legacy"
    git(repo, "worktree", "add", "-b", "legacy", str(legacy))

    result = lifecycle(repo, "install", "--target", "3")
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert state["version"] == 1
    assert state["target"] == 3
    assert state["ceiling"] == 3
    assert len(state["legacy_paths"]) == 2
    assert state["managed"] == {}


def test_audit_rejects_raw_unmanaged_worktree_after_install(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    raw = tmp_path / "raw"
    git(repo, "worktree", "add", "-b", "raw", str(raw))

    result = lifecycle(repo, "audit", check=False)

    assert result.returncode == 2
    assert "UNMANAGED_WORKTREE" in result.stderr
    assert str(raw.resolve()) in result.stderr


def test_audit_ratchets_ceiling_down_after_verified_removal(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    git(repo, "worktree", "add", "-b", "first", str(first))
    git(repo, "worktree", "add", "-b", "second", str(second))
    lifecycle(repo, "install", "--target", "1")
    git(repo, "worktree", "remove", str(second))

    lifecycle(repo, "audit", "--ratchet")
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert state["ceiling"] == 2
    assert str(second.resolve()).casefold() not in state["legacy_paths"]


def test_create_registers_custody_and_refuses_growth_at_ceiling(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    managed = tmp_path / "managed"

    lifecycle(
        repo,
        "create",
        "--path",
        str(managed),
        "--branch",
        "managed",
        "--owner",
        "founder-one",
        "--purpose",
        "bounded-test",
        "--expires",
        "2099-01-01",
    )
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    key = str(managed.resolve()).casefold()
    assert state["managed"][key]["owner"] == "founder-one"
    assert state["managed"][key]["purpose"] == "bounded-test"

    refused = lifecycle(
        repo,
        "create",
        "--path",
        str(tmp_path / "overflow"),
        "--branch",
        "overflow",
        "--owner",
        "founder-one",
        "--purpose",
        "must-refuse",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert refused.returncode == 2
    assert "WORKTREE_CEILING" in refused.stderr
    assert not (tmp_path / "overflow").exists()


def test_retire_refuses_dirty_worktree_without_force(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    managed = tmp_path / "managed"
    lifecycle(
        repo,
        "create",
        "--path",
        str(managed),
        "--branch",
        "managed",
        "--owner",
        "founder-one",
        "--purpose",
        "dirty-test",
        "--expires",
        "2099-01-01",
    )
    (managed / "untracked.bin").write_bytes(b"do not delete")

    result = lifecycle(repo, "retire", "--path", str(managed), check=False)

    assert result.returncode == 2
    assert "DIRTY_WORKTREE" in result.stderr
    assert managed.exists()
    assert (managed / "untracked.bin").read_bytes() == b"do not delete"


def test_retire_archives_detached_head_and_ratchets(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    detached = tmp_path / "detached"
    git(repo, "worktree", "add", "--detach", str(detached), "HEAD")
    head = git(detached, "rev-parse", "HEAD").stdout.strip()
    lifecycle(repo, "install", "--target", "1")

    result = lifecycle(repo, "retire", "--path", str(detached))
    payload = json.loads(result.stdout)
    archived = git(repo, "rev-parse", payload["archive_ref"]).stdout.strip()
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert archived == head
    assert not detached.exists()
    assert state["ceiling"] == 1


def test_hooks_and_agents_require_lifecycle_guard() -> None:
    pre_commit = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    pre_push = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    invocation = 'python "$ROOT/scripts/worktree_lifecycle.py" audit --quiet'
    assert invocation in pre_commit
    assert invocation in pre_push
    assert "scripts/worktree_lifecycle.py create" in agents
    assert "scripts/worktree_lifecycle.py retire" in agents
    assert "Raw `git worktree add` and recursive worktree deletion are forbidden" in agents

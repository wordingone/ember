# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT = REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "worktree_lifecycle.py"


def run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, encoding="utf-8")
    if check and result.returncode:
        raise AssertionError(f"{args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-b", "master"], repo)
    run(["git", "config", "user.name", "Ember Test"], repo)
    run(["git", "config", "user.email", "ember@example.invalid"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    run(["git", "add", "seed.txt"], repo)
    run(["git", "commit", "-m", "seed"], repo)
    return repo


def lifecycle(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        repo,
        check=check,
    )


def state_path(repo: Path) -> Path:
    common = run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repo
    ).stdout.strip()
    return Path(common) / "ember-worktree-lifecycle.json"


def test_audit_fails_closed_on_malformed_state(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install")
    state_path(repo).write_text("{not-json", encoding="utf-8")

    result = lifecycle(repo, "audit", check=False)

    assert result.returncode == 2
    assert "MALFORMED_STATE" in result.stderr


def test_audit_fails_closed_on_expired_managed_lease(tmp_path: Path) -> None:
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
        "founder-two",
        "--purpose",
        "expiry-test",
        "--expires",
        "2099-01-01",
    )
    path = state_path(repo)
    state = json.loads(path.read_text(encoding="utf-8"))
    only_record = next(iter(state["managed"].values()))
    only_record["expires"] = "2000-01-01"
    path.write_text(json.dumps(state), encoding="utf-8")

    result = lifecycle(repo, "audit", check=False)

    assert result.returncode == 2
    assert "EXPIRED_WORKTREE" in result.stderr

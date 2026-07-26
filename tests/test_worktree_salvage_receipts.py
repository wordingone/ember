# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "worktree_salvage_receipts.py"
LIFECYCLE = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, encoding="utf-8")
    if check and result.returncode:
        raise AssertionError(f"{args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], repo)


def make_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    run(["git", "init", "--bare", "-b", "master", str(origin)], tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.name", "Ember Test")
    git(repo, "config", "user.email", "ember@example.invalid")
    git(repo, "remote", "add", "origin", str(origin))
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-m", "seed")
    (origin / "objects" / "info" / "alternates").write_text(
        str(repo / ".git" / "objects").replace("\\", "/") + "\n",
        encoding="utf-8",
        newline="\n",
    )
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(origin, "update-ref", "refs/heads/master", head)
    git(repo, "update-ref", "refs/remotes/origin/master", head)
    return repo


def invoke(repo: Path, receipt_dir: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--receipt-dir",
            str(receipt_dir),
        ],
        repo,
        check=check,
    )


def receipts(receipt_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(receipt_dir.glob("*.json"))
        if path.name != "census.json"
    ]


def by_path(rows: list[dict[str, object]], path: Path) -> dict[str, object]:
    wanted = str(path.resolve()).casefold()
    return next(row for row in rows if str(row["worktree"]["canonical_path"]).casefold() == wanted)


def load_module():
    spec = importlib.util.spec_from_file_location("worktree_salvage_receipts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_clean_worktrees_get_exact_reconstruction_receipts(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    child = tmp_path / "child"
    git(repo, "worktree", "add", "-b", "child", str(child))
    (child / "child.txt").write_text("remote child\n", encoding="utf-8")
    git(child, "add", "child.txt")
    git(child, "commit", "-m", "remote child")
    child_head = git(child, "rev-parse", "HEAD").stdout.strip()
    git(tmp_path / "origin.git", "update-ref", "refs/heads/child", child_head)
    git(repo, "update-ref", "refs/remotes/origin/child", child_head)
    run([sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"], repo)
    out = tmp_path / "receipts"

    result = invoke(repo, out)
    summary = json.loads(result.stdout)
    rows = receipts(out)
    child_row = by_path(rows, child)

    assert summary["status"] == "PASS"
    assert summary["worktree_count"] == 2
    assert child_row["schema_version"] == "ember-worktree-salvage-receipt/v1"
    assert child_row["registration_class"] == "LEGACY"
    assert child_row["disposition"] == "CLEAN_REMOTE_RECONSTRUCTIBLE"
    assert child_row["durability"]["status"] == "PROVEN_REACHABLE"
    assert child_row["durability"]["head_reachable_from"] == [
        "refs/heads/child"
    ]
    assert child_row["retirement_authority"] == "NOT_GRANTED"
    assert child_row["dirty_bytes"] == []
    assert child_row["snapshot"]["stable"] is True
    assert child_row["worktree"]["head_sha"] == git(child, "rev-parse", "HEAD").stdout.strip()
    assert child_row["worktree"]["branch"] == "refs/heads/child"
    assert child_row["reconstruction"]["argv"] == [
        "git",
        "worktree",
        "add",
        "--detach",
        "<destination>",
        child_row["worktree"]["head_sha"],
    ]


def test_dirty_local_bytes_are_hashed_and_force_keep(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run([sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"], repo)
    (repo / "seed.txt").write_text("changed\n", encoding="utf-8")
    seed_bytes = (repo / "seed.txt").read_bytes()
    (repo / "untracked.bin").write_bytes(b"\x00ember-local\xff")
    out = tmp_path / "receipts"

    invoke(repo, out)
    row = by_path(receipts(out), repo)
    entries = {entry["path"]: entry for entry in row["dirty_bytes"]}

    assert row["disposition"] == "KEEP_DIRTY_LOCAL_BYTES"
    assert row["retirement_authority"] == "NOT_GRANTED"
    assert entries["seed.txt"]["working_tree_sha256"] == hashlib.sha256(seed_bytes).hexdigest()
    assert entries["seed.txt"]["working_tree_bytes"] == len(seed_bytes)
    assert entries["untracked.bin"]["working_tree_sha256"] == hashlib.sha256(
        b"\x00ember-local\xff"
    ).hexdigest()
    assert entries["untracked.bin"]["index_entries"] == []
    assert row["snapshot"]["stable"] is True


def test_clean_local_only_head_is_not_called_reconstructible(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    child = tmp_path / "local-only"
    git(repo, "worktree", "add", "-b", "local-only", str(child))
    (child / "local-only.txt").write_text("local only\n", encoding="utf-8")
    git(child, "add", "local-only.txt")
    git(child, "commit", "-m", "local only")
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    out = tmp_path / "receipts"

    summary = load_module().capture_all(repo, out)
    row = by_path(receipts(out), child)

    assert summary["status"] == "PASS"
    assert row["snapshot"]["dirty_path_count"] == 0
    assert row["disposition"] == "KEEP_CLEAN_LOCAL_ONLY"
    assert row["durability"]["status"] == "PROVEN_LOCAL_ONLY"
    assert row["durability"]["head_reachable_from"] == []



def test_stale_remote_mirror_refuses_clean_reconstructibility(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    child = tmp_path / "remote-unproven"
    git(repo, "worktree", "add", "-b", "remote-unproven", str(child))
    (child / "remote-unproven.txt").write_text("unproven\n", encoding="utf-8")
    git(child, "add", "remote-unproven.txt")
    git(child, "commit", "-m", "remote unproven")
    git(repo, "update-ref", "-d", "refs/remotes/origin/master")
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    out = tmp_path / "receipts"

    summary = load_module().capture_all(repo, out)
    row = by_path(receipts(out), child)

    assert summary["status"] == "PARTIAL_UNRESOLVED"
    assert summary["unresolved_count"] == 1
    assert row["snapshot"]["dirty_path_count"] == 0
    assert row["disposition"] == "KEEP_CLEAN_REMOTE_UNPROVEN"
    assert row["durability"]["status"] == "UNRESOLVED_STALE_REMOTE_MIRROR"
    assert row["durability"]["head_reachable_from"] == []
    assert row["durability"]["all_remote_heads_exactly_mirrored_locally"] is False


def test_missing_live_remote_snapshot_fails_before_publication(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    git(repo, "remote", "remove", "origin")
    out = tmp_path / "receipts"

    result = invoke(repo, out, check=False)

    assert result.returncode == 2
    assert "REMOTE_HEADS_UNAVAILABLE" in result.stderr
    assert not out.exists()

def test_managed_registration_is_bound_from_lifecycle_state(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run([sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"], repo)
    managed = tmp_path / "managed"
    run(
        [
            sys.executable,
            str(LIFECYCLE),
            "--repo",
            str(repo),
            "create",
            "--path",
            str(managed),
            "--branch",
            "managed",
            "--owner",
            "receipt-owner",
            "--purpose",
            "receipt-test",
            "--expires",
            "2099-01-01",
        ],
        repo,
    )
    out = tmp_path / "receipts"

    invoke(repo, out)
    row = by_path(receipts(out), managed)

    assert row["registration_class"] == "MANAGED"
    assert row["lifecycle"]["owner"] == "receipt-owner"
    assert row["lifecycle"]["purpose"] == "receipt-test"
    assert row["lifecycle"]["expires"] == "2099-01-01"


def test_dirty_paths_use_one_batch_index_query_per_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    run([sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"], repo)
    (repo / "seed.txt").write_text("dirty\n", encoding="utf-8")
    (repo / "second.txt").write_text("tracked\n", encoding="utf-8")
    run(["git", "add", "second.txt"], repo)
    run(["git", "commit", "-m", "second"], repo)
    (repo / "second.txt").write_text("also dirty\n", encoding="utf-8")
    (repo / "untracked-a.bin").write_bytes(b"a")
    (repo / "untracked-b.bin").write_bytes(b"b")
    out = tmp_path / "receipts"
    module = load_module()
    original = module.run_git
    calls: list[list[str]] = []

    def record_git(worktree: Path, args: list[str], **kwargs):
        if args[:2] == ["ls-files", "--stage"]:
            calls.append(args)
        return original(worktree, args, **kwargs)

    monkeypatch.setattr(module, "run_git", record_git)

    summary = module.capture_all(repo, out)

    assert summary["status"] == "PASS"
    assert calls == [["ls-files", "--stage", "-z"]] * 2


def test_snapshot_drift_emits_non_authorizing_refusal_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    run([sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"], repo)
    (repo / "seed.txt").write_text("dirty\n", encoding="utf-8")
    out = tmp_path / "receipts"
    module = load_module()
    original = module.hash_regular_file
    mutated = False

    def mutate_after_hash(path: Path):
        nonlocal mutated
        result = original(path)
        if path.name == "seed.txt" and not mutated:
            mutated = True
            path.write_text("drifted\n", encoding="utf-8")
        return result

    monkeypatch.setattr(module, "hash_regular_file", mutate_after_hash)

    summary = module.capture_all(repo, out)
    row = by_path(receipts(out), repo)

    assert summary["status"] == "PARTIAL_REFUSED"
    assert summary["refused_count"] == 1
    assert row["disposition"] == "REFUSE_INACCESSIBLE"
    assert row["retirement_authority"] == "NOT_GRANTED"
    assert row["refusal"]["code"] == "WORKTREE_DRIFT"
    assert row["snapshot"]["stable"] is False


def test_nested_git_directory_is_bound_as_dirty_local_custody(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    nested = repo / "nested"
    nested.mkdir()
    git(nested, "init", "-b", "master")
    git(nested, "config", "user.name", "Nested Ember Test")
    git(nested, "config", "user.email", "nested@example.invalid")
    (nested / "tracked.txt").write_text("committed\n", encoding="utf-8")
    git(nested, "add", "tracked.txt")
    git(nested, "commit", "-m", "nested seed")
    nested_head = git(nested, "rev-parse", "HEAD").stdout.strip()
    (nested / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    nested_tracked_bytes = (nested / "tracked.txt").read_bytes()
    (nested / "untracked.bin").write_bytes(b"\x00nested-local\xff")
    out = tmp_path / "receipts"

    summary = load_module().capture_all(repo, out)
    row = by_path(receipts(out), repo)
    nested_row = next(item for item in row["dirty_bytes"] if item["path"] == "nested/")

    assert summary["status"] == "PASS"
    assert row["disposition"] == "KEEP_DIRTY_LOCAL_BYTES"
    assert nested_row["working_tree_kind"] == "nested_git_worktree"
    assert nested_row["working_tree_bytes"] is None
    assert nested_row["working_tree_sha256"] is None
    assert nested_row["nested_git"]["head_sha"] == nested_head
    assert nested_row["nested_git"]["branch"] == "refs/heads/master"
    nested_dirty = {
        item["path"]: item for item in nested_row["nested_git"]["dirty_bytes"]
    }
    assert nested_dirty["tracked.txt"]["working_tree_sha256"] == hashlib.sha256(
        nested_tracked_bytes
    ).hexdigest()
    assert nested_dirty["untracked.bin"]["working_tree_sha256"] == hashlib.sha256(
        b"\x00nested-local\xff"
    ).hexdigest()
    assert nested_row["nested_git"]["stable"] is True


def test_read_only_census_locks_only_registry_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    child = tmp_path / "child"
    git(repo, "worktree", "add", "-b", "child", str(child))
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    module = load_module()
    lifecycle = module.load_lifecycle_module()
    original = lifecycle.RepositoryLock
    events: list[str] = []

    class RecordingLock:
        def __init__(self, path: Path):
            self.inner = original(path)

        def __enter__(self):
            result = self.inner.__enter__()
            events.append("enter")
            return result

        def __exit__(self, *args):
            events.append("exit")
            return self.inner.__exit__(*args)

    monkeypatch.setattr(lifecycle, "RepositoryLock", RecordingLock)
    summary = module.capture_all(repo, tmp_path / "receipts")

    assert summary["status"] == "PASS"
    assert events == ["enter", "exit"] * 2


def test_census_refuses_when_lifecycle_registry_is_locked(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run(
        [sys.executable, str(LIFECYCLE), "--repo", str(repo), "install", "--target", "3"],
        repo,
    )
    out = tmp_path / "receipts"
    module = load_module()
    lifecycle = module.load_lifecycle_module()
    common = module.common_dir(repo)

    with lifecycle.RepositoryLock(common / lifecycle.LOCK_NAME):
        try:
            module.capture_all(repo, out)
        except module.SalvageError as exc:
            assert exc.code == "LIFECYCLE_LOCKED"
        else:
            raise AssertionError("salvage census ignored the lifecycle registry lock")

    assert not out.exists()

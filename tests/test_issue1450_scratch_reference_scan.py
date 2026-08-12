# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reference/duplicate advisory scan contract for issue #1450 (``scratch_reference_scan``)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import scratch_reference_scan as scan


def _run_hidden(*args, **kwargs):
    kwargs.setdefault("shell", False)
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(*args, **kwargs)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run_hidden(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    _run_hidden(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    _run_hidden(["git", "-C", str(root), "config", "user.name", "Issue 1450 Test"], check=True)
    return root


def _track(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _run_hidden(["git", "-C", str(root), "add", relative], check=True, capture_output=True)


def _commit(root: Path) -> None:
    _run_hidden(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True, capture_output=True)


def test_grep_child_is_explicitly_shell_free_and_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    observed: dict[str, object] = {}

    def capture_run(*args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(scan.subprocess, "run", capture_run)
    scan._tracked_grep(tmp_path, "x")
    assert observed["shell"] is False
    assert observed["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_grep_treats_no_matches_as_empty_not_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    def capture_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")

    monkeypatch.setattr(scan.subprocess, "run", capture_run)
    assert scan._tracked_grep(tmp_path, "x") == []


def test_grep_raises_on_genuine_git_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    def capture_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(scan.subprocess, "run", capture_run)
    with pytest.raises(scan.ScanError, match="git grep failed"):
        scan._tracked_grep(tmp_path, "x")


def test_scan_separates_path_hits_from_name_only_hits(tmp_path: Path):
    root = _repo(tmp_path)
    # "alpha" is referenced by its literal scratch/ path -- a genuine path pin.
    _track(root, "manifests/consumer.json", '{"depends_on": "scratch/alpha/state.bin"}\n')
    # "beta" is only ever mentioned by bare name -- e.g. a programmatically-built path, the
    # exact shape that missed rung2-optstate's live consumer in the real repository.
    _track(root, "docs/notes.md", "The beta run finished clean.\n")
    _commit(root)

    alpha = scan.scan_entry(root, "alpha")
    assert alpha["path_hits"] == ["manifests/consumer.json"]
    assert alpha["name_hits"] == ["manifests/consumer.json"]
    assert alpha["references"] == ["manifests/consumer.json"]

    beta = scan.scan_entry(root, "beta")
    assert beta["path_hits"] == []
    assert beta["name_hits"] == ["docs/notes.md"]
    assert beta["references"] == ["docs/notes.md"]


def test_scan_excludes_self_referential_census_paths(tmp_path: Path):
    root = _repo(tmp_path)
    _track(root, "receipts/issue-1450/live-scratch-disposition-v1.json", '{"path": "gamma"}\n')
    _track(root, "docs/hygiene/issue-1450-scratch-custody-v1.md", "gamma is a top-level entry.\n")
    _track(root, "manifests/real-consumer.json", '{"uses": "scratch/gamma/out.bin"}\n')
    _commit(root)

    result = scan.scan_entry(root, "gamma")
    assert result["references"] == ["manifests/real-consumer.json"]


def test_scan_excludes_own_tracked_descendants(tmp_path: Path):
    root = _repo(tmp_path)
    _track(root, "scratch/delta/keep.ts", "delta worker\n")
    _commit(root)

    result = scan.scan_entry(root, "delta")
    assert result["references"] == []
    assert result["name_hits"] == []
    assert result["path_hits"] == []


@pytest.mark.parametrize("bad_name", ["", "a/b", "a\\b", ".", ".."])
def test_scan_entry_rejects_unsafe_names(tmp_path: Path, bad_name: str):
    root = _repo(tmp_path)
    _commit_empty(root)
    with pytest.raises(scan.ScanError):
        scan.scan_entry(root, bad_name)


def _commit_empty(root: Path) -> None:
    _track(root, ".keep", "")
    _commit(root)


def _write_tree(root: Path, name: str, files: dict[str, bytes]) -> None:
    base = root / "scratch" / name
    base.mkdir(parents=True)
    for relative, data in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_duplicate_check_proves_identical(tmp_path: Path):
    root = _repo(tmp_path)
    _write_tree(root, "run-a", {"x.bin": b"same bytes", "sub/y.bin": b"more bytes"})
    _write_tree(root, "run-b", {"x.bin": b"same bytes", "sub/y.bin": b"more bytes"})

    result = scan.duplicate_check(root, "run-a", "run-b")
    assert result["result"] == "PROVEN_IDENTICAL"
    assert result["a"]["tree_sha256"] == result["b"]["tree_sha256"]
    assert result["a"]["files"] == result["b"]["files"] == 2


def test_duplicate_check_proves_different_same_file_count(tmp_path: Path):
    root = _repo(tmp_path)
    _write_tree(root, "run-a", {"x.bin": b"same size!"})
    _write_tree(root, "run-b", {"x.bin": b"same size?"})

    result = scan.duplicate_check(root, "run-a", "run-b")
    assert result["result"] == "PROVEN_DIFFERENT"
    assert result["a"]["files"] == result["b"]["files"] == 1


def test_duplicate_check_rejects_identical_names(tmp_path: Path):
    root = _repo(tmp_path)
    _write_tree(root, "run-a", {"x.bin": b"x"})
    with pytest.raises(scan.ScanError, match="distinct"):
        scan.duplicate_check(root, "run-a", "run-a")


def test_write_json_refuses_to_overwrite(tmp_path: Path):
    output = tmp_path / "out.json"
    scan._write_json(output, {"a": 1})
    with pytest.raises(scan.ScanError, match="already exists"):
        scan._write_json(output, {"a": 2})

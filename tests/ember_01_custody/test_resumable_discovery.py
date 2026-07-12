# goal_id: EMBER-01
# workstream_id: EMBER-01B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

from census import (  # noqa: E402
    append_hash_journal,
    build_root_census,
    git_reference_inventory,
    git_repository_summary,
    hash_file_streaming,
    load_hash_journal,
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def init_repo(root: Path) -> str:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def test_streaming_hash_reports_partial_without_accepting_it(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    payload = b"abcdefghij"
    path.write_bytes(payload)
    events: list[dict] = []

    result = hash_file_streaming(path, chunk_size=4, on_progress=events.append)

    assert [row["completed_bytes"] for row in events] == [4, 8, 10]
    assert all(row["state"] == "partial" for row in events)
    assert all("sha256" not in row for row in events)
    assert result == {
        "state": "complete",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "algorithm": "sha256-byte-stream-v1",
    }


def test_journal_ignores_partial_and_truncated_records(tmp_path: Path) -> None:
    journal = tmp_path / "progress.jsonl"
    append_hash_journal(
        journal,
        {"artifact_key": "root:a.bin", "state": "partial", "completed_bytes": 4},
    )
    append_hash_journal(
        journal,
        {
            "artifact_key": "root:b.bin",
            "state": "complete",
            "size_bytes": 5,
            "sha256": "a" * 64,
            "algorithm": "sha256-byte-stream-v1",
        },
    )
    with journal.open("ab") as stream:
        stream.write(b'{"artifact_key":"root:c.bin"')

    completed = load_hash_journal(journal)

    assert set(completed) == {"root:b.bin"}
    assert completed["root:b.bin"]["sha256"] == "a" * 64


def test_bare_repository_and_all_refs_are_inventoryable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    head = init_repo(source)
    (source / "tracked.txt").write_text("two\n", encoding="utf-8")
    git(source, "stash", "push", "-m", "fixture-stash")
    git(source, "update-ref", "refs/pull/7/head", head)
    bare = tmp_path / "mirror.git"
    git(tmp_path, "clone", "--bare", str(source), str(bare))

    summary = git_repository_summary("bare-root", bare)
    refs = git_reference_inventory("source-root", source)

    assert summary["is_bare"] is True
    assert summary["dirty"] is None
    assert refs["ref_names"] == sorted(refs["ref_names"])
    assert "refs/stash" in refs["ref_names"]
    assert "refs/pull/7/head" in refs["ref_names"]
    assert refs["refs_sha256"]


def test_path_aliases_are_preserved_as_explicit_contradiction(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "receipt.json").write_text("{}\n", encoding="utf-8")
    spec = {
        "roots": [
            {"root_id": "alias-a", "required": True, "scan": "files"},
            {"root_id": "alias-b", "required": True, "scan": "files"},
        ]
    }

    result = build_root_census(spec, {"alias-a": root, "alias-b": root})

    aliases = [
        row for row in result["contradictions"] if row["code"] == "root_path_alias"
    ]
    assert aliases == [
        {
            "code": "root_path_alias",
            "root_ids": ["alias-a", "alias-b"],
            "resolution": "unresolved_preserve_all",
        }
    ]
    assert {row["source"]["root_id"] for row in result["artifacts"]} == {
        "alias-a",
        "alias-b",
    }
    assert str(tmp_path) not in json.dumps(result)


def test_registered_worktree_material_hashes_dirty_untracked_and_ignored(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    init_repo(source)
    (source / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git(source, "add", ".gitignore")
    git(source, "commit", "-m", "ignore fixture")
    feature = tmp_path / "feature"
    git(source, "worktree", "add", "-b", "feature", str(feature))
    (feature / "tracked.txt").write_text("modified\n", encoding="utf-8")
    (feature / "new.txt").write_text("untracked\n", encoding="utf-8")
    ignored = feature / "ignored" / "payload.bin"
    ignored.parent.mkdir()
    ignored.write_bytes(b"ignored")
    spec = {
        "roots": [
            {
                "root_id": "worktree-material",
                "required": True,
                "scan": "git_worktree_material_registry",
                "source_root_id": "repo-root",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved_requires_item_review",
            }
        ]
    }

    result = build_root_census(spec, {"repo-root": source})

    relatives = {
        row["source"]["relative_path"] for row in result["artifacts"]
    }
    assert any(path.endswith("/tracked.txt") for path in relatives)
    assert any(path.endswith("/new.txt") for path in relatives)
    assert any(path.endswith("/ignored/payload.bin") for path in relatives)
    assert all("/.git/" not in path for path in relatives)
    root_row = result["roots"][0]
    assert root_row["registered_worktree_count"] == 2
    assert root_row["materialized_worktree_count"] == 2

def test_directory_discovery_classifies_git_bare_and_non_git_bytes(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "material"
    parent.mkdir()
    repo = parent / "ember-repo"
    init_repo(repo)
    bare = parent / "ember-mirror.git"
    git(parent, "clone", "--bare", str(repo), str(bare))
    payload_root = parent / "ember-payload"
    payload_root.mkdir()
    payload = payload_root / "weights.bin"
    payload.write_bytes(b"owned-unresolved")
    unrelated = parent / "unrelated"
    unrelated.mkdir()
    (unrelated / "skip.bin").write_bytes(b"skip")
    spec = {
        "roots": [
            {
                "root_id": "discovery-root",
                "required": True,
                "scan": "directory_discovery",
                "name_patterns": ["ember*"],
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved_requires_item_review",
            }
        ]
    }

    result = build_root_census(spec, {"discovery-root": parent})

    assert "discovered_roots" in result["roots"][0], result
    discovered = result["roots"][0]["discovered_roots"]
    assert [row["name"] for row in discovered] == [
        "ember-mirror.git",
        "ember-payload",
        "ember-repo",
    ]
    assert {row["kind"] for row in discovered} == {
        "bare_git",
        "git_worktree",
        "non_git",
    }
    relatives = {
        row["source"]["relative_path"] for row in result["artifacts"]
    }
    assert "ember-payload/weights.bin" in relatives
    assert not any("unrelated" in path for path in relatives)
    assert any(path.endswith("/git-refs") for path in relatives)

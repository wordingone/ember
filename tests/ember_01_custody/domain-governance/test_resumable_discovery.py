# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

import census as census_module  # noqa: E402

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


def test_completed_journal_never_substitutes_for_current_bytes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "payload.bin"
    artifact.write_bytes(b"new!")
    fixed_ns = 1_700_000_000_000_000_000
    os.utime(artifact, ns=(fixed_ns, fixed_ns))
    journal = tmp_path / "progress.jsonl"
    append_hash_journal(journal, {"artifact_key": "root:payload.bin", "state": "complete", "size_bytes": 4, "mtime_ns_non_authoritative": fixed_ns, "sha256": hashlib.sha256(b"old!").hexdigest(), "algorithm": "sha256-byte-stream-v1"})
    result = build_root_census({"roots": [{"root_id": "root", "required": True, "scan": "files"}]}, {"root": root}, journal)
    assert result["proof_mode"] == "current_bytes_rehashed"
    assert result["artifacts"][0]["sha256"] == hashlib.sha256(b"new!").hexdigest()
    assert result["artifacts"][0]["hash_source"] == "current_bytes"


def test_concurrent_mutation_is_not_admitted_as_a_complete_hash(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "payload.bin"
    artifact.write_bytes(b"before")
    real_hash = census_module.hash_file_streaming
    def mutate_after_hash(path, *args, **kwargs):
        result = real_hash(path, *args, **kwargs)
        path.write_bytes(b"after-different-size")
        return result
    monkeypatch.setattr(census_module, "hash_file_streaming", mutate_after_hash)
    result = build_root_census({"roots": [{"root_id": "root", "required": True, "scan": "files"}]}, {"root": root})
    assert result["artifacts"][0]["sha256"] is None
    assert result["contradictions"][0]["code"] == "artifact_mutated_during_hash"


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


def test_bare_repository_survives_global_membership_verification(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    init_repo(source)
    bare = tmp_path / "mirror.git"
    git(tmp_path, "clone", "--bare", str(source), str(bare))

    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "bare-root",
                    "required": True,
                    "scan": "git_repository",
                }
            ]
        },
        {"bare-root": bare},
    )

    assert result["roots"][0]["git"]["is_bare"] is True
    assert "final_verification_inaccessible" not in {
        row["code"] for row in result["contradictions"]
    }


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
    assert str(tmp_path.resolve()).replace("\\", "/") not in json.dumps(result).replace("\\", "/")


def test_source_root_alias_relation_is_preserved_in_root_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    init_repo(root)
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "logical-worktrees",
                    "source_root_id": "physical-repo",
                    "required": True,
                    "scan": "git_worktree_registry",
                }
            ]
        },
        {"physical-repo": root},
    )

    assert result["roots"][0]["source_root_id"] == "physical-repo"
    assert "normalized_bound_path" not in result["roots"][0]


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


def test_final_worktree_membership_access_failure_is_explicit(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source"
    init_repo(source)
    calls = 0

    def fail_only_during_final_membership(root: Path) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        raise PermissionError(13, "final membership blocked")

    monkeypatch.setattr(
        census_module,
        "_git_material_paths",
        fail_only_during_final_membership,
    )
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "worktree-material",
                    "source_root_id": "physical-repo",
                    "required": True,
                    "scan": "git_worktree_material_registry",
                }
            ]
        },
        {"physical-repo": source},
    )

    errors = [
        row
        for row in result["contradictions"]
        if row["code"] == "final_verification_inaccessible"
    ]
    assert errors == [
        {
            "code": "final_verification_inaccessible",
            "root_id": "worktree-material",
            "verification": "directory_membership",
            "exception": "PermissionError",
            "winerror": None,
            "errno": 13,
            "resolution": "unresolved_retry_snapshot",
        }
    ]


def test_final_discovery_access_failure_is_explicit(
    tmp_path: Path, monkeypatch,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "ember-data").mkdir()

    def fail_final_discovery(*_args, **_kwargs):
        raise PermissionError(13, "final discovery blocked")

    monkeypatch.setattr(
        census_module,
        "_current_discovery_snapshot",
        fail_final_discovery,
    )
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "discovery",
                    "required": True,
                    "scan": "directory_discovery",
                    "name_patterns": ["ember*"],
                }
            ]
        },
        {"discovery": parent},
    )

    assert [
        row
        for row in result["contradictions"]
        if row["code"] == "final_verification_inaccessible"
    ] == [
        {
            "code": "final_verification_inaccessible",
            "root_id": "discovery",
            "verification": "discovery_snapshot",
            "exception": "PermissionError",
            "winerror": None,
            "errno": 13,
            "resolution": "unresolved_retry_snapshot",
        }
    ]


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
    assert all("normalized_path" not in row for row in discovered)
    relatives = {
        row["source"]["relative_path"] for row in result["artifacts"]
    }
    assert "ember-payload/weights.bin" in relatives
    assert not any("unrelated" in path for path in relatives)
    assert any(path.endswith("/git-refs") for path in relatives)


def test_same_physical_file_is_hashed_once_but_keeps_all_logical_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "same.bin").write_bytes(b"same")
    calls = 0
    real_hash = census_module.hash_file_streaming

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(census_module, "hash_file_streaming", counted)
    spec = {
        "roots": [
            {"root_id": "logical-a", "required": True, "scan": "files"},
            {"root_id": "logical-b", "required": True, "scan": "files"},
        ]
    }

    result = build_root_census(
        spec, {"logical-a": root, "logical-b": root}
    )

    # One shared initial hash plus one global final byte-stability verification.
    # Logical aliases must not multiply physical I/O.
    assert calls == 2
    assert len(result["artifacts"]) == 2
    assert result["artifacts"][0]["sha256"] == result["artifacts"][1]["sha256"]


def test_final_byte_stability_pass_runs_after_all_roots_are_discovered(
    tmp_path: Path, monkeypatch,
) -> None:
    early_root = tmp_path / "early"
    late_root = tmp_path / "late"
    early_root.mkdir()
    late_root.mkdir()
    early = early_root / "early.bin"
    late = late_root / "late.bin"
    early.write_bytes(b"early-before")
    late.write_bytes(b"late")
    real_hash = census_module.hash_file_streaming
    late_initial_seen = False

    def mutate_early_while_late_root_is_scanned(path, *args, **kwargs):
        nonlocal late_initial_seen
        result = real_hash(path, *args, **kwargs)
        if Path(path) == late and not late_initial_seen:
            late_initial_seen = True
            early.write_bytes(b"early-after-different-size")
        return result

    monkeypatch.setattr(
        census_module,
        "hash_file_streaming",
        mutate_early_while_late_root_is_scanned,
    )
    spec = {
        "roots": [
            {"root_id": "early", "required": True, "scan": "files"},
            {"root_id": "late", "required": True, "scan": "files"},
        ]
    }

    result = build_root_census(spec, {"early": early_root, "late": late_root})

    assert late_initial_seen is True
    changed = [
        row
        for row in result["contradictions"]
        if row["code"] == "artifact_changed_after_hash"
    ]
    assert changed == [
        {
            "code": "artifact_changed_after_hash",
            "root_id": "early",
            "relative_path": "early.bin",
            "resolution": "unresolved_retry_snapshot",
        }
    ]


def test_final_membership_pass_runs_after_all_roots_are_discovered(
    tmp_path: Path, monkeypatch,
) -> None:
    early_root = tmp_path / "early"
    late_root = tmp_path / "late"
    early_root.mkdir()
    late_root.mkdir()
    (early_root / "early.bin").write_bytes(b"early")
    (late_root / "late.bin").write_bytes(b"late")
    real_discover = census_module._discover_file_rows
    mutated = False

    def mutate_early_when_late_is_discovered(root):
        nonlocal mutated
        result = real_discover(root)
        if Path(root) == late_root and not mutated:
            mutated = True
            (early_root / "added-after-early-pass.bin").write_bytes(b"late addition")
        return result

    monkeypatch.setattr(
        census_module,
        "_discover_file_rows",
        mutate_early_when_late_is_discovered,
    )
    spec = {
        "roots": [
            {"root_id": "early", "required": True, "scan": "files"},
            {"root_id": "late", "required": True, "scan": "files"},
        ]
    }

    result = build_root_census(spec, {"early": early_root, "late": late_root})

    assert mutated is True
    changed = [
        row
        for row in result["contradictions"]
        if row["code"] == "directory_membership_changed_during_scan"
    ]
    assert changed == [
        {
            "code": "directory_membership_changed_during_scan",
            "root_id": "early",
            "resolution": "unresolved_retry_snapshot",
        }
    ]


def test_worktree_ids_are_path_derived_not_ordinal() -> None:
    common = "worktree X:/private/main\nHEAD " + "a" * 40 + "\n\n"
    with_extra = "worktree X:/private/aaa\nHEAD " + "b" * 40 + "\n\n" + common
    first = census_module.parse_worktree_porcelain(common)[0]
    second = next(row for row in census_module.parse_worktree_porcelain(with_extra) if row["normalized_path"] == "X:/private/main")
    assert first["worktree_id"] == second["worktree_id"]


def test_directory_discovery_detects_git_state_change_during_scan(
    tmp_path: Path, monkeypatch,
) -> None:
    parent = tmp_path / "material"
    parent.mkdir()
    repo = parent / "ember-repo"
    init_repo(repo)
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
    real_summary = census_module.git_repository_summary
    calls = 0

    def changing_summary(*args, **kwargs):
        nonlocal calls
        calls += 1
        summary = real_summary(*args, **kwargs)
        if calls > 1:
            summary = {**summary, "status_sha256": "f" * 64}
        return summary

    monkeypatch.setattr(census_module, "git_repository_summary", changing_summary)
    result = build_root_census(spec, {"discovery-root": parent})
    # #1384: a discovered tree whose live git state moves under a still-present,
    # still-same-kind child is the concurrent work the non-blocking-verify
    # directive sanctions. The final pass still detects it — it now reports it
    # as receipted churn naming the field that moved, instead of contradicting.
    assert result["roots"][0]["discovery_live_state_churn"] == [
        {"name": "ember-repo", "changed_fields": ["status_sha256"]}
    ]
    assert not any(
        row["code"] == "directory_snapshot_changed_during_scan"
        for row in result["contradictions"]
    )


def test_final_discovery_snapshot_pass_runs_after_all_roots(
    tmp_path: Path, monkeypatch,
) -> None:
    early_parent = tmp_path / "early-parent"
    late_parent = tmp_path / "late-parent"
    early_parent.mkdir()
    late_parent.mkdir()
    early_repo = early_parent / "ember-early"
    late_repo = late_parent / "ember-late"
    early_head = init_repo(early_repo)
    init_repo(late_repo)
    real_summary = census_module.git_repository_summary
    mutated = False

    def mutate_early_ref_while_late_discovery_runs(root_id, root):
        nonlocal mutated
        if root_id.startswith("late:") and not mutated:
            mutated = True
            git(early_repo, "update-ref", "refs/heads/late-mutation", early_head)
        return real_summary(root_id, root)

    monkeypatch.setattr(
        census_module,
        "git_repository_summary",
        mutate_early_ref_while_late_discovery_runs,
    )
    spec = {
        "roots": [
            {
                "root_id": "early",
                "required": True,
                "scan": "directory_discovery",
                "name_patterns": ["ember*"],
            },
            {
                "root_id": "late",
                "required": True,
                "scan": "directory_discovery",
                "name_patterns": ["ember*"],
            },
        ]
    }

    result = build_root_census(
        spec, {"early": early_parent, "late": late_parent}
    )

    assert mutated is True
    # The early root's final snapshot pass runs after every root has been
    # scanned, so it sees the ref that `late`'s scan created behind it. Post
    # #1384 that lands as receipted live-state churn on the early root rather
    # than as a contradiction — either way, only a pass that runs LAST can see
    # it at all, which is what this test exists to prove.
    early_row = next(row for row in result["roots"] if row["root_id"] == "early")
    late_row = next(row for row in result["roots"] if row["root_id"] == "late")
    assert [row["name"] for row in early_row["discovery_live_state_churn"]] == [
        "ember-early"
    ]
    assert "refs_sha256" in early_row["discovery_live_state_churn"][0][
        "changed_fields"
    ]
    assert "discovery_live_state_churn" not in late_row
    assert not any(
        row["code"] == "directory_snapshot_changed_during_scan"
        for row in result["contradictions"]
    )


def test_git_repository_detects_same_status_dirty_byte_change(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    dirty = repo / "tracked.txt"
    dirty.write_text("dirty-one\n", encoding="utf-8")
    spec = {"roots": [{"root_id": "repo", "required": True, "scan": "git_repository"}]}
    real_summary = census_module.git_repository_summary
    calls = 0

    def mutate_between_passes(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            dirty.write_text("dirty-two\n", encoding="utf-8")
        return real_summary(*args, **kwargs)

    monkeypatch.setattr(census_module, "git_repository_summary", mutate_between_passes)
    result = build_root_census(spec, {"repo": repo})
    assert "artifact_changed_after_hash" in {row["code"] for row in result["contradictions"]}


def test_final_git_snapshot_pass_runs_after_all_roots_are_discovered(
    tmp_path: Path, monkeypatch,
) -> None:
    early = tmp_path / "early-repo"
    late = tmp_path / "late-repo"
    early_head = init_repo(early)
    init_repo(late)
    real_summary = census_module.git_repository_summary
    mutated = False

    def mutate_early_ref_while_late_is_scanned(root_id, root):
        nonlocal mutated
        if root_id == "late" and not mutated:
            mutated = True
            git(early, "update-ref", "refs/heads/added-after-early-pass", early_head)
        return real_summary(root_id, root)

    monkeypatch.setattr(
        census_module,
        "git_repository_summary",
        mutate_early_ref_while_late_is_scanned,
    )
    spec = {
        "roots": [
            {"root_id": "early", "required": True, "scan": "git_repository"},
            {"root_id": "late", "required": True, "scan": "git_repository"},
        ]
    }

    result = build_root_census(spec, {"early": early, "late": late})

    assert mutated is True
    changed = [
        row
        for row in result["contradictions"]
        if row["code"] == "git_snapshot_changed_during_scan"
    ]
    assert changed == [
        {
            "code": "git_snapshot_changed_during_scan",
            "root_id": "early",
            "resolution": "unresolved_retry_snapshot",
        }
    ]


def test_final_git_snapshot_access_failure_is_explicit(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    real_summary = census_module.git_repository_summary
    calls = 0

    def fail_only_during_final_snapshot(root_id, root):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_summary(root_id, root)
        raise PermissionError(13, "final git snapshot blocked")

    monkeypatch.setattr(
        census_module,
        "git_repository_summary",
        fail_only_during_final_snapshot,
    )
    result = build_root_census(
        {
            "roots": [
                {"root_id": "repo", "required": True, "scan": "git_repository"}
            ]
        },
        {"repo": repo},
    )

    assert [
        row
        for row in result["contradictions"]
        if row["code"] == "final_verification_inaccessible"
    ] == [
        {
            "code": "final_verification_inaccessible",
            "root_id": "repo",
            "verification": "git_snapshot",
            "exception": "PermissionError",
            "winerror": None,
            "errno": 13,
            "resolution": "unresolved_retry_snapshot",
        }
    ]


def test_directory_discovery_detects_nested_membership_change(
    tmp_path: Path, monkeypatch,
) -> None:
    parent = tmp_path / "material"
    child = parent / "ember-payload"
    child.mkdir(parents=True)
    original = child / "one.bin"
    original.write_bytes(b"one")
    spec = {"roots": [{"root_id": "discovery", "required": True, "scan": "directory_discovery", "name_patterns": ["ember*"]}]}
    real_hash = census_module.hash_file_streaming
    calls = 0

    def add_nested_file(*args, **kwargs):
        nonlocal calls
        result = real_hash(*args, **kwargs)
        calls += 1
        if calls == 1:
            (child / "two.bin").write_bytes(b"two")
        return result

    monkeypatch.setattr(census_module, "hash_file_streaming", add_nested_file)
    result = build_root_census(spec, {"discovery": parent})
    assert "directory_membership_changed_during_scan" in {row["code"] for row in result["contradictions"]}

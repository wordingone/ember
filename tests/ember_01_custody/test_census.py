# goal_id: EMBER-01
# workstream_id: EMBER-01B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

import census as census_module  # noqa: E402
from census import (  # noqa: E402
    build_duplicate_groups,
    build_root_census,
    canonical_root_identity,
    detect_contradictions,
    git_repository_summary,
    parse_worktree_porcelain,
    sha256_file,
    tree_digest,
    validate_benchmark_registry,
)
from issue_census import ALLOWED_DISPOSITIONS  # noqa: E402


DIRECT_MANDATE = [
    "swe-bench-pro",
    "frontiercode-diamond",
    "gdpval-aa",
    "gdppdf",
    "blueprint-bench-2",
    "automationbench",
    "osworld-verified",
    "legal-agent-benchmark",
    "humanitys-last-exam",
    "terminal-bench-2.1",
    "arc-agi-1",
    "arc-agi-2",
    "arc-agi-3",
]


def benchmark_row(benchmark_id: str, provenance: str = "direct_mandate") -> dict:
    return {
        "benchmark_id": benchmark_id,
        "version": "unresolved",
        "provenance_class": provenance,
        "subject_requirement": "owned_admissible_ember_checkpoint",
        "harness_status": "unresolved",
        "data_status": "unresolved",
        "license_status": "unresolved",
        "execution_status": "not_executed",
        "subject_class": "none",
        "completion": False,
        "evidence": [],
        "split": "unresolved",
        "harness_path": None,
        "harness_identity": None,
        "comparator_requirements": {
            "owned_subject_required": True,
            "borrowed_reference_role": "frozen_reference_only",
            "lineage_signal_allowed": False,
        },
        "lineage_admissibility": "owned_subject_only",
        "completion_eligibility": "ineligible_until_exact_owned_execution",
    }


def valid_benchmark_registry() -> dict:
    rows = [benchmark_row(name) for name in DIRECT_MANDATE]
    rows.extend(
        [
            benchmark_row("unresolved-direct-01", "unresolved_direct_request"),
            benchmark_row("unresolved-direct-02", "unresolved_direct_request"),
            benchmark_row("mmlu-pro", "broader_research_candidate"),
        ]
    )
    return {
        "schema": "ember-01-benchmark-registry-v1",
        "direct_recovered_minimum": 13,
        "operator_recollection_minimum": 15,
        "benchmarks": rows,
    }


def test_hashing_is_byte_exact_and_tree_order_stable(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "b.bin").write_bytes(b"beta\x00")
    (first / "a.bin").write_bytes(b"alpha\r\n")
    (second / "a.bin").write_bytes(b"alpha\r\n")
    (second / "b.bin").write_bytes(b"beta\x00")

    assert sha256_file(first / "a.bin") == sha256_file(second / "a.bin")
    assert tree_digest(first) == tree_digest(second)

    (second / "a.bin").write_bytes(b"alpha\n")
    assert sha256_file(first / "a.bin") != sha256_file(second / "a.bin")
    assert tree_digest(first) != tree_digest(second)


def test_duplicate_groups_depend_on_bytes_not_names() -> None:
    rows = [
        {"artifact_id": "left", "sha256": "a" * 64},
        {"artifact_id": "right", "sha256": "a" * 64},
        {"artifact_id": "same-name-left", "sha256": "b" * 64},
        {"artifact_id": "same-name-right", "sha256": "c" * 64},
    ]
    assert build_duplicate_groups(rows) == [
        {"sha256": "a" * 64, "artifact_ids": ["left", "right"]}
    ]


def test_conflicting_identity_preserves_every_candidate() -> None:
    rows = [
        {
            "artifact_id": "checkpoint:step-10",
            "sha256": "a" * 64,
            "source": {"root_id": "root-a", "relative_path": "step-10.pt"},
        },
        {
            "artifact_id": "checkpoint:step-10",
            "sha256": "b" * 64,
            "source": {"root_id": "root-b", "relative_path": "step-10.pt"},
        },
    ]
    conflicts = detect_contradictions(rows)
    assert rows[0]["sha256"] != rows[1]["sha256"]
    assert conflicts == [
        {
            "code": "conflicting_artifact_identity",
            "artifact_id": "checkpoint:step-10",
            "candidate_sha256": ["a" * 64, "b" * 64],
            "resolution": "unresolved_preserve_all",
        }
    ]


def test_required_missing_root_is_explicit_and_paths_stay_portable(
    tmp_path: Path,
) -> None:
    present = tmp_path / "present"
    present.mkdir()
    (present / "receipt.json").write_text("{}\n", encoding="utf-8")
    spec = {
        "roots": [
            {
                "root_id": "present-root",
                "required": True,
                "scan": "files",
                "provenance_class": "evidence_receipt",
                "lineage_admissibility": "excluded_evidence_only",
            },
            {
                "root_id": "missing-root",
                "required": True,
                "scan": "files",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved",
            },
        ]
    }
    result = build_root_census(
        spec,
        {"present-root": present, "missing-root": tmp_path / "absent"},
    )

    assert [row["root_id"] for row in result["roots"]] == [
        "missing-root",
        "present-root",
    ]
    assert result["roots"][0]["present"] is False
    assert {
        "code": "required_root_missing",
        "root_id": "missing-root",
        "resolution": "unresolved",
    } in result["contradictions"]
    encoded = json.dumps(result, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert result["artifacts"][0]["source"] == {
        "root_id": "present-root",
        "relative_path": "receipt.json",
    }


def test_benchmark_registry_requires_all_direct_and_unresolved_names() -> None:
    registry = valid_benchmark_registry()
    assert validate_benchmark_registry(registry) == []

    registry["benchmarks"] = [
        row
        for row in registry["benchmarks"]
        if row["benchmark_id"] != "terminal-bench-2.1"
    ]
    assert "direct_mandate_missing:terminal-bench-2.1" in validate_benchmark_registry(
        registry
    )


def test_harness_or_borrowed_result_cannot_be_completed() -> None:
    registry = valid_benchmark_registry()
    automation = next(
        row
        for row in registry["benchmarks"]
        if row["benchmark_id"] == "automationbench"
    )
    automation.update(
        {
            "harness_status": "present_unverified",
            "execution_status": "executed",
            "subject_class": "borrowed_reference",
            "subject_manifest": "sha256:" + "d" * 64,
            "result_receipt": "sha256:" + "e" * 64,
            "official_boundary": True,
            "completion": True,
        }
    )
    errors = validate_benchmark_registry(registry)
    assert "completion_subject_not_owned:automationbench" in errors
    automation["subject_class"] = "owned_admissible_ember_checkpoint"
    automation["lineage_admissibility"] = "excluded_reference_or_history"
    errors = validate_benchmark_registry(registry)
    assert "completion_lineage_not_admissible:automationbench" in errors

    automation["lineage_admissibility"] = "owned_subject_only"
    automation["execution_status"] = "harness_only"
    errors = validate_benchmark_registry(registry)
    assert "completion_not_executed:automationbench" in errors


def test_completion_requires_exact_frozen_inputs_and_content_bindings() -> None:
    registry = valid_benchmark_registry()
    row = next(
        item for item in registry["benchmarks"]
        if item["benchmark_id"] == "automationbench"
    )
    row.update(
        {
            "version": "1.0",
            "split": "test",
            "harness_path": "benchmarks/automationbench/run.py",
            "harness_identity": "sha256:" + "c" * 64,
            "harness_status": "verified",
            "data_status": "frozen",
            "license_status": "verified",
            "execution_status": "executed",
            "subject_class": "owned_admissible_ember_checkpoint",
            "subject_manifest": "sha256:" + "d" * 64,
            "result_receipt": "sha256:" + "e" * 64,
            "official_boundary": True,
            "completion_eligibility": "eligible_exact_owned_execution",
            "completion": True,
        }
    )
    assert "completion_repository_unresolved:automationbench" in validate_benchmark_registry(registry)

    mutations = {
        "version": "unresolved",
        "split": "unresolved",
        "data_status": "unresolved",
        "license_status": "unresolved",
        "harness_identity": None,
        "completion_eligibility": "ineligible_until_exact_owned_execution",
        "subject_manifest": "arbitrary-subject",
        "result_receipt": "arbitrary-result",
    }
    for field, invalid in mutations.items():
        original = row[field]
        row[field] = invalid
        errors = validate_benchmark_registry(registry)
        assert any(error.startswith("completion_") for error in errors), field
        row[field] = original


def test_registry_requires_frozen_boundary_fields_and_rejects_unknown_completion() -> None:
    registry = valid_benchmark_registry()
    for row in registry["benchmarks"]:
        row.update(
            {
                "split": "unresolved",
                "harness_path": None,
                "harness_identity": None,
                "comparator_requirements": {
                    "owned_subject_required": True,
                    "borrowed_reference_role": "frozen_reference_only",
                    "lineage_signal_allowed": False,
                },
                "lineage_admissibility": "owned_subject_only",
                "completion_eligibility": "ineligible_until_exact_owned_execution",
            }
        )
    assert validate_benchmark_registry(registry) == []

    registry["benchmarks"][0].pop("split")
    assert "required_field_missing:swe-bench-pro:split" in validate_benchmark_registry(
        registry
    )
    registry["benchmarks"][0]["split"] = "unresolved"
    registry["benchmarks"].append(
        {
            **registry["benchmarks"][0],
            "benchmark_id": "unknown-benchmark",
            "provenance_class": "unknown",
            "completion": True,
            "execution_status": "executed",
            "subject_class": "owned_admissible_ember_checkpoint",
            "subject_manifest": "sha256:" + "d" * 64,
            "result_receipt": "sha256:" + "e" * 64,
            "official_boundary": True,
        }
    )
    assert (
        "completion_benchmark_class_not_frozen:unknown-benchmark"
        in validate_benchmark_registry(registry)
    )

def test_checked_in_registry_is_complete_and_claims_no_execution() -> None:
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "benchmark-registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    assert validate_benchmark_registry(registry) == []
    assert len(registry["benchmarks"]) >= 31
    assert all(row["completion"] is False for row in registry["benchmarks"])
    assert all(
        row["execution_status"] != "executed" for row in registry["benchmarks"]
    )


def test_checked_in_root_spec_names_every_known_required_surface() -> None:
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "root-spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    required_ids = {row["root_id"] for row in spec["roots"] if row["required"]}
    assert {
        "public-repository",
        "private-backup-remote",
        "private-backup-root",
        "local-ignored-payload-registry",
        "registered-worktree-material-registry",
        "local-execution-tree",
        "public-worktree",
        "avir-ember-repository",
        "avir-infra-receipts-root",
        "avir-train-daemon-discovery",
        "ember-named-root-discovery",
        "public-bare-mirror",        "benchmark-root",
        "external-data-root",
        "live-receipts-root",
        "pull-backup-root",
        "untracked-backup-root",
        "recovery-root",
        "durable-recovery-root",
        "auditor-evidence-root",
        "collaborator-evidence-root",
        "internal-execution-tree",
    } <= required_ids
    assert all(
        not any(token in json.dumps(row) for token in ("B:\\\\", "C:\\\\"))
        for row in spec["roots"]
    )


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def test_git_repository_summary_binds_head_refs_and_dirty_state(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    head = git(root, "rev-parse", "HEAD")

    clean = git_repository_summary("fixture-repo", root)
    assert clean["head"] == head
    assert clean["dirty"] is False
    assert clean["refs_sha256"]
    assert str(root) not in json.dumps(clean)

    (root / "tracked.txt").write_text("two\n", encoding="utf-8")
    dirty = git_repository_summary("fixture-repo", root)
    assert dirty["dirty"] is True
    assert dirty["status_sha256"] != clean["status_sha256"]


def test_worktree_registry_is_portable_and_preserves_each_entry() -> None:
    text = (
        "worktree X:/private/main\n"
        "HEAD " + "a" * 40 + "\n"
        "branch refs/heads/main\n\n"
        "worktree X:/private/feature\n"
        "HEAD " + "b" * 40 + "\n"
        "detached\n"
        "prunable gitdir file points to non-existent location\n\n"
    )
    rows = parse_worktree_porcelain(text)
    assert rows == [
        {
            "worktree_id": "worktree-fae3c4be302362d0",
            "normalized_path": "X:/private/feature",
            "head": "b" * 40,
            "branch": None,
            "detached": True,
            "prunable": True,
        },
        {
            "worktree_id": "worktree-63082be5dcb04b85",
            "normalized_path": "X:/private/main",
            "head": "a" * 40,
            "branch": "refs/heads/main",
            "detached": False,
            "prunable": False,
        },
    ]
    assert rows[0]["normalized_path"] == "X:/private/feature"


def test_git_repository_scan_records_identity_without_git_object_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    spec = {
        "roots": [
            {
                "root_id": "repo-root",
                "required": True,
                "scan": "git_repository",
                "provenance_class": "harness_tooling",
                "lineage_admissibility": "source_authority_not_weight_lineage",
            }
        ]
    }
    result = build_root_census(spec, {"repo-root": root})
    assert result["roots"][0]["git"]["head"] == git(root, "rev-parse", "HEAD")
    assert {row["artifact_id"] for row in result["artifacts"]} == {
        "repo-root:git-refs",
            "repo-root:git-index",
            "repo-root:git-reachable-objects",
            "repo-root:git-tracked-tree",
        "repo-root:git-status",
    }
    assert all(".git/" not in row["source"]["relative_path"] for row in result["artifacts"])


def test_git_repository_scan_binds_tracked_index_and_local_material_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    tracked = root / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    git(root, "add", ".gitignore", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    tracked.write_text("staged\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    tracked.write_text("working\n", encoding="utf-8")
    (root / "untracked.bin").write_bytes(b"untracked")
    ignored = root / "ignored" / "payload.bin"
    ignored.parent.mkdir()
    ignored.write_bytes(b"ignored")
    spec = {"roots": [{"root_id": "repo", "required": True, "scan": "git_repository"}]}

    result = build_root_census(spec, {"repo": root})
    summary = result["roots"][0]["git"]
    assert summary["reachable_object_manifest_sha256"]
    assert summary["tracked_tree_manifest_sha256"]
    assert summary["index_manifest_sha256"]
    assert result["roots"][0]["normalized_bound_path"] == str(root.resolve()).replace("\\", "/")
    artifacts = {row["source"]["relative_path"]: row for row in result["artifacts"]}
    assert artifacts["git-material/tracked.txt"]["sha256"] == sha256_file(tracked)
    assert artifacts["git-material/untracked.bin"]["sha256"] == sha256_file(root / "untracked.bin")
    assert artifacts["git-material/ignored/payload.bin"]["sha256"] == sha256_file(ignored)


def test_directory_membership_change_is_rejected(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first.bin"
    first.write_bytes(b"first")
    real_hash = census_module.hash_file_streaming
    changed = False
    def mutate_membership(path, *args, **kwargs):
        nonlocal changed
        result = real_hash(path, *args, **kwargs)
        if not changed:
            (root / "late.bin").write_bytes(b"late")
            changed = True
        return result
    monkeypatch.setattr(census_module, "hash_file_streaming", mutate_membership)
    result = build_root_census({"roots": [{"root_id": "root", "required": True, "scan": "files"}]}, {"root": root})
    assert any(row["code"] == "directory_membership_changed_during_scan" for row in result["contradictions"])


def test_inaccessible_directory_is_coverage_contradiction_not_file_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    blocked = root / "blocked"
    blocked.mkdir()
    real_iterdir = Path.iterdir
    def selective_iterdir(path):
        if path == blocked:
            raise OSError(5, "blocked directory")
        return real_iterdir(path)
    monkeypatch.setattr(Path, "iterdir", selective_iterdir)
    result = build_root_census({"roots": [{"root_id": "root", "required": True, "scan": "files"}]}, {"root": root})
    assert result["artifacts"] == []
    assert result["contradictions"] == [{
        "code": "directory_coverage_inaccessible",
        "root_id": "root",
        "relative_path": "blocked",
        "exception": "OSError",
        "winerror": None,
        "errno": 5,
        "resolution": "unresolved_preserve_directory",
    }]


def test_canonical_root_identity_excludes_mtime_receipt_metadata(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "payload.bin"
    artifact.write_bytes(b"same")
    spec = {"roots": [{"root_id": "root", "required": True, "scan": "files"}]}
    first = build_root_census(spec, {"root": root})
    os.utime(artifact, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    second = build_root_census(spec, {"root": root})
    assert first["artifacts"][0]["mtime_ns_non_authoritative"] != second["artifacts"][0]["mtime_ns_non_authoritative"]
    assert canonical_root_identity(first) == canonical_root_identity(second)


def test_remote_and_worktree_registry_modes_use_source_repo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    git(root, "remote", "add", "backup", "https://example.invalid/private.git")
    spec = {
        "roots": [
            {
                "root_id": "repo-root",
                "required": True,
                "scan": "git_repository",
                "provenance_class": "harness_tooling",
                "lineage_admissibility": "source_authority_not_weight_lineage",
            },
            {
                "root_id": "backup-remote",
                "required": True,
                "scan": "git_remote",
                "source_root_id": "repo-root",
                "remote_name": "backup",
                "provenance_class": "archive_history",
                "lineage_admissibility": "unresolved_requires_ref_review",
            },
            {
                "root_id": "worktrees",
                "required": True,
                "scan": "git_worktree_registry",
                "source_root_id": "repo-root",
                "provenance_class": "archive_history",
                "lineage_admissibility": "unresolved_requires_worktree_review",
            },
        ]
    }
    result = build_root_census(spec, {"repo-root": root})
    roots = {row["root_id"]: row for row in result["roots"]}
    assert roots["backup-remote"]["present"] is True
    assert roots["backup-remote"]["git_remote"]["remote_name"] == "backup"
    assert roots["worktrees"]["present"] is True
    assert len(roots["worktrees"]["worktrees"]) == 1
    assert str(root) not in json.dumps(result)


def test_cli_output_is_byte_stable_for_unchanged_read_only_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "receipt.json").write_text("{}\n", encoding="utf-8")
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=repository, check=True)
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repository, check=True, capture_output=True)
    source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, text=True, capture_output=True, check=True).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/master", source_commit], cwd=repository, check=True)
    spec = {
        "authority": {
            "goal_id": "EMBER-01",
            "workstream_id": "EMBER-01B",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            ),
        },
        "roots": [
            {
                "root_id": "evidence-root",
                "required": True,
                "scan": "files",
                "provenance_class": "evidence_receipt",
                "lineage_admissibility": "excluded_evidence_only",
            }
        ],
    }
    spec_path = tmp_path / "root-spec.json"
    registry_path = tmp_path / "benchmark-registry.json"
    issue_path = tmp_path / "public-issue-census.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    registry_path.write_text(json.dumps(valid_benchmark_registry()), encoding="utf-8")
    issue_path.write_text(
        json.dumps(
            {
                "schema": "ember-01-public-issue-census-v1",
                "public_master_sha": source_commit,
                "open_issue_count": 0,
                "issue_source_snapshot": [],
                "allowed_dispositions": list(ALLOWED_DISPOSITIONS),
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]
    for output in outputs:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_ROOT / "census.py"),
                "--root-spec",
                str(spec_path),
                "--benchmark-registry",
                str(registry_path),
                "--issue-census",
                str(issue_path),
                "--source-commit",
                source_commit,
                "--public-master-ref",
                "refs/remotes/origin/master",
                "--binding",
                f"evidence-root={root}",
                "--binding",
                f"public-repository={repository}",
                "--output",
                str(output),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert payload["benchmark_validation_errors"] == []
    assert payload["issue_validation_errors"] == []
    assert payload["source_commit"] == source_commit
    assert payload["canonical_manifest_sha256"]
    assert payload["benchmark_registry"]["benchmarks"]
    assert payload["public_issue_census"]["issues"] == []
    assert payload["summary"]["artifact_count"] == 1
    assert payload["summary"]["issue_row_count"] == 0
    assert payload["root_census"]["contradictions"] == []


def test_inaccessible_artifact_is_recorded_without_aborting_root(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    blocked = root / "blocked.bin"
    readable = root / "readable.bin"
    blocked.write_bytes(b"blocked")
    readable.write_bytes(b"readable")
    real_open = Path.open

    def selective_open(path, *args, **kwargs):
        if path == blocked:
            raise OSError(1920, "fixture path must not leak")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", selective_open)
    spec = {
        "roots": [
            {
                "root_id": "evidence-root",
                "required": True,
                "scan": "files",
                "provenance_class": "evidence_receipt",
                "lineage_admissibility": "excluded_evidence_only",
            }
        ]
    }
    result = build_root_census(spec, {"evidence-root": root})

    assert [row["source"]["relative_path"] for row in result["artifacts"]] == [
        "blocked.bin",
        "readable.bin",
    ]
    assert result["artifacts"][0]["sha256"] is None
    assert result["artifacts"][0]["access_error"] == {
        "exception": "OSError",
        "winerror": None,
        "errno": 1920,
    }
    assert result["artifacts"][1]["sha256"] == sha256_file(readable)
    assert result["contradictions"] == [
        {
            "code": "artifact_access_failed",
            "root_id": "evidence-root",
            "relative_path": "blocked.bin",
            "exception": "OSError",
            "winerror": None,
            "errno": 1920,
            "resolution": "unresolved_preserve_entry",
        }
    ]
    assert str(tmp_path) not in json.dumps(result)


def test_discovery_access_error_reaches_portable_artifact_handler(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    blocked = root / "blocked.bin"
    readable = root / "readable.bin"
    blocked.write_bytes(b"blocked")
    readable.write_bytes(b"readable")
    real_is_file = Path.is_file
    real_open = Path.open

    def selective_is_file(path):
        if path == blocked:
            raise OSError(1920, "discovery path must not leak")
        return real_is_file(path)

    def selective_open(path, *args, **kwargs):
        if path == blocked:
            raise OSError(1920, "open path must not leak")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", selective_is_file)
    monkeypatch.setattr(Path, "open", selective_open)
    spec = {
        "roots": [
            {
                "root_id": "evidence-root",
                "required": True,
                "scan": "files",
                "provenance_class": "evidence_receipt",
                "lineage_admissibility": "excluded_evidence_only",
            }
        ]
    }
    result = build_root_census(spec, {"evidence-root": root})

    assert [row["source"]["relative_path"] for row in result["artifacts"]] == [
        "blocked.bin",
        "readable.bin",
    ]
    assert result["artifacts"][0]["sha256"] is None
    assert result["contradictions"][0]["code"] == "artifact_access_failed"
    assert str(tmp_path) not in json.dumps(result)


def test_git_ignored_registry_hashes_ignored_bytes_without_object_walk(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    ignored = root / "ignored" / "payload.bin"
    ignored.parent.mkdir()
    ignored.write_bytes(b"payload")
    git(root, "add", ".gitignore", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    spec = {
        "roots": [
            {
                "root_id": "repo-root",
                "required": True,
                "scan": "git_repository",
                "provenance_class": "harness_tooling",
                "lineage_admissibility": "source_authority_not_weight_lineage",
            },
            {
                "root_id": "ignored-root",
                "required": True,
                "scan": "git_ignored_registry",
                "source_root_id": "repo-root",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved_requires_item_review",
            },
        ]
    }
    result = build_root_census(spec, {"repo-root": root})
    roots = {row["root_id"]: row for row in result["roots"]}
    artifacts = [
        row for row in result["artifacts"] if row["source"]["root_id"] == "ignored-root"
    ]
    assert roots["ignored-root"]["ignored_entry_count"] == 1
    assert artifacts[0]["source"]["relative_path"] == "ignored/payload.bin"
    assert artifacts[0]["sha256"] == sha256_file(ignored)
    assert str(root) not in json.dumps(result)


def test_completed_benchmark_resolves_content_bindings(tmp_path: Path) -> None:
    root = tmp_path / "repo"; root.mkdir()
    fields = {"harness_path": ("harness_identity", "h.py"), "subject_manifest_path": ("subject_manifest", "subject.json"), "result_receipt_path": ("result_receipt", "result.json"), "data_evidence_path": ("data_evidence", "data.json"), "license_evidence_path": ("license_evidence", "license.txt")}
    registry = valid_benchmark_registry(); row = next(item for item in registry["benchmarks"] if item["benchmark_id"] == "automationbench")
    row.update({"version": "1", "split": "test", "harness_status": "verified", "data_status": "frozen", "license_status": "verified", "execution_status": "executed", "subject_class": "owned_admissible_ember_checkpoint", "completion_eligibility": "eligible_exact_owned_execution", "official_boundary": True, "completion": True})
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    for path_field, (identity_field, relative) in fields.items():
        path = root / relative; path.write_text(relative, encoding="utf-8"); row[path_field] = relative; row[identity_field] = "sha256:" + sha256_file(path)
    git(root, "add", ".")
    git(root, "commit", "-m", "proof")
    head = git(root, "rev-parse", "HEAD")
    assert validate_benchmark_registry(registry, repository_root=root, source_commit=head) == []
    (root / "h.py").write_text("mutated", encoding="utf-8")
    row["harness_identity"] = "sha256:" + sha256_file(root / "h.py")
    assert "completion_harness_identity_mismatch:automationbench" in validate_benchmark_registry(registry, repository_root=root, source_commit=head)
    row["result_receipt_path"] = "../outside.json"
    assert "completion_result_receipt_path_outside_repository:automationbench" in validate_benchmark_registry(registry, repository_root=root, source_commit=head)


def test_directory_discovery_emits_full_git_identity_and_errors(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "parent"; child = parent / "ember-child"; child.mkdir(parents=True); subprocess.run(["git", "init"], cwd=child, check=True, capture_output=True); subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=child, check=True); subprocess.run(["git", "config", "user.name", "fixture"], cwd=child, check=True); (child / "tracked.txt").write_text("tracked", encoding="utf-8"); subprocess.run(["git", "add", "tracked.txt"], cwd=child, check=True); subprocess.run(["git", "commit", "-m", "fixture"], cwd=child, check=True, capture_output=True); (child / "dirty.txt").write_text("dirty", encoding="utf-8")
    blocked = parent / "ember-blocked"; blocked.mkdir(); real_iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda path: (_ for _ in ()).throw(PermissionError(13, "blocked")) if path == blocked else real_iterdir(path))
    result = build_root_census({"roots": [{"root_id": "discovery", "required": True, "scan": "directory_discovery", "name_patterns": ["ember*"]}]}, {"discovery": parent})
    summary = git_repository_summary("discovery:ember-child", child); artifacts = {row["source"]["relative_path"]: row["sha256"] for row in result["artifacts"]}
    for suffix, key in {"git-refs": "refs_sha256", "git-status": "status_sha256", "git-reachable-objects": "reachable_object_manifest_sha256", "git-tracked-tree": "tracked_tree_manifest_sha256", "git-index": "index_manifest_sha256"}.items(): assert artifacts[f"ember-child/{suffix}"] == summary[key]
    assert "ember-child/git-material/dirty.txt" in artifacts
    assert any(row["code"] == "directory_coverage_inaccessible" for row in result["contradictions"])


def test_census_cli_rejects_unresolved_source_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir(); subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    spec_path, registry_path, issue_path = tmp_path / "root.json", tmp_path / "registry.json", tmp_path / "issues.json"
    spec_path.write_text(json.dumps({"roots": [{"root_id": "public-repository", "required": True, "scan": "git_repository"}]}), encoding="utf-8"); registry_path.write_text(json.dumps(valid_benchmark_registry()), encoding="utf-8")
    issue_path.write_text(json.dumps({"public_master_sha": "a" * 40, "open_issue_count": 0, "issue_source_snapshot": [], "allowed_dispositions": list(ALLOWED_DISPOSITIONS), "issues": []}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT_ROOT / "census.py"), "--root-spec", str(spec_path), "--benchmark-registry", str(registry_path), "--issue-census", str(issue_path), "--source-commit", "a" * 40, "--public-master-ref", "refs/remotes/origin/master", "--binding", f"public-repository={repo}", "--output", str(tmp_path / "out.json")], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 1 and "source commit does not resolve" in result.stdout


def test_census_cli_rejects_issue_master_source_commit_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    (repo / "tracked.txt").write_text("one", encoding="utf-8")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-m", "one")
    issue_master = git(repo, "rev-parse", "HEAD")
    (repo / "tracked.txt").write_text("two", encoding="utf-8")
    git(repo, "commit", "-am", "two")
    source_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/master", source_commit)
    spec_path = tmp_path / "root.json"
    registry_path = tmp_path / "registry.json"
    issue_path = tmp_path / "issues.json"
    spec_path.write_text(
        json.dumps(
            {
                "roots": [
                    {
                        "root_id": "public-repository",
                        "required": True,
                        "scan": "git_repository",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry_path.write_text(json.dumps(valid_benchmark_registry()), encoding="utf-8")
    issue_path.write_text(
        json.dumps(
            {
                "public_master_sha": issue_master,
                "open_issue_count": 0,
                "issue_source_snapshot": [],
                "allowed_dispositions": list(ALLOWED_DISPOSITIONS),
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_ROOT / "census.py"),
            "--root-spec",
            str(spec_path),
            "--benchmark-registry",
            str(registry_path),
            "--issue-census",
            str(issue_path),
            "--source-commit",
            source_commit,
            "--public-master-ref",
            "refs/remotes/origin/master",
            "--binding",
            f"public-repository={repo}",
            "--output",
            str(tmp_path / "out.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "issue census public master does not match source commit" in result.stdout


def test_census_cli_rejects_historical_commit_labeled_public_master(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "one")
    historical = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    git(repo, "commit", "-am", "two")
    git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    spec = tmp_path / "spec.json"
    registry = tmp_path / "registry.json"
    issues = tmp_path / "issues.json"
    spec.write_text(json.dumps({"roots": []}), encoding="utf-8")
    registry.write_text(json.dumps({"benchmarks": []}), encoding="utf-8")
    issues.write_text(json.dumps({"public_master_sha": historical, "issues": []}), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_ROOT / "census.py"),
            "--root-spec", str(spec),
            "--benchmark-registry", str(registry),
            "--issue-census", str(issues),
            "--source-commit", historical,
            "--public-master-ref", "refs/remotes/origin/master",
            "--binding", f"public-repository={repo}",
            "--output", str(tmp_path / "out.json"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "source commit is not the bound public master ref" in result.stdout

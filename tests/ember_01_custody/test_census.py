# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
import threading
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

import census as census_module  # noqa: E402
from census import (  # noqa: E402
    build_duplicate_groups,
    build_root_census,
    bound_root_paths,
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


def test_load_json_bound_rejects_digest_mismatch(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text('{"value":1}', encoding="utf-8")

    try:
        census_module._load_json_bound(payload, "0" * 64)
    except ValueError as error:
        assert "digest does not match expected bytes" in str(error)
    else:
        raise AssertionError("mismatched bound JSON digest was accepted")


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
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
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


def test_required_root_missing_owner_or_authority_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unresolved-root"
    root.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    spec = {
        "roots": [
            {
                "root_id": "unresolved-owner-root",
                "required": True,
                "scan": "files",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved",
                # owner/authority_status omitted entirely, matching the
                # live internal-execution-tree manifest entry shape.
            }
        ]
    }
    result = build_root_census(spec, {"unresolved-owner-root": root})

    assert {
        "code": "required_root_owner_unresolved",
        "root_id": "unresolved-owner-root",
        "resolution": "unresolved",
    } in result["contradictions"]
    assert {
        "code": "required_root_authority_missing",
        "root_id": "unresolved-owner-root",
        "resolution": "unresolved",
    } in result["contradictions"]

    # A well-formed required root (owner + authority both bound) stays clean.
    well_formed_spec = {
        "roots": [
            {
                "root_id": "resolved-root",
                "required": True,
                "scan": "files",
                "provenance_class": "evidence_receipt",
                "lineage_admissibility": "excluded_evidence_only",
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
            }
        ]
    }
    clean = build_root_census(well_formed_spec, {"resolved-root": root})
    assert not any(
        row["code"] in {"required_root_owner_unresolved", "required_root_authority_missing"}
        for row in clean["contradictions"]
    )

    # Empty-string owner/authority are treated the same as absent/"unresolved".
    empty_string_spec = {
        "roots": [
            {
                "root_id": "empty-string-root",
                "required": True,
                "scan": "files",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved",
                "owner": "",
                "authority_status": "",
            }
        ]
    }
    empty = build_root_census(empty_string_spec, {"empty-string-root": root})
    assert {
        "code": "required_root_owner_unresolved",
        "root_id": "empty-string-root",
        "resolution": "unresolved",
    } in empty["contradictions"]
    assert {
        "code": "required_root_authority_missing",
        "root_id": "empty-string-root",
        "resolution": "unresolved",
    } in empty["contradictions"]

    # A NON-required root with unresolved owner/authority is never flagged.
    optional_spec = {
        "roots": [
            {
                "root_id": "optional-root",
                "required": False,
                "scan": "files",
                "provenance_class": "unresolved",
                "lineage_admissibility": "unresolved",
            }
        ]
    }
    optional = build_root_census(optional_spec, {"optional-root": root})
    assert not any(
        row["code"] in {"required_root_owner_unresolved", "required_root_authority_missing"}
        for row in optional["contradictions"]
    )


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


def test_checked_in_root_spec_distinguishes_owned_and_external_surfaces() -> None:
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "root-spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    rows = {row["root_id"]: row for row in spec["roots"]}
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
        "internal-execution-tree",
        "auditor-stale-clone",
        "auditor-evidence-root",
        "collaborator-evidence-root",
    } <= required_ids
    for root_id in (
        "auditor-stale-clone",
        "auditor-evidence-root",
        "collaborator-evidence-root",
    ):
        assert rows[root_id]["required"] is True
        assert (
            rows[root_id]["absence_policy"]
            == "external_party_evidence_absent_by_design"
        )
    internal_execution_tree = dict(rows["internal-execution-tree"])
    # #1365: cockpit runtime state is declared per-root, not asserted here
    # verbatim (that's covered by test_runtime_state_exclusions_* below).
    internal_execution_tree.pop("runtime_state_exclusions", None)
    assert internal_execution_tree == {
        "root_id": "internal-execution-tree",
        "binding": "EMBER_INTERNAL_EXECUTION_ROOT",
        "required": True,
        "scan": "git_repository",
        "source_root_id": "local-execution-tree",
        "provenance_class": "owned_lineage_candidate",
        "lineage_admissibility": "unresolved_requires_item_review",
        "mutability": "dirty_live_tree",
        "owner": "operator",
        "authority_status": "candidate_not_selected",
        "disposition": "logical_alias_of_local_execution_tree",
        # #1380: the declared alias disposition is now machine-readable, so
        # the census stops re-hashing the live tree under a second root_id.
        "alias_of_root_id": "local-execution-tree",
    }
    assert all(
        not any(token in json.dumps(row) for token in ("B:\\\\", "C:\\\\"))
        for row in spec["roots"]
    )


def test_checked_in_root_spec_runtime_state_exclusions_are_well_formed() -> None:
    # #1365: every declared exclusion is a version-controlled pattern+reason
    # pair on the root itself — never a scanner-level hardcoded glob — and
    # covers the cockpit's own state directory.
    path = REPO_ROOT / "manifests" / "ember-01-custody" / "root-spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    declaring_roots = {
        row["root_id"]: row["runtime_state_exclusions"]
        for row in spec["roots"]
        if "runtime_state_exclusions" in row
    }
    assert "local-execution-tree" in declaring_roots
    assert "internal-execution-tree" in declaring_roots
    assert "ember-named-root-discovery" in declaring_roots
    assert "registered-worktree-material-registry" in declaring_roots
    for root_id, exclusions in declaring_roots.items():
        assert isinstance(exclusions, list) and exclusions, root_id
        for entry in exclusions:
            assert isinstance(entry["pattern"], str) and entry["pattern"], root_id
            assert isinstance(entry["reason"], str) and entry["reason"], root_id
            assert "ember-cli/state" in entry["pattern"], root_id


def test_missing_required_external_root_with_closed_attestation_is_resolved() -> None:
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "external-auditor",
                    "required": True,
                    "scan": "files",
                    "provenance_class": "evidence_receipt",
                    "lineage_admissibility": "excluded_evidence_only",
                    "mutability": "auditor_managed",
                    "owner": "auditor",
                    "authority_status": "noncanonical_evidence",
                    "absence_policy": "external_party_evidence_absent_by_design",
                }
            ]
        },
        {},
    )

    assert result["roots"] == [
        {
            "root_id": "external-auditor",
            "required": True,
            "present": False,
            "scan": "files",
            "provenance_class": "evidence_receipt",
            "lineage_admissibility": "excluded_evidence_only",
            "absence_policy": "external_party_evidence_absent_by_design",
            "absence_attested": True,
        }
    ]
    assert result["contradictions"] == []



def test_required_absence_policy_cannot_bypass_owned_root_custody() -> None:
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "owned-root",
                    "required": True,
                    "scan": "files",
                    "provenance_class": "owned_lineage_candidate",
                    "lineage_admissibility": "unresolved_requires_item_review",
                    "mutability": "operator_managed",
                    "owner": "operator",
                    "authority_status": "candidate_not_selected",
                    "absence_policy": "external_party_evidence_absent_by_design",
                }
            ]
        },
        {},
    )

    assert result["roots"][0]["absence_attested"] is False
    assert {row["code"] for row in result["contradictions"]} == {
        "invalid_required_absence_policy",
        "required_root_missing",
    }

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
    assert "normalized_bound_path" not in result["roots"][0]
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
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "root",
                    "required": True,
                    "scan": "files",
                    "owner": "operator",
                    "authority_status": "noncanonical_evidence",
                }
            ]
        },
        {"root": root},
    )
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
    assert str(root.resolve()).replace("\\", "/") not in json.dumps(result).replace("\\", "/")


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
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
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
    sidecars = [tmp_path / "first.sidecar.json", tmp_path / "second.sidecar.json"]
    for output, sidecar in zip(outputs, sidecars):
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
                "--sidecar",
                str(sidecar),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    full_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
    assert full_payloads[0]["run_identity"]["execution_id"] != full_payloads[1]["run_identity"]["execution_id"]
    normalized_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
    for row in normalized_payloads:
        row["run_identity"].pop("execution_id")
    assert normalized_payloads[0] == normalized_payloads[1]
    sidecar_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sidecars]
    identities = [row["run_identity"] for row in sidecar_payloads]
    assert identities[0]["canonical_manifest_sha256"] == identities[1]["canonical_manifest_sha256"]
    assert all(row["transient_contradictions"] == [] for row in identities)
    payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert next(iter(payload)) == "run_identity"
    assert payload["run_identity"] == identities[0]
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
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
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
    assert str(tmp_path.resolve()).replace("\\", "/") not in json.dumps(result).replace("\\", "/")


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
    assert str(tmp_path.resolve()).replace("\\", "/") not in json.dumps(result).replace("\\", "/")


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
    assert str(root.resolve()).replace("\\", "/") not in json.dumps(result).replace("\\", "/")


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


def test_census_cli_binds_to_its_snapshot_commit_not_the_live_master_tip(
    tmp_path: Path,
) -> None:
    """A merge advancing origin/master while the census runs used to fail the
    run outright, freezing every code merge for the whole window (#1331). The
    census now binds to the commit its own snapshot pinned and records where the
    ref points as evidence."""
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
    assert "source commit is not the bound public master ref" not in result.stdout
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    binding = payload["public_master_binding"]
    assert binding["binding_mode"] == "snapshot_internal"
    assert binding["source_commit_is_public_master_tip"] is False
    assert binding["public_master_ref_resolved"] != historical
    assert payload["source_commit"] == historical


# ---------------------------------------------------------------------------
# Bounded-memory git_ignored_registry regression tests.
#
# Context: a real 2026-07-21 run of the full 24-root census died mid-scan at
# this exact root (journal reached 855,271 lines / 259MB before the process
# was killed) because the old code path materialized the entire recursive
# ignored-file row list into one Python list before any hashing started, and
# then kept a full copy of every relative path alive in `final_membership_records`
# for the rest of the run. These tests prove the streaming/spooling
# replacement (a) is the code path actually exercised, (b) uses meaningfully
# less peak memory than the old eager path on the exact operation that OOM'd,
# and (c) has not weakened the TOCTOU membership-change detection it replaces.
# ---------------------------------------------------------------------------


def _init_ignored_payload_repo(root: Path, file_count: int) -> Path:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / ".gitignore").write_text("payload/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    payload_dir = root / "payload"
    payload_dir.mkdir()
    for index in range(file_count):
        (payload_dir / f"f{index}.bin").write_bytes(b"x")
    git(root, "add", ".gitignore", "tracked.txt")
    git(root, "commit", "-m", "fixture")
    return payload_dir


def test_git_ignored_registry_never_calls_eager_row_materializer(
    tmp_path: Path, monkeypatch
) -> None:
    """The bounded-memory rewrite must not fall back to the old
    `_material_file_rows`/`_discover_file_rows` full-list functions for the
    git_ignored_registry scan — those are exactly what OOM'd on 2026-07-21."""
    root = tmp_path / "repo"
    _init_ignored_payload_repo(root, file_count=25)

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "git_ignored_registry must not call the eager row materializer"
        )

    monkeypatch.setattr(census_module, "_material_file_rows", _forbidden)
    monkeypatch.setattr(census_module, "_discover_file_rows", _forbidden)

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
    artifacts = [
        row for row in result["artifacts"] if row["source"]["root_id"] == "ignored-root"
    ]
    assert len(artifacts) == 25
    assert all(row["sha256"] for row in artifacts)


def test_git_ignored_registry_bounds_peak_memory_vs_eager_materialization(
    tmp_path: Path,
) -> None:
    """Quantitative memory-bound proof. Compares peak traced memory for the
    old eager row-materializer against the new streaming+spooling path on
    the identical ignored payload. The old path must hold every
    (relative_path, Path) row in one list before returning; the new path
    never should. If this regresses back to eager materialization, the new
    path's peak rises to roughly match the old path's and this test fails."""
    import tracemalloc

    root = tmp_path / "repo"
    payload_dir = _init_ignored_payload_repo(root, file_count=15_000)
    assert len(list(payload_dir.iterdir())) == 15_000

    ignored_top = sorted(set(census_module._iter_git_ignored_paths(root)))

    tracemalloc.start()
    eager_rows, _ = census_module._material_file_rows(root, ignored_top)
    _, eager_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(eager_rows) == 15_000

    tracemalloc.start()
    digest = census_module._spooled_membership_digest(
        relative
        for relative, _ in census_module._iter_material_rows(root, ignored_top)
    )
    _, lazy_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert digest

    # Same rows, same order-independent content — the lazy path must use a
    # small fraction of the eager path's peak allocation to enroll them.
    assert lazy_peak < eager_peak * 0.35, (
        f"lazy path peak {lazy_peak} bytes is not meaningfully bounded "
        f"relative to eager path peak {eager_peak} bytes"
    )


def test_git_ignored_registry_spool_file_is_cleaned_up(
    tmp_path: Path, monkeypatch
) -> None:
    """Row accumulation is spooled to a real tempfile (not just an
    in-memory buffer standing in for one) and the tempfile is deleted once
    the membership digest has been derived from it."""
    import tempfile as tempfile_module

    root = tmp_path / "repo"
    _init_ignored_payload_repo(root, file_count=40)

    created_paths: list[str] = []
    real_named_temp = tempfile_module.NamedTemporaryFile

    def _tracking_named_temp(*args, **kwargs):
        handle = real_named_temp(*args, **kwargs)
        created_paths.append(handle.name)
        return handle

    monkeypatch.setattr(census_module.tempfile, "NamedTemporaryFile", _tracking_named_temp)

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
    build_root_census(spec, {"repo-root": root})

    assert created_paths, "expected the bounded path to spool through a real tempfile"
    for spooled_path in created_paths:
        assert not os.path.exists(spooled_path), (
            f"spool file {spooled_path} was not cleaned up"
        )


def test_git_ignored_registry_membership_change_still_detected(
    tmp_path: Path, monkeypatch
) -> None:
    """The sha256-digest replacement for the TOCTOU membership check must
    catch the same class of mid-scan mutation the old full-list-equality
    check caught (see test_directory_membership_change_is_rejected above,
    same technique, applied to the git_ignored_registry scan type)."""
    root = tmp_path / "repo"
    _init_ignored_payload_repo(root, file_count=3)
    payload_dir = root / "payload"

    real_hash = census_module.hash_file_streaming
    changed = False

    def mutate_membership(path, *args, **kwargs):
        nonlocal changed
        result = real_hash(path, *args, **kwargs)
        if not changed:
            (payload_dir / "late.bin").write_bytes(b"late")
            changed = True
        return result

    monkeypatch.setattr(census_module, "hash_file_streaming", mutate_membership)

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
    assert any(
        row["code"] == "directory_membership_changed_during_scan"
        for row in result["contradictions"]
    )


def test_git_ignored_registry_membership_unchanged_is_not_flagged(
    tmp_path: Path,
) -> None:
    """No false positive: an untouched ignored payload must not trip the
    membership-changed contradiction under the new digest comparison."""
    root = tmp_path / "repo"
    _init_ignored_payload_repo(root, file_count=50)

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
    assert not any(
        row["code"] == "directory_membership_changed_during_scan"
        for row in result["contradictions"]
    )


# ---------------------------------------------------------------------------
# #1365: runtime-state exclusion (cockpit self-contamination).


_STATE_EXCLUSION = {
    "pattern": "*tools/ember-cli/state/*",
    "reason": "cockpit runtime state, see #1365",
}


def test_runtime_state_exclusion_is_disclosed_with_pattern_reason_and_count(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep.bin").write_bytes(b"keep")
    state_dir = root / "tools" / "ember-cli" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "a.jsonl").write_bytes(b"a")
    (state_dir / "b.json").write_bytes(b"b")
    spec = {
        "roots": [
            {
                "root_id": "root",
                "required": True,
                "scan": "files",
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
                "runtime_state_exclusions": [_STATE_EXCLUSION],
            }
        ]
    }
    result = build_root_census(spec, {"root": root})
    root_row = result["roots"][0]
    assert root_row["runtime_state_exclusions"] == [
        {**_STATE_EXCLUSION, "excluded_artifact_count": 2}
    ]
    assert result["runtime_state_excluded_artifact_count"] == 2
    assert {row["source"]["relative_path"] for row in result["artifacts"]} == {
        "keep.bin"
    }

    # Never silently applied: a root that does not declare the exclusion is
    # scanned in full — no hardcoded scanner-level glob, no ambient default.
    spec_no_declaration = {
        "roots": [
            {
                "root_id": "root",
                "required": True,
                "scan": "files",
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
            }
        ]
    }
    undeclared = build_root_census(spec_no_declaration, {"root": root})
    assert {row["source"]["relative_path"] for row in undeclared["artifacts"]} == {
        "keep.bin",
        "tools/ember-cli/state/a.jsonl",
        "tools/ember-cli/state/b.json",
    }
    assert "runtime_state_exclusions" not in undeclared["roots"][0]
    assert undeclared["runtime_state_excluded_artifact_count"] == 0


def test_runtime_state_exclusion_does_not_blanket_suppress_other_paths(
    tmp_path: Path, monkeypatch,
) -> None:
    """Acceptance #4: a mutation OUTSIDE the excluded set still produces a
    contradiction — declaring an exclusion never goes blanket."""
    root = tmp_path / "root"
    root.mkdir()
    watched = root / "watched.bin"
    watched.write_bytes(b"before")
    state_dir = root / "tools" / "ember-cli" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "watermark.json").write_bytes(b"{}")

    real_hash = census_module.hash_file_streaming
    mutated = False

    def mutate_after_hash(path, *args, **kwargs):
        nonlocal mutated
        result = real_hash(path, *args, **kwargs)
        if path == watched and not mutated:
            mutated = True
            watched.write_bytes(b"after-hash-mutation")
        return result

    monkeypatch.setattr(census_module, "hash_file_streaming", mutate_after_hash)
    spec = {
        "roots": [
            {
                "root_id": "root",
                "required": True,
                "scan": "files",
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
                "runtime_state_exclusions": [_STATE_EXCLUSION],
            }
        ]
    }
    result = build_root_census(spec, {"root": root})
    # Either code proves the mutation on the non-excluded path was caught
    # (immediate post-hash guard vs. the final re-verification pass,
    # depending on exactly when the write lands) — what matters is that it
    # is NOT silently absorbed the way an excluded-path mutation now is.
    assert any(
        row["code"] in {"artifact_changed_after_hash", "artifact_mutated_during_hash"}
        and row.get("relative_path") == "watched.bin"
        for row in result["contradictions"]
    )


def test_runtime_state_exclusion_applies_to_git_repository_material_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / ".gitignore").write_text(
        "tools/ember-cli/state/\n", encoding="utf-8"
    )
    git(root, "add", ".gitignore")
    git(root, "commit", "-m", "fixture")
    (root / "loose.txt").write_text("loose\n", encoding="utf-8")
    state_dir = root / "tools" / "ember-cli" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "watermark.json").write_bytes(b"{}")
    spec = {
        "roots": [
            {
                "root_id": "repo",
                "required": True,
                "scan": "git_repository",
                "provenance_class": "harness_tooling",
                "lineage_admissibility": "source_authority_not_weight_lineage",
                "runtime_state_exclusions": [_STATE_EXCLUSION],
            }
        ]
    }
    result = build_root_census(spec, {"repo": root})
    relative_paths = {row["source"]["relative_path"] for row in result["artifacts"]}
    assert "git-material/tools/ember-cli/state/watermark.json" not in relative_paths
    assert "git-material/loose.txt" in relative_paths
    assert (
        result["roots"][0]["runtime_state_exclusions"][0]["excluded_artifact_count"]
        == 1
    )
    assert not any(
        row["code"] == "directory_membership_changed_during_scan"
        for row in result["contradictions"]
    )


def test_runtime_state_exclusion_survives_background_writer_thread(
    tmp_path: Path,
) -> None:
    """Acceptance #2: a census run over a fixture root, with a background
    writer thread continuously mutating an excluded state file for the whole
    run, produces zero contradictions attributable to the excluded path."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "included.bin").write_bytes(b"keep-me")
    state_dir = root / "tools" / "ember-cli" / "state"
    state_dir.mkdir(parents=True)
    watermark = state_dir / "activity-feed-watermark.json"
    watermark.write_bytes(b'{"n":0}')

    stop_writer = threading.Event()

    def _writer() -> None:
        counter = 0
        while not stop_writer.is_set():
            counter += 1
            try:
                watermark.write_bytes(
                    json.dumps({"n": counter}).encode("utf-8")
                )
            except OSError:
                pass
            time.sleep(0.005)

    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()
    spec = {
        "roots": [
            {
                "root_id": "root",
                "required": True,
                "scan": "files",
                "owner": "operator",
                "authority_status": "noncanonical_evidence",
                "runtime_state_exclusions": [_STATE_EXCLUSION],
            }
        ]
    }
    result = None
    try:
        # The writer never stops for the whole block below, so every one of
        # these runs genuinely overlaps its mutation window.
        for _ in range(5):
            result = build_root_census(spec, {"root": root})
            assert not any(
                row["code"]
                in {
                    "artifact_changed_after_hash",
                    "artifact_mutated_during_hash",
                    "directory_membership_changed_during_scan",
                }
                for row in result["contradictions"]
            )
    finally:
        stop_writer.set()
        thread.join(timeout=2)

    assert result is not None
    relative_paths = {row["source"]["relative_path"] for row in result["artifacts"]}
    assert relative_paths == {"included.bin"}
    assert (
        result["roots"][0]["runtime_state_exclusions"][0]["excluded_artifact_count"]
        == 1
    )


def _1380_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    # A discovery parent holding two name-matching children: one that another
    # root already binds directly, one that nothing else owns (#1380).
    parent = tmp_path / "parent"
    bound_child = parent / "ember"
    stray_child = parent / "ember-stray"
    bound_child.mkdir(parents=True)
    stray_child.mkdir()
    (bound_child / "payload.bin").write_bytes(b"bound-root-bytes")
    (stray_child / "payload.bin").write_bytes(b"stray-bytes")
    return parent, bound_child, stray_child


def test_discovery_never_rescans_a_path_bound_to_another_root(tmp_path: Path) -> None:
    parent, bound_child, stray_child = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {"root_id": "bound-tree", "required": False, "scan": "files"},
                {
                    "root_id": "discovery",
                    "required": False,
                    "scan": "directory_discovery",
                    "name_patterns": ["ember*"],
                },
            ]
        },
        {"bound-tree": bound_child, "discovery": parent},
    )
    by_root: dict[str, list[str]] = {}
    for row in result["artifacts"]:
        by_root.setdefault(row["source"]["root_id"], []).append(
            row["source"]["relative_path"]
        )
    # The bound tree is hashed exactly once, under the root that binds it.
    assert by_root["bound-tree"] == ["payload.bin"]
    assert by_root["discovery"] == ["ember-stray/payload.bin"]
    # Non-colliding discovery children keep their coverage.
    assert (stray_child / "payload.bin").is_file()
    discovery_row = next(
        row for row in result["roots"] if row["root_id"] == "discovery"
    )
    assert discovery_row["discovery_bound_elsewhere"] == [
        {"name": "ember", "bound_root_ids": ["bound-tree"]}
    ]
    assert [row["name"] for row in discovery_row["discovered_roots"]] == [
        "ember-stray"
    ]
    assert discovery_row["discovered_root_count"] == 1
    # The re-scan is gone, so the live bytes no longer duplicate themselves.
    assert result["duplicate_groups"] == []
    assert not any(
        row["code"] == "directory_snapshot_changed_during_scan"
        or row["code"] == "directory_membership_changed_during_scan"
        for row in result["contradictions"]
    )


def test_alias_root_contributes_no_artifacts(tmp_path: Path) -> None:
    parent, bound_child, _ = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {"root_id": "bound-tree", "required": False, "scan": "files"},
                {
                    "root_id": "alias-tree",
                    "required": False,
                    "scan": "files",
                    "source_root_id": "bound-tree",
                    "alias_of_root_id": "bound-tree",
                    "disposition": "logical_alias_of_bound_tree",
                },
            ]
        },
        {"bound-tree": bound_child},
    )
    assert {row["source"]["root_id"] for row in result["artifacts"]} == {"bound-tree"}
    alias_row = next(row for row in result["roots"] if row["root_id"] == "alias-tree")
    assert alias_row["present"] is True
    assert alias_row["alias_of_root_id"] == "bound-tree"
    assert alias_row["artifact_contribution"] == "none_alias"
    assert result["duplicate_groups"] == []
    assert result["contradictions"] == []


def test_alias_root_that_names_no_declared_root_is_a_contradiction(
    tmp_path: Path,
) -> None:
    _, bound_child, _ = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "alias-tree",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "nonexistent-root",
                }
            ]
        },
        {"alias-tree": bound_child},
    )
    assert [row["code"] for row in result["contradictions"]] == [
        "alias_target_root_missing"
    ]
    # Fail-closed: an unverifiable alias is scanned anyway, so declaring one
    # can never delete custody material.
    assert [row["source"]["relative_path"] for row in result["artifacts"]] == [
        "payload.bin"
    ]
    alias_row = next(row for row in result["roots"] if row["root_id"] == "alias-tree")
    assert alias_row["artifact_contribution"] == "scanned_unverified_alias"


def test_alias_bound_to_different_bytes_than_its_target_is_still_hashed(
    tmp_path: Path,
) -> None:
    # rev-1380 P6: an alias whose own binding is NOT the target's path would
    # otherwise vanish from the census silently, taking its bytes with it.
    _, target_child, other_child = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {"root_id": "target", "required": False, "scan": "files"},
                {
                    "root_id": "impostor",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "target",
                },
            ]
        },
        {"target": target_child, "impostor": other_child},
    )
    assert [row["code"] for row in result["contradictions"]] == [
        "alias_target_path_mismatch"
    ]
    by_root = {
        row["source"]["root_id"]: row["source"]["relative_path"]
        for row in result["artifacts"]
    }
    # Both distinct payloads survive — nothing was silently dropped.
    assert by_root == {"target": "payload.bin", "impostor": "payload.bin"}
    assert {row["sha256"] for row in result["artifacts"]} == {
        sha256_file(target_child / "payload.bin"),
        sha256_file(other_child / "payload.bin"),
    }


def test_mutual_alias_cycle_cannot_empty_the_census(tmp_path: Path) -> None:
    # rev-1380 P5: two roots each declaring the other emptied the census with
    # zero contradictions. Every alias target must itself be a non-alias root,
    # which breaks chains and cycles by construction.
    _, first_child, second_child = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "alpha",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "beta",
                },
                {
                    "root_id": "beta",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "alpha",
                },
            ]
        },
        {"alpha": first_child, "beta": second_child},
    )
    assert [row["code"] for row in result["contradictions"]] == [
        "alias_target_is_alias",
        "alias_target_is_alias",
    ]
    assert {row["source"]["root_id"] for row in result["artifacts"]} == {
        "alpha",
        "beta",
    }


def test_alias_whose_target_is_unbound_is_still_hashed(tmp_path: Path) -> None:
    _, bound_child, _ = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {"root_id": "target", "required": False, "scan": "files"},
                {
                    "root_id": "alias-tree",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "target",
                },
            ]
        },
        {"alias-tree": bound_child},
    )
    assert [row["code"] for row in result["contradictions"]] == [
        "alias_target_unbound"
    ]
    assert [row["source"]["root_id"] for row in result["artifacts"]] == ["alias-tree"]


def test_alias_that_names_itself_is_still_hashed(tmp_path: Path) -> None:
    _, bound_child, _ = _1380_fixture(tmp_path)
    result = build_root_census(
        {
            "roots": [
                {
                    "root_id": "selfie",
                    "required": False,
                    "scan": "files",
                    "alias_of_root_id": "selfie",
                }
            ]
        },
        {"selfie": bound_child},
    )
    assert [row["code"] for row in result["contradictions"]] == [
        "alias_target_is_self"
    ]
    assert [row["source"]["root_id"] for row in result["artifacts"]] == ["selfie"]


def test_bound_root_paths_credits_only_the_root_that_owns_the_bytes(
    tmp_path: Path,
) -> None:
    _, bound_child, _ = _1380_fixture(tmp_path)
    owners = bound_root_paths(
        {
            "roots": [
                {"root_id": "bound-tree", "scan": "files"},
                {"root_id": "derived", "scan": "files", "source_root_id": "bound-tree"},
                {
                    "root_id": "alias",
                    "scan": "files",
                    "alias_of_root_id": "bound-tree",
                },
            ]
        },
        {"bound-tree": bound_child, "derived": bound_child, "alias": bound_child},
    )
    assert list(owners.values()) == [["bound-tree"]]

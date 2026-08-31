#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mutation-backed tests for Ember's executable authority spine."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_authority_conservation.py"
INVARIANT_SHA256 = "08A0EB7418C09A8088BE4658E10785107ABBB7507FC2DBCDC789936AA54E02A6"


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("authority_verifier_under_test", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

GOVERNING_SURFACES = [
    "docs/contracts/goal-clear-protocol.md",
    "docs/contracts/nc2-own-technique-contract.md",
    "docs/contracts/ember-floor-contract.md",
    "docs/contracts/goal-mode-mechanism.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/domains/governance/spec/conditions-v1.md",
    "docs/authority/ember-authority-matrix.md",
    "GOVERNANCE.md",
    "README.md",
    "CONTINUITY.md",
]

WORKSTREAM_PATH_SCOPES = {'EMBER-02A': {'mode': 'all_except',
               'prefixes': ['configs/ember-restart-3b.json',
                            'docs/ember-restart-3b-',
                            'models/ember-restart-3b/',
                            'tools/ember-restart-3b/',
                            'receipts/ember-restart-3b/',
                            'inference/ember-restart-3b/',
                            'data/ember-restart-3b/',
                            'tests/ember_restart_model/',
                            'docs/ember-restart-eval-',
                            'docs/ember-restart-terminal-',
                            'docs/ember-restart-browser-',
                            'docs/ember-restart-audio-',
                            'docs/ember-restart-image-',
                            'manifests/ember-restart-eval-',
                            'scripts/ember_restart_eval',
                            'tests/test_ember_restart_eval',
                            'docs/ember-restart-sql-',
                            'docs/ember-restart-structured-tools-',
                            'docs/ember-restart-dynamics-',
                            'scripts/ember_restart_measured_receipts',
                            'tests/test_ember_restart_measured_receipts']},
 'EMBER-02B': {'mode': 'only',
               'prefixes': ['configs/ember-restart-3b.json',
                            'docs/ember-restart-3b-',
                            'models/ember-restart-3b/',
                            'tools/ember-restart-3b/',
                            'receipts/ember-restart-3b/',
                            'inference/ember-restart-3b/',
                            'data/ember-restart-3b/',
                            'tests/ember_restart_model/']},
 'EMBER-02C': {'mode': 'only',
               'prefixes': ['docs/ember-restart-eval-',
                            'docs/ember-restart-terminal-',
                            'docs/ember-restart-browser-',
                            'docs/ember-restart-audio-',
                            'docs/ember-restart-image-',
                            'manifests/ember-restart-eval-',
                            'scripts/ember_restart_eval',
                            'tests/test_ember_restart_eval',
                            'docs/ember-restart-sql-',
                            'docs/ember-restart-structured-tools-',
                            'docs/ember-restart-dynamics-',
                            'scripts/ember_restart_measured_receipts',
                            'tests/test_ember_restart_measured_receipts']}}

CONSERVATION_HEADER = """<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->
"""

VALID_EXECUTION_BOUNDARY = {
    "schema": "ember-execution-boundary-v1",
    "goal_id": "EMBER-02",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    "execution_class": "goal_executing",
    "allows_new_network": True,
    "permitted_operations": [
        "repository_governance",
        "record_coherence_repair",
        "spine_implementation",
        "owned_3b_pretraining",
        "owned_evaluation",
        "owned_serving",
    ],
    "blocked_operations": [
        "sub_3b_new_network",
        "borrowed_lineage_signal",
        "historical_artifact_execution",
        "capability_or_completion_claim",
        "benchmark_credit_without_owned_checkpoint",
    ],
    "prerequisite_receipts": ["fixture prerequisite receipt"],
    "next_executable_command": (
        "python src/ember/governance/scripts/ember_restart/contract.py validate "
        "configs/ember-restart-3b.json"
    ),
}


def render_boundary(boundary: dict) -> str:
    return (
        "<!-- EMBER_EXECUTION_BOUNDARY_V1\n"
        + json.dumps(boundary, indent=2, sort_keys=True)
        + "\n-->\n"
    )

VALID_POLICY = {
    "schema": "ember-authority-v1",
    "invariant_sha256": INVARIANT_SHA256,
    "active_goal_id": "EMBER-02",
    "active_workstream_ids": ["EMBER-02A", "EMBER-02B", "EMBER-02C"],
    "goal_graph_node_ids": [
        "EMBER-01",
        "EMBER-02A",
        "EMBER-02B",
        "EMBER-02C",
        "EMBER-02P",
    ],
    "workstream_path_scopes": WORKSTREAM_PATH_SCOPES,
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    "authority_only_goal": False,
    "allows_new_network": True,
    "highest_amendable_authority": "GOAL.md",
    "required_governing_surfaces": GOVERNING_SURFACES,
    "model_birth": {
        "minimum_total_parameters": 3_000_000_000,
        "required_native_capabilities": [
            "text",
            "image",
            "audio",
            "reasoning",
            "structured_tool_use",
        ],
        "sufficient_training_required": True,
        "parameter_shell_is_model_birth": False,
    },
    "hard_rungs_total_parameters": [
        3_000_000_000,
        7_000_000_000,
        15_000_000_000,
        27_000_000_001,
    ],
    "destination": {
        "minimum_total_parameters_exclusive": 27_000_000_000,
        "initial_total_parameter_band": [30_000_000_000, 35_000_000_000],
        "single_gpu_vram_gib": 24,
        "competitive_reference_parameters": [27_000_000_000, 31_000_000_000],
    },
    "architecture": {
        "owned_unified_decoder": True,
        "sparse_differentiated_capacity": True,
        "headline_hypothesis": "Verified Expert Accretion",
        "published_family_backbone_allowed": False,
        "task_level_expert_routing": True,
    },
    "benchmark_custody": {
        "additional_direct_recovered": ["ARC-AGI 1", "ARC-AGI 2", "ARC-AGI 3"],
        "broader_named_families_minimum": 31,
        "direct_recovered_minimum": 13,
        "no_silent_retirement": True,
        "operator_recollection_minimum": 15,
        "owned_checkpoint_binding_required": True,
        "recovered_operator_mandate": [
            "SWE-Bench Pro",
            "FrontierCode Diamond",
            "GDPval-AA",
            "GDPpdf",
            "Blueprint-Bench 2",
            "AutomationBench",
            "OSWorld-Verified",
            "Legal Agent Benchmark",
            "Humanity's Last Exam",
            "Terminal-Bench 2.1",
        ],
        "unrecovered_direct_names_minimum": 2,
    },
    "lineage": {
        "borrowed_models_role": "frozen_reference_only",
        "forbidden_model_mediated_signals": [
            "weights",
            "outputs",
            "teachers",
            "judges",
            "filters",
            "ranks",
            "curricula",
            "stopping_decisions",
            "hidden_external_cognition",
        ],
        "published_ideas_allowed": True,
        "transparent_deterministic_tools_allowed": True,
    },
    "negative_evidence": {
        "may_delete_required_capability": False,
        "may_erase_research_family": False,
        "may_force_named_successor": False,
        "preserve_synergy_order_scale_modality_substrate_routing_precision_retests": True,
    },
    "reasoning_evidence": {
        "checkpoint_bound": True,
        "unseen_tasks_required": True,
        "required_axes": [
            "multi_step",
            "compositional",
            "counterfactual",
            "causal",
            "action_coherence",
            "component_deletion",
        ],
        "forbidden_substitutes": [
            "borrowed_model",
            "search",
            "script",
            "verifier",
            "tool_wrapper",
            "human_intervention",
        ],
        "hidden_trace_disclosure_required": False,
    },
    "totality": [
        "creation_primitive",
        "foundation_model",
        "organism",
        "body",
        "general_local_ai_laboratory",
        "individual_local_ownership",
        "whole_stack_ownership",
        "operational_and_cognitive_self_sufficiency",
    ],
    "operator_relationship": {
        "dynamically_configurable": True,
        "explicit": True,
        "revocable": True,
        "behavior_tested": True,
        "operator_retains_final_scope_authority": True,
    },
    "mutation_controls_required": [
        "invariant_tamper",
        "missing_discrepancy",
        "sub_3b_network",
        "missing_native_modality",
        "missing_native_reasoning",
        "borrowed_backbone",
        "model_mediated_signal",
        "mechanism_erasure",
        "missing_totality_member",
        "ambiguous_identity",
        "missing_goal_binding",
        "non_authority_completion_claim",
        "benchmark_obligation_erasure",
        "governing_surface_semantic_drift",
        "selection_duplicate_key",
        "selection_path_substitution",
        "historical_execution_reenable",
    ],
    "required_future_artifact_fields": [
        "goal_id",
        "workstream_id",
        "next_executed_outcome",
    ],
}


def render_goal(policy: dict) -> str:
    return (
        "# EMBER — Constitution\n\n"
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(policy, indent=2, sort_keys=True)
        + "\n-->\n\n"
        "The prose constitution conserves the machine contract above.\n"
    )


def write_valid_crosswalk(root: Path, matrix_path: Path) -> None:
    """Give the fixture the authority supersession packet leg 4 demands.

    A valid minimal authority repo is not just the D-matrix. Once
    docs/authority/ember-authority-matrix.md exists, authority_supersession_gate treats the
    tree as a current-authority tree and requires, fail-closed, all three of:

      1. manifests/authority/issue-35-authority-supersession-crosswalk-v1.json,
      2. scripts/verify_authority_supersession_crosswalk.py (the gate imports the
         validator from the tree under test, not from this repo), and
      3. docs/roadmap/milestones/EMBER-*.md, because the crosswalk's milestone_ids
         must equal the live roadmap contracts and an empty roadmap is an error.

    The crosswalk itself is closed-schema: every object's key set must match
    exactly, discrepancy_ids must equal the matrix's own D identifiers, each
    evidence path must exist with a matching sha256, every declared source id
    needs exactly one row, no row may claim completion credit, and
    crosswalk_sha256 is the canonical hash of the payload minus that field.
    Anything added here must keep all of those true -- see
    scripts/verify_authority_supersession_crosswalk.py for the contract, and
    manifests/authority/issue-35-authority-supersession-crosswalk-v1.json in this
    repo for the production-scale example.

    source_commit is the all-zero sha: the fixture tree has no commits when this
    runs, and an honest placeholder is what the #1381 re-pin coupling rule wants
    to see. That rule only fires when the pins move across a diff, so a fixture
    that writes this packet once, identically, never trips it.
    """
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO_ROOT / "scripts" / "verify_authority_supersession_crosswalk.py",
        root / "scripts" / "verify_authority_supersession_crosswalk.py",
    )

    milestone_id = "EMBER-02"
    milestone_dir = root / "docs" / "roadmap" / "milestones"
    milestone_dir.mkdir(parents=True, exist_ok=True)
    (milestone_dir / f"{milestone_id}.md").write_text(
        f"# {milestone_id}\n\nFixture milestone contract.\n", encoding="utf-8"
    )

    matrix_rel = matrix_path.relative_to(root).as_posix()
    matrix_sha = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    evidence = [{"path": matrix_rel, "sha256": matrix_sha}]
    discrepancy_ids = sorted(
        set(re.findall(r"\|\s*(D-\d{3})\s*\|", matrix_path.read_text(encoding="utf-8")))
    )
    assert discrepancy_ids, "fixture matrix must carry D identifiers"

    payload = {
        "schema_version": "ember-authority-supersession-crosswalk-v1",
        "repository": "wordingone/ember",
        "source_commit": "0" * 40,
        "current_authority": {
            "matrix_path": matrix_rel,
            "matrix_sha256": matrix_sha,
            "discrepancy_ids": discrepancy_ids,
            "milestone_ids": [milestone_id],
            "historical_terminal": "HISTORICAL_ORPHANED",
        },
        "source_registries": [
            {
                "registry_id": "fixture-legacy-registry",
                "expected_source_ids": ["fixture-legacy-001", "fixture-legacy-002"],
                "evidence": evidence,
            }
        ],
        "rows": [
            {
                "source_registry": "fixture-legacy-registry",
                "source_id": "fixture-legacy-001",
                "source_kind": "legacy_milestone",
                "statement": "fixture legacy obligation carried into the live matrix",
                "disposition": "SUPERSEDED",
                "targets": [discrepancy_ids[0], milestone_id],
                "evidence": evidence,
                "completion_credit": False,
            },
            {
                "source_registry": "fixture-legacy-registry",
                "source_id": "fixture-legacy-002",
                "source_kind": "legacy_condition",
                "statement": "fixture legacy condition with no live successor",
                "disposition": "HISTORICAL_ORPHANED",
                "targets": ["HISTORICAL_ORPHANED"],
                "evidence": evidence,
                "completion_credit": False,
            },
        ],
    }
    payload["crosswalk_sha256"] = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    crosswalk_path = (
        root
        / "manifests"
        / "authority"
        / "issue-35-authority-supersession-crosswalk-v1.json"
    )
    crosswalk_path.parent.mkdir(parents=True, exist_ok=True)
    crosswalk_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_valid_fixture(root: Path) -> None:
    invariant_source = next(
        path
        for path in (
            REPO_ROOT / "docs" / "authority" / "INVARIANT.md",
            REPO_ROOT / "INVARIANT.md",
        )
        if path.is_file()
    )
    invariant = invariant_source.read_bytes()
    assert hashlib.sha256(invariant).hexdigest().upper() == INVARIANT_SHA256
    (root / "INVARIANT.md").write_bytes(invariant)
    (root / "REDACTIONS.md").write_text("# Fixture redactions policy\n", encoding="utf-8")

    for rel in GOVERNING_SURFACES:
        if rel == "docs/authority/ember-authority-matrix.md":
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CONSERVATION_HEADER + f"\n# {rel}\n", encoding="utf-8")

    manifest = [
        "# Ember authority conservation matrix",
        "",
        "| discrepancy | disposition | enforced by | evidence/open question |",
        "|---|---|---|---|",
    ]
    for number in range(1, 63):
        manifest.append(
            f"| D-{number:03d} | ENFORCED | GOAL.md | ledger D-{number:03d} |"
        )
    manifest_path = root / "docs" / "authority" / "ember-authority-matrix.md"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        CONSERVATION_HEADER + "\n" + "\n".join(manifest) + "\n",
        encoding="utf-8",
    )

    write_valid_crosswalk(root, manifest_path)

    state = """# Current artifact identity resolver

| id | object_type | canonical_identity | artifact_class | parameter_count | trained_tokens | backend | capability_credit | evidence |
|---|---|---|---|---:|---:|---|---|---|
| owned-rung2 | checkpoint | sha256:owned-rung2 | historical_only | 2195000000 | 12550144 | disconnected_owned_server | none | historical receipt |
| qwen-reference | backend | model:qwen-reference | borrowed_reference | 27000000000 | unknown | qwen | none | explicit reference seat |
| ember-target | model_target | uninstantiated:ember-target | target | 30000000001 | 0 | owned | none | docs/domains/governance/authority/GOAL.md |
"""
    (root / "STATE.md").write_text(
        "Current artifact identity and maturity state: [CONTINUITY.md](CONTINUITY.md), "
        "under the migrated STATE.md artifact-state resolver section; STATE.md is a "
        "compatibility pointer only and carries no independent authority.\n",
        encoding="utf-8",
    )
    continuity = root / "CONTINUITY.md"
    continuity.write_text(continuity.read_text(encoding="utf-8") + "\n" + state, encoding="utf-8")
    with continuity.open("a", encoding="utf-8") as stream:
        stream.write("\n" + render_boundary(copy.deepcopy(VALID_EXECUTION_BOUNDARY)))

    config = {
        "authority": {
            "artifact_class": "historical_only",
            "execution_authority": "denied",
            "goal_id": "EMBER-02",
            "next_executed_outcome": "authority classification only",
        }
    }
    config_path = root / "configs" / "historical.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    for rel in (
        "scripts/conv_c03_muon_ns3_live.py",
        "scripts/timeshare_pretrain.py",
        "scripts/train_multimodal_v0.py",
    ):
        runner = root / rel
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text(
            "# EMBER_ARTIFACT_CLASS=historical_only\n"
            "raise SystemExit('historical_only: fixture')\n",
            encoding="utf-8",
        )

    policy = copy.deepcopy(VALID_POLICY)
    policy["conservation_hashes"] = {
        "authority_matrix_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest().upper(),
        "governing_surfaces_sha256": {
            rel: hashlib.sha256((root / rel).read_bytes()).hexdigest().upper()
            for rel in GOVERNING_SURFACES
        },
    }
    (root / "GOAL.md").write_text(render_goal(policy), encoding="utf-8")


def run_verifier(
    root: Path,
    selection: Path | None = None,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VERIFIER), "--root", str(root), "--json"]
    if selection is not None:
        command.extend(["--selection", str(selection)])
    command.extend(extra_args)
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

def rewrite_policy(root: Path, mutate) -> None:
    text = (root / "GOAL.md").read_text(encoding="utf-8")
    match = re.search(r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", text, re.DOTALL)
    assert match is not None
    policy = json.loads(match.group(1))
    mutate(policy)
    (root / "GOAL.md").write_text(render_goal(policy), encoding="utf-8")


def refresh_continuity_hash(root: Path) -> None:
    digest = hashlib.sha256((root / "CONTINUITY.md").read_bytes()).hexdigest().upper()
    rewrite_policy(
        root,
        lambda policy: policy["conservation_hashes"]["governing_surfaces_sha256"].update(
            {"CONTINUITY.md": digest}
        ),
    )


def rewrite_boundary(root: Path, mutate) -> None:
    path = root / "CONTINUITY.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"<!--\s*EMBER_EXECUTION_BOUNDARY_V1\s*\r?\n(.*?)\r?\n-->",
        text,
        re.DOTALL,
    )
    assert match is not None
    boundary = json.loads(match.group(1))
    mutate(boundary)
    text = (
        text[: match.start()]
        + render_boundary(boundary).rstrip("\n")
        + text[match.end() :]
    )
    path.write_text(text, encoding="utf-8")
    refresh_continuity_hash(root)


def assert_rejected(root: Path, code: str, selection: Path | None = None) -> None:
    result = run_verifier(root, selection)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert code in {item["code"] for item in payload["errors"]}, payload


def test_valid_authority_fixture_passes(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["certificate_legs"] == {str(i): True for i in range(1, 8)}


def test_repository_old_or_new_authority_layout_passes() -> None:
    result = run_verifier(REPO_ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_duplicate_governing_surface_migration_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    new_matrix = tmp_path / "docs" / "authority" / "ember-authority-matrix.md"
    old_matrix = tmp_path / "docs" / "ember-authority-matrix.md"
    old_matrix.write_bytes(new_matrix.read_bytes())

    assert_rejected(tmp_path, "surface.path_duplicate")


def migrate_authority_fixture(root: Path) -> None:
    authority = root / "docs" / "authority"
    authority.mkdir(parents=True, exist_ok=True)
    goal_authority = root / "docs" / "domains" / "governance" / "authority"
    goal_authority.mkdir(parents=True, exist_ok=True)
    for name in (
        "GOAL.md",
        "INVARIANT.md",
        "GOVERNANCE.md",
        "CONTINUITY.md",
        "REDACTIONS.md",
        "STATE.md",
    ):
        destination = goal_authority / name if name == "GOAL.md" else authority / name
        (root / name).replace(destination)

    matrix_path = root / "docs" / "authority" / "ember-authority-matrix.md"
    matrix_path.write_text(
        matrix_path.read_text(encoding="utf-8").replace(
            "| ENFORCED | GOAL.md |", "| ENFORCED | docs/domains/governance/authority/GOAL.md |"
        ),
        encoding="utf-8",
    )
    matrix_digest = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    crosswalk_path = (
        root
        / "manifests"
        / "authority"
        / "issue-35-authority-supersession-crosswalk-v1.json"
    )
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    crosswalk["current_authority"]["matrix_sha256"] = matrix_digest
    for registry in crosswalk["source_registries"]:
        for evidence in registry["evidence"]:
            evidence["sha256"] = matrix_digest
    for row in crosswalk["rows"]:
        for evidence in row["evidence"]:
            evidence["sha256"] = matrix_digest
    crosswalk.pop("crosswalk_sha256")
    crosswalk["crosswalk_sha256"] = hashlib.sha256(
        json.dumps(
            crosswalk, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    crosswalk_path.write_text(
        json.dumps(crosswalk, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    goal_path = goal_authority / "GOAL.md"
    text = goal_path.read_text(encoding="utf-8")
    match = re.search(r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", text, re.DOTALL)
    assert match is not None
    policy = json.loads(match.group(1))
    policy["highest_amendable_authority"] = "docs/domains/governance/authority/GOAL.md"
    policy["required_governing_surfaces"] = [
        f"docs/authority/{rel}"
        if rel in {"GOVERNANCE.md", "CONTINUITY.md"}
        else rel
        for rel in policy["required_governing_surfaces"]
    ]
    hashes = policy["conservation_hashes"]["governing_surfaces_sha256"]
    for name in ("GOVERNANCE.md", "CONTINUITY.md"):
        hashes[f"docs/authority/{name}"] = hashes.pop(name)
    hashes["docs/authority/ember-authority-matrix.md"] = matrix_digest.upper()
    policy["conservation_hashes"]["authority_matrix_sha256"] = matrix_digest.upper()
    goal_path.write_text(render_goal(policy), encoding="utf-8")


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    (
        ("docs/authority/STATE.md", "docs/authority/STATE.md"),
        (
            "docs/domains/governance/authority/STATE.md",
            "docs/domains/governance/authority/STATE.md",
        ),
    ),
)
def test_state_transition_path_accepts_one_candidate(
    tmp_path: Path, relative_path: str, expected: str
) -> None:
    verifier = load_verifier_module()
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[CONTINUITY.md](CONTINUITY.md)\n", encoding="utf-8")

    assert verifier.authority_relative_path(tmp_path, "STATE.md") == expected


def test_state_transition_path_rejects_two_candidates(tmp_path: Path) -> None:
    verifier = load_verifier_module()
    for relative_path in (
        "docs/authority/STATE.md",
        "docs/domains/governance/authority/STATE.md",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[CONTINUITY.md](CONTINUITY.md)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate canonical authority document STATE.md"):
        verifier.authority_relative_path(tmp_path, "STATE.md")


def test_migrated_authority_fixture_passes(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    migrate_authority_fixture(tmp_path)

    result = run_verifier(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", (
    "GOAL.md",
    "INVARIANT.md",
    "GOVERNANCE.md",
    "CONTINUITY.md",
    "REDACTIONS.md",
    "STATE.md",
))
def test_duplicate_authority_path_is_rejected(tmp_path: Path, name: str) -> None:
    write_valid_fixture(tmp_path)
    migrated = (
        tmp_path / "docs" / "domains" / "governance" / "authority" / name
        if name == "GOAL.md"
        else tmp_path / "docs" / "authority" / name
    )
    migrated.parent.mkdir(parents=True, exist_ok=True)
    migrated.write_bytes((tmp_path / name).read_bytes())

    result = run_verifier(tmp_path)

    assert result.returncode != 0
    assert "authority.path_duplicate" in result.stdout
    assert name in result.stdout


def test_execution_boundary_missing_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    path = tmp_path / "CONTINUITY.md"
    text = re.sub(
        r"\n?<!--\s*EMBER_EXECUTION_BOUNDARY_V1\s*\r?\n.*?\r?\n-->\r?\n?",
        "\n",
        path.read_text(encoding="utf-8"),
        count=1,
        flags=re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")
    refresh_continuity_hash(tmp_path)
    assert_rejected(tmp_path, "boundary.missing")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda boundary: boundary.update(allows_new_network=False),
            "boundary.new_network_mismatch",
        ),
        (
            lambda boundary: boundary.update(execution_class="authority_only"),
            "boundary.execution_class_mismatch",
        ),
        (
            lambda boundary: boundary.update(goal_id="EMBER-01"),
            "boundary.goal_mismatch",
        ),
        (
            lambda boundary: boundary.update(
                next_executed_outcome="EMBER-01 clean 3B custody and identity spine"
            ),
            "boundary.outcome_mismatch",
        ),
        (
            lambda boundary: boundary["blocked_operations"].remove(
                "sub_3b_new_network"
            ),
            "boundary.blocked_operation_erased",
        ),
    ],
)
def test_execution_boundary_incompatibility_is_rejected(
    tmp_path: Path, mutation, code: str
) -> None:
    write_valid_fixture(tmp_path)
    rewrite_boundary(tmp_path, mutation)
    assert_rejected(tmp_path, code)


def test_execution_boundary_tracks_policy_not_constants(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    rewrite_policy(
        tmp_path,
        lambda policy: policy.update(
            authority_only_goal=True,
            allows_new_network=False,
        ),
    )
    result = run_verifier(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    codes = {item["code"] for item in json.loads(result.stdout)["errors"]}
    assert {
        "boundary.execution_class_mismatch",
        "boundary.new_network_mismatch",
    } <= codes


def test_lower_precedence_document_cannot_authorize_completion(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    rogue = tmp_path / "docs" / "rogue-goal.md"
    rogue.write_text(
        "# Active Ember goal\n\n"
        "This document is a binding completion law and authorizes a completed Ember model.\n",
        encoding="utf-8",
    )
    result = run_verifier(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "authority.lower_precedence_claim" in {
        item["code"] for item in payload["errors"]
    }


def test_untracked_authority_shaped_scratch_is_not_part_of_git_guard(tmp_path: Path, monkeypatch) -> None:
    """Only untracked scratch products are outside the commit-level scan."""
    (tmp_path / ".git").write_text("gitdir: fixture\n", encoding="utf-8")
    tracked = "scratch/tracked.md"
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import verify_authority_conservation as verifier

    monkeypatch.setattr(
        verifier,
        "subprocess",
        SimpleNamespace(
            run=lambda *args, **kwargs: subprocess.CompletedProcess(
                args, 0, stdout=(tracked + "\0").encode(), stderr=b""
            )
        ),
    )
    rogue = tmp_path / "scratch" / "historical-authority.md"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text(
        "# Active Ember goal\n\n"
        "This document is a binding completion law and authorizes a completed Ember model.\n",
        encoding="utf-8",
    )
    tracked_file = tmp_path / tracked
    tracked_file.write_text(rogue.read_text(encoding="utf-8"), encoding="utf-8")
    errors: list[dict] = []
    verifier.check_lower_precedence_authority(tmp_path, errors)
    assert [item["code"] for item in errors] == ["authority.lower_precedence_claim"]


def test_explicitly_historical_document_has_no_live_authority(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    historical = tmp_path / "docs" / "old-launch-brief.md"
    historical.write_text(
        "<!-- EMBER_ARTIFACT_CLASS=historical_only -->\n\n"
        "# Launch authorization\n\n"
        "This preserved record authorized a superseded experiment.\n",
        encoding="utf-8",
    )
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_registry_status_cannot_erase_a_research_family(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    registry = tmp_path / "docs" / "ledgers" / "technique-registry.jsonl"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"id": "exact-twin", "status": "KILL"}) + "\n",
        encoding="utf-8",
    )
    result = run_verifier(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "authority.mechanism_erasure" in {
        item["code"] for item in payload["errors"]
    }


def test_executable_cannot_relegalize_terminal_registry_status(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    bypass = tmp_path / "scripts" / "bypass.py"
    bypass.parent.mkdir(parents=True, exist_ok=True)
    bypass.write_text(
        'import registry_gate as gate\n'
        'gate.LEGAL_STATUSES = gate.LEGAL_STATUSES | {"PARK"}\n',
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "authority.mechanism_erasure_bypass")


def test_enforced_matrix_row_must_name_a_real_surface(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    manifest = tmp_path / "docs" / "authority" / "ember-authority-matrix.md"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace(
        "| D-062 | ENFORCED | GOAL.md |",
        "| D-062 | ENFORCED | docs/does-not-exist.md |",
    )
    manifest.write_text(text, encoding="utf-8")
    result = run_verifier(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "manifest.enforcement_target_missing" in {
        item["code"] for item in payload["errors"]
    }


def write_ember02_selection(root: Path) -> Path:
    goal = (
        root
        / "goals"
        / "ember"
        / "ember-02-3b-foundation-birth"
        / "goal.md"
    )
    goal.parent.mkdir(parents=True, exist_ok=True)
    goal.write_text(
        "---\ngoal_id: EMBER-02\nallows_new_network: true\n---\n",
        encoding="utf-8",
    )
    selection = root / "selection.md"
    selection.write_text(
        "state: active\n"
        "active_goal: EMBER-02\n"
        "active_goal_path: "
        "goals/ember/ember-02-3b-foundation-birth/goal.md\n",
        encoding="utf-8",
    )
    return selection


def test_historical_artifact_preserves_original_goal_across_transition(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    config = tmp_path / "configs" / "historical.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["authority"]["goal_id"] = "EMBER-00"
    config.write_text(json.dumps(payload), encoding="utf-8")
    result = run_verifier(tmp_path, write_ember02_selection(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_nonhistorical_artifact_goal_id_must_match_durable_selection(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    borrowed = tmp_path / "configs" / "borrowed.json"
    borrowed.write_text(
        json.dumps(
            {
                "authority": {
                    "artifact_class": "borrowed_reference",
                    "execution_authority": "reference_only",
                    "goal_id": "EMBER-00",
                    "next_executed_outcome": "reference comparison",
                    "capability_credit": "none",
                    "frozen": True,
                    "lineage_ingress": False,
                    "model_mediated_signals": [],
                }
            }
        ),
        encoding="utf-8",
    )
    result = run_verifier(tmp_path, write_ember02_selection(tmp_path))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.goal_binding" in {item["code"] for item in payload["errors"]}


def test_ember02_selection_requires_exact_goal_path(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    selection = tmp_path / "selection.md"
    selection.write_text(
        "state: active\n"
        "active_goal: EMBER-02\n"
        "active_goal_path: goals/ember/not-the-custody-spine/EMBER-02/goal.md\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "selection.path_exact_mismatch", selection)


def test_selection_rejects_duplicate_control_keys(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    selection = tmp_path / "selection.md"
    selection.write_text(
        "state: paused\n"
        "state: active\n"
        "active_goal: EMBER-02\n"
        "active_goal_path: goals/ember/ember-02-3b-foundation-birth/goal.md\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "selection.duplicate_key", selection)


def test_exact_ember02_selection_and_goal_file_pass(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    goal = (
        tmp_path
        / "goals"
        / "ember"
        / "ember-02-3b-foundation-birth"
        / "goal.md"
    )
    goal.parent.mkdir(parents=True)
    goal.write_text(
        "---\ngoal_id: EMBER-02\nallows_new_network: true\n---\n",
        encoding="utf-8",
    )
    selection = tmp_path / "selection.md"
    selection.write_text(
        "state: active\n"
        "active_goal: EMBER-02\n"
        "active_goal_path: goals/ember/ember-02-3b-foundation-birth/goal.md\n",
        encoding="utf-8",
    )
    result = run_verifier(tmp_path, selection)
    assert result.returncode == 0, result.stdout + result.stderr


def write_graph_selection(root: Path) -> Path:
    write_valid_fixture(root)
    authority_root = root / "authority"
    coordinator_root = authority_root / "coordinator"
    nodes = []
    for workstream in (
        "EMBER-01",
        "EMBER-02A",
        "EMBER-02B",
        "EMBER-02C",
        "EMBER-02P",
    ):
        relative_goal = Path("coordinator") / "goals" / workstream / "goal.md"
        goal = authority_root / relative_goal
        goal.parent.mkdir(parents=True, exist_ok=True)
        goal.write_text(f"# {workstream}\n", encoding="utf-8")
        nodes.append(
            {
                "id": workstream,
                "goal_path": relative_goal.as_posix(),
                "goal_sha256": hashlib.sha256(goal.read_bytes()).hexdigest(),
                "state": "PRESTAGING",
            }
        )
    graph = coordinator_root / "EMBER-GOAL-GRAPH.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text(
        json.dumps(
            {
                "schema_version": "ember-goal-graph-v1",
                "program": {"id": "EMBER", "state": "ACTIVE"},
                "nodes": nodes,
            }
        ),
        encoding="utf-8",
    )
    selection = coordinator_root / "EMBER-GOAL-RESUME.md"
    selection.write_text(
        "state: active\n"
        "active_goal: graph\n"
        f"active_goal_path: {graph}\n",
        encoding="utf-8",
    )
    return selection


def test_graph_selection_binds_active_workstream_goal_bytes(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 0, result.stdout + result.stderr


def test_graph_selection_rejects_stale_workstream_goal_hash(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)
    graph_path = selection.parent / "EMBER-GOAL-GRAPH.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["nodes"][1]["goal_sha256"] = "0" * 64
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_goal_hash_mismatch" in {
        item["code"] for item in payload["errors"]
    }


def mutate_graph(selection: Path, mutation) -> None:
    graph_path = selection.parent / "EMBER-GOAL-GRAPH.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    mutation(graph)
    graph_path.write_text(json.dumps(graph), encoding="utf-8")


@pytest.mark.parametrize("extra_id", ["EMBER-99", "EMBER-02A-shadow"])
def test_graph_selection_rejects_unlisted_node_id(
    tmp_path: Path, extra_id: str
) -> None:
    selection = write_graph_selection(tmp_path)

    def add_unlisted(graph: dict) -> None:
        node = copy.deepcopy(graph["nodes"][1])
        node["id"] = extra_id
        graph["nodes"].append(node)

    mutate_graph(selection, add_unlisted)

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_node_set" in {
        item["code"] for item in payload["errors"]
    }


def test_graph_selection_rejects_duplicate_expected_node(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)

    def duplicate_expected(graph: dict) -> None:
        graph["nodes"].append(copy.deepcopy(graph["nodes"][1]))

    mutate_graph(selection, duplicate_expected)

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_workstream" in {
        item["code"] for item in payload["errors"]
    }


def test_graph_selection_rejects_invalid_node_state(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)
    mutate_graph(selection, lambda graph: graph["nodes"][1].update(state="PAUSED"))

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_workstream_state" in {
        item["code"] for item in payload["errors"]
    }


@pytest.mark.parametrize("goal_path", ["../escaped/goal.md", "C:/escaped/goal.md"])
def test_graph_selection_rejects_goal_path_escape(
    tmp_path: Path, goal_path: str
) -> None:
    selection = write_graph_selection(tmp_path)
    mutate_graph(
        selection,
        lambda graph: graph["nodes"][1].update(goal_path=goal_path),
    )

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert {
        "selection.graph_goal_path",
        "selection.graph_goal_path_escape",
    } & {item["code"] for item in payload["errors"]}


def test_graph_selection_rejects_inactive_program(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)
    mutate_graph(
        selection,
        lambda graph: graph["program"].update(state="PAUSED"),
    )

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_program" in {
        item["code"] for item in payload["errors"]
    }


def test_graph_selection_rejects_schema_mismatch(tmp_path: Path) -> None:
    selection = write_graph_selection(tmp_path)
    mutate_graph(
        selection,
        lambda graph: graph.update(schema_version="ember-goal-graph-v0"),
    )

    result = run_verifier(tmp_path, selection)

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "selection.graph_schema" in {
        item["code"] for item in payload["errors"]
    }


def test_hash_bound_external_classification_supports_protected_control_json(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    protected = tmp_path / "configs" / "protected-control.json"
    protected.write_text("[]\n", encoding="utf-8")
    digest = hashlib.sha256(protected.read_bytes()).hexdigest()
    with (tmp_path / "CONTINUITY.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n| path | artifact_class | execution_authority | goal_id | "
            "next_executed_outcome | sha256 |\n"
            "|---|---|---|---|---|---|\n"
            "| configs/protected-control.json | historical_only | denied | "
            f"EMBER-02 | authority classification only | {digest} |\n"
        )
    refresh_continuity_hash(tmp_path)
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_external_config_classification_is_bound_to_exact_bytes(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    protected = tmp_path / "configs" / "protected-control.json"
    protected.write_text("[]\n", encoding="utf-8")
    with (tmp_path / "CONTINUITY.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n| path | artifact_class | execution_authority | goal_id | "
            "next_executed_outcome | sha256 |\n"
            "|---|---|---|---|---|---|\n"
            "| configs/protected-control.json | historical_only | denied | "
            f"EMBER-02 | authority classification only | {'0' * 64} |\n"
        )
    refresh_continuity_hash(tmp_path)
    assert_rejected(tmp_path, "config.classification_hash_mismatch")

def test_invariant_tamper_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    with (tmp_path / "INVARIANT.md").open("ab") as stream:
        stream.write(b"tamper")
    assert_rejected(tmp_path, "invariant.hash")


def test_missing_discrepancy_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    manifest = tmp_path / "docs" / "authority" / "ember-authority-matrix.md"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text(
        "\n".join(line for line in lines if "| D-062 |" not in line) + "\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "manifest.discrepancy_missing")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda policy: policy["model_birth"].update(
                minimum_total_parameters=2_200_000_000
            ),
            "policy.minimum_3b",
        ),
        (
            lambda policy: policy["model_birth"]["required_native_capabilities"].remove(
                "audio"
            ),
            "policy.native_capabilities",
        ),
        (
            lambda policy: policy["model_birth"]["required_native_capabilities"].remove(
                "reasoning"
            ),
            "policy.native_capabilities",
        ),
        (
            lambda policy: policy["architecture"].update(
                published_family_backbone_allowed=True
            ),
            "policy.published_backbone",
        ),
        (
            lambda policy: policy["negative_evidence"].update(
                may_erase_research_family=True
            ),
            "policy.negative_evidence.may_erase_research_family",
        ),
        (
            lambda policy: policy["totality"].remove("general_local_ai_laboratory"),
            "policy.totality",
        ),
        (
            lambda policy: policy["reasoning_evidence"]["forbidden_substitutes"].remove(
                "tool_wrapper"
            ),
            "policy.reasoning.substitutes",
        ),
        (
            lambda policy: policy.update(authority_only_goal=True),
            "policy.authority_only",
        ),
        (
            lambda policy: policy["mutation_controls_required"].remove(
                "ambiguous_identity"
            ),
            "policy.mutation_controls",
        ),
        (
            lambda policy: policy["benchmark_custody"][
                "recovered_operator_mandate"
            ].remove("Terminal-Bench 2.1"),
            "policy.benchmark_mandate",
        ),
    ],
)
def test_policy_drift_mutations_are_rejected(tmp_path: Path, mutation, code: str) -> None:
    write_valid_fixture(tmp_path)
    rewrite_policy(tmp_path, mutation)
    assert_rejected(tmp_path, code)


@pytest.mark.parametrize(
    ("authority_patch", "code"),
    [
        ({"total_parameters": 2_200_000_000}, "config.sub_3b_network"),
        ({"published_family_backbone": "llama"}, "config.borrowed_backbone"),
        ({"model_mediated_signals": ["teachers"]}, "config.model_mediated_signal"),
    ],
)
def test_candidate_lineage_mutations_are_rejected(
    tmp_path: Path, authority_patch: dict, code: str
) -> None:
    write_valid_fixture(tmp_path)
    authority = {
        "artifact_class": "research_candidate",
        "execution_authority": "allowed",
        "goal_id": "EMBER-02",
        "next_executed_outcome": "clean 3B birth",
        "total_parameters": 3_000_000_000,
        "native_capabilities": copy.deepcopy(
            VALID_POLICY["model_birth"]["required_native_capabilities"]
        ),
        "published_family_backbone": "none",
        "model_mediated_signals": [],
    }
    authority.update(authority_patch)
    config = tmp_path / "configs" / "candidate.json"
    config.write_text(json.dumps({"authority": authority}), encoding="utf-8")
    assert_rejected(tmp_path, code)


def test_missing_goal_binding_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    config = tmp_path / "configs" / "historical.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    del payload["authority"]["goal_id"]
    config.write_text(json.dumps(payload), encoding="utf-8")
    assert_rejected(tmp_path, "config.goal_id_missing")


def test_content_addressed_authority_sidecar_is_validated_without_model_semantics(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    artifact = tmp_path / "configs" / "historical.json"
    sidecar = tmp_path / "configs" / "historical.authority.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": "ember-content-addressed-authority-binding/v1",
                "artifact_path": "configs/historical.json",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "authority": {
                    "goal_id": "EMBER-02",
                    "workstream_id": "EMBER-02A",
                    "next_executed_outcome": (
                        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
                    ),
                    "artifact_class": "historical_only",
                    "execution_authority": "denied",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["artifact_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    assert_rejected(tmp_path, "config.authority_sidecar_invalid")


def test_any_declared_model_mediated_signal_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    config = tmp_path / "configs" / "candidate.json"
    config.write_text(
        json.dumps(
            {
                "authority": {
                    "artifact_class": "research_candidate",
                    "execution_authority": "allowed",
                    "goal_id": "EMBER-02",
                    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
                    "total_parameters": 3_000_000_000,
                    "native_capabilities": [
                        "text",
                        "image",
                        "audio",
                        "reasoning",
                        "structured_tool_use",
                    ],
                    "published_family_backbone": "none",
                    "model_mediated_signals": ["distillation"],
                }
            }
        ),
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "config.model_mediated_signal")


def test_borrowed_reference_requires_frozen_non_ingress_seat(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    config = tmp_path / "configs" / "borrowed.json"
    config.write_text(
        json.dumps(
            {
                "authority": {
                    "artifact_class": "borrowed_reference",
                    "execution_authority": "reference_only",
                    "goal_id": "EMBER-02",
                    "next_executed_outcome": "reference comparison",
                    "capability_credit": "none",
                    "frozen": False,
                    "lineage_ingress": True,
                    "model_mediated_signals": [],
                }
            }
        ),
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "config.borrowed_not_frozen")
    assert_rejected(tmp_path, "config.borrowed_lineage_ingress")


def test_governing_surface_semantic_mutation_breaks_hash(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    surface = tmp_path / "docs" / "contracts" / "goal-clear-protocol.md"
    surface.write_text(
        surface.read_text(encoding="utf-8") + "\nAudio may be deferred.\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "surface.hash_mismatch")


def test_matrix_semantic_mutation_breaks_hash(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    matrix = tmp_path / "docs" / "authority" / "ember-authority-matrix.md"
    matrix.write_text(
        matrix.read_text(encoding="utf-8").replace(
            "ledger D-045", "requirement meaning erased"
        ),
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "manifest.hash_mismatch")


def test_historical_training_runner_cannot_be_reenabled(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    runner = tmp_path / "scripts" / "train_multimodal_v0.py"
    runner.write_text(
        "# EMBER_ARTIFACT_CLASS=historical_only\nprint('live again')\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "historical.execution_guard_missing")


def test_future_artifact_binding_parser_is_exact() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from verify_authority_conservation import validate_artifact_binding

    goal = "EMBER-00"
    outcome = "EMBER-02 clean 3B custody and identity spine"
    workstream = "EMBER-00A"
    allowed = (workstream,)
    assert validate_artifact_binding(
        json.dumps(
            {
                "goal_id": goal,
                "workstream_id": workstream,
                "next_executed_outcome": outcome,
            }
        ),
        ".json",
        goal,
        outcome,
        allowed,
    )
    assert not validate_artifact_binding(
        json.dumps(
            {
                "goal_id": goal,
                "workstream_id": "EMBER-99Z",
                "next_executed_outcome": outcome,
            }
        ),
        ".json",
        goal,
        outcome,
        allowed,
    )
    assert validate_artifact_binding(
        f"# goal_id: {goal}\n"
        f"# workstream_id: {workstream}\n"
        f"# next_executed_outcome: {outcome}\n",
        ".py",
        goal,
        outcome,
        allowed,
    )
    assert not validate_artifact_binding(
        json.dumps({"goal_id": goal, "next_executed_outcome": "later"}),
        ".json",
        goal,
        outcome,
        allowed,
    )
    assert validate_artifact_binding(
        json.dumps(
            {
                "goal_id": goal,
                "workstream_id": workstream,
                "next_executed_outcome": outcome,
            }
        )
        + "\n",
        ".jsonl",
        goal,
        outcome,
        allowed,
    )
    assert validate_artifact_binding(
        f"# goal_id: {goal}\n"
        f"# workstream_id: {workstream}\n"
        f"# next_executed_outcome: {outcome}\n",
        ".py",
        goal,
        outcome,
        allowed,
    )
    assert validate_artifact_binding(
        f"// goal_id: {goal}\n"
        f"// workstream_id: {workstream}\n"
        f"// next_executed_outcome: {outcome}\n",
        ".ts",
        goal,
        outcome,
        allowed,
    )
    assert not validate_artifact_binding(
        json.dumps({"goal_id": goal, "next_executed_outcome": outcome}),
        ".json",
        goal,
        outcome,
        allowed,
    )


def test_future_artifact_binding_accepts_only_named_child_workstreams() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from verify_authority_conservation import validate_artifact_binding

    goal = "EMBER-02"
    outcome = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    allowed = ("EMBER-02A", "EMBER-02B", "EMBER-02C")
    assert validate_artifact_binding(
        json.dumps(
            {
                "goal_id": goal,
                "workstream_id": "EMBER-02B",
                "next_executed_outcome": outcome,
            }
        ),
        ".json",
        goal,
        outcome,
        allowed,
    )


def test_workstream_path_scope_prevents_parallel_authority_overlap() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from verify_authority_conservation import workstream_path_allowed

    scopes = {
        "EMBER-02A": {
            "mode": "all_except",
            "prefixes": ["manifests/ember-01-custody/", "scripts/ember_01_custody/"],
        },
        "EMBER-02B": {
            "mode": "only",
            "prefixes": ["manifests/ember-01-custody/", "scripts/ember_01_custody/"],
        },
    }
    assert workstream_path_allowed("GOAL.md", "EMBER-02A", scopes)
    assert not workstream_path_allowed(
        "scripts/ember_01_custody/hash_roots.py", "EMBER-02A", scopes
    )
    assert workstream_path_allowed(
        "scripts/ember_01_custody/hash_roots.py", "EMBER-02B", scopes
    )
    assert not workstream_path_allowed(
        "scripts/verify_authority_conservation.py", "EMBER-02B", scopes
    )


def test_source_annotations_are_not_authority_markers() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from verify_authority_conservation import validate_artifact_binding

    text = (
        "# goal_id: EMBER-02\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
        "def check(\n"
        "    workstream_id: str,\n"
        ") -> bool:\n"
        "    return True\n"
    )
    assert validate_artifact_binding(
        text,
        ".py",
        "EMBER-02",
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        ("EMBER-02A",),
    )


def test_pre_push_guard_uses_the_selected_remote_not_origin() -> None:
    hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert 'REMOTE_MASTER="$REMOTE/master"' in hook
    assert "origin/master" not in hook


def git_fixture(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_staged_verification_reads_governing_bytes_from_index(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "add", ".")

    matrix = tmp_path / "docs" / "authority" / "ember-authority-matrix.md"
    valid_working_copy = matrix.read_text(encoding="utf-8")
    matrix.write_text(
        valid_working_copy.replace("ledger D-045", "staged semantic drift"),
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", "docs/authority/ember-authority-matrix.md")
    matrix.write_text(valid_working_copy, encoding="utf-8")

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "manifest.hash_mismatch" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_staged_binding_covers_scripts_and_python_experiments(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    control = tmp_path / "scripts" / "new_control.py"
    control.write_text("print('control')\n", encoding="utf-8")
    git_fixture(tmp_path, "add", "scripts/new_control.py")
    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload

    binding = (
        "# goal_id: EMBER-02\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
    )
    control.write_text(binding + "print('control')\n", encoding="utf-8")
    experiment = tmp_path / "experiments" / "candidate.py"
    experiment.parent.mkdir(parents=True, exist_ok=True)
    experiment.write_text(binding + "print('candidate')\n", encoding="utf-8")
    ts_binding = binding.replace("# ", "// ")
    ts_control = tmp_path / "tools" / "new_control.ts"
    ts_control.parent.mkdir(parents=True, exist_ok=True)
    ts_control.write_text(ts_binding + "export const control = true;\n", encoding="utf-8")
    git_fixture(
        tmp_path,
        "add",
        "scripts/new_control.py",
        "experiments/candidate.py",
        "tools/new_control.ts",
    )
    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 0, result.stdout + result.stderr


def test_staged_exact_authority_path_migration_does_not_mint_new_authority(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    control = tmp_path / "scripts" / "legacy_path_consumer.py"
    control.write_text('GOAL_PATH = "GOAL.md"\n', encoding="utf-8")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    control.write_text(
        'GOAL_PATH = "docs/domains/governance/authority/GOAL.md"\n', encoding="utf-8"
    )
    git_fixture(tmp_path, "add", "scripts/legacy_path_consumer.py")
    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 0, result.stdout + result.stderr


def test_staged_authority_path_migration_rejects_mixed_behavior_change(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    control = tmp_path / "scripts" / "legacy_path_consumer.py"
    control.write_text('GOAL_PATH = "GOAL.md"\n', encoding="utf-8")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    control.write_text(
        'GOAL_PATH = "docs/domains/governance/authority/GOAL.md"\nprint("new behavior")\n',
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", "scripts/legacy_path_consumer.py")
    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def stage_cross_workstream_path_migration(
    root: Path,
    *,
    extra_consumer_bytes: str = "",
    consumer_path: str = "tools/ember-restart-3b/consumer.py",
) -> None:
    """Stage one tracked rename plus an exact 02B consumer path rewrite."""
    write_valid_fixture(root)
    git_fixture(root, "init")
    git_fixture(root, "config", "user.email", "fixture@example.invalid")
    git_fixture(root, "config", "user.name", "fixture")
    legacy = root / "legacy" / "module.py"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        "# goal_id: EMBER-02\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )
    consumer = root / Path(*consumer_path.split("/"))
    consumer.parent.mkdir(parents=True, exist_ok=True)
    consumer.write_text(
        "# goal_id: EMBER-02\n"
        "# workstream_id: EMBER-02B\n"
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
        'MODULE_PATH = "legacy/module.py"\n',
        encoding="utf-8",
    )
    git_fixture(root, "add", ".")
    git_fixture(root, "commit", "-m", "fixture")

    destination = root / "src" / "module.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    git_fixture(root, "mv", "legacy/module.py", "src/module.py")
    consumer.write_text(
        consumer.read_text(encoding="utf-8").replace(
            "legacy/module.py", "src/module.py"
        )
        + extra_consumer_bytes,
        encoding="utf-8",
    )
    migration = (
        root
        / "manifests"
        / "authority"
        / "path-migrations"
        / "fixture-migration-v1.json"
    )
    migration.parent.mkdir(parents=True, exist_ok=True)
    migration.write_text(
        json.dumps(
            {
                "schema_version": "ember-exact-path-migration-map/v1",
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": (
                    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
                ),
                "renames": [
                    {
                        "source_path": "legacy/module.py",
                        "target_path": "src/module.py",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git_fixture(root, "add", ".")


def check_staged_for_pr_workstream(root: Path, expected: str) -> list[dict[str, object]]:
    verifier = load_verifier_module()
    errors: list[dict[str, object]] = []
    verifier.check_changed_artifact_bindings(
        root,
        copy.deepcopy(VALID_POLICY),
        errors,
        staged=True,
        expected_workstream=expected,
    )
    return errors


def test_tracked_exact_rename_map_authorizes_cross_workstream_path_only_delta(
    tmp_path: Path,
) -> None:
    stage_cross_workstream_path_migration(tmp_path)

    assert check_staged_for_pr_workstream(tmp_path, "EMBER-02A") == []


def test_tracked_exact_rename_map_rejects_path_rewrite_plus_one_extra_byte(
    tmp_path: Path,
) -> None:
    stage_cross_workstream_path_migration(
        tmp_path, extra_consumer_bytes='print("semantic change")\n'
    )

    errors = check_staged_for_pr_workstream(tmp_path, "EMBER-02A")
    assert "artifact.pr_workstream_mismatch" in {
        item["code"] for item in errors
    }, errors


def test_tracked_exact_rename_map_does_not_bypass_owner_scope(
    tmp_path: Path,
) -> None:
    stage_cross_workstream_path_migration(
        tmp_path, consumer_path="scripts/consumer.py"
    )

    errors = check_staged_for_pr_workstream(tmp_path, "EMBER-02A")
    assert "artifact.workstream_scope" in {
        item["code"] for item in errors
    }, errors


def test_tracked_exact_rename_map_cannot_authorize_an_unperformed_rename(
    tmp_path: Path,
) -> None:
    stage_cross_workstream_path_migration(tmp_path)
    git_fixture(tmp_path, "mv", "src/module.py", "legacy/module.py")
    git_fixture(tmp_path, "add", ".")

    errors = check_staged_for_pr_workstream(tmp_path, "EMBER-02A")
    assert "artifact.path_migration_rename_missing" in {
        item["code"] for item in errors
    }, errors


def test_changed_range_exact_path_migration_preserves_historical_authority(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    control = tmp_path / "scripts" / "historical_control.py"
    control.write_text(
        "# goal_id: EMBER-00\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-01 clean 3B custody and identity spine\n"
        'INVARIANT_PATH = "INVARIANT.md"\n',
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "historical fixture")

    control.write_text(
        control.read_text(encoding="utf-8").replace(
            '"INVARIANT.md"', '"docs/domains/governance/authority/INVARIANT.md"'
        ),
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", "scripts/historical_control.py")
    git_fixture(tmp_path, "commit", "-m", "move authority path")
    result = run_verifier(
        tmp_path, extra_args=("--changed-range", "HEAD^..HEAD")
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_changed_range_path_migration_rejects_mixed_behavior_change(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    control = tmp_path / "scripts" / "historical_control.py"
    control.write_text(
        "# goal_id: EMBER-00\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-01 clean 3B custody and identity spine\n"
        'INVARIANT_PATH = "INVARIANT.md"\n',
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "historical fixture")

    control.write_text(
        control.read_text(encoding="utf-8").replace(
            '"INVARIANT.md"', '"docs/domains/governance/authority/INVARIANT.md"'
        )
        + 'print("new behavior")\n',
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", "scripts/historical_control.py")
    git_fixture(tmp_path, "commit", "-m", "mixed migration")
    result = run_verifier(
        tmp_path, extra_args=("--changed-range", "HEAD^..HEAD")
    )
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_changed_range_uses_committed_endpoint_not_dirty_worktree(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    control = tmp_path / "scripts" / "historical_control.py"
    historical = (
        "# goal_id: EMBER-00\n"
        "# workstream_id: EMBER-02A\n"
        "# next_executed_outcome: EMBER-01 clean 3B custody and identity spine\n"
        'INVARIANT_PATH = "INVARIANT.md"\n'
    )
    control.write_text(historical, encoding="utf-8")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "historical fixture")

    migrated = historical.replace(
        '"INVARIANT.md"', '"docs/domains/governance/authority/INVARIANT.md"'
    )
    control.write_text(migrated + 'print("committed behavior")\n', encoding="utf-8")
    git_fixture(tmp_path, "add", "scripts/historical_control.py")
    git_fixture(tmp_path, "commit", "-m", "mixed migration")

    # A dirty worktree must not hide the semantic edit already committed at
    # the right endpoint of the range.
    control.write_text(migrated, encoding="utf-8")
    _write_sidecar(
        tmp_path,
        "scripts/historical_control.py",
        control.read_bytes(),
    )
    result = run_verifier(
        tmp_path, extra_args=("--changed-range", "HEAD^..HEAD")
    )
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_renamed_control_cannot_drop_binding_or_escape_by_path(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    original = tmp_path / "scripts" / "bound_control.py"
    binding = (
        "# goal_id: EMBER-02\n"
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
    )
    body = "".join(f"VALUE_{index} = {index}\n" for index in range(30))
    original.write_text(binding + body, encoding="utf-8")
    git_fixture(tmp_path, "add", "scripts/bound_control.py")
    git_fixture(tmp_path, "commit", "-m", "bound control")

    destination = tmp_path / "baseline" / "renamed_control.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    git_fixture(
        tmp_path,
        "mv",
        "scripts/bound_control.py",
        "baseline/renamed_control.py",
    )
    destination.write_text(body, encoding="utf-8")
    git_fixture(tmp_path, "add", "baseline/renamed_control.py")
    name_status = git_fixture(
        tmp_path,
        "diff",
        "--cached",
        "--name-status",
        "--find-renames",
    ).stdout
    assert name_status.startswith("R"), name_status

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def _write_sidecar(
    tmp_path: Path,
    artifact_relative: str,
    artifact_bytes: bytes,
    *,
    digest: str | None = None,
    artifact_path: str | None = None,
    goal_id: str = "EMBER-02",
    workstream_id: str = "EMBER-02A",
    next_executed_outcome: str = (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    ),
) -> Path:
    """Write an artifact plus a `<name>.authority.json` sidecar beside it."""
    artifact = tmp_path / artifact_relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(artifact_bytes)
    sidecar = {
        "schema_version": "ember-content-addressed-authority-binding/v1",
        "artifact_path": artifact_path if artifact_path is not None else artifact_relative,
        "artifact_sha256": digest
        if digest is not None
        else hashlib.sha256(artifact_bytes).hexdigest(),
        "authority": {
            "goal_id": goal_id,
            "workstream_id": workstream_id,
            "next_executed_outcome": next_executed_outcome,
        },
    }
    sidecar_path = Path(str(artifact).rsplit(".", 1)[0] + ".authority.json")
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return artifact


def test_sidecar_binds_an_artifact_that_cannot_carry_the_binding_inline(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "receipts/frozen/evidence.json"
    _write_sidecar(
        tmp_path, relative, b'{"schema":"frozen-v1","note":"no inline binding"}'
    )
    git_fixture(
        tmp_path,
        "add",
        relative,
        "receipts/frozen/evidence.authority.json",
    )

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 0, result.stdout + result.stderr


def test_sidecar_binds_unsupported_inline_format_before_format_refusal(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "tools/launchers/Ember.cmd"
    _write_sidecar(tmp_path, relative, b"@echo off\n")
    git_fixture(
        tmp_path,
        "add",
        relative,
        "tools/launchers/Ember.authority.json",
    )

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 0, result.stdout + result.stderr


def test_sidecar_with_wrong_goal_binding_still_fails_leg4(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "receipts/frozen/evidence.json"
    _write_sidecar(
        tmp_path,
        relative,
        b'{"schema":"frozen-v1","note":"wrong goal"}',
        goal_id="EMBER-01",
    )
    git_fixture(
        tmp_path,
        "add",
        relative,
        "receipts/frozen/evidence.authority.json",
    )

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_sidecar_digest_mismatch_is_rejected_not_exempted(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "receipts/frozen/evidence.json"
    _write_sidecar(
        tmp_path,
        relative,
        b'{"schema":"frozen-v1","note":"digest will not match"}',
        digest="0" * 64,
    )
    git_fixture(
        tmp_path,
        "add",
        relative,
        "receipts/frozen/evidence.authority.json",
    )

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_sidecar_pointed_at_a_different_path_does_not_bind(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "receipts/frozen/evidence.json"
    _write_sidecar(
        tmp_path,
        relative,
        b'{"schema":"frozen-v1","note":"sidecar names a different artifact"}',
        artifact_path="receipts/frozen/other.json",
    )
    git_fixture(
        tmp_path,
        "add",
        relative,
        "receipts/frozen/evidence.authority.json",
    )

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


def test_unknown_artifact_without_sidecar_fails_as_today(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "receipts/frozen/evidence.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema":"frozen-v1","note":"no sidecar at all"}', encoding="utf-8")
    git_fixture(tmp_path, "add", relative)

    result = run_verifier(tmp_path, extra_args=("--staged",))
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in payload["errors"]
    }, payload


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("active_goal_id", "policy.active_goal_id"),
        ("next_executed_outcome", "policy.next_executed_outcome"),
    ],
)
def test_policy_requires_exact_goal_execution_binding(
    tmp_path: Path, field: str, code: str
) -> None:
    write_valid_fixture(tmp_path)
    rewrite_policy(tmp_path, lambda policy: policy.pop(field))
    assert_rejected(tmp_path, code)


def test_ambiguous_identity_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    state = tmp_path / "CONTINUITY.md"
    with state.open("a", encoding="utf-8") as stream:
        stream.write(
            "| duplicate | checkpoint | sha256:owned-rung2 | historical_only | "
            "2195000000 | 12550144 | none | none | duplicate identity |\n"
        )
    refresh_continuity_hash(tmp_path)
    assert_rejected(tmp_path, "state.ambiguous_identity")


def _append_execution_measurement_row(tmp_path: Path, evidence: str) -> None:
    with (tmp_path / "CONTINUITY.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "| measured-result | benchmark_result | receipt-sha256:"
            f"{'a' * 64} | execution_measurement_only | not_claimed | 51200 | "
            f"eval_cuda | none | {evidence} |\n"
        )
    refresh_continuity_hash(tmp_path)


def test_execution_measurement_only_row_accepts_closed_claim_boundary(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    _append_execution_measurement_row(
        tmp_path,
        "execution+measurement only; no sufficiency/capability/comparison claim; "
        "caveat: chance-level score",
    )
    result = run_verifier(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_execution_measurement_only_row_without_caveat_is_rejected(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    _append_execution_measurement_row(
        tmp_path,
        "execution+measurement only; no sufficiency/capability/comparison claim",
    )
    assert_rejected(tmp_path, "state.execution_measurement_caveat_missing")


def test_execution_measurement_only_row_with_capability_credit_is_rejected(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    _append_execution_measurement_row(
        tmp_path,
        "execution+measurement only; no sufficiency/capability/comparison claim; "
        "caveat: chance-level score",
    )
    state = tmp_path / "CONTINUITY.md"
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            "| eval_cuda | none | execution+measurement only",
            "| eval_cuda | claimed | execution+measurement only",
        ),
        encoding="utf-8",
    )
    refresh_continuity_hash(tmp_path)
    assert_rejected(tmp_path, "state.execution_measurement_credit")

def test_continuity_identity_rows_loss_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    continuity = tmp_path / "CONTINUITY.md"
    content = continuity.read_text(encoding="utf-8")
    markers = ("| owned-rung2 |", "| qwen-reference |", "| ember-target |")
    content = "\n".join(line for line in content.splitlines() if not line.startswith(markers)) + "\n"
    continuity.write_text(content, encoding="utf-8")
    refresh_continuity_hash(tmp_path)
    assert_rejected(tmp_path, "state.identity_rows_missing")


def test_state_pointer_tamper_is_rejected(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    (tmp_path / "STATE.md").write_text("STATE rows moved elsewhere\n", encoding="utf-8")
    assert_rejected(tmp_path, "state.pointer_invalid")


CROSSWALK_REL = "manifests/authority/issue-35-authority-supersession-crosswalk-v1.json"


def _crosswalk_fixture(
    *, source_commit: str, matrix_sha: str, evidence_sha: str
) -> dict:
    """The crosswalk fields the re-pin coupling rule reads, and nothing else."""
    return {
        "schema_version": "ember-authority-supersession-crosswalk-v1",
        "repository": "wordingone/ember",
        "source_commit": source_commit,
        "current_authority": {
            "matrix_path": "docs/authority/ember-authority-matrix.md",
            "matrix_sha256": matrix_sha,
        },
        "source_registries": [
            {
                "registry_id": "legacy",
                "evidence": [
                    {"path": "docs/domains/governance/spec/conditions-v1.md", "sha256": evidence_sha}
                ],
            }
        ],
        "rows": [],
        "crosswalk_sha256": "d" * 64,
    }


def _seed_crosswalk_repo(root: Path, payload: dict) -> None:
    write_valid_fixture(root)
    crosswalk = root / CROSSWALK_REL
    crosswalk.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    git_fixture(root, "init")
    git_fixture(root, "config", "user.email", "fixture@example.invalid")
    git_fixture(root, "config", "user.name", "fixture")
    git_fixture(root, "add", ".")
    git_fixture(root, "commit", "-m", "fixture")


def _stage_crosswalk(root: Path, payload: dict) -> list[dict]:
    (root / CROSSWALK_REL).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    git_fixture(root, "add", CROSSWALK_REL)
    result = run_verifier(root, extra_args=("--staged",))
    return json.loads(result.stdout)["errors"]


def test_crosswalk_content_repin_without_moving_source_commit_is_rejected(
    tmp_path: Path,
) -> None:
    """Issue #1381 contract (a): a re-pin may never leave the previous commit's
    name behind. Without this the field is a pin nothing keeps true, and
    --expected-source-commit silently certifies against the wrong commit."""
    _seed_crosswalk_repo(
        tmp_path,
        _crosswalk_fixture(source_commit="a" * 40, matrix_sha="1" * 64, evidence_sha="2" * 64),
    )

    errors = _stage_crosswalk(
        tmp_path,
        # content pin moves, source_commit deliberately left stale
        _crosswalk_fixture(source_commit="a" * 40, matrix_sha="1" * 64, evidence_sha="3" * 64),
    )

    stale = [
        item for item in errors
        if item["code"] == "authority.crosswalk_source_commit_stale"
    ]
    assert stale, errors
    assert "legacy:docs/domains/governance/spec/conditions-v1.md" in stale[0]["detail"]
    assert "a" * 40 in stale[0]["detail"]


def test_crosswalk_content_repin_that_moves_source_commit_is_accepted(
    tmp_path: Path,
) -> None:
    _seed_crosswalk_repo(
        tmp_path,
        _crosswalk_fixture(source_commit="a" * 40, matrix_sha="1" * 64, evidence_sha="2" * 64),
    )

    errors = _stage_crosswalk(
        tmp_path,
        _crosswalk_fixture(source_commit="b" * 40, matrix_sha="1" * 64, evidence_sha="3" * 64),
    )

    assert "authority.crosswalk_source_commit_stale" not in {
        item["code"] for item in errors
    }, errors


def test_moving_source_commit_alone_is_not_a_content_repin(tmp_path: Path) -> None:
    """The self-hash moves whenever any field moves, so coupling on it would
    fire on every edit. Only described-content digests count."""
    _seed_crosswalk_repo(
        tmp_path,
        _crosswalk_fixture(source_commit="a" * 40, matrix_sha="1" * 64, evidence_sha="2" * 64),
    )

    payload = _crosswalk_fixture(
        source_commit="a" * 40, matrix_sha="1" * 64, evidence_sha="2" * 64
    )
    payload["crosswalk_sha256"] = "e" * 64
    errors = _stage_crosswalk(tmp_path, payload)

    assert "authority.crosswalk_source_commit_stale" not in {
        item["code"] for item in errors
    }, errors


IDENTITY_REL = "data/fixture/input-identity.json"
SHARD_REL = "data/fixture/shard.json"
RECEIPT_REL = "data/fixture/shard.receipt.json"


def _digest(root: Path, rel: str) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def _seed_input_identity_repo(root: Path, receipt_body: str = "minted once") -> None:
    """A tree whose config selects an identity manifest pinning shard + receipt."""
    write_valid_fixture(root)
    data = root / "data" / "fixture"
    data.mkdir(parents=True, exist_ok=True)
    (root / SHARD_REL).write_text('{"records": []}\n', encoding="utf-8")
    (root / RECEIPT_REL).write_text(
        json.dumps({"admission": receipt_body}) + "\n", encoding="utf-8"
    )
    _repin_identity(root)
    config_path = root / "configs" / "historical.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["training"] = {"input_identity_manifest": IDENTITY_REL}
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _repin_identity(root: Path) -> None:
    """Re-pin the manifest onto whatever the pinned files currently hold."""
    (root / IDENTITY_REL).write_text(
        json.dumps(
            {
                "schema_version": "ember-input-identity-v1",
                "artifact_id": "fixture-rung-v1",
                "shard_path": SHARD_REL,
                "sha256": _digest(root, SHARD_REL),
                "bytes": (root / SHARD_REL).stat().st_size,
                "admission_receipt_path": RECEIPT_REL,
                "admission_receipt_sha256": _digest(root, RECEIPT_REL),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _identity_errors(root: Path) -> list[dict]:
    result = run_verifier(root)
    return json.loads(result.stdout)["errors"]


def test_reminted_admission_receipt_without_a_repin_is_rejected(tmp_path: Path) -> None:
    """Issue #1394: PR #1333 re-minted the production rung receipt and left the
    manifest pinning the old bytes, so the defect surfaced only when a certified
    run failed closed at InputIdentityError byte_drift hours later."""
    _seed_input_identity_repo(tmp_path)

    (tmp_path / RECEIPT_REL).write_text(
        json.dumps({"admission": "re-minted"}) + "\n", encoding="utf-8"
    )

    stale = [
        item for item in _identity_errors(tmp_path)
        if item["code"] == "input_identity.pin_stale"
    ]
    assert stale, _identity_errors(tmp_path)
    assert RECEIPT_REL in stale[0]["detail"]
    assert _digest(tmp_path, RECEIPT_REL) in stale[0]["detail"]


def test_reminted_admission_receipt_with_a_repin_is_accepted(tmp_path: Path) -> None:
    _seed_input_identity_repo(tmp_path)

    (tmp_path / RECEIPT_REL).write_text(
        json.dumps({"admission": "re-minted"}) + "\n", encoding="utf-8"
    )
    _repin_identity(tmp_path)

    errors = _identity_errors(tmp_path)
    assert not [item for item in errors if item["code"].startswith("input_identity.")], errors


def test_edits_outside_the_pinned_set_are_not_a_repin_obligation(tmp_path: Path) -> None:
    """The rule must stay quiet on the diffs that make up ordinary work."""
    _seed_input_identity_repo(tmp_path)

    (tmp_path / "data" / "fixture" / "notes.md").write_text("unrelated\n", encoding="utf-8")

    errors = _identity_errors(tmp_path)
    assert not [item for item in errors if item["code"].startswith("input_identity.")], errors


def test_pin_claiming_bytes_no_artifact_carries_is_rejected(tmp_path: Path) -> None:
    """The reverse direction: a manifest re-pinned onto a hash nothing matches."""
    _seed_input_identity_repo(tmp_path)
    identity = json.loads((tmp_path / IDENTITY_REL).read_text(encoding="utf-8"))
    identity["admission_receipt_sha256"] = "f" * 64
    (tmp_path / IDENTITY_REL).write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    assert_rejected(tmp_path, "input_identity.pin_stale")


def test_shard_repin_is_coupled_on_the_same_rule(tmp_path: Path) -> None:
    """Every artefact the manifest pins is covered, not the receipt alone."""
    _seed_input_identity_repo(tmp_path)
    (tmp_path / SHARD_REL).write_text('{"records": [1]}\n', encoding="utf-8")

    assert_rejected(tmp_path, "input_identity.pin_stale")


def test_shard_byte_count_pin_is_checked_alongside_the_digest(tmp_path: Path) -> None:
    """Runtime admission checks the count separately, so one pin can pass while
    the other fails closed."""
    _seed_input_identity_repo(tmp_path)
    identity = json.loads((tmp_path / IDENTITY_REL).read_text(encoding="utf-8"))
    identity["bytes"] = identity["bytes"] + 1
    (tmp_path / IDENTITY_REL).write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    assert_rejected(tmp_path, "input_identity.pin_stale")


def test_pinned_artifact_that_is_absent_is_rejected(tmp_path: Path) -> None:
    _seed_input_identity_repo(tmp_path)
    (tmp_path / RECEIPT_REL).unlink()

    assert_rejected(tmp_path, "input_identity.pinned_file_missing")


def test_admission_receipt_path_without_a_digest_is_rejected(tmp_path: Path) -> None:
    """Half a pin admits unbound bytes, which is the failure the pin exists for."""
    _seed_input_identity_repo(tmp_path)
    identity = json.loads((tmp_path / IDENTITY_REL).read_text(encoding="utf-8"))
    del identity["admission_receipt_sha256"]
    (tmp_path / IDENTITY_REL).write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    assert_rejected(tmp_path, "input_identity.admission_pin_incomplete")


def test_identity_manifest_named_by_a_config_must_exist(tmp_path: Path) -> None:
    _seed_input_identity_repo(tmp_path)
    (tmp_path / IDENTITY_REL).unlink()

    assert_rejected(tmp_path, "input_identity.pinned_file_missing")


def test_windows_cmd_control_is_admitted_only_by_its_exact_authority_sidecar(
    tmp_path: Path,
) -> None:
    write_valid_fixture(tmp_path)
    git_fixture(tmp_path, "init")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    git_fixture(tmp_path, "config", "user.name", "fixture")
    git_fixture(tmp_path, "add", ".")
    git_fixture(tmp_path, "commit", "-m", "fixture")

    relative = "tools/launchers/Ember.cmd"
    artifact = _write_sidecar(
        tmp_path,
        relative,
        b"@echo off\necho governed launcher\n",
    )
    sidecar = tmp_path / "tools" / "launchers" / "Ember.authority.json"
    git_fixture(tmp_path, "add", relative, "tools/launchers/Ember.authority.json")

    accepted = run_verifier(tmp_path, extra_args=("--staged",))
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["artifact_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    git_fixture(tmp_path, "add", "tools/launchers/Ember.authority.json")
    refused = run_verifier(tmp_path, extra_args=("--staged",))
    assert refused.returncode == 1, refused.stdout + refused.stderr
    receipt = json.loads(refused.stdout)
    assert "artifact.goal_binding" in {
        item["code"] for item in receipt["errors"]
    }, receipt
    assert "artifact.binding_format_unsupported" not in {
        item["code"] for item in receipt["errors"]
    }, receipt
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() != payload["artifact_sha256"]

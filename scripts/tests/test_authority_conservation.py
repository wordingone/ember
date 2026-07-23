#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mutation-backed tests for Ember's executable authority spine."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_authority_conservation.py"
INVARIANT_SHA256 = "08A0EB7418C09A8088BE4658E10785107ABBB7507FC2DBCDC789936AA54E02A6"

GOVERNING_SURFACES = [
    "docs/goal-clear-protocol.md",
    "docs/nc2-own-technique-contract.md",
    "docs/ember-floor-contract.md",
    "docs/goal-mode-mechanism.md",
    "docs/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/spec/conditions-v1.md",
    "docs/ember-authority-matrix.md",
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
        "python scripts/ember_restart/contract.py validate "
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


def write_valid_fixture(root: Path) -> None:
    invariant = (REPO_ROOT / "INVARIANT.md").read_bytes()
    assert hashlib.sha256(invariant).hexdigest().upper() == INVARIANT_SHA256
    (root / "INVARIANT.md").write_bytes(invariant)

    for rel in GOVERNING_SURFACES:
        if rel == "docs/ember-authority-matrix.md":
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
    manifest_path = root / "docs" / "ember-authority-matrix.md"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        CONSERVATION_HEADER + "\n" + "\n".join(manifest) + "\n",
        encoding="utf-8",
    )

    state = """# Current artifact identity resolver

| id | object_type | canonical_identity | artifact_class | parameter_count | trained_tokens | backend | capability_credit | evidence |
|---|---|---|---|---:|---:|---|---|---|
| owned-rung2 | checkpoint | sha256:owned-rung2 | historical_only | 2195000000 | 12550144 | disconnected_owned_server | none | historical receipt |
| qwen-reference | backend | model:qwen-reference | borrowed_reference | 27000000000 | unknown | qwen | none | explicit reference seat |
| ember-target | model_target | uninstantiated:ember-target | target | 30000000001 | 0 | owned | none | GOAL.md |
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
    registry = tmp_path / "docs" / "technique-registry.jsonl"
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
    manifest = tmp_path / "docs" / "ember-authority-matrix.md"
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
    manifest = tmp_path / "docs" / "ember-authority-matrix.md"
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
    surface = tmp_path / "docs" / "goal-clear-protocol.md"
    surface.write_text(
        surface.read_text(encoding="utf-8") + "\nAudio may be deferred.\n",
        encoding="utf-8",
    )
    assert_rejected(tmp_path, "surface.hash_mismatch")


def test_matrix_semantic_mutation_breaks_hash(tmp_path: Path) -> None:
    write_valid_fixture(tmp_path)
    matrix = tmp_path / "docs" / "ember-authority-matrix.md"
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

    matrix = tmp_path / "docs" / "ember-authority-matrix.md"
    valid_working_copy = matrix.read_text(encoding="utf-8")
    matrix.write_text(
        valid_working_copy.replace("ledger D-045", "staged semantic drift"),
        encoding="utf-8",
    )
    git_fixture(tmp_path, "add", "docs/ember-authority-matrix.md")
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

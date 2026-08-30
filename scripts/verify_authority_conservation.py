#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed verifier for Ember's authority and totality conservation contract.

This is an authority verifier, not a capability receipt.  It proves that the
current tree cannot redefine Ember through a smaller network, borrowed learned
signal, missing native capability, erased research obligation, or ambiguous
artifact identity.  It never claims that an Ember model has been trained.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


INVARIANT_SHA256 = "08A0EB7418C09A8088BE4658E10785107ABBB7507FC2DBCDC789936AA54E02A6"
POLICY_SCHEMA = "ember-authority-v1"
ACTIVE_GOAL_ID = "EMBER-02"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
ACTIVE_WORKSTREAM_IDS = ["EMBER-02A", "EMBER-02B", "EMBER-02C"]
GOAL_GRAPH_NODE_IDS = [
    "EMBER-01",
    "EMBER-02A",
    "EMBER-02B",
    "EMBER-02C",
    "EMBER-02P",
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
EXPECTED_ACTIVE_GOAL_SUFFIX = (
    "goals/ember/ember-02-3b-foundation-birth/goal.md"
)
GOAL_GRAPH_SCHEMA = "ember-goal-graph-v1"
GOAL_GRAPH_STATES = {
    "ACTIVE",
    "PRESTAGING",
    "WAITING_ON_DEPENDENCY",
    "CERTIFIED",
}
POLICY_RE = re.compile(
    r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
CONSERVATION_RE = re.compile(
    r"<!--\s*EMBER_CONSERVATION_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
EXECUTION_BOUNDARY_RE = re.compile(
    r"<!--\s*EMBER_EXECUTION_BOUNDARY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
EXECUTION_BOUNDARY_SCHEMA = "ember-execution-boundary-v1"
EXECUTION_CLASSES = {"authority_only", "goal_executing"}
EXECUTION_OPERATIONS = {
    "owned_3b_pretraining",
    "owned_training_growth",
    "owned_evaluation",
    "owned_serving",
}
REQUIRED_BLOCKED_OPERATIONS = [
    "sub_3b_new_network",
    "borrowed_lineage_signal",
    "historical_artifact_execution",
    "capability_or_completion_claim",
    "benchmark_credit_without_owned_checkpoint",
]
HISTORICAL_ONLY_MARKER = "<!-- EMBER_ARTIFACT_CLASS=historical_only -->"
CONFIG_CLASSIFICATION_HEADER = [
    "path",
    "artifact_class",
    "execution_authority",
    "goal_id",
    "next_executed_outcome",
    "sha256",
]

REQUIRED_CAPABILITIES = [
    "text",
    "image",
    "audio",
    "reasoning",
    "structured_tool_use",
]
REQUIRED_RUNGS = [3_000_000_000, 7_000_000_000, 15_000_000_000, 27_000_000_001]
REQUIRED_SURFACES = [
    "docs/contracts/goal-clear-protocol.md",
    "docs/contracts/nc2-own-technique-contract.md",
    "docs/contracts/ember-floor-contract.md",
    "docs/contracts/goal-mode-mechanism.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/spec/conditions-v1.md",
    "docs/authority/ember-authority-matrix.md",
    "GOVERNANCE.md",
    "README.md",
    "CONTINUITY.md",
]
AUTHORITY_DOCUMENT_NAMES = (
    "GOAL.md",
    "INVARIANT.md",
    "GOVERNANCE.md",
    "CONTINUITY.md",
    "REDACTIONS.md",
    "STATE.md",
)
AUTHORITY_DIRECTORY = PurePosixPath("docs/authority")
AUTHORITY_DOMAIN_DIRECTORY = PurePosixPath("docs/domains/governance/authority")


def authority_canonical_relative_path(name: str) -> PurePosixPath:
    if name in {"GOAL.md", "STATE.md"}:
        return AUTHORITY_DOMAIN_DIRECTORY / name
    return AUTHORITY_DIRECTORY / name


def authority_candidate_relative_paths(name: str) -> tuple[PurePosixPath, ...]:
    old_rel = PurePosixPath(name)
    canonical_rel = authority_canonical_relative_path(name)
    if name == "STATE.md":
        return (old_rel, AUTHORITY_DIRECTORY / name, canonical_rel)
    return (old_rel, canonical_rel)


FORBIDDEN_MODEL_SIGNALS = [
    "weights",
    "outputs",
    "teachers",
    "judges",
    "filters",
    "ranks",
    "curricula",
    "stopping_decisions",
    "hidden_external_cognition",
]
REASONING_AXES = [
    "multi_step",
    "compositional",
    "counterfactual",
    "causal",
    "action_coherence",
    "component_deletion",
]
REASONING_SUBSTITUTES = [
    "borrowed_model",
    "search",
    "script",
    "verifier",
    "tool_wrapper",
    "human_intervention",
]
TOTALITY = [
    "creation_primitive",
    "foundation_model",
    "organism",
    "body",
    "general_local_ai_laboratory",
    "individual_local_ownership",
    "whole_stack_ownership",
    "operational_and_cognitive_self_sufficiency",
]
MUTATION_CLASSES = [
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
]
AUTHORITY_MATRIX = "docs/authority/ember-authority-matrix.md"
GOVERNING_SURFACE_MIGRATIONS = {
    "docs/contracts/goal-clear-protocol.md": "docs/goal-clear-protocol.md",
    "docs/contracts/nc2-own-technique-contract.md": "docs/nc2-own-technique-contract.md",
    "docs/contracts/ember-floor-contract.md": "docs/ember-floor-contract.md",
    "docs/contracts/goal-mode-mechanism.md": "docs/goal-mode-mechanism.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md": "docs/registry-dispatch-gate-spec-v0.md",
    AUTHORITY_MATRIX: "docs/ember-authority-matrix.md",
}
HISTORICAL_EXECUTABLES = [
    "scripts/conv_c03_muon_ns3_live.py",
    "scripts/timeshare_pretrain.py",
    "scripts/train_multimodal_v0.py",
]
TIMESHARE_IMPORT_BOUNDARY_MANIFEST = (
    "docs/ember-restart/timeshare-importer-classification-1451-v1.json"
)
TIMESHARE_EXECUTION_BOUNDARY_KEYS = {"helper", "main", "entrypoint"}
TIMESHARE_IMPORT_MANIFEST_KEYS = {
    "schema",
    "source",
    "source_sha256",
    "import_denial",
    "execution_boundary",
    "importers",
}
TIMESHARE_EXECUTION_BOUNDARY = {
    "helper": "_historical_only_refusal",
    "main": "main",
    "entrypoint": "__main__",
}
REQUIRED_OPERATOR_BENCHMARKS = [
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
]
ADDITIONAL_DIRECT_BENCHMARKS = ["ARC-AGI 1", "ARC-AGI 2", "ARC-AGI 3"]
EXPECTED_CONSERVATION = {
    "minimum_new_network_parameters": "3000000000",
    "destination_total_parameters": ">27000000000",
    "required_native_capabilities": ",".join(REQUIRED_CAPABILITIES),
    "borrowed_lineage": "frozen_reference_only",
    "mechanism_erasure": "forbidden",
}
LOWER_AUTHORITY_PATTERNS = [
    re.compile(r"(?im)^\s*#{1,6}\s+active\s+ember\s+goal\b"),
    re.compile(r"(?i)\bthis\s+(?:document|ledger|contract|file)\s+is\s+(?:the\s+)?(?:single\s+source\s+of\s+truth|binding\s+completion\s+law|active\s+control)\b"),
    re.compile(r"(?i)\blaunch\s+authorization\b"),
    re.compile(r"(?i)\bauthoriz(?:e|es|ed|ing)\s+(?:a\s+)?completed\s+ember\s+model\b"),
    re.compile(r"(?m)^\s*ACTIVE_GOAL\s*[:=]"),
]



def finding(leg: int, code: str, detail: str) -> dict[str, Any]:
    return {"leg": leg, "code": code, "detail": detail}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def authority_relative_path(root: Path, name: str) -> str:
    if name not in AUTHORITY_DOCUMENT_NAMES:
        raise ValueError(f"unknown authority document: {name}")
    candidates = authority_candidate_relative_paths(name)
    present = [
        rel.as_posix()
        for rel in candidates
        if (root / rel).exists() or (root / rel).is_symlink()
    ]
    if len(present) > 1:
        raise ValueError(
            f"duplicate canonical authority document {name}: {', '.join(present)}"
        )
    if not present:
        raise ValueError(
            f"canonical authority document {name} is absent from "
            + ", ".join(rel.as_posix() for rel in candidates)
        )
    selected = root / present[0]
    if not selected.is_file() or selected.is_symlink():
        raise ValueError(
            f"canonical authority document {name} is not a regular file: {present[0]}"
        )
    return present[0]


def authority_path(root: Path, name: str) -> Path:
    return root / authority_relative_path(root, name)


def canonical_authority_reference(root: Path, name: str) -> str:
    canonical_rel = authority_canonical_relative_path(name).as_posix()
    if (root / canonical_rel).is_file() and not (root / name).is_file():
        return canonical_rel
    if name == "STATE.md":
        docs_rel = (AUTHORITY_DIRECTORY / name).as_posix()
        if (root / docs_rel).is_file() and not (root / name).is_file():
            return docs_rel
    return name


def governing_surface_relative_path(root: Path, canonical_rel: str) -> str:
    old_rel = GOVERNING_SURFACE_MIGRATIONS.get(canonical_rel)
    if old_rel is None:
        return canonical_rel
    present = [
        rel
        for rel in (old_rel, canonical_rel)
        if (root / rel).exists() or (root / rel).is_symlink()
    ]
    if len(present) > 1:
        raise ValueError(
            f"duplicate governing surface {canonical_rel}: {', '.join(present)}"
        )
    if not present:
        raise ValueError(
            f"governing surface {canonical_rel} is absent from both "
            f"{old_rel} and {canonical_rel}"
        )
    selected = root / present[0]
    if not selected.is_file() or selected.is_symlink():
        raise ValueError(
            f"governing surface {canonical_rel} is not a regular file: {present[0]}"
        )
    return present[0]


def expected_governing_surfaces(root: Path) -> list[str]:
    authority_names = set(AUTHORITY_DOCUMENT_NAMES)
    result: list[str] = []
    for rel in REQUIRED_SURFACES:
        if rel in authority_names:
            result.append(canonical_authority_reference(root, rel))
            continue
        try:
            result.append(governing_surface_relative_path(root, rel))
        except ValueError:
            result.append(rel)
    return result


def check_authority_path_layout(root: Path, errors: list[dict[str, Any]]) -> None:
    for name in AUTHORITY_DOCUMENT_NAMES:
        try:
            authority_relative_path(root, name)
        except ValueError as exc:
            code = "authority.path_duplicate" if "duplicate" in str(exc) else "authority.path_missing"
            errors.append(finding(3, code, str(exc)))
    for canonical_rel in GOVERNING_SURFACE_MIGRATIONS:
        try:
            governing_surface_relative_path(root, canonical_rel)
        except ValueError as exc:
            code = (
                "surface.path_duplicate"
                if "duplicate" in str(exc)
                else "surface.path_invalid"
            )
            errors.append(finding(3, code, str(exc)))


def parse_goal_policy(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        path = authority_path(root, "GOAL.md")
    except ValueError as exc:
        errors.append(finding(3, "goal.missing", str(exc)))
        return None
    try:
        text = read_text(path)
    except Exception as exc:
        errors.append(finding(3, "goal.unreadable", str(exc)))
        return None
    match = POLICY_RE.search(text)
    if not match:
        errors.append(
            finding(3, "goal.machine_contract_missing", "EMBER_AUTHORITY_V1 block is absent")
        )
        return None
    try:
        policy = json.loads(match.group(1))
    except Exception as exc:
        errors.append(finding(3, "goal.machine_contract_invalid", str(exc)))
        return None
    if not isinstance(policy, dict):
        errors.append(finding(3, "goal.machine_contract_not_object", "policy must be an object"))
        return None
    return policy


def expect(
    errors: list[dict[str, Any]],
    leg: int,
    condition: bool,
    code: str,
    detail: str,
) -> None:
    if not condition:
        errors.append(finding(leg, code, detail))


def check_policy(root: Path, policy: dict[str, Any] | None, errors: list[dict[str, Any]]) -> None:
    if policy is None:
        for leg in (1, 3, 4, 5, 7):
            errors.append(finding(leg, "policy.unavailable", "GOAL machine contract unavailable"))
        return

    expect(errors, 3, policy.get("schema") == POLICY_SCHEMA, "policy.schema", POLICY_SCHEMA)
    expect(
        errors,
        4,
        policy.get("active_goal_id") == ACTIVE_GOAL_ID,
        "policy.active_goal_id",
        ACTIVE_GOAL_ID,
    )
    expect(
        errors,
        4,
        policy.get("next_executed_outcome") == NEXT_EXECUTED_OUTCOME,
        "policy.next_executed_outcome",
        NEXT_EXECUTED_OUTCOME,
    )
    expect(
        errors,
        4,
        policy.get("active_workstream_ids") == ACTIVE_WORKSTREAM_IDS,
        "policy.active_workstream_ids",
        "active child workstreams must be exact and parent-bound",
    )
    expect(
        errors,
        4,
        policy.get("goal_graph_node_ids") == GOAL_GRAPH_NODE_IDS,
        "policy.goal_graph_node_ids",
        "durable goal graph node set must be closed and exact",
    )
    expect(
        errors,
        4,
        policy.get("workstream_path_scopes") == WORKSTREAM_PATH_SCOPES,
        "policy.workstream_path_scopes",
        "child workstreams must retain exact conflict-free path scopes",
    )
    expect(
        errors,
        1,
        policy.get("invariant_sha256") == INVARIANT_SHA256,
        "policy.invariant_hash",
        INVARIANT_SHA256,
    )
    expect(
        errors,
        3,
        policy.get("highest_amendable_authority") == canonical_authority_reference(root, "GOAL.md"),
        "policy.highest_amendable_authority",
        f"must be {canonical_authority_reference(root, 'GOAL.md')}",
    )
    expect(
        errors,
        3,
        policy.get("required_governing_surfaces") == expected_governing_surfaces(root),
        "policy.governing_surfaces",
        "required governing surface list drifted",
    )

    benchmark = policy.get("benchmark_custody") or {}
    expect(
        errors,
        4,
        benchmark.get("recovered_operator_mandate") == REQUIRED_OPERATOR_BENCHMARKS,
        "policy.benchmark_mandate",
        "the exact recovered ten-name mandate must remain intact",
    )
    expect(
        errors,
        4,
        benchmark.get("additional_direct_recovered")
        == ADDITIONAL_DIRECT_BENCHMARKS,
        "policy.benchmark_direct_additions",
        "ARC-AGI 1/2/3 must remain directly recovered obligations",
    )
    expected_benchmark_counts = {
        "direct_recovered_minimum": 13,
        "operator_recollection_minimum": 15,
        "unrecovered_direct_names_minimum": 2,
        "broader_named_families_minimum": 31,
    }
    for field, expected_value in expected_benchmark_counts.items():
        expect(
            errors,
            4,
            benchmark.get(field) == expected_value,
            f"policy.benchmark_{field}",
            f"{field} must equal {expected_value}",
        )
    expect(
        errors,
        4,
        benchmark.get("no_silent_retirement") is True,
        "policy.benchmark_no_silent_retirement",
        "benchmark blockers and pivots may not erase obligations",
    )
    expect(
        errors,
        4,
        benchmark.get("owned_checkpoint_binding_required") is True,
        "policy.benchmark_checkpoint_binding",
        "owned-model benchmark credit must bind exact owned checkpoint bytes",
    )

    birth = policy.get("model_birth") or {}
    expect(
        errors,
        3,
        birth.get("minimum_total_parameters") == 3_000_000_000,
        "policy.minimum_3b",
        "first admissible network must contain at least 3,000,000,000 parameters",
    )
    expect(
        errors,
        3,
        birth.get("required_native_capabilities") == REQUIRED_CAPABILITIES,
        "policy.native_capabilities",
        "text,image,audio,reasoning,structured_tool_use are jointly required",
    )
    expect(
        errors,
        3,
        birth.get("sufficient_training_required") is True,
        "policy.sufficient_training",
        "parameter allocation or smoke execution cannot establish model birth",
    )
    expect(
        errors,
        3,
        birth.get("parameter_shell_is_model_birth") is False,
        "policy.parameter_shell",
        "parameter shell must not count as a model birth",
    )
    expect(
        errors,
        3,
        policy.get("hard_rungs_total_parameters") == REQUIRED_RUNGS,
        "policy.hard_rungs",
        "required hard rungs are 3B, 7B, 15B, and >27B",
    )

    destination = policy.get("destination") or {}
    expect(
        errors,
        3,
        destination.get("minimum_total_parameters_exclusive") == 27_000_000_000,
        "policy.destination_gt_27b",
        "destination must be strictly above 27B",
    )
    expect(
        errors,
        3,
        destination.get("initial_total_parameter_band") == [30_000_000_000, 35_000_000_000],
        "policy.destination_band",
        "initial target band must be 30-35B",
    )
    expect(
        errors,
        3,
        destination.get("single_gpu_vram_gib") == 24,
        "policy.single_gpu",
        "single GPU memory envelope must be 24 GiB",
    )
    expect(
        errors,
        3,
        destination.get("competitive_reference_parameters")
        == [27_000_000_000, 31_000_000_000],
        "policy.competitive_references",
        "frozen comparison scales must be 27B and 31B",
    )

    architecture = policy.get("architecture") or {}
    for key in ("owned_unified_decoder", "sparse_differentiated_capacity", "task_level_expert_routing"):
        expect(errors, 3, architecture.get(key) is True, f"policy.architecture.{key}", key)
    expect(
        errors,
        3,
        architecture.get("headline_hypothesis") == "Verified Expert Accretion",
        "policy.verified_expert_accretion",
        "Verified Expert Accretion must be the headline causal hypothesis",
    )
    expect(
        errors,
        4,
        architecture.get("published_family_backbone_allowed") is False,
        "policy.published_backbone",
        "published model families may not become Ember's backbone",
    )

    lineage = policy.get("lineage") or {}
    expect(
        errors,
        4,
        lineage.get("borrowed_models_role") == "frozen_reference_only",
        "policy.borrowed_role",
        "borrowed models are frozen references only",
    )
    expect(
        errors,
        4,
        lineage.get("forbidden_model_mediated_signals") == FORBIDDEN_MODEL_SIGNALS,
        "policy.model_mediated_signals",
        "borrowed learned influence list drifted",
    )
    expect(errors, 4, lineage.get("published_ideas_allowed") is True, "policy.published_ideas", "published ideas remain admissible research input")
    expect(errors, 4, lineage.get("transparent_deterministic_tools_allowed") is True, "policy.deterministic_tools", "transparent deterministic tools remain admissible")

    negative = policy.get("negative_evidence") or {}
    for key in ("may_delete_required_capability", "may_erase_research_family", "may_force_named_successor"):
        expect(errors, 4, negative.get(key) is False, f"policy.negative_evidence.{key}", key)
    expect(
        errors,
        4,
        negative.get(
            "preserve_synergy_order_scale_modality_substrate_routing_precision_retests"
        )
        is True,
        "policy.negative_evidence.retests",
        "negative evidence must preserve later interaction/regime tests",
    )

    reasoning = policy.get("reasoning_evidence") or {}
    expect(errors, 3, reasoning.get("checkpoint_bound") is True, "policy.reasoning.checkpoint_bound", "reasoning evidence must bind checkpoint bytes")
    expect(errors, 3, reasoning.get("unseen_tasks_required") is True, "policy.reasoning.unseen", "unseen reasoning tasks required")
    expect(errors, 3, reasoning.get("required_axes") == REASONING_AXES, "policy.reasoning.axes", "reasoning axes drifted")
    expect(errors, 3, reasoning.get("forbidden_substitutes") == REASONING_SUBSTITUTES, "policy.reasoning.substitutes", "harness/search/tool/human substitutions forbidden")
    expect(errors, 3, reasoning.get("hidden_trace_disclosure_required") is False, "policy.reasoning.hidden_trace", "hidden trace disclosure is not the reasoning definition")

    expect(errors, 3, policy.get("totality") == TOTALITY, "policy.totality", "primitive/model/organism/body/lab/ownership/stack/self-sufficiency totality drifted")

    relationship = policy.get("operator_relationship") or {}
    for key in ("dynamically_configurable", "explicit", "revocable", "behavior_tested", "operator_retains_final_scope_authority"):
        expect(errors, 3, relationship.get(key) is True, f"policy.operator_relationship.{key}", key)

    expect(
        errors,
        5,
        policy.get("mutation_controls_required") == MUTATION_CLASSES,
        "policy.mutation_controls",
        "known drift-class mutation controls are incomplete",
    )
    expect(
        errors,
        4,
        policy.get("required_future_artifact_fields")
        == ["goal_id", "workstream_id", "next_executed_outcome"],
        "policy.future_artifact_fields",
        "future PR/run/control artifacts require goal, workstream, and next outcome",
    )
    expect(errors, 7, policy.get("authority_only_goal") is False, "policy.authority_only", f"{ACTIVE_GOAL_ID} must retain model-execution authority")
    expect(errors, 7, policy.get("allows_new_network") is True, "policy.new_network", f"{ACTIVE_GOAL_ID} must permit the owned >=3B network")


def check_invariant(root: Path, policy: dict[str, Any] | None, errors: list[dict[str, Any]]) -> None:
    try:
        path = authority_path(root, "INVARIANT.md")
    except ValueError as exc:
        errors.append(finding(1, "invariant.missing", str(exc)))
        return
    actual = sha256(path)
    expect(errors, 1, actual == INVARIANT_SHA256, "invariant.hash", f"expected {INVARIANT_SHA256}, got {actual}")
    if policy is not None:
        expect(errors, 1, policy.get("invariant_sha256") == actual, "invariant.policy_binding", "GOAL policy hash does not bind current invariant bytes")


def parse_conservation_header(text: str) -> dict[str, str] | None:
    match = CONSERVATION_RE.search(text)
    if not match:
        return None
    values: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            return None
        key, value = line.split("=", 1)
        if key in values:
            return None
        values[key] = value
    return values


def check_governing_surfaces(root: Path, policy: dict[str, Any] | None, errors: list[dict[str, Any]]) -> None:
    expected_surfaces = expected_governing_surfaces(root)
    surfaces = expected_surfaces if policy is None else policy.get("required_governing_surfaces", expected_surfaces)
    if not isinstance(surfaces, list):
        errors.append(finding(3, "surfaces.invalid_list", "required_governing_surfaces must be a list"))
        return
    conservation_hashes = (policy or {}).get("conservation_hashes") or {}
    surface_hashes = conservation_hashes.get("governing_surfaces_sha256")
    if not isinstance(surface_hashes, dict) or set(surface_hashes) != set(surfaces):
        errors.append(
            finding(
                3,
                "surface.hash_contract_invalid",
                "docs/domains/governance/authority/GOAL.md must hash-bind every required governing surface",
            )
        )
        surface_hashes = {}
    for rel in surfaces:
        path = root / str(rel)
        if not path.is_file():
            errors.append(finding(3, "surface.missing", str(rel)))
            continue
        try:
            header = parse_conservation_header(read_text(path))
        except Exception as exc:
            errors.append(finding(3, "surface.unreadable", f"{rel}: {exc}"))
            continue
        if header is None:
            errors.append(finding(3, "surface.conservation_header_missing", str(rel)))
            continue
        if header != EXPECTED_CONSERVATION:
            errors.append(
                finding(
                    3,
                    "surface.conservation_drift",
                    f"{rel}: expected {EXPECTED_CONSERVATION}, got {header}",
                )
            )
        expected_hash = str(surface_hashes.get(rel, "")).upper()
        actual_hash = sha256(path)
        if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
            errors.append(finding(3, "surface.hash_missing", str(rel)))
        elif actual_hash != expected_hash:
            errors.append(
                finding(
                    3,
                    "surface.hash_mismatch",
                    f"{rel}: expected {expected_hash}, got {actual_hash}",
                )
            )


def check_manifest(
    root: Path, policy: dict[str, Any] | None, errors: list[dict[str, Any]]
) -> None:
    try:
        matrix_rel = governing_surface_relative_path(root, AUTHORITY_MATRIX)
    except ValueError:
        return
    path = root / matrix_rel
    if not path.is_file():
        errors.append(finding(2, "manifest.missing", f"{matrix_rel} is absent"))
        return
    expected_hash = str(
        ((policy or {}).get("conservation_hashes") or {}).get(
            "authority_matrix_sha256", ""
        )
    ).upper()
    actual_hash = sha256(path)
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        errors.append(
            finding(2, "manifest.hash_missing", "docs/domains/governance/authority/GOAL.md matrix hash is absent")
        )
    elif actual_hash != expected_hash:
        errors.append(
            finding(
                2,
                "manifest.hash_mismatch",
                f"expected {expected_hash}, got {actual_hash}",
            )
        )
    rows: list[tuple[str, str, str, str]] = []
    for raw in read_text(path).splitlines():
        if not raw.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if len(cells) != 4 or not re.fullmatch(r"D-\d{3}", cells[0]):
            continue
        rows.append((cells[0], cells[1], cells[2], cells[3]))
    ids = [row[0] for row in rows]
    expected = [f"D-{number:03d}" for number in range(1, 63)]
    counts = Counter(ids)
    missing = [item for item in expected if counts[item] == 0]
    duplicate = [item for item, count in counts.items() if count != 1]
    extra = [item for item in counts if item not in expected]
    if missing:
        errors.append(finding(2, "manifest.discrepancy_missing", ",".join(missing)))
    if duplicate:
        errors.append(finding(2, "manifest.discrepancy_duplicate", ",".join(sorted(duplicate))))
    if extra:
        errors.append(finding(2, "manifest.discrepancy_extra", ",".join(sorted(extra))))
    allowed = {"ENFORCED", "HISTORICAL_ONLY", "OPEN_RESEARCH"}
    for did, disposition_text, enforced_by, evidence in rows:
        dispositions = {part.strip() for part in re.split(r"[;,]", disposition_text) if part.strip()}
        if not dispositions or not dispositions <= allowed:
            errors.append(finding(2, "manifest.disposition_invalid", f"{did}: {disposition_text}"))
        if "ENFORCED" in dispositions:
            if not enforced_by:
                errors.append(finding(2, "manifest.enforcement_missing", did))
            else:
                targets = [
                    part.strip().strip("`").split("#", 1)[0]
                    for part in enforced_by.split(";")
                    if part.strip()
                ]
                missing_targets = [target for target in targets if not (root / target).is_file()]
                if not targets or missing_targets:
                    errors.append(
                        finding(
                            2,
                            "manifest.enforcement_target_missing",
                            f"{did}: {missing_targets or enforced_by}",
                        )
                    )
        if not evidence:
            errors.append(finding(2, "manifest.evidence_missing", did))


def _execution_boundary_for_source(root: Path) -> dict[str, str] | None:
    manifest_path = root / TIMESHARE_IMPORT_BOUNDARY_MANIFEST
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(read_text(manifest_path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    boundary = payload.get("execution_boundary")
    if (
        set(payload) != TIMESHARE_IMPORT_MANIFEST_KEYS
        or payload.get("source") != "scripts/timeshare_pretrain.py"
    ):
        return None
    if (
        not isinstance(boundary, dict)
        or set(boundary) != TIMESHARE_EXECUTION_BOUNDARY_KEYS
        or boundary != TIMESHARE_EXECUTION_BOUNDARY
    ):
        return None
    return {key: str(boundary[key]) for key in TIMESHARE_EXECUTION_BOUNDARY_KEYS}


def _first_executable_statement(statements: list[ast.stmt]) -> ast.stmt | None:
    statements = list(statements)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements.pop(0)
    while (
        statements
        and isinstance(statements[0], ast.ImportFrom)
        and statements[0].module == "__future__"
    ):
        statements.pop(0)
    return statements[0] if statements else None


def _check_execution_only_shape(
    rel: str,
    tree: ast.Module,
    boundary: Mapping[str, str],
    errors: list[dict[str, Any]],
) -> None:
    helper_name = boundary["helper"]
    main_name = boundary["main"]
    helper_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == helper_name]
    main_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == main_name]
    if len(helper_defs) != 1:
        errors.append(finding(4, "historical.execution_helper_missing", rel))
    if len(main_defs) != 1:
        errors.append(finding(4, "historical.execution_main_missing", rel))
    if len(helper_defs) != 1 or len(main_defs) != 1:
        return

    helper_first = _first_executable_statement(helper_defs[0].body)
    helper_guarded = (
        isinstance(helper_first, ast.Raise)
        and isinstance(helper_first.exc, ast.Call)
        and isinstance(helper_first.exc.func, ast.Name)
        and helper_first.exc.func.id == "SystemExit"
    )
    if not helper_guarded:
        errors.append(finding(4, "historical.execution_helper_guard", rel))

    main_first = _first_executable_statement(main_defs[0].body)
    main_calls_helper = (
        isinstance(main_first, ast.Expr)
        and isinstance(main_first.value, ast.Call)
        and isinstance(main_first.value.func, ast.Name)
        and main_first.value.func.id == helper_name
        and not main_first.value.args
        and not main_first.value.keywords
    )
    if not main_calls_helper:
        errors.append(finding(4, "historical.execution_main_call", rel))

    entrypoint_guards = []
    for node in tree.body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        if (
            isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == boundary["entrypoint"]
        ):
            entrypoint_guards.append(node)
    if len(entrypoint_guards) != 1:
        errors.append(finding(4, "historical.execution_entrypoint", rel))
        return
    entry_first = _first_executable_statement(entrypoint_guards[0].body)
    entry_calls_main = (
        isinstance(entry_first, ast.Expr)
        and isinstance(entry_first.value, ast.Call)
        and isinstance(entry_first.value.func, ast.Name)
        and entry_first.value.func.id == main_name
        and not entry_first.value.args
        and not entry_first.value.keywords
    )
    if not entry_calls_main:
        errors.append(finding(4, "historical.execution_entrypoint", rel))


def check_historical_executables(root: Path, errors: list[dict[str, Any]]) -> None:
    execution_boundary = _execution_boundary_for_source(root)
    for rel in HISTORICAL_EXECUTABLES:
        path = root / rel
        if not path.is_file():
            errors.append(finding(4, "historical.executable_missing", rel))
            continue
        text = read_text(path)
        if not text.lstrip("\ufeff \t\r\n").startswith(
            "# EMBER_ARTIFACT_CLASS=historical_only"
        ):
            errors.append(finding(4, "historical.marker_missing", rel))
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            errors.append(finding(4, "historical.syntax_invalid", f"{rel}: {exc}"))
            continue
        if rel == "scripts/timeshare_pretrain.py" and execution_boundary is not None:
            _check_execution_only_shape(rel, tree, execution_boundary, errors)
            continue
        first = _first_executable_statement(tree.body)
        guarded = (
            isinstance(first, ast.Raise)
            and isinstance(first.exc, ast.Call)
            and isinstance(first.exc.func, ast.Name)
            and first.exc.func.id == "SystemExit"
        )
        if not guarded:
            errors.append(
                finding(
                    4,
                    "historical.execution_guard_missing",
                    f"{rel}: first executable statement must raise SystemExit",
                )
            )


def check_execution_only_import_boundary(
    root: Path, errors: list[dict[str, Any]]
) -> None:
    """Validate the stage-2 importer contract without weakening the old lock.

    The manifest is optional in stage 1: its absence means no importer
    boundary has been enabled. A fully closed manifest enables the exact
    helper/main/__main__ execution shape; malformed or foreign manifests leave
    the base-kernel direct-raise rule active and are rejected below.
    """
    manifest_path = root / TIMESHARE_IMPORT_BOUNDARY_MANIFEST
    if not manifest_path.is_file():
        return
    try:
        payload = json.loads(read_text(manifest_path))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        errors.append(
            finding(4, "historical.import_manifest_invalid", str(exc))
        )
        return
    if not isinstance(payload, dict):
        errors.append(
            finding(4, "historical.import_manifest_invalid", "root must be an object")
        )
        return
    if set(payload) != TIMESHARE_IMPORT_MANIFEST_KEYS:
        errors.append(
            finding(
                4,
                "historical.import_manifest_keys",
                "exact top-level importer manifest keys required",
            )
        )
    if payload.get("schema") != "ember-timeshare-importer-classification-v1":
        errors.append(
            finding(4, "historical.import_manifest_schema", str(payload.get("schema")))
        )
    if payload.get("import_denial") != "execution_only":
        errors.append(
            finding(4, "historical.import_manifest_denial", "execution_only required")
        )
    execution_boundary = payload.get("execution_boundary")
    if (
        not isinstance(execution_boundary, dict)
        or set(execution_boundary) != TIMESHARE_EXECUTION_BOUNDARY_KEYS
        or execution_boundary != TIMESHARE_EXECUTION_BOUNDARY
    ):
        errors.append(
            finding(
                4,
                "historical.import_manifest_execution_contract",
                "closed helper/main/__main__ execution boundary required",
            )
        )
    source_rel = payload.get("source")
    source_path = root / "scripts" / "timeshare_pretrain.py"
    if source_rel != "scripts/timeshare_pretrain.py":
        errors.append(
            finding(4, "historical.import_manifest_source", str(source_rel))
        )
    source_hash = payload.get("source_sha256")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        errors.append(
            finding(4, "historical.import_manifest_source_hash", "64-hex source_sha256 required")
        )
    elif source_path.is_file() and sha256(source_path) != source_hash.upper():
        errors.append(
            finding(4, "historical.import_manifest_source_hash", "source bytes do not match")
        )
    rows = payload.get("importers")
    if not isinstance(rows, list) or not rows:
        errors.append(
            finding(4, "historical.import_manifest_rows", "non-empty importers list required")
        )
        return
    seen: set[str] = set()
    required = {
        "path", "classification", "import_outcome", "sha256",
        "module_scope", "nested_import_count",
    }

    def is_timeshare_import(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Import)
            and any(alias.name == "timeshare_pretrain" for alias in node.names)
        ) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "timeshare_pretrain"
        )

    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            errors.append(
                finding(4, "historical.import_manifest_row", "closed importer row required")
            )
            continue
        rel = row["path"]
        if (
            not isinstance(rel, str)
            or not rel.startswith("scripts/")
            or Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or rel in seen
            or rel == "scripts/timeshare_pretrain.py"
        ):
            errors.append(
                finding(4, "historical.import_manifest_path", str(rel))
            )
            continue
        seen.add(rel)
        path = root / rel
        if not path.is_file():
            errors.append(finding(4, "historical.import_manifest_missing", rel))
            continue
        header = "\n".join(read_text(path).splitlines()[:20])
        if "EMBER_ARTIFACT_CLASS=historical_only" not in header:
            errors.append(finding(4, "historical.import_manifest_marker", rel))
        if row["classification"] != "historical_only":
            errors.append(finding(4, "historical.import_manifest_class", rel))
        if row["import_outcome"] not in {
            "importable", "execution_denied_by_own_guard"
        }:
            errors.append(finding(4, "historical.import_manifest_outcome", rel))
        if not isinstance(row["module_scope"], bool):
            errors.append(finding(4, "historical.import_manifest_scope", rel))
        if (
            isinstance(row["nested_import_count"], bool)
            or not isinstance(row["nested_import_count"], int)
            or row["nested_import_count"] < 0
        ):
            errors.append(finding(4, "historical.import_manifest_nested", rel))
        try:
            tree = ast.parse(read_text(path), filename=rel)
            module_scope = any(is_timeshare_import(node) for node in tree.body)
            nested_import_count = sum(
                1
                for node in ast.walk(tree)
                if is_timeshare_import(node) and node not in tree.body
            )
            if row["module_scope"] is not module_scope:
                errors.append(finding(4, "historical.import_manifest_scope", rel))
            if row["nested_import_count"] != nested_import_count:
                errors.append(finding(4, "historical.import_manifest_nested", rel))
        except SyntaxError as exc:
            errors.append(finding(4, "historical.import_manifest_syntax", f"{rel}: {exc}"))
        row_hash = row["sha256"]
        if not isinstance(row_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", row_hash):
            errors.append(finding(4, "historical.import_manifest_hash", rel))
        elif sha256(path) != row_hash.upper():
            errors.append(finding(4, "historical.import_manifest_hash", rel))


def parse_graph_selection(
    selection_path: Path,
    active_path: str,
    policy: dict[str, Any] | None,
    errors: list[dict[str, Any]],
) -> str | None:
    valid = True
    selected_graph = Path(active_path)
    if not selected_graph.is_absolute():
        selected_graph = (selection_path.parent / selected_graph).resolve()
    if selected_graph.name != "EMBER-GOAL-GRAPH.json":
        errors.append(
            finding(4, "selection.graph_path_invalid", str(selected_graph))
        )
        valid = False
    if not selected_graph.is_file():
        errors.append(
            finding(4, "selection.graph_file_missing", str(selected_graph))
        )
        return None
    try:
        graph = json.loads(read_text(selected_graph))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        errors.append(finding(4, "selection.graph_invalid", str(exc)))
        return None
    if not isinstance(graph, dict):
        errors.append(finding(4, "selection.graph_invalid", "root must be an object"))
        return None
    if graph.get("schema_version") != GOAL_GRAPH_SCHEMA:
        errors.append(
            finding(
                4,
                "selection.graph_schema",
                str(graph.get("schema_version", "<missing>")),
            )
        )
        valid = False
    program = graph.get("program")
    if (
        not isinstance(program, dict)
        or program.get("id") != "EMBER"
        or program.get("state") != "ACTIVE"
    ):
        errors.append(
            finding(4, "selection.graph_program", "EMBER program must be ACTIVE")
        )
        valid = False
    if policy is None:
        errors.append(
            finding(4, "selection.graph_policy_missing", "docs/domains/governance/authority/GOAL.md policy is unavailable")
        )
        return None
    expected_workstreams = policy.get("active_workstream_ids")
    if (
        not isinstance(expected_workstreams, list)
        or not expected_workstreams
        or not all(isinstance(item, str) and item for item in expected_workstreams)
    ):
        errors.append(
            finding(
                4,
                "selection.graph_policy_workstreams",
                "active workstream policy is invalid",
            )
        )
        return None
    expected_graph_nodes = policy.get("goal_graph_node_ids")
    if (
        not isinstance(expected_graph_nodes, list)
        or not expected_graph_nodes
        or not all(isinstance(item, str) and item for item in expected_graph_nodes)
        or len(expected_graph_nodes) != len(set(expected_graph_nodes))
        or not set(expected_workstreams).issubset(expected_graph_nodes)
    ):
        errors.append(
            finding(
                4,
                "selection.graph_policy_nodes",
                "goal graph node policy is invalid",
            )
        )
        return None
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        errors.append(finding(4, "selection.graph_nodes", "nodes must be an array"))
        return None
    by_id: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not node["id"]
        ):
            errors.append(
                finding(4, "selection.graph_node_id", "every node needs a string id")
            )
            valid = False
            continue
        by_id.setdefault(node["id"], []).append(node)
    observed_node_ids = Counter(
        node["id"]
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    )
    if observed_node_ids != Counter(expected_graph_nodes):
        errors.append(
            finding(
                4,
                "selection.graph_node_set",
                "graph node IDs must exactly equal goal_graph_node_ids",
            )
        )
        valid = False
    graph_root = selected_graph.parent.parent.resolve()
    for workstream in expected_graph_nodes:
        matches = by_id.get(workstream, [])
        if len(matches) != 1:
            errors.append(
                finding(
                    4,
                    "selection.graph_workstream",
                    f"{workstream}: expected exactly one node, found {len(matches)}",
                )
            )
            valid = False
            continue
        node = matches[0]
        if node.get("state") not in GOAL_GRAPH_STATES:
            errors.append(
                finding(
                    4,
                    "selection.graph_workstream_state",
                    f"{workstream}: {node.get('state', '<missing>')}",
                )
            )
            valid = False
        raw_goal_path = node.get("goal_path")
        declared_hash = node.get("goal_sha256")
        if (
            not isinstance(raw_goal_path, str)
            or not raw_goal_path
            or Path(raw_goal_path).is_absolute()
        ):
            errors.append(
                finding(
                    4,
                    "selection.graph_goal_path",
                    f"{workstream}: invalid goal_path",
                )
            )
            valid = False
            continue
        goal_path = (graph_root / raw_goal_path).resolve()
        try:
            goal_path.relative_to(graph_root)
        except ValueError:
            errors.append(
                finding(
                    4,
                    "selection.graph_goal_path_escape",
                    f"{workstream}: {raw_goal_path}",
                )
            )
            valid = False
            continue
        if not goal_path.is_file():
            errors.append(
                finding(
                    4,
                    "selection.graph_goal_file_missing",
                    f"{workstream}: {goal_path}",
                )
            )
            valid = False
            continue
        actual_hash = hashlib.sha256(goal_path.read_bytes()).hexdigest()
        if (
            not isinstance(declared_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", declared_hash)
            or declared_hash != actual_hash
        ):
            errors.append(
                finding(
                    4,
                    "selection.graph_goal_hash_mismatch",
                    f"{workstream}: declared goal bytes do not match",
                )
            )
            valid = False
    active_goal = policy.get("active_goal_id")
    if not isinstance(active_goal, str) or not re.fullmatch(r"EMBER-\d{2}", active_goal):
        errors.append(
            finding(4, "selection.graph_policy_goal", str(active_goal or "<missing>"))
        )
        return None
    return active_goal if valid else None


def parse_selection(
    path: Path | None,
    errors: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> str | None:
    if path is None:
        return None
    if not path.is_file():
        errors.append(finding(4, "selection.missing", "durable selection file is absent"))
        return None
    values: dict[str, str] = {}
    valid = True
    for raw in read_text(path).splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        if key in {"state", "active_goal", "active_goal_path"} and key in values:
            errors.append(finding(4, "selection.duplicate_key", key))
            valid = False
            continue
        values[key] = value.strip()
    if values.get("state") != "active":
        errors.append(finding(4, "selection.not_active", "durable selection state must be active"))
        valid = False
    active_goal = values.get("active_goal", "")
    active_path = values.get("active_goal_path", "")
    if active_goal == "graph":
        if not active_path or active_path == "none":
            errors.append(finding(4, "selection.path_missing", "active_goal_path is absent"))
            return None
        return parse_graph_selection(path, active_path, policy, errors)
    if not re.fullmatch(r"EMBER-\d{2}", active_goal):
        errors.append(finding(4, "selection.goal_invalid", active_goal or "<missing>"))
        valid = False
    if not active_path or active_path == "none":
        errors.append(finding(4, "selection.path_missing", "active_goal_path is absent"))
        valid = False
    elif active_goal and active_goal.lower() not in active_path.lower():
        errors.append(finding(4, "selection.path_goal_mismatch", active_path))
        valid = False
    if active_goal == ACTIVE_GOAL_ID and active_path:
        normalized = active_path.replace("\\", "/").lower()
        if not normalized.endswith(EXPECTED_ACTIVE_GOAL_SUFFIX):
            errors.append(
                finding(
                    4,
                    "selection.path_exact_mismatch",
                    EXPECTED_ACTIVE_GOAL_SUFFIX,
                )
            )
            valid = False
        else:
            selected_goal = Path(active_path)
            if not selected_goal.is_absolute():
                selected_goal = (path.parent / selected_goal).resolve()
            if not selected_goal.is_file():
                errors.append(
                    finding(4, "selection.goal_file_missing", str(selected_goal))
                )
                valid = False
            else:
                selected_text = read_text(selected_goal)
                if not re.search(
                    rf"(?m)^goal_id:\s*{re.escape(ACTIVE_GOAL_ID)}\s*$",
                    selected_text,
                ):
                    errors.append(
                        finding(4, "selection.goal_file_id_mismatch", str(selected_goal))
                    )
                    valid = False
                if not re.search(
                    r"(?m)^allows_new_network:\s*true\s*$", selected_text
                ):
                    errors.append(
                        finding(4, "selection.goal_forbids_network", str(selected_goal))
                    )
                    valid = False
    return active_goal if valid else None


def parse_config_classifications(
    root: Path, errors: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    try:
        continuity_path = authority_path(root, "CONTINUITY.md")
    except ValueError:
        return {}
    lines = read_text(continuity_path).splitlines()
    table_rows: list[list[str]] = []
    for index, raw in enumerate(lines):
        if not raw.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if cells != CONFIG_CLASSIFICATION_HEADER:
            continue
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                if table_rows:
                    break
                continue
            if not candidate.lstrip().startswith("|"):
                break
            row = [cell.strip() for cell in candidate.strip().strip("|").split("|")]
            if len(row) != len(CONFIG_CLASSIFICATION_HEADER):
                continue
            if all(set(cell) <= {"-", ":"} for cell in row):
                continue
            table_rows.append(row)
        break

    classifications: dict[str, dict[str, str]] = {}
    for row in table_rows:
        item = dict(zip(CONFIG_CLASSIFICATION_HEADER, row))
        rel = item["path"]
        if rel in classifications:
            errors.append(finding(4, "config.classification_duplicate", rel))
            continue
        if not rel.startswith("configs/") or not rel.endswith(".json"):
            errors.append(finding(4, "config.classification_path_invalid", rel))
            continue
        if item["artifact_class"] != "historical_only":
            errors.append(
                finding(4, "config.external_class_invalid", f"{rel}: historical_only required")
            )
        if not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"]):
            errors.append(finding(4, "config.classification_hash_invalid", rel))
        classifications[rel] = item
    return classifications


def check_configs(root: Path, policy: dict[str, Any] | None, errors: list[dict[str, Any]], active_goal: str | None = None) -> None:
    config_root = root / "configs"
    if not config_root.is_dir():
        errors.append(finding(4, "configs.missing", "configs directory is absent"))
        return
    paths: list[Path] = []
    sidecar_authorities: dict[str, dict[str, Any]] = {}
    for path in sorted(config_root.rglob("*.json")):
        if not path.name.endswith(".authority.json"):
            paths.append(path)
            continue
        rel = path.relative_to(root).as_posix()
        artifact_rel = rel[: -len(".authority.json")] + ".json"
        artifact_path = root / artifact_rel
        try:
            sidecar = json.loads(read_text(path))
            authority = sidecar.get("authority") if isinstance(sidecar, dict) else None
            valid = bool(
                isinstance(sidecar, dict)
                and set(sidecar) == {
                    "schema_version", "artifact_path", "artifact_sha256", "authority"
                }
                and sidecar.get("schema_version")
                == "ember-content-addressed-authority-binding/v1"
                and sidecar.get("artifact_path") == artifact_rel
                and artifact_path.is_file()
                and sidecar.get("artifact_sha256") == sha256(artifact_path).lower()
                and isinstance(authority, dict)
                and set(authority) == {
                    "goal_id",
                    "workstream_id",
                    "next_executed_outcome",
                    "artifact_class",
                    "execution_authority",
                }
                and authority.get("goal_id")
                == (active_goal or (policy or {}).get("active_goal_id"))
                and isinstance(authority.get("workstream_id"), str)
                and bool(authority.get("workstream_id"))
                and isinstance(authority.get("next_executed_outcome"), str)
                and bool(authority.get("next_executed_outcome"))
                and authority.get("artifact_class") == "historical_only"
                and authority.get("execution_authority") == "denied"
            )
        except Exception:
            valid = False
        if not valid:
            errors.append(finding(4, "config.authority_sidecar_invalid", rel))
        else:
            sidecar_authorities[artifact_rel] = authority
    if not paths:
        errors.append(finding(4, "configs.empty", "no classified configs found"))
        return
    required_caps = set(REQUIRED_CAPABILITIES)
    allows_new = bool((policy or {}).get("allows_new_network"))
    classifications = parse_config_classifications(root, errors)
    seen_paths: set[str] = set()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        seen_paths.add(rel)
        try:
            payload = json.loads(read_text(path))
        except Exception as exc:
            errors.append(finding(4, "config.invalid_json", f"{rel}: {exc}"))
            continue
        authority = payload.get("authority") if isinstance(payload, dict) else None
        if not isinstance(authority, dict):
            sidecar_authority = sidecar_authorities.get(rel)
            if sidecar_authority is not None:
                authority = sidecar_authority
                external = None
            else:
                external = classifications.get(rel)
            if external is None:
                if sidecar_authority is None:
                    errors.append(finding(4, "config.authority_missing", rel))
                    continue
            else:
                actual_hash = sha256(path)
                if actual_hash != external["sha256"].upper():
                    errors.append(
                        finding(
                            4,
                            "config.classification_hash_mismatch",
                            f"{rel}: expected {external['sha256']}, got {actual_hash}",
                        )
                    )
                authority = external
        for field in ("goal_id", "next_executed_outcome"):
            if not isinstance(authority.get(field), str) or not authority[field].strip():
                errors.append(finding(4, f"config.{field}_missing", rel))
        artifact_class = authority.get("artifact_class")
        execution = authority.get("execution_authority")
        if artifact_class == "historical_only":
            if execution != "denied":
                errors.append(finding(4, "config.historical_execution", rel))
            continue
        if active_goal is not None and authority.get("goal_id") != active_goal:
            errors.append(
                finding(
                    4,
                    "selection.goal_binding",
                    f"{rel}: expected {active_goal}, got {authority.get('goal_id')}",
                )
            )
        if (policy or {}).get("authority_only_goal") is True:
            errors.append(
                finding(
                    7,
                    "config.dispatchable_during_authority_only",
                    f"{rel}: only historical execution-denied configs are legal",
                )
            )
        if artifact_class == "borrowed_reference":
            if execution != "reference_only":
                errors.append(finding(4, "config.borrowed_execution", rel))
            if authority.get("capability_credit") not in (None, "none"):
                errors.append(finding(4, "config.borrowed_capability_credit", rel))
            if authority.get("frozen") is not True:
                errors.append(finding(4, "config.borrowed_not_frozen", rel))
            if authority.get("lineage_ingress") is not False:
                errors.append(finding(4, "config.borrowed_lineage_ingress", rel))
            if authority.get("model_mediated_signals"):
                errors.append(finding(4, "config.model_mediated_signal", rel))
            continue
        if artifact_class not in {"research_candidate", "model_milestone"}:
            errors.append(finding(4, "config.artifact_class_invalid", f"{rel}: {artifact_class}"))
            continue
        if not allows_new:
            errors.append(finding(7, "config.new_network_forbidden", rel))
        params = authority.get("total_parameters")
        if not isinstance(params, int) or params < 3_000_000_000:
            errors.append(finding(4, "config.sub_3b_network", f"{rel}: {params}"))
        caps = authority.get("native_capabilities")
        if not isinstance(caps, list) or set(caps) != required_caps or len(caps) != len(required_caps):
            errors.append(finding(4, "config.native_capabilities", rel))
        backbone = str(authority.get("published_family_backbone", "")).strip().lower()
        if backbone not in ("", "none"):
            errors.append(finding(4, "config.borrowed_backbone", f"{rel}: {backbone}"))
        signals = authority.get("model_mediated_signals")
        if not isinstance(signals, list) or signals:
            errors.append(
                finding(
                    4,
                    "config.model_mediated_signal",
                    f"{rel}: model_mediated_signals must be an explicit empty list",
                )
            )
    for rel in sorted(set(classifications) - seen_paths):
        errors.append(finding(4, "config.classification_target_missing", rel))


def _tracked_relative_paths(root: Path) -> set[str] | None:
    """Return the index paths for a Git worktree, or ``None`` off-Git."""
    if not (root / ".git").exists():
        return None
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if tracked.returncode != 0:
        return None
    return {
        raw.decode("utf-8", "surrogateescape")
        for raw in tracked.stdout.split(b"\0")
        if raw
    }


def check_lower_precedence_authority(root: Path, errors: list[dict[str, Any]]) -> None:
    allowed = {
        *(canonical_authority_reference(root, name) for name in AUTHORITY_DOCUMENT_NAMES),
        *expected_governing_surfaces(root),
    }
    excluded_prefixes = (
        ".git/",
        "receipts/",
        "docs/history/",
        "scripts/ember_totality/receipts-",
    )
    suffixes = {".md", ".json", ".toml", ".yaml", ".yml"}
    # A live checkout may contain large, untracked run products under
    # ``scratch/``.  They are not part of the commit being guarded and must
    # not be able to block a push merely because a copied historical note
    # contains authority-shaped prose.  Keep scanning tracked scratch files
    # and every other untracked path; only untracked ``scratch/`` is outside
    # this commit-level authority check.
    tracked_rel = _tracked_relative_paths(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
        if tracked_rel is not None and rel.startswith("scratch/") and rel not in tracked_rel:
            continue
        if rel in allowed or rel.startswith(excluded_prefixes):
            continue
        try:
            text = read_text(path)
        except (UnicodeDecodeError, OSError):
            continue
        if text.lstrip("\ufeff \t\r\n").startswith(HISTORICAL_ONLY_MARKER):
            continue
        if any(pattern.search(text) for pattern in LOWER_AUTHORITY_PATTERNS):
            errors.append(
                finding(
                    4,
                    "authority.lower_precedence_claim",
                    f"{rel} contains an authority/launch/completion claim outside the authority allowlist",
                )
            )


def check_mechanism_registry(root: Path, errors: list[dict[str, Any]]) -> None:
    path = root / "docs" / "ledgers" / "technique-registry.jsonl"
    erasure_statuses = {"KILL", "PARK", "EXCLUDED", "RETIRED"}
    registry_lines = read_text(path).splitlines() if path.is_file() else []
    for line_number, raw in enumerate(registry_lines, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            errors.append(finding(4, "authority.registry_invalid", f"line {line_number}: {exc}"))
            continue
        status = str(row.get("status", "")).upper()
        if status in erasure_statuses:
            errors.append(
                finding(
                    4,
                    "authority.mechanism_erasure",
                    f"{row.get('id', '<missing-id>')}: status {status} erases or indefinitely parks a research family",
                )
            )

    bypass_re = re.compile(
        r"LEGAL_STATUSES\s*=\s*[^\n]*(?:KILL|PARK|EXCLUDED|RETIRED)",
        re.IGNORECASE,
    )
    for source_root in (root / "scripts", root / "tools"):
        if not source_root.is_dir():
            continue
        for source in sorted(source_root.rglob("*.py")):
            rel = source.relative_to(root).as_posix()
            if rel.startswith("scripts/tests/"):
                continue
            text = read_text(source)
            match = bypass_re.search(text)
            if not match:
                continue
            prefix = text[: match.start()]
            historical_guarded = (
                prefix.lstrip("\ufeff \t\r\n").startswith(
                    "# EMBER_ARTIFACT_CLASS=historical_only"
                )
                and "raise SystemExit" in prefix
                and "historical_only" in prefix
            )
            if historical_guarded:
                continue
            errors.append(
                finding(
                    4,
                    "authority.mechanism_erasure_bypass",
                    f"{rel} re-legalizes a terminal registry status",
                )
            )


def check_authority_supersession_crosswalk(
    root: Path, errors: list[dict[str, Any]]
) -> None:
    try:
        from authority_supersession_gate import (
            AuthoritySupersessionGateError,
            validate_current_authority_crosswalk,
        )
        result = validate_current_authority_crosswalk(root, require_current_authority=False)
        if result is not None and result.get("status") not in {"PASS", "PASS_WITH_CUSTODY_GAPS"}:
            raise AuthoritySupersessionGateError(
                f"unexpected crosswalk status: {result.get('status')!r}"
            )
    except Exception as exc:
        errors.append(finding(4, "authority.supersession_crosswalk_invalid", str(exc)))


def parse_markdown_table(text: str, expected_columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in text.splitlines():
        if not raw.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if len(cells) != expected_columns:
            continue
        if not cells or cells[0] in {"id", "---"} or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def check_state(root: Path, errors: list[dict[str, Any]]) -> None:
    try:
        pointer_path = authority_path(root, "STATE.md")
        path = authority_path(root, "CONTINUITY.md")
    except ValueError as exc:
        errors.append(finding(6, "state.missing", str(exc)))
        return
    pointer_lines = [line.strip() for line in read_text(pointer_path).splitlines() if line.strip()]
    if len(pointer_lines) != 1 or "CONTINUITY.md" not in pointer_lines[0]:
        errors.append(finding(6, "state.pointer_invalid", f"{authority_relative_path(root, 'STATE.md')} must be a one-line docs/authority/CONTINUITY.md pointer"))
    rows = parse_markdown_table(read_text(path), 9)
    if not rows:
        errors.append(finding(6, "state.identity_rows_missing", "no 9-column identity rows in docs/authority/CONTINUITY.md"))
        return
    ids = [row[0] for row in rows]
    identities = [row[2] for row in rows]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count != 1)
    duplicate_identity = sorted(item for item, count in Counter(identities).items() if count != 1)
    if duplicate_ids:
        errors.append(finding(6, "state.duplicate_id", ",".join(duplicate_ids)))
    if duplicate_identity:
        errors.append(finding(6, "state.ambiguous_identity", ",".join(duplicate_identity)))
    allowed_classes = {
        "historical_only",
        "borrowed_reference",
        "research_prototype",
        "target",
        "current_admissible",
        "execution_measurement_only",
    }
    seen_classes = set()
    for row in rows:
        rid, object_type, identity, artifact_class, params, _tokens, backend, credit, evidence = row
        seen_classes.add(artifact_class)
        if artifact_class not in allowed_classes:
            errors.append(finding(6, "state.artifact_class_invalid", f"{rid}: {artifact_class}"))
        try:
            numeric_params = int(params)
        except ValueError:
            numeric_params = None
        if numeric_params is not None and numeric_params < 3_000_000_000:
            if artifact_class != "historical_only" or credit.lower() != "none":
                errors.append(finding(6, "state.sub_3b_credit", rid))
        if artifact_class == "borrowed_reference" and credit.lower() != "none":
            errors.append(finding(6, "state.borrowed_credit", rid))
        if artifact_class == "execution_measurement_only":
            if credit.lower() != "none":
                errors.append(finding(6, "state.execution_measurement_credit", rid))
            if re.fullmatch(r"receipt-sha256:[0-9a-f]{64}", identity) is None:
                errors.append(finding(6, "state.execution_measurement_identity", rid))
            if (
                "execution+measurement only" not in evidence
                or "no sufficiency/capability/comparison claim" not in evidence
            ):
                errors.append(finding(6, "state.execution_measurement_boundary_missing", rid))
            if re.search(r"(?:^|;\s*)caveat:\s*\S", evidence) is None:
                errors.append(finding(6, "state.execution_measurement_caveat_missing", rid))
        if artifact_class == "target" and not identity.startswith("uninstantiated:"):
            errors.append(finding(6, "state.target_identity", rid))
        if not object_type or not identity or not backend:
            errors.append(finding(6, "state.identity_field_missing", rid))
    for required in ("historical_only", "borrowed_reference", "target"):
        if required not in seen_classes:
            errors.append(finding(6, "state.required_class_missing", required))


def check_execution_boundary(
    root: Path,
    policy: dict[str, Any] | None,
    errors: list[dict[str, Any]],
) -> None:
    try:
        path = authority_path(root, "CONTINUITY.md")
    except ValueError as exc:
        errors.append(finding(7, "boundary.missing", str(exc)))
        return
    try:
        text = read_text(path)
    except Exception as exc:
        errors.append(finding(7, "boundary.unreadable", str(exc)))
        return
    matches = EXECUTION_BOUNDARY_RE.findall(text)
    if not matches:
        errors.append(
            finding(7, "boundary.missing", "EMBER_EXECUTION_BOUNDARY_V1 is absent")
        )
        return
    if len(matches) != 1:
        errors.append(
            finding(
                7,
                "boundary.duplicate",
                f"expected one execution boundary, found {len(matches)}",
            )
        )
        return
    try:
        boundary = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        errors.append(finding(7, "boundary.invalid_json", str(exc)))
        return
    if not isinstance(boundary, dict):
        errors.append(finding(7, "boundary.not_object", "boundary must be an object"))
        return

    expect(
        errors,
        7,
        boundary.get("schema") == EXECUTION_BOUNDARY_SCHEMA,
        "boundary.schema",
        EXECUTION_BOUNDARY_SCHEMA,
    )
    execution_class = boundary.get("execution_class")
    expect(
        errors,
        7,
        execution_class in EXECUTION_CLASSES,
        "boundary.execution_class_invalid",
        str(execution_class),
    )
    for field in ("permitted_operations", "blocked_operations", "prerequisite_receipts"):
        value = boundary.get(field)
        expect(
            errors,
            7,
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value),
            "boundary.field_invalid",
            field,
        )
    command = boundary.get("next_executable_command")
    expect(
        errors,
        7,
        isinstance(command, str) and bool(command.strip()),
        "boundary.command_missing",
        "next_executable_command",
    )
    blocked = boundary.get("blocked_operations")
    if isinstance(blocked, list):
        for operation in REQUIRED_BLOCKED_OPERATIONS:
            expect(
                errors,
                7,
                operation in blocked,
                "boundary.blocked_operation_erased",
                operation,
            )
    permitted = boundary.get("permitted_operations")
    if isinstance(permitted, list):
        if execution_class == "authority_only":
            for operation in EXECUTION_OPERATIONS:
                expect(
                    errors,
                    7,
                    operation not in permitted,
                    "boundary.authority_only_execution_op",
                    operation,
                )
        elif execution_class == "goal_executing":
            expect(
                errors,
                7,
                "owned_3b_pretraining" in permitted,
                "boundary.execution_op_missing",
                "owned_3b_pretraining",
            )

    if policy is None:
        return
    expect(
        errors,
        7,
        boundary.get("goal_id") == policy.get("active_goal_id"),
        "boundary.goal_mismatch",
        f"boundary={boundary.get('goal_id')}, policy={policy.get('active_goal_id')}",
    )
    expect(
        errors,
        7,
        boundary.get("next_executed_outcome") == policy.get("next_executed_outcome"),
        "boundary.outcome_mismatch",
        "execution boundary and GOAL outcome differ",
    )
    allows_new_network = boundary.get("allows_new_network")
    expect(
        errors,
        7,
        isinstance(allows_new_network, bool)
        and allows_new_network == policy.get("allows_new_network"),
        "boundary.new_network_mismatch",
        "execution boundary and GOAL network authority differ",
    )
    expect(
        errors,
        7,
        (execution_class == "authority_only")
        == (policy.get("authority_only_goal") is True),
        "boundary.execution_class_mismatch",
        "execution class and authority_only_goal differ",
    )


def validate_artifact_binding(
    text: str,
    suffix: str,
    active_goal: str,
    next_outcome: str,
    allowed_workstreams: tuple[str, ...] | list[str] = (),
) -> bool:
    allowed = set(allowed_workstreams)

    def valid_binding(binding: dict[str, Any]) -> bool:
        workstream = binding.get("workstream_id")
        return bool(
            binding.get("goal_id") == active_goal
            and binding.get("next_executed_outcome") == next_outcome
            and (
                isinstance(workstream, str) and workstream in allowed
            )
        )

    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        binding = payload.get("authority")
        if not isinstance(binding, dict):
            binding = payload
        return valid_binding(binding)
    if suffix == ".jsonl":
        rows = []
        try:
            rows = [json.loads(raw) for raw in text.splitlines() if raw.strip()]
        except json.JSONDecodeError:
            return False
        return bool(rows) and all(
            isinstance(row, dict) and valid_binding(row)
            for row in rows
        )
    def marker_values(field: str) -> list[str]:
        values: list[str] = []
        marker = f"{field}:"
        for raw in text.splitlines():
            line = raw.strip()
            is_marker_surface = False
            if line.startswith("<!--") and line.endswith("-->"):
                line = line[4:-3].strip()
                is_marker_surface = True
            elif line.startswith("//"):
                line = line[2:].strip()
                is_marker_surface = True
            elif line.startswith("#"):
                line = line[1:].strip()
                is_marker_surface = True
            elif suffix in {".md", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
                is_marker_surface = True
            if is_marker_surface and line.startswith(marker):
                values.append(line[len(marker) :].strip())
        return values

    goal_matches = marker_values("goal_id")
    outcome_matches = marker_values("next_executed_outcome")
    workstream_matches = marker_values("workstream_id")
    return bool(
        goal_matches == [active_goal]
        and outcome_matches == [next_outcome]
        and (
            len(workstream_matches) == 1
            and workstream_matches[0] in allowed
        )
    )


def artifact_workstream_ids(text: str, suffix: str) -> set[str]:
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return set()
        if not isinstance(payload, dict):
            return set()
        binding = payload.get("authority")
        if not isinstance(binding, dict):
            binding = payload
        value = binding.get("workstream_id")
        return {value} if isinstance(value, str) else set()
    if suffix == ".jsonl":
        try:
            rows = [json.loads(raw) for raw in text.splitlines() if raw.strip()]
        except json.JSONDecodeError:
            return set()
        return {
            row["workstream_id"]
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("workstream_id"), str)
        }
    values: set[str] = set()
    marker = "workstream_id:"
    for raw in text.splitlines():
        line = raw.strip()
        is_marker_surface = False
        if line.startswith("<!--") and line.endswith("-->"):
            line = line[4:-3].strip()
            is_marker_surface = True
        elif line.startswith("//"):
            line = line[2:].strip()
            is_marker_surface = True
        elif line.startswith("#"):
            line = line[1:].strip()
            is_marker_surface = True
        elif suffix in {".md", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
            is_marker_surface = True
        if is_marker_surface and line.startswith(marker):
            values.add(line[len(marker) :].strip())
    return values


def workstream_path_allowed(
    relative_path: str,
    workstream_id: str,
    scopes: dict[str, Any],
) -> bool:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    scope = scopes.get(workstream_id)
    if not isinstance(scope, dict):
        return False
    prefixes = scope.get("prefixes")
    if not isinstance(prefixes, list) or not all(
        isinstance(prefix, str) and prefix for prefix in prefixes
    ):
        return False
    matches = any(normalized.startswith(prefix) for prefix in prefixes)
    if scope.get("mode") == "only":
        return matches
    if scope.get("mode") == "all_except":
        return not matches
    return False


def verified_derived_receipt_index_paths(
    root: Path,
    changed_paths: set[str],
    errors: list[dict[str, Any]],
) -> set[str]:
    """Authorize only byte-exact deterministic claims-index outputs."""
    derived_paths = {"receipts/INDEX.jsonl", "receipts/CLAIMS.md"}
    if not changed_paths & derived_paths:
        return set()
    try:
        import importlib.util
        builder_path = root / "src" / "ember" / "governance" / "scripts" / "build_claims_index.py"
        spec = importlib.util.spec_from_file_location(
            "ember_authority_claims_index_builder", builder_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {builder_path}")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        rows, _stats = builder.build_index(root / "receipts")
        expected = {
            "receipts/INDEX.jsonl": builder.render_index_jsonl(rows),
            "receipts/CLAIMS.md": builder.render_claims_md(rows),
        }
        for relative, expected_text in expected.items():
            actual_text = (root / relative).read_text(
                encoding="utf-8", errors="strict"
            )
            if actual_text != expected_text:
                raise ValueError(f"{relative} is not deterministic derived output")
        return derived_paths
    except Exception as exc:
        errors.append(finding(4, "artifact.derived_index_invalid", str(exc)))
        return set()


CROSSWALK_REL = "manifests/authority/issue-35-authority-supersession-crosswalk-v1.json"


def crosswalk_content_pins(payload: Any) -> dict[str, str]:
    """Every content digest the crosswalk pins, keyed by what it describes.

    Deliberately excludes `crosswalk_sha256` (a self-hash, which moves whenever
    ANY field moves, including source_commit itself) so the coupling rule below
    reacts to described-content drift only.
    """
    if not isinstance(payload, dict):
        raise ValueError("crosswalk payload must be an object")
    pins: dict[str, str] = {}
    authority = payload.get("current_authority")
    if isinstance(authority, dict):
        pins[f"matrix:{authority.get('matrix_path')}"] = str(
            authority.get("matrix_sha256")
        )
    groups: list[tuple[str, Any]] = []
    for registry in payload.get("source_registries") or []:
        if isinstance(registry, dict):
            groups.append((str(registry.get("registry_id")), registry.get("evidence")))
    for row in payload.get("rows") or []:
        if isinstance(row, dict):
            label = f"{row.get('source_registry')}/{row.get('source_id')}"
            groups.append((label, row.get("evidence")))
    for label, evidence in groups:
        for item in evidence or []:
            if isinstance(item, dict):
                pins[f"{label}:{item.get('path')}"] = str(item.get("sha256"))
    return pins


def _git_blob(root: Path, revision: str, rel: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{rel}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def check_crosswalk_source_commit_repin(
    root: Path,
    errors: list[dict[str, Any]],
    *,
    changed_range: str | None = None,
    staged: bool = False,
) -> None:
    """`source_commit` must move whenever the crosswalk's content pins move.

    Contract (a) of issue #1381. Without this the field is a pin nothing keeps
    true, and `--expected-source-commit` converts an honest "unverified" into a
    silent "verified against the wrong commit" -- worse than no pin at all.

    The rule is a coupling rule, checked across a diff, because no single-state
    check can express it: the crosswalk is re-pinned in the SAME commit as the
    content it describes, so at authoring time no commit yet holds those bytes
    and "the pins must reproduce at source_commit" is unsatisfiable by
    construction. What IS enforceable, and what this enforces, is that a re-pin
    may never leave the previous commit's name behind.
    """
    if not changed_range and not staged:
        return
    if staged:
        before_rev, after_rev = "HEAD", ""
    else:
        base = re.split(r"\.\.\.?", changed_range or "", maxsplit=1)
        if len(base) != 2 or not base[0] or not base[1]:
            errors.append(
                finding(
                    4,
                    "authority.crosswalk_range_unparsed",
                    f"cannot read a base and head from range {changed_range!r}",
                )
            )
            return
        before_rev, after_rev = base[0], base[1]

    before_bytes = _git_blob(root, before_rev, CROSSWALK_REL)
    # `git show :path` reads the index -- the staged bytes are what a staged run
    # certifies, not the worktree's.
    after_bytes = _git_blob(root, after_rev, CROSSWALK_REL)
    if before_bytes is None or after_bytes is None or before_bytes == after_bytes:
        # Added, removed, or untouched: nothing to couple. Absence and malformation
        # are already fatal in check_authority_supersession_crosswalk.
        return
    try:
        before = json.loads(before_bytes.decode("utf-8"))
        after = json.loads(after_bytes.decode("utf-8"))
        before_pins = crosswalk_content_pins(before)
        after_pins = crosswalk_content_pins(after)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(finding(4, "authority.crosswalk_repin_unreadable", str(exc)))
        return
    if before_pins == after_pins:
        return
    if before.get("source_commit") != after.get("source_commit"):
        return
    moved = sorted(
        key
        for key in set(before_pins) | set(after_pins)
        if before_pins.get(key) != after_pins.get(key)
    )
    errors.append(
        finding(
            4,
            "authority.crosswalk_source_commit_stale",
            f"crosswalk content pins changed while source_commit stayed "
            f"{after.get('source_commit')!r}; moved pins: {', '.join(moved)}",
        )
    )


INPUT_IDENTITY_SCHEMA = "ember-input-identity-v1"


def _identity_pinned_file(
    root: Path, manifest_rel: str, value: Any, errors: list[dict[str, Any]]
) -> Path | None:
    """Resolve a manifest-declared repository-relative path, or record why not."""
    if not isinstance(value, str) or not value:
        errors.append(
            finding(
                4,
                "input_identity.path_invalid",
                f"{manifest_rel}: pinned path must be a non-empty relative string",
            )
        )
        return None
    relative = PurePosixPath(value.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(
            finding(
                4,
                "input_identity.path_invalid",
                f"{manifest_rel}: pinned path {value!r} leaves the worktree",
            )
        )
        return None
    path = root / relative.as_posix()
    if not path.is_file():
        errors.append(
            finding(
                4,
                "input_identity.pinned_file_missing",
                f"{manifest_rel} pins {relative.as_posix()}, which is absent",
            )
        )
        return None
    return path


def _expect_pinned_digest(
    root: Path,
    manifest_rel: str,
    pinned_rel: Any,
    pinned_sha: Any,
    errors: list[dict[str, Any]],
) -> None:
    path = _identity_pinned_file(root, manifest_rel, pinned_rel, errors)
    if path is None:
        return
    if not isinstance(pinned_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", pinned_sha) is None:
        errors.append(
            finding(
                4,
                "input_identity.pin_malformed",
                f"{manifest_rel}: {pinned_rel} carries no sha256 pin",
            )
        )
        return
    actual = sha256(path)
    if actual != pinned_sha.upper():
        errors.append(
            finding(
                4,
                "input_identity.pin_stale",
                f"{manifest_rel} pins {pinned_rel} at {pinned_sha.lower()}, "
                f"but those bytes hash to {actual.lower()}",
            )
        )


def check_input_identity_pins(root: Path, errors: list[dict[str, Any]]) -> None:
    """Every input-identity manifest must pin the bytes that are actually there.

    Contract of issue #1394. The manifest and the artefacts it pins are separate
    files that one change must move together: PR #1333 re-minted
    `owned-four-domain-production-rung-v1.receipt.json` without re-pinning
    `input-identity.json`, and nothing noticed until a certified run failed
    closed at `InputIdentityError byte_drift` hours later.

    Deliberately a state rule rather than a coupling-over-a-diff rule like
    `check_crosswalk_source_commit_repin` above. That rule has to read a diff
    because a crosswalk is re-pinned in the same commit as the content it
    describes, so no single tree can decide it. Here the property -- the pin
    names the bytes on disk -- is decidable from one tree, and deciding it there
    is strictly stronger: it rejects every diff a coupling rule would reject,
    plus the ones it cannot see (a merge of two independently valid branches, a
    re-pin onto a hash no file carries, a receipt edit arriving by any other
    path). Both directions of #1394 fall out of the one comparison.

    Manifests are reached through the configs that select them, which is the
    selection path `resolve_input_identity` itself walks, so a new config or a
    new manifest is covered the day it lands. Execution authority is not
    filtered on: a pin that misdescribes its bytes is a false statement whether
    or not the config naming it may currently dispatch, and curing it edits the
    manifest, never the frozen historical config.
    """
    config_root = root / "configs"
    if not config_root.is_dir():
        # check_configs already reports the absence; nothing to select from.
        return
    manifest_rels: list[str] = []
    for config_path in sorted(config_root.rglob("*.json")):
        try:
            payload = json.loads(read_text(config_path))
        except Exception:
            # check_configs reports unparseable configs; do not double-report.
            continue
        training = payload.get("training") if isinstance(payload, dict) else None
        if not isinstance(training, dict):
            continue
        selected = training.get("input_identity_manifest")
        if isinstance(selected, str) and selected and selected not in manifest_rels:
            manifest_rels.append(selected)

    for manifest_rel in sorted(manifest_rels):
        manifest_path = _identity_pinned_file(root, "configs", manifest_rel, errors)
        if manifest_path is None:
            continue
        try:
            identity = json.loads(read_text(manifest_path))
        except Exception as exc:
            errors.append(
                finding(4, "input_identity.manifest_unreadable", f"{manifest_rel}: {exc}")
            )
            continue
        if not isinstance(identity, dict) or identity.get("schema_version") != INPUT_IDENTITY_SCHEMA:
            # Other identity schemas carry their own pins and their own rules.
            continue
        shard_rel = identity.get("shard_path")
        _expect_pinned_digest(root, manifest_rel, shard_rel, identity.get("sha256"), errors)
        shard_path = root / str(shard_rel) if isinstance(shard_rel, str) else None
        pinned_bytes = identity.get("bytes")
        if shard_path is not None and shard_path.is_file() and pinned_bytes != shard_path.stat().st_size:
            # Runtime admission checks the byte count separately from the digest,
            # so a manifest can satisfy one pin and still fail closed on the other.
            errors.append(
                finding(
                    4,
                    "input_identity.pin_stale",
                    f"{manifest_rel} pins {shard_rel} at {pinned_bytes!r} bytes, "
                    f"but the file holds {shard_path.stat().st_size}",
                )
            )
        receipt_rel = identity.get("admission_receipt_path")
        receipt_sha = identity.get("admission_receipt_sha256")
        if receipt_rel is None and receipt_sha is None:
            continue
        if receipt_rel is None or receipt_sha is None:
            errors.append(
                finding(
                    4,
                    "input_identity.admission_pin_incomplete",
                    f"{manifest_rel}: an admission receipt needs both a path and a sha256",
                )
            )
            continue
        _expect_pinned_digest(root, manifest_rel, receipt_rel, receipt_sha, errors)


def check_changed_artifact_bindings(
    root: Path,
    policy: dict[str, Any] | None,
    errors: list[dict[str, Any]],
    *,
    changed_range: str | None = None,
    staged: bool = False,
    expected_workstream: str | None = None,
) -> None:
    if not changed_range and not staged:
        return
    if policy is None:
        errors.append(finding(4, "artifact.policy_missing", "GOAL policy unavailable"))
        return
    command = ["git", "diff"]
    if staged:
        command.append("--cached")
    command.extend(
        ["--find-renames", "--find-copies", "--name-only", "--diff-filter=ACMRT"]
    )
    if changed_range:
        command.append(changed_range)
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        errors.append(
            finding(4, "artifact.diff_failed", result.stderr.strip() or "git diff failed")
        )
        return
    active_goal = str(policy.get("active_goal_id", ""))
    next_outcome = str(policy.get("next_executed_outcome", ""))
    allowed_workstreams = tuple(policy.get("active_workstream_ids") or ())
    scopes = policy.get("workstream_path_scopes") or {}
    changed_paths = {
        rel.replace("\\", "/") for rel in result.stdout.splitlines()
    }
    range_base: str | None = None
    range_endpoint: str | None = None
    if changed_range:
        left, separator, right = changed_range.partition("..")
        if separator != ".." or not left or not right or right.startswith("."):
            errors.append(
                finding(4, "artifact.changed_range_invalid", changed_range)
            )
            return
        resolved: list[str] = []
        for revision in (left, right):
            commit = subprocess.run(
                ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if commit.returncode != 0 or not commit.stdout.strip():
                errors.append(
                    finding(4, "artifact.changed_range_invalid", changed_range)
                )
                return
            resolved.append(commit.stdout.strip())
        range_base, range_endpoint = resolved
    verified_derived_paths = verified_derived_receipt_index_paths(
        root, changed_paths, errors
    )

    def read_candidate_text(normalized: str, *, optional: bool = False) -> str | None:
        if staged:
            object_name = f":{normalized}"
        elif range_endpoint is not None:
            object_name = f"{range_endpoint}:{normalized}"
        else:
            try:
                return read_text(root / normalized)
            except Exception:
                if optional:
                    return None
                raise
        shown = subprocess.run(
            ["git", "show", object_name],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if shown.returncode != 0:
            if optional:
                return None
            raise OSError(shown.stderr.strip() or f"cannot read {object_name}")
        return shown.stdout

    migration_pairs = (
        ("docs/ember-authority-matrix.md", "docs/authority/ember-authority-matrix.md"),
        ("docs/ember-completeness.md", "docs/contracts/ember-completeness.md"),
        ("docs/registry-dispatch-gate-spec-v0.md", "docs/contracts/registry-dispatch-gate-spec-v0.md"),
        ("docs/nc2-own-technique-contract.md", "docs/contracts/nc2-own-technique-contract.md"),
        ("docs/goal-mode-mechanism.md", "docs/contracts/goal-mode-mechanism.md"),
        ("docs/goal-clear-protocol.md", "docs/contracts/goal-clear-protocol.md"),
        ("docs/goal-live-session.md", "docs/guides/goal-live-session.md"),
        ("docs/ember-floor-contract.md", "docs/contracts/ember-floor-contract.md"),
        ("docs/custody-disposition-20260708.md", "docs/custody/custody-disposition-20260708.md"),
        ("docs/r1-exit-evidence-inventory-20260805.md", "docs/custody/r1-exit-evidence-inventory-20260805.md"),
        ("docs/START-HERE.md", "docs/guides/START-HERE.md"),
        ("docs/PROBLEMS.md", "docs/roadmap/PROBLEMS.md"),
        ("docs/README.md", "docs/DOCS-README.md"),
        ("CONTINUITY.md", "docs/authority/CONTINUITY.md"),
        ("GOVERNANCE.md", "docs/authority/GOVERNANCE.md"),
        ("INVARIANT.md", "docs/authority/INVARIANT.md"),
        ("REDACTIONS.md", "docs/authority/REDACTIONS.md"),
        ("STATE.md", "docs/domains/governance/authority/STATE.md"),
        ("docs/authority/STATE.md", "docs/domains/governance/authority/STATE.md"),
        ("GOAL.md", "docs/domains/governance/authority/GOAL.md"),
    )

    def exact_path_migration_only(normalized: str, staged_text: str) -> bool:
        if staged:
            prior_revision = "HEAD"
        elif range_base is not None:
            prior_revision = range_base
        else:
            return False
        prior = subprocess.run(
            ["git", "show", f"{prior_revision}:{normalized}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if prior.returncode != 0 or prior.stdout == staged_text:
            return False
        transformed = prior.stdout
        sentinels: dict[str, str] = {}
        for index, (_, destination) in enumerate(migration_pairs):
            sentinel = f"__EMBER_AUTHORITY_PATH_{index}__"
            if sentinel in transformed:
                return False
            transformed = transformed.replace(destination, sentinel)
            sentinels[sentinel] = destination
        for source, destination in migration_pairs:
            transformed = transformed.replace(source, destination)
        for sentinel, destination in sentinels.items():
            transformed = transformed.replace(sentinel, destination)
        return transformed == staged_text

    for rel in sorted(changed_paths):
        normalized = rel.replace("\\", "/")
        if normalized in verified_derived_paths:
            continue
        suffix = Path(normalized).suffix.lower()
        control_path = normalized.startswith(
            (
                "receipts/",
                "configs/",
                "experiments/",
                "scripts/",
                "tools/",
                ".github/",
                ".githooks/",
                "baseline/",
            )
        )
        source_suffixes = {
            ".py",
            ".sh",
            ".ps1",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".rs",
            ".c",
            ".cc",
            ".cpp",
            ".cxx",
            ".h",
            ".hpp",
            ".cu",
            ".cuh",
            ".go",
            ".java",
            ".kt",
            ".kts",
            ".rb",
            ".pl",
            ".lua",
            ".swift",
            ".cs",
        }
        if not control_path and suffix not in source_suffixes:
            continue
        inline_binding_supported = suffix in {
            "",
            ".json",
            ".jsonl",
            ".md",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            *source_suffixes,
        }
        try:
            candidate_text = read_candidate_text(normalized)
            if candidate_text is None:
                raise OSError("cannot read candidate bytes")
            text = candidate_text
            # The .jsonl branch below narrows `text` to the added rows. A
            # content-addressed sidecar binds the whole artifact, so keep the
            # full bytes before that narrowing happens.
            artifact_text = text
            if suffix == ".jsonl":
                diff_command = ["git", "diff"]
                if staged:
                    diff_command.append("--cached")
                if changed_range:
                    diff_command.append(changed_range)
                diff_command.extend(["--unified=0", "--", normalized])
                changed = subprocess.run(
                    diff_command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if changed.returncode != 0:
                    raise OSError(changed.stderr.strip() or "cannot read JSONL diff")
                added = [
                    raw[1:]
                    for raw in changed.stdout.splitlines()
                    if raw.startswith("+") and not raw.startswith("+++") and raw[1:].strip()
                ]
                text = "\n".join(added)
        except Exception as exc:
            errors.append(finding(4, "artifact.binding_unreadable", f"{normalized}: {exc}"))
            continue
        if exact_path_migration_only(normalized, artifact_text):
            continue
        # An artifact that cannot carry the binding inline — a generated file
        # with a fixed schema, or frozen evidence whose sha256 another document
        # cites, so that adding fields to it would break the citation — binds
        # through a content-addressed sidecar beside it, named by replacing the
        # artifact's suffix with `.authority.json`. The sidecar is only
        # believed when it names this exact path AND records the artifact's
        # current digest, so it cannot be pointed at a file it does not
        # describe, and it cannot survive the artifact being edited.
        sidecar_rel = str(PurePosixPath(normalized).with_suffix(".authority.json"))
        sidecar_text = (
            read_candidate_text(sidecar_rel, optional=True)
            if sidecar_rel != normalized
            else None
        )
        if sidecar_text is not None:
            try:
                sidecar = json.loads(sidecar_text)
                expected_digest = hashlib.sha256(
                    artifact_text.encode("utf-8")
                ).hexdigest()
                binding_valid = bool(
                    isinstance(sidecar, dict)
                    and sidecar.get("schema_version")
                    == "ember-content-addressed-authority-binding/v1"
                    and sidecar.get("artifact_path") == normalized
                    and sidecar.get("artifact_sha256") == expected_digest
                    and validate_artifact_binding(
                        sidecar_text,
                        ".json",
                        active_goal,
                        next_outcome,
                        allowed_workstreams,
                    )
                )
                workstreams = artifact_workstream_ids(sidecar_text, ".json")
            except Exception:
                binding_valid = False
                workstreams = set()
        elif inline_binding_supported:
            binding_valid = validate_artifact_binding(
                text,
                suffix,
                active_goal,
                next_outcome,
                allowed_workstreams,
            )
            workstreams = artifact_workstream_ids(text, suffix)
        else:
            errors.append(
                finding(4, "artifact.binding_format_unsupported", normalized)
            )
            continue
        if not binding_valid:
            errors.append(
                finding(
                    4,
                    "artifact.goal_binding",
                    f"{normalized}: requires goal_id={active_goal!r} and next_executed_outcome={next_outcome!r}",
                )
            )
            continue
        if len(workstreams) != 1:
            errors.append(
                finding(
                    4,
                    "artifact.workstream_binding",
                    f"{normalized}: requires exactly one workstream_id",
                )
            )
            continue
        workstream = next(iter(workstreams))
        if expected_workstream is not None and workstream != expected_workstream:
            errors.append(
                finding(
                    4,
                    "artifact.pr_workstream_mismatch",
                    f"{normalized}: bound to {workstream}, PR declares {expected_workstream}",
                )
            )
            continue
        if not workstream_path_allowed(normalized, workstream, scopes):
            errors.append(
                finding(
                    4,
                    "artifact.workstream_scope",
                    f"{normalized}: outside the exclusive scope of {workstream}",
                )
            )


def build_certificate(errors: list[dict[str, Any]]) -> dict[str, Any]:
    legs = {
        str(leg): not any(item["leg"] == leg for item in errors)
        for leg in range(1, 8)
    }
    return {
        "schema": "ember-authority-certificate-v1",
        "ok": all(legs.values()),
        "certificate_legs": legs,
        "errors": errors,
    }


def verify(
    root: Path,
    selection: Path | None = None,
    *,
    changed_range: str | None = None,
    staged: bool = False,
) -> dict[str, Any]:
    if staged:
        if changed_range:
            return build_certificate(
                [
                    finding(
                        4,
                        "artifact.diff_mode_conflict",
                        "--staged and --changed-range are mutually exclusive",
                    )
                ]
            )
        with tempfile.TemporaryDirectory(prefix="ember-staged-index-") as temp_dir:
            staged_root = Path(temp_dir).resolve()
            prefix = staged_root.as_posix().rstrip("/") + "/"
            materialized = subprocess.run(
                ["git", "checkout-index", "--all", "--force", f"--prefix={prefix}"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if materialized.returncode != 0:
                return build_certificate(
                    [
                        finding(
                            4,
                            "artifact.staged_materialization_failed",
                            materialized.stderr.strip()
                            or "git checkout-index failed",
                        )
                    ]
                )
            staged_payload = verify(staged_root, selection)
            policy_errors: list[dict[str, Any]] = []
            staged_policy = parse_goal_policy(staged_root, policy_errors)
            binding_errors: list[dict[str, Any]] = []
            check_changed_artifact_bindings(
                root,
                staged_policy,
                binding_errors,
                staged=True,
            )
            check_crosswalk_source_commit_repin(root, binding_errors, staged=True)
            return build_certificate(staged_payload["errors"] + binding_errors)

    errors: list[dict[str, Any]] = []
    check_authority_path_layout(root, errors)
    policy = parse_goal_policy(root, errors)
    check_policy(root, policy, errors)
    active_goal = parse_selection(selection, errors, policy)
    if active_goal is not None and policy is not None:
        expect(
            errors,
            4,
            active_goal == policy.get("active_goal_id"),
            "selection.policy_goal_mismatch",
            f"selection={active_goal}, policy={policy.get('active_goal_id')}",
        )
    check_invariant(root, policy, errors)
    check_manifest(root, policy, errors)
    check_governing_surfaces(root, policy, errors)
    check_configs(root, policy, errors, active_goal)
    check_input_identity_pins(root, errors)
    check_historical_executables(root, errors)
    check_execution_only_import_boundary(root, errors)
    check_lower_precedence_authority(root, errors)
    check_mechanism_registry(root, errors)
    check_authority_supersession_crosswalk(root, errors)
    check_state(root, errors)
    check_execution_boundary(root, policy, errors)
    check_changed_artifact_bindings(
        root,
        policy,
        errors,
        changed_range=changed_range,
        staged=staged,
    )
    check_crosswalk_source_commit_repin(
        root, errors, changed_range=changed_range, staged=staged
    )
    return build_certificate(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--selection")
    diff_mode = parser.add_mutually_exclusive_group()
    diff_mode.add_argument("--changed-range")
    diff_mode.add_argument("--staged", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = verify(
        Path(args.root).resolve(),
        Path(args.selection).resolve() if args.selection else None,
        changed_range=args.changed_range,
        staged=args.staged,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "PASS" if payload["ok"] else "FAIL"
        print(f"EMBER_AUTHORITY_CONSERVATION {status}")
        for item in payload["errors"]:
            print(f"  leg {item['leg']} {item['code']}: {item['detail']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    from gate_provenance import emit_gate_provenance

    emit_gate_provenance(__file__)
    sys.exit(main())

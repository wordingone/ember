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
from pathlib import Path
from typing import Any


INVARIANT_SHA256 = "08A0EB7418C09A8088BE4658E10785107ABBB7507FC2DBCDC789936AA54E02A6"
POLICY_SCHEMA = "ember-authority-v1"
ACTIVE_GOAL_ID = "EMBER-02"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
ACTIVE_WORKSTREAM_IDS = ["EMBER-02A", "EMBER-02B", "EMBER-02C"]
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
POLICY_RE = re.compile(
    r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
CONSERVATION_RE = re.compile(
    r"<!--\s*EMBER_CONSERVATION_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
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
AUTHORITY_MATRIX = "docs/ember-authority-matrix.md"
HISTORICAL_EXECUTABLES = [
    "scripts/conv_c03_muon_ns3_live.py",
    "scripts/timeshare_pretrain.py",
    "scripts/train_multimodal_v0.py",
]
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


def parse_goal_policy(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    path = root / "GOAL.md"
    if not path.is_file():
        errors.append(finding(3, "goal.missing", "GOAL.md is absent"))
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


def check_policy(policy: dict[str, Any] | None, errors: list[dict[str, Any]]) -> None:
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
        policy.get("highest_amendable_authority") == "GOAL.md",
        "policy.highest_amendable_authority",
        "must be GOAL.md",
    )
    expect(
        errors,
        3,
        policy.get("required_governing_surfaces") == REQUIRED_SURFACES,
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
    path = root / "INVARIANT.md"
    if not path.is_file():
        errors.append(finding(1, "invariant.missing", "INVARIANT.md is absent"))
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
    surfaces = REQUIRED_SURFACES if policy is None else policy.get("required_governing_surfaces", REQUIRED_SURFACES)
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
                "GOAL.md must hash-bind every required governing surface",
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
    path = root / AUTHORITY_MATRIX
    if not path.is_file():
        errors.append(finding(2, "manifest.missing", f"{AUTHORITY_MATRIX} is absent"))
        return
    expected_hash = str(
        ((policy or {}).get("conservation_hashes") or {}).get(
            "authority_matrix_sha256", ""
        )
    ).upper()
    actual_hash = sha256(path)
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        errors.append(
            finding(2, "manifest.hash_missing", "GOAL.md matrix hash is absent")
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


def check_historical_executables(root: Path, errors: list[dict[str, Any]]) -> None:
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
        statements = list(tree.body)
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
        first = statements[0] if statements else None
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


def parse_selection(path: Path | None, errors: list[dict[str, Any]]) -> str | None:
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
    if not re.fullmatch(r"EMBER-\d{2}", active_goal):
        errors.append(finding(4, "selection.goal_invalid", active_goal or "<missing>"))
        valid = False
    active_path = values.get("active_goal_path", "")
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
    state_path = root / "STATE.md"
    if not state_path.is_file():
        return {}
    lines = read_text(state_path).splitlines()
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
    paths = sorted(config_root.rglob("*.json"))
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
            external = classifications.get(rel)
            if external is None:
                errors.append(finding(4, "config.authority_missing", rel))
                continue
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


def check_lower_precedence_authority(root: Path, errors: list[dict[str, Any]]) -> None:
    allowed = {
        "GOAL.md",
        "INVARIANT.md",
        *REQUIRED_SURFACES,
    }
    excluded_prefixes = (
        ".git/",
        "receipts/",
        "docs/history/",
        "scripts/ember_totality/receipts-",
    )
    suffixes = {".md", ".json", ".toml", ".yaml", ".yml"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        rel = path.relative_to(root).as_posix()
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
    path = root / "docs" / "technique-registry.jsonl"
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
    path = root / "STATE.md"
    if not path.is_file():
        errors.append(finding(6, "state.missing", "STATE.md is absent"))
        return
    rows = parse_markdown_table(read_text(path), 9)
    if not rows:
        errors.append(finding(6, "state.identity_rows_missing", "no 9-column identity rows"))
        return
    ids = [row[0] for row in rows]
    identities = [row[2] for row in rows]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count != 1)
    duplicate_identity = sorted(item for item, count in Counter(identities).items() if count != 1)
    if duplicate_ids:
        errors.append(finding(6, "state.duplicate_id", ",".join(duplicate_ids)))
    if duplicate_identity:
        errors.append(finding(6, "state.ambiguous_identity", ",".join(duplicate_identity)))
    allowed_classes = {"historical_only", "borrowed_reference", "research_prototype", "target", "current_admissible"}
    seen_classes = set()
    for row in rows:
        rid, object_type, identity, artifact_class, params, _tokens, backend, credit, _evidence = row
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
        if artifact_class == "target" and not identity.startswith("uninstantiated:"):
            errors.append(finding(6, "state.target_identity", rid))
        if not object_type or not identity or not backend:
            errors.append(finding(6, "state.identity_field_missing", rid))
    for required in ("historical_only", "borrowed_reference", "target"):
        if required not in seen_classes:
            errors.append(finding(6, "state.required_class_missing", required))


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
    for rel in sorted(set(result.stdout.splitlines())):
        normalized = rel.replace("\\", "/")
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
        if suffix not in {
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
        }:
            errors.append(
                finding(4, "artifact.binding_format_unsupported", normalized)
            )
            continue
        try:
            if staged:
                shown = subprocess.run(
                    ["git", "show", f":{normalized}"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if shown.returncode != 0:
                    raise OSError(shown.stderr.strip() or "cannot read staged bytes")
                text = shown.stdout
            else:
                text = read_text(root / normalized)
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
        binding_valid = validate_artifact_binding(
            text,
            suffix,
            active_goal,
            next_outcome,
            allowed_workstreams,
        )
        if not binding_valid:
            errors.append(
                finding(
                    4,
                    "artifact.goal_binding",
                    f"{normalized}: requires goal_id={active_goal!r} and next_executed_outcome={next_outcome!r}",
                )
            )
            continue
        workstreams = artifact_workstream_ids(text, suffix)
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
            return build_certificate(staged_payload["errors"] + binding_errors)

    errors: list[dict[str, Any]] = []
    active_goal = parse_selection(selection, errors)
    policy = parse_goal_policy(root, errors)
    check_policy(policy, errors)
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
    check_historical_executables(root, errors)
    check_lower_precedence_authority(root, errors)
    check_mechanism_registry(root, errors)
    check_state(root, errors)
    check_changed_artifact_bindings(
        root,
        policy,
        errors,
        changed_range=changed_range,
        staged=staged,
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
    sys.exit(main())

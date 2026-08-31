# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate the exact current-source producer admitted for issue #675.

This is a source/descriptor admission boundary.  It does not execute the
event and grants no event or scientific credit.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping


_FIELDS = {
    "schema_version",
    "source_commit",
    "mode",
    "producer_sha256",
    "component_sha256",
    "scope",
    "historical_dependencies",
    "claims",
    "no_new_parallel_authority",
    "contract_sha256",
}
_COMPONENT_KEYS = {
    "adapter",
    "event_inputs",
    "input_builder",
    "host_commit_probe",
    "host_commit_simulation",
    "measured_dry_run",
    "gradient_lineage",
    "model_lineage",
    "momentum_lineage",
    "muon",
    "rung2_runtime",
    "writer",
}
_CLAIMS = {
    "actual_event": False,
    "scientific_result": False,
    "whole_step": False,
    "material_loss_bridge": False,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")


class ProducerContractRefusal(ValueError):
    """Named pre-dispatch refusal for a producer contract defect."""


def _refuse(code: str) -> None:
    raise ProducerContractRefusal(code)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        _refuse("PRODUCER_COMPONENT_UNAVAILABLE")


def _read_contract(path: Path) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _refuse("PRODUCER_CONTRACT_UNREADABLE")
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _refuse("PRODUCER_CONTRACT_SCHEMA_INVALID")
    supplied = value.get("contract_sha256")
    unsigned = dict(value)
    unsigned.pop("contract_sha256", None)
    expected = hashlib.sha256(_canonical(unsigned)).hexdigest()
    if supplied != expected:
        _refuse("PRODUCER_CONTRACT_TAMPERED")
    return value


def _source_contract(path: Path) -> None:
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        _refuse("PRODUCER_SOURCE_INVALID")
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    if any(name == "timeshare_pretrain" or name.startswith("timeshare_pretrain.") for name in imported):
        _refuse("PRODUCER_HISTORICAL_DEPENDENCY")

    mode_ok = False
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "GOVERNED_VERTICAL_MODE"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "governed-vertical"
        ):
            mode_ok = True
    if not mode_ok or set(functions).isdisjoint({"run_governed_vertical"}) or "main" not in functions:
        _refuse("PRODUCER_ENTRYPOINT_INVALID")
    main_calls_runner = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_governed_vertical"
        for node in ast.walk(functions["main"])
    )
    if not main_calls_runner:
        _refuse("PRODUCER_ENTRYPOINT_INVALID")


def validate_producer_contract(
    *,
    contract_path: Path,
    source_commit: str,
    producer_path: Path,
    component_paths: Mapping[str, Path],
) -> dict[str, object]:
    """Return the verified closed descriptor or refuse before dispatch."""

    contract = _read_contract(contract_path)
    if (
        not isinstance(source_commit, str)
        or _COMMIT.fullmatch(source_commit) is None
        or contract["source_commit"] != source_commit
        or contract["schema_version"] != "q2-governed-producer-contract-v1"
        or contract["mode"] != "governed-vertical"
        or contract["scope"] != "TARGET_TENSOR_COUNTERFACTUAL"
        or contract["historical_dependencies"] != []
        or contract["claims"] != _CLAIMS
        or contract["no_new_parallel_authority"] is not True
    ):
        _refuse("PRODUCER_CONTRACT_MISMATCH")
    if set(component_paths) != _COMPONENT_KEYS:
        _refuse("PRODUCER_COMPONENT_SET_INVALID")
    declared_components = contract["component_sha256"]
    if not isinstance(declared_components, dict) or set(declared_components) != _COMPONENT_KEYS:
        _refuse("PRODUCER_COMPONENT_SET_INVALID")
    if any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in declared_components.values()
    ):
        _refuse("PRODUCER_COMPONENT_HASH_INVALID")

    actual_producer = _sha(producer_path)
    if contract["producer_sha256"] != actual_producer:
        _refuse("PRODUCER_SOURCE_HASH_MISMATCH")
    for key, path in component_paths.items():
        if declared_components[key] != _sha(path):
            _refuse("PRODUCER_COMPONENT_HASH_MISMATCH")
    _source_contract(producer_path)
    return contract


def build_producer_contract(
    *, source_commit: str, producer_path: Path,
    component_paths: Mapping[str, Path],
) -> dict[str, object]:
    """Build the closed descriptor that the validator independently rechecks."""
    if not isinstance(source_commit,str) or _COMMIT.fullmatch(source_commit) is None:
        _refuse("PRODUCER_CONTRACT_MISMATCH")
    if set(component_paths)!=_COMPONENT_KEYS:
        _refuse("PRODUCER_COMPONENT_SET_INVALID")
    _source_contract(producer_path)
    contract: dict[str,object]={
        "schema_version":"q2-governed-producer-contract-v1",
        "source_commit":source_commit,
        "mode":"governed-vertical",
        "producer_sha256":_sha(producer_path),
        "component_sha256":{key:_sha(path) for key,path in sorted(component_paths.items())},
        "scope":"TARGET_TENSOR_COUNTERFACTUAL",
        "historical_dependencies":[],
        "claims":dict(_CLAIMS),
        "no_new_parallel_authority":True,
    }
    contract["contract_sha256"]=hashlib.sha256(_canonical(contract)).hexdigest()
    return contract

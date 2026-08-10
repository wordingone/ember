# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


COMPLETION_VERIFIER_SYMBOLS = (
    "VALIDATE_IDENTITY_REL",
    "run",
    "_flipped_sha256",
    "_identity_tamper_mutants",
    "_run_identity_tamper_battery",
)

SURFACE_SCHEMA = "ember-cond4-battery-surface-v3"
EXECUTION_SCHEMA = "ember-cond4-battery-execution-v1"


class Cond4SurfaceError(ValueError):
    pass


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in _target_names(item)}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _pattern_names(pattern: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name is not None:
        names.add(pattern.name)
    elif isinstance(pattern, ast.MatchMapping) and pattern.rest is not None:
        names.add(pattern.rest)
    for child in ast.iter_child_nodes(pattern):
        names.update(_pattern_names(child))
    return names


def _bound_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {name for target in node.targets for name in _target_names(target)}
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return _target_names(node.target)
    if isinstance(node, ast.Delete):
        return {name for target in node.targets for name in _target_names(target)}
    if isinstance(node, ast.NamedExpr):
        return _target_names(node.target)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".", 1)[0] for alias in node.names}

    names: set[str] = set()
    if isinstance(node, (ast.For, ast.AsyncFor)):
        names.update(_target_names(node.target))
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        for item in node.items:
            if item.optional_vars is not None:
                names.update(_target_names(item.optional_vars))
    elif isinstance(node, ast.ExceptHandler) and node.name is not None:
        names.add(node.name)
    elif isinstance(node, ast.Match):
        for case in node.cases:
            names.update(_pattern_names(case.pattern))
    for child in ast.iter_child_nodes(node):
        names.update(_bound_names(child))
    return names


def behavior_surface_sha256(source: bytes, names: Iterable[str]) -> str:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as error:
        raise Cond4SurfaceError(f"completion verifier is not valid UTF-8 Python: {error}") from error

    wanted = tuple(names)
    definitions: dict[str, list[ast.AST]] = {}
    for node in tree.body:
        for bound_name in _bound_names(node):
            definitions.setdefault(bound_name, []).append(node)
    missing = [name for name in wanted if name not in definitions]
    if missing:
        raise Cond4SurfaceError(f"missing cond4 behavior definitions: {missing}")

    closure: set[str] = set()
    pending = list(wanted)
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        for node in definitions[name]:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id in definitions
                    and child.id not in closure
                ):
                    pending.append(child.id)

    payload = {
        "schema": SURFACE_SCHEMA,
        "roots": list(wanted),
        "definitions": [
            {
                "name": name,
                "ast": [
                    ast.dump(node, annotate_fields=True, include_attributes=False)
                    for node in definitions[name]
                ],
            }
            for name in sorted(closure)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def completion_verifier_surface_sha256(path: Path) -> str:
    return behavior_surface_sha256(path.read_bytes(), COMPLETION_VERIFIER_SYMBOLS)


def completion_verifier_binding_valid(
    source: bytes, binding: Mapping[str, Any]
) -> bool:
    if hashlib.sha256(source).hexdigest() == binding.get("sha256"):
        return True
    surface = binding.get("battery_surface")
    if not isinstance(surface, Mapping):
        return False
    if surface.get("schema") != SURFACE_SCHEMA:
        return False
    if tuple(surface.get("symbols", ())) != COMPLETION_VERIFIER_SYMBOLS:
        return False
    return surface.get("sha256") == behavior_surface_sha256(
        source, COMPLETION_VERIFIER_SYMBOLS
    )


def _execution_marker(receipt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    verification = receipt.get("verification")
    if not isinstance(verification, Mapping):
        return None
    marker = verification.get("cond4_battery_execution")
    return marker if isinstance(marker, Mapping) else None


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def cond4_receipt_transition_valid(
    base_source: bytes,
    head_source: bytes,
    base_receipt: Mapping[str, Any],
    head_receipt: Mapping[str, Any],
) -> bool:
    """Require a new execution receipt whenever the Cond-4 behavior changes."""
    implementation = head_receipt.get("implementation")
    if not isinstance(implementation, Mapping):
        return False
    head_binding = implementation.get("completion_verifier")
    if not isinstance(head_binding, Mapping) or not completion_verifier_binding_valid(
        head_source, head_binding
    ):
        return False

    base_surface = behavior_surface_sha256(base_source, COMPLETION_VERIFIER_SYMBOLS)
    head_surface = behavior_surface_sha256(head_source, COMPLETION_VERIFIER_SYMBOLS)
    if base_surface == head_surface:
        return True

    base_marker = _execution_marker(base_receipt)
    head_marker = _execution_marker(head_receipt)
    if head_marker is None or head_marker == base_marker:
        return False
    if head_marker.get("schema") != EXECUTION_SCHEMA:
        return False
    if head_marker.get("completion_verifier_surface_sha256") != head_surface:
        return False
    if head_marker.get("result") != "PASS":
        return False
    command = head_marker.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) and part for part in command
    ):
        return False
    executed_at = _aware_timestamp(head_marker.get("executed_at"))
    if executed_at is None:
        return False
    if base_marker is not None:
        base_executed_at = _aware_timestamp(base_marker.get("executed_at"))
        if base_executed_at is None or executed_at <= base_executed_at:
            return False
    return True

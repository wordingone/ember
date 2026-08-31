#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate the public #580 cache-tensor commitment without inventing private replay."""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# issue2015 exact-local-import:src/ember/governance/scripts/lib/invariant.py
import importlib.util as _ember_2560a87c017c05b0_importlib
import sys as _ember_2560a87c017c05b0_sys
from pathlib import Path as _ember_2560a87c017c05b0_Path
_ember_2560a87c017c05b0_path = _ember_2560a87c017c05b0_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'lib', 'invariant.py')
if not _ember_2560a87c017c05b0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lib/invariant.py')
_ember_2560a87c017c05b0_aliases = ('_ember_issue2015_2560a87c017c05b0', 'invariant', 'scripts.lib.invariant')
_ember_2560a87c017c05b0_existing = []
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_candidate = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_candidate is not None and all(_ember_2560a87c017c05b0_candidate is not item for item in _ember_2560a87c017c05b0_existing):
        _ember_2560a87c017c05b0_existing.append(_ember_2560a87c017c05b0_candidate)
if len(_ember_2560a87c017c05b0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lib/invariant.py')
if _ember_2560a87c017c05b0_existing:
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_existing[0]
    _ember_2560a87c017c05b0_observed = getattr(_ember_2560a87c017c05b0_module, '__file__', None)
    if _ember_2560a87c017c05b0_observed is None or _ember_2560a87c017c05b0_Path(_ember_2560a87c017c05b0_observed).resolve() != _ember_2560a87c017c05b0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lib/invariant.py')
else:
    _ember_2560a87c017c05b0_spec = _ember_2560a87c017c05b0_importlib.spec_from_file_location('_ember_issue2015_2560a87c017c05b0', _ember_2560a87c017c05b0_path)
    if _ember_2560a87c017c05b0_spec is None or _ember_2560a87c017c05b0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_importlib.module_from_spec(_ember_2560a87c017c05b0_spec)
    for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
        _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
        if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
        _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
    try:
        _ember_2560a87c017c05b0_spec.loader.exec_module(_ember_2560a87c017c05b0_module)
    except BaseException:
        for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
            if _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias) is _ember_2560a87c017c05b0_module:
                _ember_2560a87c017c05b0_sys.modules.pop(_ember_2560a87c017c05b0_alias, None)
        raise
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
stamp = getattr(_ember_2560a87c017c05b0_module, 'stamp')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lib/invariant.py


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
TICKET = "580RERUN-CACHE-TENSOR-COMMITMENT"
EXPECTED_TENSORS = {
    "grad_pre_gate",
    "theta_gate_pre",
    "pre_momentum",
    "grad_post_gate",
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
SOURCE_REL = Path("src/ember/governance/scripts/cbase_grow_rung2_event.py")
PUBLIC_TEST_RELS = (
    Path("scripts/test_580_b1m_resolver_fix.py"),
    Path("scripts/test_580_optimizer_id_helper.py"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def load_siblings(
    root: Path, historical: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    sibling_paths = historical.get("sibling_to")
    if (
        not isinstance(sibling_paths, list)
        or len(sibling_paths) != 2
        or not all(isinstance(item, str) and item for item in sibling_paths)
    ):
        raise ValueError("historical sibling_to must name exactly two receipts")
    result: dict[str, dict[str, Any]] = {}
    for rel in sibling_paths:
        path = (root / rel).resolve()
        if path.parent != (root / "receipts").resolve():
            raise ValueError("sibling receipt must be a direct receipts child")
        data = load_json(path)
        result[path.name] = {
            "path": rel.replace("\\", "/"),
            "sha256": sha256_file(path),
            "data": data,
        }
    if len(result) != 2:
        raise ValueError("sibling receipt names must be unique")
    return result


def _phase_b1m(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "phase_b1m"
    ]
    if len(matches) != 1:
        raise ValueError("current source must define exactly one phase_b1m")
    return matches[0]


def validate_current_source(root: Path) -> dict[str, Any]:
    source_path = root / SOURCE_REL
    source = source_path.read_text(encoding="utf-8", errors="strict")
    phase = _phase_b1m(source)
    resolver_calls = [
        node
        for node in ast.walk(phase)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resolve_gate_momentum_buffer"
    ]
    executable_index_calls = [
        node
        for node in ast.walk(phase)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "index"
    ]
    missing_buffer_refusals = [
        node
        for node in ast.walk(phase)
        if isinstance(node, ast.If)
        and any(isinstance(child, ast.Raise) for child in ast.walk(node))
        and "pre_momentum is None" in ast.unparse(node.test)
    ]
    if len(resolver_calls) != 1:
        raise ValueError("phase_b1m must call the authoritative resolver exactly once")
    if executable_index_calls:
        raise ValueError("phase_b1m still contains an executable index lookup")
    if len(missing_buffer_refusals) != 1:
        raise ValueError("phase_b1m must fail closed when pre_momentum is absent")

    public_tests = []
    for rel in PUBLIC_TEST_RELS:
        path = root / rel
        if not path.is_file():
            raise ValueError(f"public #580 test source missing: {rel.as_posix()}")
        public_tests.append({"path": rel.as_posix(), "sha256": sha256_file(path)})
    return {
        "source": {"path": SOURCE_REL.as_posix(), "sha256": sha256_file(source_path)},
        "authoritative_resolver_call_count": len(resolver_calls),
        "executable_global_index_lookup_count": len(executable_index_calls),
        "missing_buffer_fail_closed_guard_count": len(missing_buffer_refusals),
        "public_test_sources": public_tests,
        "dynamic_historical_trainer_test_replayed": False,
        "dynamic_historical_trainer_test_replay_reason": (
            "the current public tree intentionally execution-denies the historical "
            "sub-3B trainer and every importer"
        ),
    }


def validate_commitment(
    historical: dict[str, Any],
    siblings: dict[str, dict[str, Any]],
    source_validation: dict[str, Any],
) -> dict[str, Any]:
    if historical.get("ticket") != TICKET:
        raise ValueError("historical ticket mismatch")
    tensors = historical.get("cache_tensors")
    if not isinstance(tensors, dict) or set(tensors) != EXPECTED_TENSORS:
        raise ValueError("historical cache_tensors must contain the exact four keys")

    for name in sorted(EXPECTED_TENSORS):
        row = tensors[name]
        if not isinstance(row, dict):
            raise ValueError(f"{name} commitment must be an object")
        digest = row.get("sha256")
        if not isinstance(digest, str) or SHA_RE.fullmatch(digest) is None:
            raise ValueError(f"{name} sha256 is invalid")
        byte_length = row.get("byte_length")
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
            raise ValueError(f"{name} byte_length is invalid")
        dtype = row.get("tensor_dtype")
        if dtype not in {"torch.float32", "torch.bfloat16"}:
            raise ValueError(f"{name} tensor_dtype is invalid")
        shape = row.get("tensor_shape")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or not all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in shape
            )
        ):
            raise ValueError(f"{name} tensor_shape is invalid")

        sibling_name = row.get("source_receipt")
        if sibling_name not in siblings:
            raise ValueError(f"{name} source_receipt is not a bound sibling")
        sibling_cache_paths = siblings[sibling_name]["data"].get("cache_paths")
        if not isinstance(sibling_cache_paths, dict):
            raise ValueError(f"{name} sibling cache_paths is missing")
        if sibling_cache_paths.get(name) != row.get("cache_path_as_recorded"):
            raise ValueError(f"{name} cache path does not match its sibling receipt")

    cross_check = tensors["pre_momentum"].get("cross_check_against_public_scalar")
    b3 = siblings["cbase-grow-rung2-event-580rerun-20260710-b3.json"]["data"]
    if not isinstance(cross_check, dict) or cross_check.get("match") is not True:
        raise ValueError("pre_momentum public scalar cross-check is absent")
    if cross_check.get("public_value") != b3.get("pre_buffer_rms_consumed"):
        raise ValueError("pre_momentum public scalar differs from the b3 receipt")
    if (
        cross_check.get("recomputed_rms_from_this_exact_cache_tensor")
        != cross_check.get("public_value")
    ):
        raise ValueError("pre_momentum historical recomputation is internally inconsistent")
    if historical.get("verdict") != "COMMITMENT_RECORDED_REPLAY_BOUNDED_NONPUBLIC":
        raise ValueError("historical verdict boundary mismatch")
    if source_validation.get("authoritative_resolver_call_count") != 1:
        raise ValueError("current source resolver binding is invalid")

    return {
        "all_checks_passed": True,
        "tensor_count": len(tensors),
        "tensor_names": sorted(tensors),
        "sibling_receipt_count": len(siblings),
        "pre_momentum_public_scalar_match": True,
        "current_source_resolver_binding": "PASS",
    }


def build_receipt(
    root: Path,
    historical_path: Path,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    historical_path = historical_path.resolve()
    if historical_path.parent != (root / "receipts").resolve():
        raise ValueError("historical receipt must be a direct receipts child")
    historical = load_json(historical_path)
    siblings = load_siblings(root, historical)
    source_validation = validate_current_source(root)
    public_validation = validate_commitment(historical, siblings, source_validation)
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    receipt = {
        "ticket": TICKET,
        "ts": ts,
        "issue": 700,
        "source_issue": 580,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "mode": "PUBLIC_COMMITMENT_CURRENT_TREE_REVALIDATION",
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": historical_path.relative_to(root).as_posix(),
        "historical_receipt_sha256": sha256_file(historical_path),
        "siblings": [
            {
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for _, item in sorted(siblings.items())
        ],
        "current_source_validation": source_validation,
        "public_commitment_validation": public_validation,
        "producer": {
            "path": Path(__file__).resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verdict": "PUBLIC_COMMITMENT_REVALIDATED_PRIVATE_BYTES_UNAVAILABLE",
        "claim_boundary": {
            "public_commitment_structure_and_current_source_revalidated": True,
            "exact_private_tensor_bytes_replayed": False,
            "private_tensor_hashes_recomputed": False,
            "historical_tensor_identity_claim_reasserted": False,
            "training_claim": False,
            "model_capability_claim": False,
            "issue_580_completion_claim": False,
        },
        "paid_api_surface_used": False,
    }
    return stamp(receipt, str(root))


def publish(receipt: dict[str, Any], target: Path, root: Path) -> None:
    target = target.resolve()
    allowed = (root.resolve() / "receipts").resolve()
    if target.parent != allowed:
        raise ValueError("output must be under receipts")
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with target.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--historical-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(args.root, args.historical_receipt)
    publish(receipt, args.output, args.root)
    print(json.dumps({"status": "PASS", "ticket": receipt["ticket"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

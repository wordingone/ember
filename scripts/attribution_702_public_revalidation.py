#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate #702's public arithmetic without promoting its blocked attribution."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


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
TICKET = "EMBER-702-ATTRIBUTION"
EXPECTED_HISTORICAL_SHA256 = (
    "b0ee011a7afd121e218514ed982beb61ca6d1d7b405ec525deea91232f61edad"
)
EXPECTED_RATIO_KEYS = (
    "stage_ratio",
    "inner_ratio",
    "gpu_ratio",
    "host_unavoidable_ratio",
    "stage_plus_host_unavoidable_ratio",
)
CI_KEYS = (
    ("stage_ratio", "T_stage_over_T_step"),
    ("inner_ratio", "T_inner_over_T_step"),
    ("gpu_ratio", "T_gpu_over_T_step"),
    ("host_unavoidable_ratio", "T_host_unavoidable_over_T_step"),
    (
        "stage_plus_host_unavoidable_ratio",
        "T_stage_plus_T_host_unavoidable_over_T_step",
    ),
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


def _bootstrap_ci95(
    values: list[float], *, n_resamples: int, rng: np.random.Generator
) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    indices = rng.integers(0, len(array), size=(n_resamples, len(array)))
    means = array[indices].mean(axis=1)
    return {
        "lower": round(float(np.percentile(means, 2.5)), 6),
        "upper": round(float(np.percentile(means, 97.5)), 6),
        "mean": round(float(array.mean()), 6),
        "n_samples": len(values),
        "n_resamples": n_resamples,
    }


def _validate_ratio_arrays(historical: dict[str, Any]) -> dict[str, list[float]]:
    ratios = historical.get("per_step_span_ratios")
    if not isinstance(ratios, dict) or set(ratios) != set(EXPECTED_RATIO_KEYS):
        raise ValueError("per_step_span_ratios must contain the exact five ratio arrays")
    lengths: set[int] = set()
    validated: dict[str, list[float]] = {}
    for name in EXPECTED_RATIO_KEYS:
        values = ratios[name]
        if not isinstance(values, list):
            raise ValueError(f"{name} must be an array")
        lengths.add(len(values))
        clean: list[float] = []
        for value in values:
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"{name} values must be finite numeric scalars")
            clean.append(float(value))
        validated[name] = clean
    if len(lengths) != 1 or not lengths or next(iter(lengths)) <= 0:
        raise ValueError("ratio arrays must have equal nonzero lengths")
    return validated


def validate_public_arithmetic(historical: dict[str, Any]) -> dict[str, Any]:
    if historical.get("ticket") != TICKET:
        raise ValueError("historical ticket mismatch")
    if historical.get("issue") != "wordingone/ember#702":
        raise ValueError("historical issue binding mismatch")
    if historical.get("verdict") != "FACTOR1_FIRST":
        raise ValueError("historical verdict mismatch")
    if historical.get("gates_all_passed") is not True:
        raise ValueError("historical gates_all_passed is not true")
    seed = historical.get("bootstrap_seed")
    n_resamples = historical.get("n_bootstrap_resamples")
    if seed != 0 or n_resamples != 10000:
        raise ValueError("historical bootstrap contract mismatch")

    ratios = _validate_ratio_arrays(historical)
    recorded = historical.get("ci95")
    if not isinstance(recorded, dict) or set(recorded) != {item[1] for item in CI_KEYS}:
        raise ValueError("historical ci95 must contain the exact five spans")
    rng = np.random.default_rng(seed)
    recomputed: dict[str, dict[str, Any]] = {}
    for ratio_key, ci_key in CI_KEYS:
        actual = _bootstrap_ci95(
            ratios[ratio_key], n_resamples=n_resamples, rng=rng
        )
        if recorded.get(ci_key) != actual:
            raise ValueError(
                f"{ci_key} bootstrap mismatch: recorded={recorded.get(ci_key)!r} "
                f"recomputed={actual!r}"
            )
        recomputed[ci_key] = actual

    predicates = historical.get("predicates")
    if predicates != {"D_direct_copy": False, "F_factor1": True}:
        raise ValueError("historical predicate table mismatch")
    inner = recomputed["T_inner_over_T_step"]
    stage = recomputed["T_stage_over_T_step"]
    return {
        "all_checks_passed": True,
        "sample_count": inner["n_samples"],
        "bootstrap_seed": seed,
        "bootstrap_resamples": n_resamples,
        "combined_inner_mean": inner["mean"],
        "combined_inner_ci95": [inner["lower"], inner["upper"]],
        "stage_mean": stage["mean"],
        "stage_ci95": [stage["lower"], stage["upper"]],
        "factor1_predicate_arithmetic_revalidated": (
            inner["lower"] >= 0.1 and stage["lower"] < 0.1
        ),
        "recorded_source_identity_present": bool(historical.get("git_sha")),
        "optimizer_inner_span_scope": (
            "combined Muon and AdamW self._inner.step work plus any file-backed "
            "traffic inside those calls; no NS5-specific split"
        ),
    }


def build_receipt(
    root: Path,
    historical_path: Path,
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    historical_path = historical_path.resolve()
    digest = sha256_file(historical_path)
    if digest != EXPECTED_HISTORICAL_SHA256:
        raise ValueError(
            "historical receipt SHA-256 mismatch: "
            f"expected {EXPECTED_HISTORICAL_SHA256}, got {digest}"
        )
    if historical_path.parent != (root / "receipts").resolve():
        raise ValueError("historical receipt must be a direct receipts child")
    historical = load_json(historical_path)
    arithmetic = validate_public_arithmetic(historical)
    if arithmetic["recorded_source_identity_present"]:
        raise ValueError("historical receipt unexpectedly claims executing source identity")

    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    receipt = {
        "ticket": TICKET,
        "ts": ts,
        "issue": 700,
        "source_issue": 702,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "mode": "PUBLIC_HISTORICAL_ARITHMETIC_REVALIDATION",
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": historical_path.relative_to(root).as_posix(),
        "historical_receipt_sha256": digest,
        "public_arithmetic_revalidation": arithmetic,
        "adjudication": {
            "independent_falsification_comment": (
                "https://github.com/wordingone/ember/issues/702"
                "#issuecomment-4947441605"
            ),
            "coordinator_split_adjudication_comment": (
                "https://github.com/wordingone/ember/issues/702"
                "#issuecomment-4947469112"
            ),
            "current_open_disposition_comment": (
                "https://github.com/wordingone/ember/issues/702"
                "#issuecomment-5013454316"
            ),
        },
        "producer": {
            "path": Path(__file__).resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verdict": "COMBINED_INNER_ARITHMETIC_REVALIDATED_CONTRACT_GRADE_BLOCKED",
        "claim_boundary": {
            "historical_combined_inner_arithmetic_revalidated": True,
            "live_2p2b_experiment_replayed": False,
            "exact_executing_source_identity_recovered": False,
            "current_interval_tenancy_proof_recovered": False,
            "per_optimizer_inner_spans_present": False,
            "ns5_specific_span_present": False,
            "contract_grade_attribution_claim": False,
            "branch_a_ns5_routing_claim": False,
            "matched_cure_ab_claim": False,
            "major_reduction_claim": False,
            "issue_702_completion_claim": False,
            "training_claim": False,
            "model_capability_claim": False,
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

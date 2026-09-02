#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compose the ruled dimensionless R1-E7 gradient-norm-ratio sigma receipt."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/r1_exit_battery.py
import importlib.util as _ember_2afec9f76b7cd933_importlib
import sys as _ember_2afec9f76b7cd933_sys
from pathlib import Path as _ember_2afec9f76b7cd933_Path
_ember_2afec9f76b7cd933_path = _ember_2afec9f76b7cd933_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'r1_exit_battery.py')
if not _ember_2afec9f76b7cd933_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/r1_exit_battery.py')
_ember_2afec9f76b7cd933_aliases = ('_ember_issue2015_2afec9f76b7cd933', 'r1_exit_battery', 'scripts.r1_exit_battery')
_ember_2afec9f76b7cd933_existing = []
for _ember_2afec9f76b7cd933_alias in _ember_2afec9f76b7cd933_aliases:
    _ember_2afec9f76b7cd933_candidate = _ember_2afec9f76b7cd933_sys.modules.get(_ember_2afec9f76b7cd933_alias)
    if _ember_2afec9f76b7cd933_candidate is not None and all(_ember_2afec9f76b7cd933_candidate is not item for item in _ember_2afec9f76b7cd933_existing):
        _ember_2afec9f76b7cd933_existing.append(_ember_2afec9f76b7cd933_candidate)
if len(_ember_2afec9f76b7cd933_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/r1_exit_battery.py')
if _ember_2afec9f76b7cd933_existing:
    _ember_2afec9f76b7cd933_module = _ember_2afec9f76b7cd933_existing[0]
    _ember_2afec9f76b7cd933_observed = getattr(_ember_2afec9f76b7cd933_module, '__file__', None)
    if _ember_2afec9f76b7cd933_observed is None or _ember_2afec9f76b7cd933_Path(_ember_2afec9f76b7cd933_observed).resolve() != _ember_2afec9f76b7cd933_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/r1_exit_battery.py')
else:
    _ember_2afec9f76b7cd933_spec = _ember_2afec9f76b7cd933_importlib.spec_from_file_location('_ember_issue2015_2afec9f76b7cd933', _ember_2afec9f76b7cd933_path)
    if _ember_2afec9f76b7cd933_spec is None or _ember_2afec9f76b7cd933_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/r1_exit_battery.py')
    _ember_2afec9f76b7cd933_module = _ember_2afec9f76b7cd933_importlib.module_from_spec(_ember_2afec9f76b7cd933_spec)
    for _ember_2afec9f76b7cd933_alias in _ember_2afec9f76b7cd933_aliases:
        _ember_2afec9f76b7cd933_prior = _ember_2afec9f76b7cd933_sys.modules.get(_ember_2afec9f76b7cd933_alias)
        if _ember_2afec9f76b7cd933_prior is not None and _ember_2afec9f76b7cd933_prior is not _ember_2afec9f76b7cd933_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/r1_exit_battery.py')
        _ember_2afec9f76b7cd933_sys.modules[_ember_2afec9f76b7cd933_alias] = _ember_2afec9f76b7cd933_module
    try:
        _ember_2afec9f76b7cd933_spec.loader.exec_module(_ember_2afec9f76b7cd933_module)
    except BaseException:
        for _ember_2afec9f76b7cd933_alias in _ember_2afec9f76b7cd933_aliases:
            if _ember_2afec9f76b7cd933_sys.modules.get(_ember_2afec9f76b7cd933_alias) is _ember_2afec9f76b7cd933_module:
                _ember_2afec9f76b7cd933_sys.modules.pop(_ember_2afec9f76b7cd933_alias, None)
        raise
for _ember_2afec9f76b7cd933_alias in _ember_2afec9f76b7cd933_aliases:
    _ember_2afec9f76b7cd933_prior = _ember_2afec9f76b7cd933_sys.modules.get(_ember_2afec9f76b7cd933_alias)
    if _ember_2afec9f76b7cd933_prior is not None and _ember_2afec9f76b7cd933_prior is not _ember_2afec9f76b7cd933_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/r1_exit_battery.py')
    _ember_2afec9f76b7cd933_sys.modules[_ember_2afec9f76b7cd933_alias] = _ember_2afec9f76b7cd933_module
pooled_sigma_seed = getattr(_ember_2afec9f76b7cd933_module, 'pooled_sigma_seed')
# issue2015 exact-local-import-end:src/ember/governance/scripts/r1_exit_battery.py


PREREG_PIN = "3d48d3870919bd04cec735f68d0fad45fcfae0b2"
SCHEMA = "issue1464-r1-e7-ratio-sigma-composition-v1"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unavailable or invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _self_digest(value: dict[str, Any], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _atomic_create(path: Path, value: dict[str, Any]) -> None:
    raw = _canonical(value) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def normalized_grad_norm_ratio_sigma(
    seed_series: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    seeds = sorted(seed_series)
    if len(seeds) < 2:
        raise ValueError("gradient-norm ratio sigma requires at least two seeds")
    by_seed = [{row["step"]: row.get("grad_norm") for row in seed_series[seed]} for seed in seeds]
    matched = set.intersection(*(set(rows) for rows in by_seed))
    if not matched:
        raise ValueError("gradient-norm ratio sigma has no matched steps")
    variances: list[float] = []
    for step in sorted(matched):
        values = [rows[step] for rows in by_seed]
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
            for value in values
        ):
            raise ValueError("gradient norms must be positive finite numbers")
        mean = statistics.fmean(float(value) for value in values)
        normalized = [float(value) / mean for value in values]
        variances.append(statistics.pvariance(normalized))
    return {
        "sigma_seed": math.sqrt(statistics.fmean(variances)),
        "matched_step_count": len(matched),
        "seeds": seeds,
        "seed_order_invariant": True,
        "two_seed_identity": "sqrt(mean_t(((g1-g2)/(g1+g2))^2))",
    }


def _telemetry_series(path: Path) -> tuple[str, list[dict[str, Any]]]:
    by_run: dict[str, dict[int, dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("telemetry contains invalid JSON") from error
        if event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        run_id = payload.get("run_id")
        step = payload.get("step")
        if not isinstance(run_id, str) or not run_id or type(step) is not int or step <= 0:
            raise ValueError("telemetry train_step identity is invalid")
        if step in by_run.setdefault(run_id, {}):
            raise ValueError("telemetry contains duplicate train_step")
        row = {"step": step}
        for field in ("loss", "grad_norm"):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"telemetry {field} is missing or invalid")
            try:
                number = float(value)
            except ValueError as error:
                raise ValueError(f"telemetry {field} is missing or invalid") from error
            if not math.isfinite(number):
                raise ValueError(f"telemetry {field} is missing or invalid")
            row[field] = number
        by_run[run_id][step] = row
    if len(by_run) != 1:
        raise ValueError("telemetry must contain exactly one train_step run")
    run_id, rows = next(iter(by_run.items()))
    ordered = [rows[step] for step in sorted(rows)]
    if [row["step"] for row in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("telemetry steps are not contiguous from one")
    return run_id, ordered


def _threshold(path: Path, identifier: str) -> int:
    payload = _load(path, "threshold authority")
    matches = [row for row in payload.get("entries", []) if isinstance(row, dict) and row.get("id") == identifier]
    if len(matches) != 1 or type(matches[0].get("value")) is not int:
        raise ValueError(f"threshold {identifier} is invalid")
    return matches[0]["value"]


def compose_e7_v2(
    *,
    evidence_path: Path,
    v1_receipt_path: Path,
    telemetry_paths: tuple[Path, Path],
    thresholds_path: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    evidence_path = Path(evidence_path)
    v1_receipt_path = Path(v1_receipt_path)
    telemetry_paths = tuple(Path(path) for path in telemetry_paths)
    thresholds_path = Path(thresholds_path)
    output_dir = Path(output_dir)
    receipt_path = output_dir / "r1-e7-v2.json"
    composition_path = output_dir / "r1-e7-v2-composition.json"
    if receipt_path.exists() or composition_path.exists():
        raise FileExistsError("E7 v2 output already exists")

    evidence = _load(evidence_path, "E7 v1 evidence")
    if evidence.get("self_sha256") != _self_digest(evidence, "self_sha256"):
        raise ValueError("E7 v1 evidence self digest mismatch")
    v1 = _load(v1_receipt_path, "E7 v1 receipt")
    thresholds_sha = _sha(thresholds_path)
    prereg = v1.get("prereg")
    if (
        v1.get("schema") != "r1-exit-battery/v1"
        or v1.get("exit_criterion") != "R1-E7"
        or v1.get("status") != "MET"
        or not isinstance(prereg, dict)
        or prereg.get("pin") != PREREG_PIN
        or prereg.get("thresholds_sha256") != thresholds_sha
        or evidence.get("authority", {}).get("prereg_pin") != PREREG_PIN
        or evidence.get("authority", {}).get("thresholds", {}).get("sha256") != thresholds_sha
        or evidence.get("canonical_composition_receipt", {}).get("sha256") != _sha(v1_receipt_path)
    ):
        raise ValueError("E7 v1 authority binding is invalid")
    replicas = evidence.get("replicas")
    if not isinstance(replicas, list) or len(replicas) != 2:
        raise ValueError("E7 v1 evidence must bind exactly two replicas")

    seed_series: dict[str, list[dict[str, Any]]] = {}
    telemetry_inventory: list[dict[str, Any]] = []
    expected = {str(Path(row.get("telemetry", {}).get("path", "")).resolve()): row for row in replicas}
    for path in telemetry_paths:
        resolved = str(path.resolve())
        replica = expected.get(resolved)
        if replica is None:
            raise ValueError("telemetry path is not bound by E7 v1 evidence")
        ref = replica.get("telemetry", {})
        if ref.get("sha256") != _sha(path) or ref.get("bytes") != path.stat().st_size:
            raise ValueError("telemetry bytes disagree with E7 v1 evidence")
        run_id, series = _telemetry_series(path)
        seed_series[run_id] = series
        telemetry_inventory.append({"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size, "run_id": run_id})
    t01 = _threshold(thresholds_path, "T-01")
    if len(seed_series) != 2 or any(len(series) < t01 for series in seed_series.values()):
        raise ValueError("E7 v2 requires two distinct R1-scale telemetry series")

    loss = pooled_sigma_seed(seed_series, metric="loss")
    grad_norm = pooled_sigma_seed(seed_series, metric="grad_norm")
    ratio = normalized_grad_norm_ratio_sigma(seed_series)
    if min(loss["matched_step_count"], grad_norm["matched_step_count"], ratio["matched_step_count"]) < t01:
        raise ValueError("E7 v2 sigma is below the matched R1 scale")
    grad_norm["validator_input"] = False
    receipt = copy.deepcopy(v1)
    receipt["ticket"] = "r1-exit-battery-e7-v2"
    receipt["ts"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt["prereg"] = copy.deepcopy(prereg)
    receipt["result"] = {
        "status": "MET",
        "sigma_seed": {"loss": loss, "grad_norm_ratio": ratio, "grad_norm": grad_norm},
        "method_disclosure": (
            "grad_norm_ratio: each positive finite seed grad_norm divided by the across-seed mean at each matched step; "
            "population variance across normalized seeds per step, averaged across steps, then square root; seed-order invariant; "
            "with two seeds equals sqrt(mean_t(((g1-g2)/(g1+g2))^2)), approximately half literal ratio deviation near one; "
            "grad_norm retained for record only and is not a validator input"
        ),
    }
    receipt["receipt_sha256"] = _self_digest(receipt, "receipt_sha256")

    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_create(receipt_path, receipt)
    composition = {
        "schema_version": SCHEMA,
        "status": "COMPOSED",
        "inputs": {
            "evidence_v1_sha256": _sha(evidence_path),
            "e7_v1_sha256": _sha(v1_receipt_path),
            "thresholds_sha256": thresholds_sha,
            "telemetry": telemetry_inventory,
        },
        "outputs": {
            "e7_v2_path": receipt_path.name,
            "e7_v2_raw_sha256": _sha(receipt_path),
            "e7_v2_self_sha256": receipt["receipt_sha256"],
        },
        "estimator": receipt["result"]["method_disclosure"],
    }
    composition["self_sha256"] = _self_digest(composition, "self_sha256")
    _atomic_create(composition_path, composition)
    return receipt_path, composition_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-v1", type=Path, required=True)
    parser.add_argument("--receipt-v1", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, action="append", required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if len(args.telemetry) != 2:
        parser.error("exactly two --telemetry paths are required")
    receipt, composition = compose_e7_v2(
        evidence_path=args.evidence_v1,
        v1_receipt_path=args.receipt_v1,
        telemetry_paths=tuple(args.telemetry),
        thresholds_path=args.thresholds,
        output_dir=args.output_dir,
    )
    print(json.dumps({"receipt": str(receipt), "receipt_sha256": _sha(receipt), "composition": str(composition), "composition_sha256": _sha(composition)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

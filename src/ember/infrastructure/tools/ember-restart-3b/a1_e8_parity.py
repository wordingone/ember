# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""No-overwrite producer for the frozen R1-E8 Tier-2 parity receipt."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from durable_io import atomic_create_durable


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import r1_e8_validator as validator  # noqa: E402


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


def _verify_self(value: dict[str, Any], label: str) -> None:
    claimed = value.get("receipt_sha256")
    unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if claimed != hashlib.sha256(_canonical(unsigned)).hexdigest():
        raise ValueError(f"{label} self digest mismatch")


def _decimal(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{label} is invalid") from error
    if not number.is_finite():
        raise ValueError(f"{label} is invalid")
    return number


def _thresholds(path: Path) -> tuple[dict[str, Any], str]:
    payload = _load(path, "threshold authority")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("threshold authority is invalid")
    values = {row.get("id"): row.get("value") for row in entries if isinstance(row, dict)}
    for identifier in ("T-06", "T-09", "T-20"):
        if identifier not in values:
            raise ValueError(f"threshold {identifier} is absent")
    return values, _sha(path)


def derive_parity_series(
    telemetry_path: Path,
    *,
    run_id: str,
    run_receipt_sha256: str,
    steps: int,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id or type(steps) is not int or steps <= 0:
        raise ValueError("parity series request is invalid")
    by_step: dict[int, dict[str, Any]] = {}
    for line in Path(telemetry_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("parity telemetry contains invalid JSON") from error
        if event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("run_id") != run_id:
            continue
        step = payload.get("step")
        if type(step) is not int or step <= 0 or step in by_step:
            raise ValueError("parity telemetry step identity is invalid")
        loss = _decimal(payload.get("loss"), "parity loss")
        grad_norm = _decimal(payload.get("grad_norm"), "parity grad_norm")
        if grad_norm < 0:
            raise ValueError("parity grad_norm is invalid")
        by_step[step] = {
            "step": step,
            "loss": validator._serial(loss),
            "grad_norm": validator._serial(grad_norm),
        }
    if sorted(by_step) != list(range(1, steps + 1)):
        raise ValueError("parity telemetry does not contain the exact contiguous window")
    return {
        "schema_version": validator.PARITY_SERIES_SCHEMA,
        "run_receipt_sha256": run_receipt_sha256,
        "samples": [by_step[step] for step in range(1, steps + 1)],
    }


def _ref(packet_root: Path, path: Path) -> dict[str, str]:
    packet_root = packet_root.resolve()
    path = path.resolve()
    if path.parent != packet_root:
        raise ValueError("parity receipt inputs must be flat packet files")
    return {"path": path.name, "sha256": _sha(path)}


def mint_parity_receipt(
    *,
    packet_root: Path,
    candidate_run: Path,
    reference_run: Path,
    candidate_telemetry: Path,
    candidate_run_id: str,
    reference_telemetry: Path,
    reference_run_id: str,
    liveness_receipt: Path,
    thresholds_path: Path,
    e7_receipt: Path,
) -> Path:
    packet_root = Path(packet_root)
    candidate_run = Path(candidate_run)
    reference_run = Path(reference_run)
    liveness_receipt = Path(liveness_receipt)
    e7_receipt = Path(e7_receipt)
    candidate_series_path = packet_root / "tier2-parity-series.json"
    reference_series_path = packet_root / "tier1-parity-series.json"
    receipt_path = packet_root / "a1-e8-parity.json"
    if any(path.exists() for path in (candidate_series_path, reference_series_path, receipt_path)):
        raise FileExistsError("parity output already exists")

    thresholds, thresholds_sha = _thresholds(Path(thresholds_path))
    t06 = validator._decimal(thresholds["T-06"], "T06_INVALID")
    t09 = int(validator._decimal(thresholds["T-09"], "T09_INVALID"))
    t20 = validator._decimal(thresholds["T-20"], "T20_INVALID")
    candidate = _load(candidate_run, "candidate run")
    reference = _load(reference_run, "reference run")
    _verify_self(candidate, "candidate run")
    _verify_self(reference, "reference run")
    validator._validate_run(candidate, arm="A1", tier="TIER2", t06=t06)
    validator._validate_run(reference, arm="A1", tier="TIER1", t06=t06)
    validator._same_identity(candidate, reference, "PARITY_IDENTITY_MISMATCH")
    if candidate.get("architecture_revision") != reference.get("architecture_revision") or candidate.get("parameter_count") != reference.get("parameter_count"):
        raise ValueError("PARITY_IDENTITY_MISMATCH")

    liveness = _load(liveness_receipt, "liveness receipt")
    _verify_self(liveness, "liveness receipt")
    if liveness.get("schema_version") != validator.LIVENESS_SCHEMA or liveness.get("thresholds_sha256") != thresholds_sha or liveness.get("verdict") != "FALLBACK_REQUIRED":
        raise ValueError("parity liveness binding is invalid")
    e7 = _load(e7_receipt, "E7 receipt")
    _verify_self(e7, "E7 receipt")
    if e7.get("schema") != "r1-exit-battery/v1" or e7.get("exit_criterion") != "R1-E7" or e7.get("status") != "MET" or e7.get("prereg", {}).get("thresholds_sha256") != thresholds_sha:
        raise ValueError("E7 receipt is not green and threshold-bound")

    candidate_sha = _sha(candidate_run)
    reference_sha = _sha(reference_run)
    candidate_series = derive_parity_series(Path(candidate_telemetry), run_id=candidate_run_id, run_receipt_sha256=candidate_sha, steps=t09)
    reference_series = derive_parity_series(Path(reference_telemetry), run_id=reference_run_id, run_receipt_sha256=reference_sha, steps=t09)
    loss_delta = sum(
        abs(_decimal(candidate_row["loss"], "candidate loss") - _decimal(reference_row["loss"], "reference loss"))
        for candidate_row, reference_row in zip(candidate_series["samples"], reference_series["samples"])
    ) / Decimal(t09)
    candidate_grad = sum(_decimal(row["grad_norm"], "candidate grad_norm") for row in candidate_series["samples"])
    reference_grad = sum(_decimal(row["grad_norm"], "reference grad_norm") for row in reference_series["samples"])
    if reference_grad == 0:
        raise ValueError("reference grad norm is zero")
    grad_ratio = candidate_grad / reference_grad
    sigma = e7.get("result", {}).get("sigma_seed", {})
    loss_limit = t20 * _decimal(sigma.get("loss", {}).get("sigma_seed"), "E7 loss sigma")
    grad_limit = t20 * _decimal(sigma.get("grad_norm_ratio", {}).get("sigma_seed"), "E7 grad ratio sigma")
    metrics = {
        "mean_abs_loss_delta": validator._serial(loss_delta),
        "grad_norm_ratio": validator._serial(grad_ratio),
        "loss_limit": validator._serial(loss_limit),
        "grad_norm_ratio_limit": validator._serial(grad_limit),
    }
    verdict = "PASS" if loss_delta <= loss_limit and abs(grad_ratio - Decimal(1)) <= grad_limit else "FAIL"
    packet_root.mkdir(parents=True, exist_ok=True)
    atomic_create_durable(candidate_series_path, _canonical(candidate_series) + b"\n")
    atomic_create_durable(reference_series_path, _canonical(reference_series) + b"\n")
    receipt = {
        "schema_version": validator.PARITY_SCHEMA,
        "thresholds_sha256": thresholds_sha,
        "liveness_receipt_sha256": _sha(liveness_receipt),
        "candidate_run": _ref(packet_root, candidate_run),
        "reference_run": _ref(packet_root, reference_run),
        "candidate_series": _ref(packet_root, candidate_series_path),
        "reference_series": _ref(packet_root, reference_series_path),
        "r1_e7_receipt": _ref(packet_root, e7_receipt),
        "metrics": metrics,
        "verdict": verdict,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    atomic_create_durable(receipt_path, _canonical(receipt) + b"\n")
    return receipt_path

#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pure, fail-closed validator for EMBER-02 R1-E8 A1 receipts.

This module does not train, project a charged budget, or mint evidence.  It
only reopens already-produced receipt bytes and recomputes the numeric gates.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any


LIVENESS_SCHEMA = "ember02-r1-e8-liveness-v1"
PARITY_SCHEMA = "ember02-r1-e8-parity-v1"
RUN_SCHEMA = "ember02-r1-e8-run-v1"
CONTRACT_SCHEMA = "ember02-r2-charged-budget-contract-v1"
LIVENESS_SERIES_SCHEMA = "ember02-r1-e8-liveness-series-v1"
PARITY_SERIES_SCHEMA = "ember02-r1-e8-parity-series-v1"
Q = Decimal("0.000000000001")


class E8ValidationError(ValueError):
    pass


class E8EvidenceMissing(E8ValidationError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise E8ValidationError(f"{code}: {detail}" if detail else code)


def _missing(code: str, detail: str = "") -> None:
    raise E8EvidenceMissing(f"{code}: {detail}" if detail else code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decimal(value: Any, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        _fail(code, "numeric receipt fields must be decimal strings or integers")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        _fail(code, f"invalid decimal {value!r}")
    if not result.is_finite():
        _fail(code, "non-finite decimal")
    return result


def _serial(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 50
        return format(value.quantize(Q, rounding=ROUND_HALF_EVEN), "f")


def _closed(doc: dict[str, Any], expected: set[str], code: str) -> None:
    if set(doc) != expected:
        _fail(code, f"fields={sorted(doc)} expected={sorted(expected)}")


def _self_digest(doc: dict[str, Any], code: str) -> None:
    claimed = doc.get("receipt_sha256")
    unsigned = {key: value for key, value in doc.items() if key != "receipt_sha256"}
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if claimed != _sha(raw):
        _fail(code, "receipt_sha256 does not match canonical unsigned JSON")


def _load_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        doc = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(code, str(exc))
    if not isinstance(doc, dict):
        _fail(code, "top level must be an object")
    return doc, raw


def _reopen_ref(base: Path, ref: Any, code: str, *, self_digest: bool = True) -> tuple[dict[str, Any], str]:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        _fail(code, "reference must contain only path and sha256")
    rel = Path(ref["path"]) if isinstance(ref["path"], str) else Path(".")
    if rel.is_absolute() or ".." in rel.parts or str(rel) in ("", "."):
        _fail(code, "reference path must be packet-relative and non-traversing")
    path = (base / rel).resolve()
    if base.resolve() not in path.parents:
        _fail(code, "reference escaped packet root")
    doc, raw = _load_json(path, code)
    digest = _sha(raw)
    if ref.get("sha256") != digest:
        _fail("REFERENCE_SHA_MISMATCH", str(rel))
    if self_digest:
        _self_digest(doc, code)
    return doc, digest


RUN_FIELDS = {
    "schema_version", "arm_id", "tier", "mechanism", "status",
    "certified_launch_sha256", "source_commit", "architecture_revision",
    "parameter_count", "active_parameter_count", "contains_router_or_experts",
    "optimizer", "identity", "energy_sample_coverage", "checkpoint_sha256",
    "receipt_sha256",
}
IDENTITY_FIELDS = {
    "comparison_id", "corpus_authority_sha256", "shard_sequence_sha256",
    "tokenizer_sha256", "seed", "cursor_start", "schedule_sha256", "genesis_sha256",
}


def _validate_run(doc: dict[str, Any], *, arm: str, tier: str | None, t06: Decimal) -> None:
    _closed(doc, RUN_FIELDS, "RUN_FIELDS_INVALID")
    if doc.get("schema_version") != RUN_SCHEMA or doc.get("status") != "TERMINAL" or doc.get("arm_id") != arm:
        _fail("RUN_SCHEMA_INVALID")
    certified = doc.get("certified_launch_sha256")
    if not isinstance(certified, str) or len(certified) != 64:
        _fail("CERTIFIED_LAUNCH_INVALID")
    identity = doc.get("identity")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        _fail("RUN_IDENTITY_INVALID")
    if tier is not None and doc.get("tier") != tier:
        _fail("RUN_TIER_INVALID")
    if arm == "A1":
        if doc.get("parameter_count", 0) < 3_000_000_000 or doc.get("active_parameter_count", 0) < 3_000_000_000:
            _fail("A1_SUB_3B")
        if doc.get("contains_router_or_experts") is not False or "dense" not in str(doc.get("architecture_revision", "")):
            _fail("A1_NOT_DENSE")
    if tier == "TIER1":
        optimizer = doc.get("optimizer")
        if not isinstance(optimizer, dict) or set(optimizer) != {"kind", "full_state", "cpu_offload", "covered_parameter_count"}:
            _fail("TIER1_OPTIMIZER_INVALID")
        if optimizer != {
            "kind": "AdamW", "full_state": True, "cpu_offload": True,
            "covered_parameter_count": doc.get("parameter_count"),
        }:
            _fail("TIER1_OPTIMIZER_INVALID")
    if _decimal(doc.get("energy_sample_coverage"), "ENERGY_COVERAGE_INVALID") < t06:
        _fail("ENERGY_COVERAGE_BELOW_T06")


def _same_identity(left: dict[str, Any], right: dict[str, Any], code: str) -> None:
    if left.get("source_commit") != right.get("source_commit") or left.get("identity") != right.get("identity"):
        _fail(code)


def _liveness_measurements(series: dict[str, Any], run_sha: str) -> tuple[Decimal, Decimal]:
    _closed(series, {"schema_version", "run_receipt_sha256", "samples"}, "LIVENESS_SERIES_FIELDS_INVALID")
    if series.get("schema_version") != LIVENESS_SERIES_SCHEMA or series.get("run_receipt_sha256") != run_sha:
        _fail("LIVENESS_SERIES_BINDING_INVALID")
    samples = series.get("samples")
    if not isinstance(samples, list) or not samples:
        _fail("LIVENESS_SERIES_EMPTY")
    tokens = Decimal(0)
    seconds = Decimal(0)
    joules = Decimal(0)
    expected_step = 1
    for row in samples:
        if not isinstance(row, dict) or set(row) != {"step", "tokens", "wall_seconds", "proxy_joules"} or row.get("step") != expected_step:
            _fail("LIVENESS_SERIES_STEP_INVALID")
        expected_step += 1
        token_count = _decimal(row["tokens"], "LIVENESS_SERIES_NUMERIC_INVALID")
        wall = _decimal(row["wall_seconds"], "LIVENESS_SERIES_NUMERIC_INVALID")
        energy = _decimal(row["proxy_joules"], "LIVENESS_SERIES_NUMERIC_INVALID")
        if token_count <= 0 or wall <= 0 or energy < 0:
            _fail("LIVENESS_SERIES_NUMERIC_INVALID")
        tokens += token_count
        seconds += wall
        joules += energy
    return tokens / seconds, joules / tokens


def _find_receipts(search_roots: list[Path], name: str) -> list[Path]:
    found: list[Path] = []
    for root in search_roots:
        if root.is_dir():
            found.extend(path for path in root.rglob(name) if path.is_file())
    return sorted(set(path.resolve() for path in found))


def _validate_parity(
    path: Path, *, liveness_sha: str, thresholds: dict[str, Any], thresholds_sha256: str, t06: Decimal
) -> dict[str, Any]:
    doc, _ = _load_json(path, "PARITY_UNREADABLE")
    _closed(doc, {
        "schema_version", "thresholds_sha256", "liveness_receipt_sha256", "candidate_run",
        "reference_run", "candidate_series", "reference_series", "r1_e7_receipt",
        "metrics", "verdict", "receipt_sha256",
    }, "PARITY_FIELDS_INVALID")
    _self_digest(doc, "PARITY_SELF_DIGEST_INVALID")
    if doc.get("schema_version") != PARITY_SCHEMA:
        _fail("PARITY_SCHEMA_INVALID")
    if doc.get("thresholds_sha256") != thresholds_sha256:
        _fail("THRESHOLDS_SHA_MISMATCH")
    if doc.get("liveness_receipt_sha256") != liveness_sha:
        _fail("PARITY_LIVENESS_BINDING_INVALID")
    base = path.parent
    candidate, candidate_sha = _reopen_ref(base, doc["candidate_run"], "PARITY_CANDIDATE_INVALID")
    reference, reference_sha = _reopen_ref(base, doc["reference_run"], "PARITY_REFERENCE_INVALID")
    _validate_run(candidate, arm="A1", tier="TIER2", t06=t06)
    _validate_run(reference, arm="A1", tier="TIER1", t06=t06)
    _same_identity(candidate, reference, "PARITY_IDENTITY_MISMATCH")
    if candidate.get("architecture_revision") != reference.get("architecture_revision") or candidate.get("parameter_count") != reference.get("parameter_count"):
        _fail("PARITY_IDENTITY_MISMATCH")
    candidate_series, _ = _reopen_ref(base, doc["candidate_series"], "PARITY_CANDIDATE_SERIES_INVALID", self_digest=False)
    reference_series, _ = _reopen_ref(base, doc["reference_series"], "PARITY_REFERENCE_SERIES_INVALID", self_digest=False)
    for series, run_sha in ((candidate_series, candidate_sha), (reference_series, reference_sha)):
        _closed(series, {"schema_version", "run_receipt_sha256", "samples"}, "PARITY_SERIES_FIELDS_INVALID")
        if series.get("schema_version") != PARITY_SERIES_SCHEMA or series.get("run_receipt_sha256") != run_sha:
            _fail("PARITY_SERIES_BINDING_INVALID")
    candidate_samples = candidate_series.get("samples")
    reference_samples = reference_series.get("samples")
    t09 = int(_decimal(thresholds["T-09"], "T09_INVALID"))
    if not isinstance(candidate_samples, list) or not isinstance(reference_samples, list) or len(candidate_samples) != t09 or len(reference_samples) != t09:
        _fail("PARITY_STEP_COUNT_MISMATCH")
    loss_delta = Decimal(0)
    candidate_grad = Decimal(0)
    reference_grad = Decimal(0)
    for step, (cand, ref) in enumerate(zip(candidate_samples, reference_samples), start=1):
        expected = {"step", "loss", "grad_norm"}
        if not isinstance(cand, dict) or not isinstance(ref, dict) or set(cand) != expected or set(ref) != expected or cand["step"] != step or ref["step"] != step:
            _fail("PARITY_STEP_IDENTITY_MISMATCH")
        loss_delta += abs(_decimal(cand["loss"], "PARITY_NUMERIC_INVALID") - _decimal(ref["loss"], "PARITY_NUMERIC_INVALID"))
        candidate_grad += _decimal(cand["grad_norm"], "PARITY_NUMERIC_INVALID")
        reference_grad += _decimal(ref["grad_norm"], "PARITY_NUMERIC_INVALID")
    if reference_grad == 0:
        _fail("PARITY_NUMERIC_INVALID", "zero reference grad norm")
    mean_loss_delta = loss_delta / Decimal(t09)
    grad_ratio = candidate_grad / reference_grad
    e7, _ = _reopen_ref(base, doc["r1_e7_receipt"], "E7_RECEIPT_INVALID")
    if e7.get("schema") != "r1-exit-battery/v1" or e7.get("exit_criterion") != "R1-E7" or e7.get("status") != "MET":
        _fail("E7_NOT_GREEN")
    if e7.get("prereg", {}).get("thresholds_sha256") != thresholds_sha256:
        _fail("E7_THRESHOLDS_MISMATCH")
    sigma = e7.get("result", {}).get("sigma_seed", {})
    loss_sigma = _decimal(sigma.get("loss", {}).get("sigma_seed"), "E7_SIGMA_MISSING")
    grad_sigma = _decimal(sigma.get("grad_norm_ratio", {}).get("sigma_seed"), "E7_SIGMA_MISSING")
    t20 = _decimal(thresholds["T-20"], "T20_INVALID")
    loss_limit = t20 * loss_sigma
    grad_limit = t20 * grad_sigma
    expected_metrics = {
        "mean_abs_loss_delta": _serial(mean_loss_delta),
        "grad_norm_ratio": _serial(grad_ratio),
        "loss_limit": _serial(loss_limit),
        "grad_norm_ratio_limit": _serial(grad_limit),
    }
    if doc.get("metrics") != expected_metrics:
        _fail("PARITY_ARITHMETIC_MISMATCH")
    passed = mean_loss_delta <= loss_limit and abs(grad_ratio - Decimal(1)) <= grad_limit
    expected_verdict = "PASS" if passed else "FAIL"
    if doc.get("verdict") != expected_verdict:
        _fail("PARITY_VERDICT_MISMATCH")
    return {"status": "MET" if passed else "NOT_MET", "metrics": expected_metrics, "receipt": str(path)}


def validate_e8(search_roots: list[Path], thresholds: dict[str, Any], thresholds_sha256: str | None) -> dict[str, Any]:
    liveness_paths = _find_receipts(search_roots, "*liveness*.json")
    if not liveness_paths:
        return {"status": "EVIDENCE_MISSING", "detail": "A1_LIVENESS_RECEIPT_MISSING", "needs": LIVENESS_SCHEMA}
    if len(liveness_paths) != 1:
        return {"status": "REFUSED", "detail": f"LIVENESS_RECEIPT_AMBIGUOUS: {len(liveness_paths)} candidates"}
    try:
        path = liveness_paths[0]
        doc, raw = _load_json(path, "LIVENESS_UNREADABLE")
        _closed(doc, {
            "schema_version", "thresholds_sha256", "charged_budget_contract", "tier1_run", "a3_run",
            "a1_series", "a3_series", "measurements", "verdict", "receipt_sha256",
        }, "LIVENESS_FIELDS_INVALID")
        _self_digest(doc, "LIVENESS_SELF_DIGEST_INVALID")
        if doc.get("schema_version") != LIVENESS_SCHEMA:
            _fail("LIVENESS_SCHEMA_INVALID")
        if thresholds_sha256 is None or doc.get("thresholds_sha256") != thresholds_sha256:
            _fail("THRESHOLDS_SHA_MISMATCH")
        t06 = _decimal(thresholds["T-06"], "T06_INVALID")
        t08 = _decimal(thresholds["T-08"], "T08_INVALID")
        if doc.get("charged_budget_contract") is None:
            _missing("CHARGED_BUDGET_CONTRACT_MISSING", "no liveness formula is inferred")
        base = path.parent
        tier1, tier1_sha = _reopen_ref(base, doc["tier1_run"], "TIER1_RUN_INVALID")
        a3, a3_sha = _reopen_ref(base, doc["a3_run"], "A3_RUN_INVALID")
        _validate_run(tier1, arm="A1", tier="TIER1", t06=t06)
        _validate_run(a3, arm="A3", tier=None, t06=t06)
        _same_identity(tier1, a3, "MATCHED_IDENTITY_MISMATCH")
        a1_series, _ = _reopen_ref(base, doc["a1_series"], "A1_LIVENESS_SERIES_INVALID", self_digest=False)
        a3_series, _ = _reopen_ref(base, doc["a3_series"], "A3_LIVENESS_SERIES_INVALID", self_digest=False)
        a1_tps, a1_jpt = _liveness_measurements(a1_series, tier1_sha)
        a3_tps, a3_jpt = _liveness_measurements(a3_series, a3_sha)
        contract, _ = _reopen_ref(base, doc["charged_budget_contract"], "CHARGED_BUDGET_CONTRACT_INVALID")
        _closed(contract, {"schema_version", "status", "comparison_id", "a1_run_sha256", "a3_run_sha256", "projected_r2_tokens", "receipt_sha256"}, "CHARGED_BUDGET_CONTRACT_FIELDS_INVALID")
        if contract.get("schema_version") != CONTRACT_SCHEMA or contract.get("status") != "FROZEN":
            _fail("CHARGED_BUDGET_CONTRACT_INVALID")
        if contract.get("comparison_id") != tier1["identity"]["comparison_id"] or contract.get("a1_run_sha256") != tier1_sha or contract.get("a3_run_sha256") != a3_sha:
            _fail("CHARGED_BUDGET_CONTRACT_BINDING_INVALID")
        projected = contract.get("projected_r2_tokens")
        if not isinstance(projected, dict) or set(projected) != {"a1", "a3"}:
            _fail("CHARGED_BUDGET_CONTRACT_INVALID")
        a1_projected = _decimal(projected["a1"], "CHARGED_BUDGET_CONTRACT_INVALID")
        a3_projected = _decimal(projected["a3"], "CHARGED_BUDGET_CONTRACT_INVALID")
        if a1_projected < 0 or a3_projected <= 0:
            _fail("CHARGED_BUDGET_CONTRACT_INVALID")
        ratio = a1_projected / a3_projected
        expected_measurements = {
            "a1_tokens_per_second": _serial(a1_tps),
            "a1_joules_per_token": _serial(a1_jpt),
            "a3_tokens_per_second": _serial(a3_tps),
            "a3_joules_per_token": _serial(a3_jpt),
            "equal_budget_ratio": _serial(ratio),
        }
        if doc.get("measurements") != expected_measurements:
            _fail("LIVENESS_ARITHMETIC_MISMATCH")
        verdict = "TIER1_LIVE" if ratio >= t08 else "FALLBACK_REQUIRED"
        if doc.get("verdict") != verdict:
            _fail("LIVENESS_VERDICT_MISMATCH")
        parity_paths = _find_receipts(search_roots, "a1-e8-parity.json")
        if verdict == "TIER1_LIVE":
            if parity_paths:
                _fail("PARITY_FORBIDDEN_WHEN_TIER1_LIVE")
            return {"status": "MET", "detail": "R1-E8 Tier1 liveness leg passed", "components": {"liveness": expected_measurements, "parity": "NOT_REQUIRED"}}
        if not parity_paths:
            _missing("PARITY_RECEIPT_MISSING", "Tier1 is below T-08")
        if len(parity_paths) != 1:
            _fail("PARITY_RECEIPT_AMBIGUOUS")
        parity = _validate_parity(parity_paths[0], liveness_sha=_sha(raw), thresholds=thresholds, thresholds_sha256=thresholds_sha256, t06=t06)
        return {"status": parity["status"], "detail": "R1-E8 Tier2 parity adjudicated", "components": {"liveness": expected_measurements, "parity": parity}}
    except E8EvidenceMissing as exc:
        return {"status": "EVIDENCE_MISSING", "detail": str(exc)}
    except E8ValidationError as exc:
        return {"status": "REFUSED", "detail": str(exc)}

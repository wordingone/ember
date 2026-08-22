# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load_battery():
    spec = importlib.util.spec_from_file_location("r1_exit_battery_e8_test", SCRIPTS / "r1_exit_battery.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BATTERY = _load_battery()
THRESHOLDS, THRESHOLDS_SHA = BATTERY.load_thresholds()


def _receipt_digest(doc: dict) -> str:
    unsigned = {key: value for key, value in doc.items() if key != "receipt_sha256"}
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, doc: dict, *, self_digest: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = copy.deepcopy(doc)
    if self_digest:
        payload["receipt_sha256"] = _receipt_digest(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _ref(root: Path, name: str, doc: dict, *, self_digest: bool = True) -> dict:
    digest = _write_json(root / name, doc, self_digest=self_digest)
    return {"path": name, "sha256": digest}


def _identity() -> dict:
    return {
        "comparison_id": "r1-e8-a1-vs-a3",
        "corpus_authority_sha256": "1" * 64,
        "shard_sequence_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "seed": 147,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": "4" * 64,
        "genesis_sha256": "5" * 64,
    }


def _run(arm: str, *, tier: str, mechanism: str) -> dict:
    dense = arm == "A1"
    return {
        "schema_version": "ember02-r1-e8-run-v1",
        "arm_id": arm,
        "tier": tier,
        "mechanism": mechanism,
        "status": "TERMINAL",
        "certified_launch_sha256": "6" * 64,
        "source_commit": "a45b41ffcc2753f5027e77d4ea59021d68ec46fb",
        "architecture_revision": "ember-dense-3b-a1-v1" if dense else "ember-sparse-3b-v2",
        "parameter_count": 3_839_000_000,
        "active_parameter_count": 3_839_000_000 if dense else 1_021_000_000,
        "contains_router_or_experts": not dense,
        "optimizer": {
            "kind": "AdamW",
            "full_state": True,
            "cpu_offload": tier == "TIER1",
            "covered_parameter_count": 3_839_000_000,
        },
        "identity": _identity(),
        "energy_sample_coverage": "0.950000000000",
        "checkpoint_sha256": "7" * 64,
    }


def _liveness_series(run_sha: str, *, tokens: int, joules: str) -> dict:
    return {
        "schema_version": "ember02-r1-e8-liveness-series-v1",
        "run_receipt_sha256": run_sha,
        "samples": [
            {"step": 1, "tokens": tokens // 2, "wall_seconds": "5", "proxy_joules": str(int(joules) // 2)},
            {"step": 2, "tokens": tokens - tokens // 2, "wall_seconds": "5", "proxy_joules": str(int(joules) - int(joules) // 2)},
        ],
    }


def _parity_series(run_sha: str, *, loss_offset: str = "0") -> dict:
    offset = float(loss_offset)
    return {
        "schema_version": "ember02-r1-e8-parity-series-v1",
        "run_receipt_sha256": run_sha,
        "samples": [
            {"step": step, "loss": f"{1.0 + offset + step / 1000:.12f}", "grad_norm": "2.000000000000"}
            for step in range(1, 101)
        ],
    }


def _packet(root: Path, *, projected_a1: str = "340", include_contract: bool = True, include_parity: bool = False) -> dict:
    tier1 = _run("A1", tier="TIER1", mechanism="adamw-cpu-offload")
    a3 = _run("A3", tier="A3", mechanism="role-prior-sparse")
    tier1_ref = _ref(root, "tier1-run.json", tier1)
    a3_ref = _ref(root, "a3-run.json", a3)
    a1_series_ref = _ref(root, "a1-live-series.json", _liveness_series(tier1_ref["sha256"], tokens=340, joules="100"), self_digest=False)
    a3_series_ref = _ref(root, "a3-live-series.json", _liveness_series(a3_ref["sha256"], tokens=1000, joules="200"), self_digest=False)
    contract_ref = None
    if include_contract:
        contract_ref = _ref(root, "r2-charged-budget.json", {
            "schema_version": "ember02-r2-charged-budget-contract-v1",
            "status": "FROZEN",
            "comparison_id": "r1-e8-a1-vs-a3",
            "a1_run_sha256": tier1_ref["sha256"],
            "a3_run_sha256": a3_ref["sha256"],
            "projected_r2_tokens": {"a1": projected_a1, "a3": "1000"},
        })
    ratio = f"{float(projected_a1) / 1000:.12f}"
    liveness = {
        "schema_version": "ember02-r1-e8-liveness-v1",
        "thresholds_sha256": THRESHOLDS_SHA,
        "charged_budget_contract": contract_ref,
        "tier1_run": tier1_ref,
        "a3_run": a3_ref,
        "a1_series": a1_series_ref,
        "a3_series": a3_series_ref,
        "measurements": {
            "a1_tokens_per_second": "34.000000000000",
            "a1_joules_per_token": "0.294117647059",
            "a3_tokens_per_second": "100.000000000000",
            "a3_joules_per_token": "0.200000000000",
            "equal_budget_ratio": ratio,
        },
        "verdict": "TIER1_LIVE" if float(projected_a1) / 1000 >= float(THRESHOLDS["T-08"]) else "FALLBACK_REQUIRED",
    }
    liveness_ref = _ref(root, "a1-e8-liveness.json", liveness)
    if include_parity:
        candidate = _run("A1", tier="TIER2", mechanism="owned-projected-gradient")
        reference = _run("A1", tier="TIER1", mechanism="adamw-cpu-offload")
        candidate_ref = _ref(root, "tier2-run.json", candidate)
        reference_ref = _ref(root, "tier1-reference-run.json", reference)
        candidate_series = _ref(root, "tier2-parity-series.json", _parity_series(candidate_ref["sha256"]), self_digest=False)
        reference_series = _ref(root, "tier1-parity-series.json", _parity_series(reference_ref["sha256"]), self_digest=False)
        e7_ref = _ref(root, "r1-e7.json", {
            "schema": "r1-exit-battery/v1",
            "exit_criterion": "R1-E7",
            "status": "MET",
            "prereg": {"thresholds_sha256": THRESHOLDS_SHA},
            "result": {"sigma_seed": {
                "loss": {"sigma_seed": "0.1"},
                "grad_norm_ratio": {"sigma_seed": "0.1"},
                "grad_norm": {"sigma_seed": "0.2", "validator_input": False},
            }},
        })
        parity = {
            "schema_version": "ember02-r1-e8-parity-v1",
            "thresholds_sha256": THRESHOLDS_SHA,
            "liveness_receipt_sha256": liveness_ref["sha256"],
            "candidate_run": candidate_ref,
            "reference_run": reference_ref,
            "candidate_series": candidate_series,
            "reference_series": reference_series,
            "r1_e7_receipt": e7_ref,
            "metrics": {
                "mean_abs_loss_delta": "0.000000000000",
                "grad_norm_ratio": "1.000000000000",
                "loss_limit": "0.200000000000",
                "grad_norm_ratio_limit": "0.200000000000",
            },
            "verdict": "PASS",
        }
        _ref(root, "a1-e8-parity.json", parity)
    return liveness


def _check(root: Path) -> dict:
    return BATTERY.check_r1_e8([root], THRESHOLDS, thresholds_sha256=THRESHOLDS_SHA)


def _rewrite_liveness_dependency(root: Path, target: str, mutator) -> None:
    target_path = root / target
    target_doc = json.loads(target_path.read_text("utf-8"))
    mutator(target_doc)
    target_sha = _write_json(target_path, target_doc, self_digest=True)
    liveness_path = root / "a1-e8-liveness.json"
    liveness = json.loads(liveness_path.read_text("utf-8"))
    run_key, series_key, series_name, contract_key = (
        ("tier1_run", "a1_series", "a1-live-series.json", "a1_run_sha256")
        if target == "tier1-run.json"
        else ("a3_run", "a3_series", "a3-live-series.json", "a3_run_sha256")
    )
    liveness[run_key]["sha256"] = target_sha
    series_path = root / series_name
    series = json.loads(series_path.read_text("utf-8"))
    series["run_receipt_sha256"] = target_sha
    liveness[series_key]["sha256"] = _write_json(series_path, series)
    contract_path = root / "r2-charged-budget.json"
    contract = json.loads(contract_path.read_text("utf-8"))
    contract[contract_key] = target_sha
    liveness["charged_budget_contract"]["sha256"] = _write_json(contract_path, contract, self_digest=True)
    _write_json(liveness_path, liveness, self_digest=True)


def _rewrite_parity_dependency(root: Path, target: str, mutator) -> None:
    target_path = root / target
    target_doc = json.loads(target_path.read_text("utf-8"))
    mutator(target_doc)
    target_sha = _write_json(target_path, target_doc, self_digest="receipt_sha256" in target_doc)
    if target == "a1-e8-parity.json":
        return
    parity_path = root / "a1-e8-parity.json"
    parity = json.loads(parity_path.read_text("utf-8"))
    if target == "tier2-run.json":
        parity["candidate_run"]["sha256"] = target_sha
        series_path = root / "tier2-parity-series.json"
        series = json.loads(series_path.read_text("utf-8"))
        series["run_receipt_sha256"] = target_sha
        parity["candidate_series"]["sha256"] = _write_json(series_path, series)
    elif target == "tier2-parity-series.json":
        parity["candidate_series"]["sha256"] = target_sha
    elif target == "r1-e7.json":
        parity["r1_e7_receipt"]["sha256"] = target_sha
    _write_json(parity_path, parity, self_digest=True)


def test_tier1_live_packet_is_met(tmp_path: Path):
    _packet(tmp_path)
    assert _check(tmp_path)["status"] == "MET"


def test_absent_charged_budget_contract_stays_evidence_missing(tmp_path: Path):
    _packet(tmp_path, include_contract=False)
    result = _check(tmp_path)
    assert result["status"] == "EVIDENCE_MISSING"
    assert "CHARGED_BUDGET_CONTRACT_MISSING" in result["detail"]


def test_fallback_requires_parity(tmp_path: Path):
    _packet(tmp_path, projected_a1="320")
    assert _check(tmp_path)["status"] == "EVIDENCE_MISSING"


def test_fallback_with_green_parity_is_met(tmp_path: Path):
    _packet(tmp_path, projected_a1="320", include_parity=True)
    assert _check(tmp_path)["status"] == "MET"


def test_live_v1_e7_shape_without_ratio_sigma_is_refused(tmp_path: Path):
    """Catches dimensionally invalid aliasing of raw grad-norm sigma."""
    _packet(tmp_path, projected_a1="320", include_parity=True)
    _rewrite_parity_dependency(
        tmp_path,
        "r1-e7.json",
        lambda d: d["result"]["sigma_seed"].pop("grad_norm_ratio"),
    )
    result = _check(tmp_path)
    assert result["status"] == "REFUSED"
    assert "E7_SIGMA_MISSING" in result["detail"]


def test_fallback_with_honest_out_of_band_parity_is_not_met(tmp_path: Path):
    _packet(tmp_path, projected_a1="320", include_parity=True)
    series_path = tmp_path / "tier2-parity-series.json"
    series = json.loads(series_path.read_text("utf-8"))
    for row in series["samples"]:
        row["loss"] = f"{float(row['loss']) + 0.3:.12f}"
    series_sha = _write_json(series_path, series)
    parity_path = tmp_path / "a1-e8-parity.json"
    parity = json.loads(parity_path.read_text("utf-8"))
    parity["candidate_series"]["sha256"] = series_sha
    parity["metrics"]["mean_abs_loss_delta"] = "0.300000000000"
    parity["verdict"] = "FAIL"
    _write_json(parity_path, parity, self_digest=True)
    assert _check(tmp_path)["status"] == "NOT_MET"


def test_parity_is_refused_when_tier1_is_live(tmp_path: Path):
    _packet(tmp_path, include_parity=True)
    assert _check(tmp_path)["status"] == "REFUSED"


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda d: d.update(schema_version="wrong"), "LIVENESS_SCHEMA_INVALID"),
        (lambda d: d.update(extra="unknown"), "LIVENESS_FIELDS_INVALID"),
        (lambda d: d.update(thresholds_sha256="0" * 64), "THRESHOLDS_SHA_MISMATCH"),
        (lambda d: d["measurements"].update(equal_budget_ratio="0.999000000000"), "LIVENESS_ARITHMETIC_MISMATCH"),
        (lambda d: d["measurements"].update(a1_tokens_per_second="99.000000000000"), "LIVENESS_ARITHMETIC_MISMATCH"),
    ],
)
def test_liveness_receipt_tamper_is_refused(tmp_path: Path, mutator, reason: str):
    _packet(tmp_path)
    path = tmp_path / "a1-e8-liveness.json"
    doc = json.loads(path.read_text("utf-8"))
    mutator(doc)
    _write_json(path, doc, self_digest=True)
    result = _check(tmp_path)
    assert result["status"] == "REFUSED"
    assert reason in result["detail"]


@pytest.mark.parametrize(
    ("target", "mutator", "reason"),
    [
        ("tier1-run.json", lambda d: d.update(parameter_count=2_999_999_999), "A1_SUB_3B"),
        ("tier1-run.json", lambda d: d.update(contains_router_or_experts=True), "A1_NOT_DENSE"),
        ("tier1-run.json", lambda d: d["optimizer"].update(kind="SGD"), "TIER1_OPTIMIZER_INVALID"),
        ("tier1-run.json", lambda d: d["optimizer"].update(cpu_offload=False), "TIER1_OPTIMIZER_INVALID"),
        ("tier1-run.json", lambda d: d["optimizer"].update(covered_parameter_count=1), "TIER1_OPTIMIZER_INVALID"),
        ("tier1-run.json", lambda d: d.update(certified_launch_sha256=None), "CERTIFIED_LAUNCH_INVALID"),
        ("a3-run.json", lambda d: d["identity"].update(seed=999), "MATCHED_IDENTITY_MISMATCH"),
        ("tier1-run.json", lambda d: d.update(energy_sample_coverage="0.94"), "ENERGY_COVERAGE_BELOW_T06"),
    ],
)
def test_run_leg_forgery_is_refused(tmp_path: Path, target: str, mutator, reason: str):
    _packet(tmp_path)
    _rewrite_liveness_dependency(tmp_path, target, mutator)
    result = _check(tmp_path)
    assert result["status"] == "REFUSED"
    assert reason in result["detail"]


@pytest.mark.parametrize(
    ("target", "mutator", "reason"),
    [
        ("tier2-run.json", lambda d: d["identity"].update(seed=999), "PARITY_IDENTITY_MISMATCH"),
        ("tier2-parity-series.json", lambda d: d["samples"].pop(), "PARITY_STEP_COUNT_MISMATCH"),
        ("r1-e7.json", lambda d: d.update(status="NOT_MET"), "E7_NOT_GREEN"),
        ("a1-e8-parity.json", lambda d: d["metrics"].update(grad_norm_ratio="2.0"), "PARITY_ARITHMETIC_MISMATCH"),
    ],
)
def test_parity_leg_forgery_is_refused(tmp_path: Path, target: str, mutator, reason: str):
    _packet(tmp_path, projected_a1="320", include_parity=True)
    _rewrite_parity_dependency(tmp_path, target, mutator)
    result = _check(tmp_path)
    assert result["status"] == "REFUSED"
    assert reason in result["detail"]

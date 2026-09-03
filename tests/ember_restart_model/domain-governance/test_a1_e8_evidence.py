# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""R1-E8 C2 tests: the liveness evidence producer, proven against the REAL
validator (`scripts/r1_e8_validator.validate_e8`) as its first real
downstream consumer -- never a mock of that function."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
SCRIPTS = ROOT / "src" / "ember" / "governance" / "scripts"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_evidence():
    inserted = str(TOOLS) not in sys.path
    if inserted:
        sys.path.insert(0, str(TOOLS))
    try:
        return _load_module(TOOLS / "a1_e8_evidence.py", "a1_e8_evidence_under_test")
    finally:
        if inserted:
            sys.path.remove(str(TOOLS))


EVIDENCE = _load_evidence()
VALIDATOR = _load_module(SCRIPTS / "r1_e8_validator.py", "r1_e8_validator_under_test")

THRESHOLDS_PATH = (
    ROOT
    / "docs"
    / "domains"
    / "governance"
    / "spec"
    / "ember02-preregistration-thresholds-v1.json"
)


def _real_thresholds() -> tuple[dict, str]:
    raw = THRESHOLDS_PATH.read_bytes()
    doc = json.loads(raw)
    values = {
        entry["id"]: entry["value"]
        for entry in doc["entries"]
        if entry.get("frozen_form") == "number"
    }
    return values, hashlib.sha256(raw).hexdigest()


THRESHOLDS, THRESHOLDS_SHA = _real_thresholds()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _with_self_digest(value: dict) -> dict:
    value = dict(value)
    value["receipt_sha256"] = _canonical_sha(value)
    return value


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(doc) + b"\n")


def _identity(*, comparison_id: str = "r1-e8-a1-vs-a3") -> dict:
    return {
        "comparison_id": comparison_id,
        "corpus_authority_sha256": "1" * 64,
        "shard_sequence_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "seed": 147,
        "cursor_start": {"global_step": 0, "record_index": 0, "tokens_seen": 0},
        "schedule_sha256": "4" * 64,
        "genesis_sha256": "5" * 64,
    }


def _run(arm: str, *, tier: str, identity: dict | None = None, source_commit: str = "a" * 40) -> dict:
    dense = arm == "A1"
    return _with_self_digest({
        "schema_version": "ember02-r1-e8-run-v1",
        "arm_id": arm,
        "tier": tier,
        "mechanism": "adamw-cpu-offload" if dense else "role-prior-sparse",
        "status": "TERMINAL",
        "certified_launch_sha256": "6" * 64,
        "source_commit": source_commit,
        "architecture_revision": "ember-dense-3b-a1-v1" if dense else "ember-sparse-3b-v2",
        "parameter_count": 3_839_000_000,
        "active_parameter_count": 3_839_000_000 if dense else 1_021_000_000,
        "contains_router_or_experts": not dense,
        "optimizer": {
            "kind": "AdamW", "full_state": True, "cpu_offload": tier == "TIER1",
            "covered_parameter_count": 3_839_000_000,
        },
        "identity": identity if identity is not None else _identity(),
        "energy_sample_coverage": "0.960000000000",
        "checkpoint_sha256": "7" * 64,
    })


def _telemetry_row(step: int, run_id: str, *, tokens: int, wall_seconds: str, proxy_joules: str) -> dict:
    return {
        "ts": f"2026-08-21T00:{step // 60:02d}:{step % 60:02d}Z",
        "kind": "train_step",
        "source": "ember-restart-3b",
        "payload": {
            "run_id": run_id, "step": step, "loss": 1.0, "grad_norm": 1.0,
            "tokens": tokens, "wall_seconds": wall_seconds, "proxy_joules": proxy_joules,
        },
    }


def _write_telemetry(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _contract(*, comparison_id: str, tier1_sha: str, a3_sha: str, a1_tokens: str, a3_tokens: str = "1000") -> dict:
    return _with_self_digest({
        "schema_version": "ember02-r2-charged-budget-contract-v1",
        "status": "FROZEN",
        "comparison_id": comparison_id,
        "a1_run_sha256": tier1_sha,
        "a3_run_sha256": a3_sha,
        "projected_r2_tokens": {"a1": a1_tokens, "a3": a3_tokens},
    })


def _stage_run(tmp_path: Path, name: str, doc: dict) -> Path:
    path = tmp_path / "sources" / f"{name}.json"
    _write_json(path, doc)
    return path


def _sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# RED-matrix refusals
# ---------------------------------------------------------------------------

def test_missing_charged_budget_contract_is_evidence_missing_not_refused(tmp_path: Path) -> None:
    identity = _identity()
    tier1 = _run("A1", tier="TIER1", identity=identity)
    a3 = _run("A3", tier="A3", identity=identity)
    tier1_path = _stage_run(tmp_path, "tier1", tier1)
    a3_path = _stage_run(tmp_path, "a3", a3)
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    a3_tel = tmp_path / "a3-telemetry.jsonl"
    _write_telemetry(a1_tel, [_telemetry_row(1, "a1run", tokens=17, wall_seconds="5", proxy_joules="50")])
    _write_telemetry(a3_tel, [_telemetry_row(1, "a3run", tokens=50, wall_seconds="5", proxy_joules="25")])
    with pytest.raises(EVIDENCE.E8EvidenceProducerMissing, match="CHARGED_BUDGET_CONTRACT_MISSING"):
        EVIDENCE.mint_liveness_receipt(
            tmp_path / "packet",
            tier1_run_source=tier1_path, a3_run_source=a3_path,
            charged_budget_contract_source=tmp_path / "sources" / "absent-contract.json",
            a1_telemetry_path=a1_tel, a1_run_id="a1run",
            a3_telemetry_path=a3_tel, a3_run_id="a3run",
            thresholds_path=THRESHOLDS_PATH,
        )
    assert not (tmp_path / "packet").exists() or not list((tmp_path / "packet").glob("*liveness*.json")), \
        "a refused mint must leave no liveness receipt behind"
    real = VALIDATOR.validate_e8([tmp_path / "packet"], THRESHOLDS, THRESHOLDS_SHA)
    assert real["status"] == "EVIDENCE_MISSING", real
    assert "A1_LIVENESS_RECEIPT_MISSING" in real["detail"], real


def test_noncontiguous_telemetry_step_refuses(tmp_path: Path) -> None:
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    _write_telemetry(a1_tel, [
        _telemetry_row(1, "a1run", tokens=17, wall_seconds="5", proxy_joules="50"),
        _telemetry_row(3, "a1run", tokens=17, wall_seconds="5", proxy_joules="50"),
    ])
    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="noncontiguous"):
        EVIDENCE.derive_liveness_series(a1_tel, run_id="a1run", run_receipt_sha256="0" * 64)


def test_nonpositive_tokens_refuses(tmp_path: Path) -> None:
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    _write_telemetry(a1_tel, [_telemetry_row(1, "a1run", tokens=0, wall_seconds="5", proxy_joules="50")])
    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="tokens"):
        EVIDENCE.derive_liveness_series(a1_tel, run_id="a1run", run_receipt_sha256="0" * 64)


def test_negative_proxy_joules_refuses(tmp_path: Path) -> None:
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    _write_telemetry(a1_tel, [_telemetry_row(1, "a1run", tokens=17, wall_seconds="5", proxy_joules="-1")])
    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="proxy_joules"):
        EVIDENCE.derive_liveness_series(a1_tel, run_id="a1run", run_receipt_sha256="0" * 64)


def test_matched_identity_mismatch_refuses(tmp_path: Path) -> None:
    tier1 = _run("A1", tier="TIER1", identity=_identity(comparison_id="cmp-a"))
    a3 = _run("A3", tier="A3", identity=_identity(comparison_id="cmp-b"))
    tier1_path = _stage_run(tmp_path, "tier1", tier1)
    a3_path = _stage_run(tmp_path, "a3", a3)
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    a3_tel = tmp_path / "a3-telemetry.jsonl"
    _write_telemetry(a1_tel, [_telemetry_row(1, "a1run", tokens=17, wall_seconds="5", proxy_joules="50")])
    _write_telemetry(a3_tel, [_telemetry_row(1, "a3run", tokens=50, wall_seconds="5", proxy_joules="25")])
    contract_path = tmp_path / "sources" / "contract.json"
    _write_json(contract_path, _contract(
        comparison_id="cmp-a", tier1_sha=_sha_of(tier1_path), a3_sha=_sha_of(a3_path), a1_tokens="340",
    ))
    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="MATCHED_IDENTITY_MISMATCH"):
        EVIDENCE.mint_liveness_receipt(
            tmp_path / "packet",
            tier1_run_source=tier1_path, a3_run_source=a3_path,
            charged_budget_contract_source=contract_path,
            a1_telemetry_path=a1_tel, a1_run_id="a1run",
            a3_telemetry_path=a3_tel, a3_run_id="a3run",
            thresholds_path=THRESHOLDS_PATH,
        )


def test_tampered_run_receipt_self_digest_refuses(tmp_path: Path) -> None:
    tier1 = _run("A1", tier="TIER1")
    tier1["parameter_count"] = 4_000_000_000  # tamper after self-digest was minted
    tier1_path = _stage_run(tmp_path, "tier1", tier1)
    with pytest.raises(EVIDENCE.E8EvidenceProducerError, match="self-digest"):
        EVIDENCE.reopen_run_receipt(tier1_path, arm="A1")


# ---------------------------------------------------------------------------
# GREEN: real end-to-end packets through the REAL validator
# ---------------------------------------------------------------------------

def _stage_happy_packet(tmp_path: Path, *, a1_projected: str) -> tuple[Path, dict]:
    identity = _identity()
    tier1 = _run("A1", tier="TIER1", identity=identity)
    a3 = _run("A3", tier="A3", identity=identity)
    tier1_path = _stage_run(tmp_path, "tier1", tier1)
    a3_path = _stage_run(tmp_path, "a3", a3)
    tier1_sha = _sha_of(tier1_path)
    a3_sha = _sha_of(a3_path)
    a1_tel = tmp_path / "a1-telemetry.jsonl"
    a3_tel = tmp_path / "a3-telemetry.jsonl"
    _write_telemetry(a1_tel, [
        _telemetry_row(1, "a1run", tokens=170, wall_seconds="5", proxy_joules="50"),
        _telemetry_row(2, "a1run", tokens=170, wall_seconds="5", proxy_joules="50"),
    ])
    _write_telemetry(a3_tel, [
        _telemetry_row(1, "a3run", tokens=500, wall_seconds="5", proxy_joules="100"),
        _telemetry_row(2, "a3run", tokens=500, wall_seconds="5", proxy_joules="100"),
    ])
    contract_path = tmp_path / "sources" / "contract.json"
    _write_json(contract_path, _contract(
        comparison_id="r1-e8-a1-vs-a3", tier1_sha=tier1_sha, a3_sha=a3_sha, a1_tokens=a1_projected,
    ))
    packet_root = tmp_path / "packet"
    output = EVIDENCE.mint_liveness_receipt(
        packet_root,
        tier1_run_source=tier1_path, a3_run_source=a3_path,
        charged_budget_contract_source=contract_path,
        a1_telemetry_path=a1_tel, a1_run_id="a1run",
        a3_telemetry_path=a3_tel, a3_run_id="a3run",
        thresholds_path=THRESHOLDS_PATH,
    )
    return packet_root, json.loads(output.read_bytes())


def test_tier1_live_packet_reaches_real_met(tmp_path: Path) -> None:
    # ratio = 340/1000 = 0.34 >= T-08 (0.33) -> TIER1_LIVE, no parity needed.
    packet_root, doc = _stage_happy_packet(tmp_path, a1_projected="340")
    assert doc["schema_version"] == "ember02-r1-e8-liveness-v1"
    assert doc["verdict"] == "TIER1_LIVE"
    assert doc["measurements"]["equal_budget_ratio"] == "0.340000000000"
    unsigned = {k: v for k, v in doc.items() if k != "receipt_sha256"}
    assert doc["receipt_sha256"] == _canonical_sha(unsigned)

    real = VALIDATOR.validate_e8([packet_root], THRESHOLDS, THRESHOLDS_SHA)
    assert real["status"] == "MET", real
    assert real["components"]["parity"] == "NOT_REQUIRED", real


def test_fallback_required_packet_is_evidence_missing_without_parity(tmp_path: Path) -> None:
    # ratio = 300/1000 = 0.30 < T-08 (0.33) -> FALLBACK_REQUIRED; no parity receipt minted here.
    packet_root, doc = _stage_happy_packet(tmp_path, a1_projected="300")
    assert doc["verdict"] == "FALLBACK_REQUIRED"

    real = VALIDATOR.validate_e8([packet_root], THRESHOLDS, THRESHOLDS_SHA)
    assert real["status"] == "EVIDENCE_MISSING", real
    assert "PARITY_RECEIPT_MISSING" in real["detail"], real


def test_mint_refuses_to_overwrite_an_existing_packet(tmp_path: Path) -> None:
    packet_root, _doc = _stage_happy_packet(tmp_path, a1_projected="340")
    identity = _identity()
    tier1 = _run("A1", tier="TIER1", identity=identity)
    tier1_path = _stage_run(tmp_path, "tier1-again", tier1)
    with pytest.raises(FileExistsError):
        EVIDENCE._write_atomic_no_overwrite(packet_root / EVIDENCE.TIER1_FILENAME, b"{}")

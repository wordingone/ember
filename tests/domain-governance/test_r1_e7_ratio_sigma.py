# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _module():
    return importlib.import_module("r1_e7_ratio_sigma")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value) + b"\n")


def _write_telemetry(path: Path, *, run_id: str, gradients: list[float]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for step, gradient in enumerate(gradients, start=1):
            handle.write(json.dumps({
                "ts": f"2026-08-21T00:00:{step:02d}Z",
                "kind": "train_step",
                "source": "ember-restart-3b",
                "payload": {
                    "run_id": run_id,
                    "step": step,
                    "loss": 2.0 - step / 1000,
                    "grad_norm": gradient,
                },
            }, sort_keys=True) + "\n")


def test_normalized_ratio_sigma_is_analytic_and_seed_order_invariant() -> None:
    """Catches raw-norm sigma reuse, order dependence, and wrong pooling."""
    module = _module()
    series = {
        "seed-b": [{"step": 1, "grad_norm": 3.0}, {"step": 2, "grad_norm": 2.0}],
        "seed-a": [{"step": 1, "grad_norm": 1.0}, {"step": 2, "grad_norm": 2.0}],
    }
    result = module.normalized_grad_norm_ratio_sigma(series)
    assert result["sigma_seed"] == pytest.approx(math.sqrt(0.125))
    assert result["matched_step_count"] == 2
    assert result["seeds"] == ["seed-a", "seed-b"]
    assert result == module.normalized_grad_norm_ratio_sigma(dict(reversed(list(series.items()))))


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_normalized_ratio_sigma_refuses_nonpositive_or_nonfinite_norms(bad: float) -> None:
    """Catches admitting a zero denominator or non-finite F-11 authority."""
    module = _module()
    with pytest.raises(ValueError, match="positive finite"):
        module.normalized_grad_norm_ratio_sigma({
            "seed-a": [{"step": 1, "grad_norm": 1.0}],
            "seed-b": [{"step": 1, "grad_norm": bad}],
        })


def test_compose_e7_v2_binds_inputs_prereg_and_no_overwrite(tmp_path: Path) -> None:
    """Catches an unbound remint, prereg drift, or overwriting custody bytes."""
    module = _module()
    telemetry_a = tmp_path / "seed-a.jsonl"
    telemetry_b = tmp_path / "seed-b.jsonl"
    _write_telemetry(telemetry_a, run_id="seed-a", gradients=[1.0] * 100)
    _write_telemetry(telemetry_b, run_id="seed-b", gradients=[3.0] * 100)
    thresholds = ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json"
    prereg = {
        "document": "docs/domains/governance/spec/ember02-preregistration-v1.md",
        "pin": "3d48d3870919bd04cec735f68d0fad45fcfae0b2",
        "thresholds_sha256": _sha(thresholds),
    }
    v1 = tmp_path / "r1-e7-v1.json"
    _write_json(v1, {
        "ticket": "r1-exit-battery-e7",
        "schema": "r1-exit-battery/v1",
        "prereg": prereg,
        "exit_criterion": "R1-E7",
        "status": "MET",
        "result": {"sigma_seed": {"loss": {}, "grad_norm": {}}},
    })
    evidence_payload = {
        "schema": "issue1464-r1-e7-sigma-seed-evidence-v1",
        "authority": {"prereg_pin": prereg["pin"], "thresholds": {"sha256": _sha(thresholds)}},
        "canonical_composition_receipt": {"sha256": _sha(v1)},
        "replicas": [
            {"seed": 1, "run_root": "A:/custody/seed-a", "telemetry": {"path": str(telemetry_a), "sha256": _sha(telemetry_a), "bytes": telemetry_a.stat().st_size}},
            {"seed": 2, "run_root": "B:/custody/seed-b", "telemetry": {"path": str(telemetry_b), "sha256": _sha(telemetry_b), "bytes": telemetry_b.stat().st_size}},
        ],
    }
    evidence_payload["self_sha256"] = hashlib.sha256(_canonical(evidence_payload)).hexdigest()
    evidence = tmp_path / "evidence-v1.json"
    _write_json(evidence, evidence_payload)
    output = tmp_path / "v2"

    receipt_path, composition_path = module.compose_e7_v2(
        evidence_path=evidence,
        v1_receipt_path=v1,
        telemetry_paths=(telemetry_a, telemetry_b),
        thresholds_path=thresholds,
        output_dir=output,
    )
    receipt = json.loads(receipt_path.read_text("utf-8"))
    composition = json.loads(composition_path.read_text("utf-8"))
    assert receipt["prereg"] == prereg
    assert receipt["result"]["sigma_seed"]["grad_norm_ratio"]["sigma_seed"] == pytest.approx(0.5)
    assert receipt["result"]["sigma_seed"]["grad_norm"]["validator_input"] is False
    assert receipt["receipt_sha256"] == hashlib.sha256(_canonical({k: v for k, v in receipt.items() if k != "receipt_sha256"})).hexdigest()
    assert composition["inputs"]["evidence_v1_sha256"] == _sha(evidence)
    assert composition["outputs"]["e7_v2_raw_sha256"] == _sha(receipt_path)
    assert composition["self_sha256"] == hashlib.sha256(_canonical({k: v for k, v in composition.items() if k != "self_sha256"})).hexdigest()
    first = receipt_path.read_bytes(), composition_path.read_bytes()
    with pytest.raises(FileExistsError):
        module.compose_e7_v2(
            evidence_path=evidence,
            v1_receipt_path=v1,
            telemetry_paths=(telemetry_a, telemetry_b),
            thresholds_path=thresholds,
            output_dir=output,
        )
    assert first == (receipt_path.read_bytes(), composition_path.read_bytes())

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ember_restart" / "prediction_contract.py"
SHA = "a" * 64


def prediction_envelope(*, capability: str = "text", output: dict | None = None) -> dict:
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": SHA,
        "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {
            "id": "fixture",
            "version": "v1",
            "capability": capability,
            "split_sha256": "e" * 64,
            "protocol_sha256": "f" * 64,
        },
        "decoding": {
            "strategy": "GREEDY_AUTOREGRESSIVE",
            "teacher_forcing": False,
            "max_new_tokens": 32,
            "temperature": 0,
            "top_p": 1,
            "stop_token_ids": [2],
        },
        "rows": [
            {
                "id": "sample-1",
                "input_sha256": "1" * 64,
                "generated_token_ids": [7, 8],
                "stop_reason": "eos",
                "output": output or {"kind": "text", "text": "answer"},
            }
        ],
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(value) for value in args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_central_contract_remains_package_importable() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "from scripts.ember_restart import contract"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_validates_checkpoint_bound_autoregressive_predictions(tmp_path: Path) -> None:
    artifact = tmp_path / "predictions.json"
    write_json(artifact, prediction_envelope())

    result = run_cli("validate", artifact)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "benchmark_id": "fixture",
        "capability": "text",
        "checkpoint_manifest_sha256": SHA,
        "row_count": 1,
        "valid": True,
    }


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value["decoding"].update(teacher_forcing=True), "teacher_forcing"),
        (lambda value: value["decoding"].update(strategy="TEACHER_FORCED_ARGMAX"), "strategy"),
        (lambda value: value["rows"].append(copy.deepcopy(value["rows"][0])), "duplicate id"),
        (lambda value: value["rows"][0].update(generated_token_ids=[]), "generated_token_ids"),
        (lambda value: value.update(checkpoint_manifest_sha256="not-a-hash"), "checkpoint_manifest_sha256"),
        (lambda value: value.update(extra="fail-open"), "unexpected field"),
    ],
)
def test_rejects_unbound_or_non_autoregressive_artifacts(
    tmp_path: Path, mutate, error: str
) -> None:
    value = prediction_envelope()
    mutate(value)
    artifact = tmp_path / "predictions.json"
    write_json(artifact, value)

    result = run_cli("validate", artifact)

    assert result.returncode == 1
    assert error in result.stderr


@pytest.mark.parametrize(
    ("capability", "output", "adapter", "expected"),
    [
        ("text", {"kind": "text", "text": "A"}, "text", [{"id": "sample-1", "answer": "A"}]),
        (
            "reasoning",
            {"kind": "text", "text": "42"},
            "reasoning",
            [{"id": "sample-1", "answer": "42"}],
        ),
        (
            "audio",
            {"kind": "transcript", "text": "hello"},
            "audio",
            [{"id": "sample-1", "transcript": "hello"}],
        ),
        ("image", {"kind": "choice", "value": "B"}, "mmmu", [{"id": "sample-1", "prediction": "B"}]),
        ("tool", {"kind": "sql", "sql": "SELECT 1"}, "spider", [{"index": 0, "sql": "SELECT 1"}]),
        (
            "tool",
            {"kind": "tool_call", "name": "lookup", "arguments": {"city": "Paris"}},
            "tool",
            {"sample-1": {"name": "lookup", "arguments": {"city": "Paris"}}},
        ),
    ],
)
def test_materializes_exact_frozen_scorer_inputs(
    tmp_path: Path,
    capability: str,
    output: dict,
    adapter: str,
    expected: object,
) -> None:
    artifact = tmp_path / "predictions.json"
    materialized = tmp_path / "scorer-input.json"
    write_json(artifact, prediction_envelope(capability=capability, output=output))

    result = run_cli("materialize", artifact, "--adapter", adapter, "--output", materialized)

    assert result.returncode == 0, result.stderr
    assert json.loads(materialized.read_text(encoding="utf-8")) == expected


def test_adapter_cannot_reinterpret_capability_or_output_kind(tmp_path: Path) -> None:
    artifact = tmp_path / "predictions.json"
    materialized = tmp_path / "scorer-input.json"
    write_json(artifact, prediction_envelope(capability="text"))

    result = run_cli("materialize", artifact, "--adapter", "audio", "--output", materialized)

    assert result.returncode == 1
    assert "adapter audio requires capability audio" in result.stderr
    assert not materialized.exists()

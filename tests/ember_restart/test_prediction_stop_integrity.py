# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ember_restart" / "prediction_contract.py"
SHA = "a" * 64


def envelope() -> dict:
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
            "capability": "text",
            "split_sha256": "e" * 64,
            "protocol_sha256": "f" * 64,
        },
        "decoding": {
            "strategy": "GREEDY_AUTOREGRESSIVE",
            "teacher_forcing": False,
            "max_new_tokens": 4,
            "temperature": 0,
            "top_p": 1,
            "stop_token_ids": [2],
        },
        "rows": [
            {
                "id": "sample-1",
                "input_sha256": "1" * 64,
                "generated_token_ids": [7, 2],
                "stop_reason": "eos",
                "output": {"kind": "text", "text": "answer"},
            }
        ],
    }


def validate(tmp_path: Path, value: dict) -> subprocess.CompletedProcess[str]:
    artifact = tmp_path / "predictions.json"
    artifact.write_text(json.dumps(value), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(artifact)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda value: value["decoding"].update(stop_token_ids=[32_000]),
            "stop_token_ids",
        ),
        (
            lambda value: value["rows"][0].update(generated_token_ids=[7, 32_000]),
            "generated_token_ids",
        ),
        (
            lambda value: value["rows"][0].update(
                generated_token_ids=[7, 8], stop_reason="eos"
            ),
            "last generated token",
        ),
        (
            lambda value: value["rows"][0].update(
                generated_token_ids=[7, 8], stop_reason="max_new_tokens"
            ),
            "max_new_tokens stop requires exactly",
        ),
    ],
)
def test_rejects_out_of_vocab_ids_or_inconsistent_stop_evidence(
    tmp_path: Path, mutate, error: str
) -> None:
    value = envelope()
    mutate(value)

    result = validate(tmp_path, value)

    assert result.returncode == 1
    assert error in result.stderr

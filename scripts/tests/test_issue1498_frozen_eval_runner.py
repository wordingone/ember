# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.r1_frozen_eval_runner import (
    FrozenEvalRefusal,
    _canonical_bytes,
    _checkpoint_identity,
    _load_suite,
    _probe_results,
    execute_frozen_eval,
    validate_results_receipt,
)


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SUITE = ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json"
_AUTHORITY = json.loads(CANONICAL_SUITE.read_text(encoding="utf-8"))
_DEFAULT_OUTPUTS = {row["row_id"]: row["expected_output"] for row in _AUTHORITY["tasks"]}


def _raw_json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, dict]:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    shard = checkpoint / "shared-model.pt"
    shard.write_bytes(b"SELFTEST_FIXTURE_MODEL_BYTES")
    shard_sha = hashlib.sha256(shard.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "ember-sparse-checkpoint-v5",
        "shards": [{"role": "shared_model", "path": shard.name, "sha256": shard_sha}],
        "shared_model_shard_sha256": shard_sha,
    }
    manifest_path = checkpoint / "checkpoint-manifest.json"
    manifest_path.write_bytes(_raw_json(manifest))
    suite_path = tmp_path / "suite.json"
    suite_path.write_bytes(CANONICAL_SUITE.read_bytes())
    suite_sha = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    _, suite = _load_suite(suite_path, suite_sha)
    return checkpoint, suite_path, suite_sha, suite


class _Transport:
    def __init__(self, manifest_sha: str, outputs: dict[str, str] | None = None):
        self.identity = {
            "mode": "FROZEN_EVAL",
            "seat": "OWNED_ADMITTED",
            "checkpoint_sha256": manifest_sha,
            "model_name": f"ember-owned:{manifest_sha[:12]}",
            "model_config_sha256": "a" * 64,
            "tokenizer_sha256": "b" * 64,
            "server_source_sha256": "c" * 64,
        }
        self.outputs = outputs or _DEFAULT_OUTPUTS
        self.requests: list[dict] = []

    def get_json(self, url: str) -> dict:
        assert url.endswith("/v1/models")
        return dict(self.identity)

    def post_json(self, url: str, payload: dict) -> dict:
        assert url.endswith("/v1/chat/completions")
        self.requests.append(payload)
        row_id = payload["ember_frozen_row_id"]
        return {
            "model": self.identity["model_name"],
            "choices": [{"message": {"role": "assistant", "content": self.outputs[row_id]}}],
            "owned_identity": {key: value for key, value in self.identity.items() if key != "mode"},
        }


def test_owned_frozen_eval_binds_suite_checkpoint_and_exact_rows(tmp_path: Path):
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    manifest_sha = hashlib.sha256((checkpoint / "checkpoint-manifest.json").read_bytes()).hexdigest()
    transport = _Transport(manifest_sha)
    out = tmp_path / "run"

    receipt = execute_frozen_eval(
        suite_path=suite_path,
        expected_suite_sha256=suite_sha,
        checkpoint_dir=checkpoint,
        endpoint="http://127.0.0.1:8173",
        output_dir=out,
        transport=transport,
    )

    assert (out / "frozen-eval-suite.json").read_bytes() == suite_path.read_bytes()
    assert json.loads((out / "frozen-eval-results.json").read_text()) == receipt
    assert receipt["eval_suite_id"] == suite["eval_suite_id"]
    assert receipt["eval_suite_sha256"] == suite_sha
    assert receipt["checkpoint_manifest_sha256"] == manifest_sha
    assert receipt["checkpoint_file_sha256s"] == {
        "shared_model": hashlib.sha256((checkpoint / "shared-model.pt").read_bytes()).hexdigest()
    }
    assert receipt["results"] == {
        "mmlu-pro-10choice": {
            "value": 1.0,
            "n_items": 32,
            "correct": 32,
            "minimum_correct": 6,
            "chance_rate": 0.1,
            "passed": True,
        },
        "arc-challenge-4choice": {
            "value": 1.0,
            "n_items": 32,
            "correct": 32,
            "minimum_correct": 13,
            "chance_rate": 0.25,
            "passed": True,
        },
    }
    assert receipt["tool_access"] == "none"
    assert receipt["execution_claim"] is True
    assert receipt["result_credit"] is False
    assert [request["ember_frozen_row_id"] for request in transport.requests] == [
        row["row_id"] for row in suite["tasks"]
    ]
    assert [request["ember_context_limit_tokens"] for request in transport.requests] == [4096] * 64
    assert all("tools" not in request and request["stream"] is False for request in transport.requests)


def test_probe_results_are_adjudicated_independently(tmp_path: Path) -> None:
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    manifest_sha = hashlib.sha256((checkpoint / "checkpoint-manifest.json").read_bytes()).hexdigest()
    outputs = dict(_DEFAULT_OUTPUTS)
    mmlu_rows = [row for row in suite["tasks"] if row["probe_id"] == "mmlu-pro-10choice"]
    arc_rows = [row for row in suite["tasks"] if row["probe_id"] == "arc-challenge-4choice"]
    for row in mmlu_rows[5:]:
        outputs[row["row_id"]] = "Z"
    for row in arc_rows[14:]:
        outputs[row["row_id"]] = "Z"

    receipt = execute_frozen_eval(
        suite_path=suite_path,
        expected_suite_sha256=suite_sha,
        checkpoint_dir=checkpoint,
        endpoint="http://127.0.0.1:8173",
        output_dir=tmp_path / "run",
        transport=_Transport(manifest_sha, outputs),
    )

    assert receipt["results"]["mmlu-pro-10choice"] == {
        "value": 5 / 32,
        "n_items": 32,
        "correct": 5,
        "minimum_correct": 6,
        "chance_rate": 0.1,
        "passed": False,
    }
    assert receipt["results"]["arc-challenge-4choice"] == {
        "value": 14 / 32,
        "n_items": 32,
        "correct": 14,
        "minimum_correct": 13,
        "chance_rate": 0.25,
        "passed": True,
    }


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda receipt: receipt.pop("schema"), "RESULT_RECEIPT_SCHEMA_INVALID"),
        (
            lambda receipt: receipt["rows"][0].update(row_id="foreign-row"),
            "RESULT_RECEIPT_ROWS_INVALID",
        ),
        (
            lambda receipt: receipt.update(receipt_sha256="f" * 64),
            "RESULT_RECEIPT_SELF_HASH_INVALID",
        ),
    ],
)
def test_result_receipt_validator_refuses_schema_row_or_self_hash_tamper(
    tmp_path: Path, mutation, code: str
) -> None:
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    manifest_sha, checkpoint_hashes = _checkpoint_identity(checkpoint)
    receipt = execute_frozen_eval(
        suite_path=suite_path,
        expected_suite_sha256=suite_sha,
        checkpoint_dir=checkpoint,
        endpoint="http://127.0.0.1:8173",
        output_dir=tmp_path / "run",
        transport=_Transport(manifest_sha),
    )
    tampered = deepcopy(receipt)
    mutation(tampered)

    with pytest.raises(FrozenEvalRefusal, match=code):
        validate_results_receipt(
            tampered,
            suite=suite,
            suite_sha256=suite_sha,
            checkpoint_manifest_sha256=manifest_sha,
            checkpoint_file_sha256s=checkpoint_hashes,
        )


def test_result_receipt_recomputes_passed_from_bound_output_after_self_hash_remint(tmp_path: Path) -> None:
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    manifest_sha, checkpoint_hashes = _checkpoint_identity(checkpoint)
    outputs = dict(_DEFAULT_OUTPUTS)
    outputs[suite["tasks"][0]["row_id"]] = "Z"
    receipt = execute_frozen_eval(
        suite_path=suite_path,
        expected_suite_sha256=suite_sha,
        checkpoint_dir=checkpoint,
        endpoint="http://127.0.0.1:8173",
        output_dir=tmp_path / "run",
        transport=_Transport(manifest_sha, outputs),
    )
    assert receipt["rows"][0]["passed"] is False
    tampered = deepcopy(receipt)
    tampered["rows"][0]["passed"] = True
    tampered["results"] = _probe_results(suite, tampered["rows"])
    tampered["receipt_sha256"] = hashlib.sha256(
        _canonical_bytes(tampered, omit="receipt_sha256")
    ).hexdigest()

    with pytest.raises(FrozenEvalRefusal, match="RESULT_RECEIPT_ROWS_INVALID"):
        validate_results_receipt(
            tampered,
            suite=suite,
            suite_sha256=suite_sha,
            checkpoint_manifest_sha256=manifest_sha,
            checkpoint_file_sha256s=checkpoint_hashes,
        )


def test_output_persistence_is_bounded_before_publication(tmp_path: Path) -> None:
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    manifest_sha, _ = _checkpoint_identity(checkpoint)
    outputs = dict(_DEFAULT_OUTPUTS)
    outputs[suite["tasks"][0]["row_id"]] = "x" * 4097
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="RESPONSE_OUTPUT_TOO_LARGE"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=suite_sha,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=_Transport(manifest_sha, outputs),
        )
    assert not out.exists()


@pytest.mark.parametrize(
    "endpoint",
    ["https://127.0.0.1:8173", "http://localhost:8173", "http://10.0.0.2:8173", "http://user@127.0.0.1:8173"],
)
def test_foreign_or_credentialed_endpoint_refuses_without_output(tmp_path: Path, endpoint: str):
    checkpoint, suite_path, suite_sha, _ = _fixture(tmp_path)
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="ENDPOINT_NOT_OWNED_LOOPBACK"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=suite_sha,
            checkpoint_dir=checkpoint,
            endpoint=endpoint,
            output_dir=out,
            transport=_Transport("0" * 64),
        )
    assert not out.exists()


def test_loaded_checkpoint_identity_mismatch_refuses_without_output(tmp_path: Path):
    checkpoint, suite_path, suite_sha, _ = _fixture(tmp_path)
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="ENDPOINT_CHECKPOINT_MISMATCH"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=suite_sha,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=_Transport("0" * 64),
        )
    assert not out.exists()


def test_checkpoint_shard_tamper_refuses_before_endpoint_or_output(tmp_path: Path):
    checkpoint, suite_path, suite_sha, _ = _fixture(tmp_path)
    (checkpoint / "shared-model.pt").write_bytes(b"TAMPERED")
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="CHECKPOINT_SHARD_SHA_MISMATCH"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=suite_sha,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=_Transport("0" * 64),
        )
    assert not out.exists()


def test_suite_hash_or_closed_policy_drift_refuses_without_output(tmp_path: Path):
    checkpoint, suite_path, suite_sha, suite = _fixture(tmp_path)
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="EVAL_SUITE_SHA_MISMATCH"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256="0" * 64,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=_Transport("0" * 64),
        )
    authority = json.loads(suite_path.read_text(encoding="utf-8"))
    authority["retry_policy"]["max_attempts"] = 2
    suite_path.write_bytes(_raw_json(authority))
    drift_sha = hashlib.sha256(suite_path.read_bytes()).hexdigest()
    with pytest.raises(FrozenEvalRefusal, match="EVAL_SUITE_SCHEMA_INVALID"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=drift_sha,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=_Transport("0" * 64),
        )
    assert not out.exists()


def test_response_identity_and_shape_are_fail_closed(tmp_path: Path):
    checkpoint, suite_path, suite_sha, _ = _fixture(tmp_path)
    manifest_sha = hashlib.sha256((checkpoint / "checkpoint-manifest.json").read_bytes()).hexdigest()
    transport = _Transport(manifest_sha)
    original = transport.post_json

    def bad_post(url: str, payload: dict) -> dict:
        response = original(url, payload)
        response["owned_identity"]["checkpoint_sha256"] = "f" * 64
        return response

    transport.post_json = bad_post
    out = tmp_path / "run"
    with pytest.raises(FrozenEvalRefusal, match="RESPONSE_IDENTITY_MISMATCH"):
        execute_frozen_eval(
            suite_path=suite_path,
            expected_suite_sha256=suite_sha,
            checkpoint_dir=checkpoint,
            endpoint="http://127.0.0.1:8173",
            output_dir=out,
            transport=transport,
        )
    assert not out.exists()

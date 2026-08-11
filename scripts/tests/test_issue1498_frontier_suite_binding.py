# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import frontier_receipt as frontier  # noqa: E402
import r1_exit_battery as battery  # noqa: E402
import r1_frozen_eval_runner as runner  # noqa: E402


CANONICAL_SUITE = json.loads(
    (ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json").read_text(encoding="utf-8")
)
SUITE_ID = CANONICAL_SUITE["suite_id"]


def _write_json(path: Path, value: dict) -> str:
    raw = (
        (ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json").read_bytes()
        if value == CANONICAL_SUITE
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _checkpoint(tmp_path: Path) -> tuple[Path, dict]:
    shard_path = tmp_path / "shared-model.pt"
    shard_path.write_bytes(b"owned-checkpoint-bytes")
    shard_sha = hashlib.sha256(shard_path.read_bytes()).hexdigest()
    manifest = {
        "shared_model_shard_sha256": shard_sha,
        "shards": [
            {
                "role": "shared_model",
                "path": shard_path.name,
                "sha256": shard_sha,
            }
        ],
    }
    manifest_path = tmp_path / "checkpoint-manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path, manifest


def _results(tmp_path: Path, manifest_path: Path, suite_sha256: str) -> Path:
    path = tmp_path / "frozen-eval-results.json"
    suite_path = tmp_path / "frozen-eval-suite.json"
    authority = (
        json.loads(suite_path.read_text(encoding="utf-8"))
        if suite_path.exists()
        else {}
    )
    try:
        _raw, suite = runner._load_suite(suite_path, suite_sha256)
    except runner.FrozenEvalRefusal:
        suite = {}
    if isinstance(suite.get("tasks"), list) and suite["tasks"]:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        rows = [
            {
                "row_id": task["row_id"],
                "judge": task["judge"],
                "passed": True,
                "output": task["expected_output"],
                "output_sha256": hashlib.sha256(
                    task["expected_output"].encode("utf-8")
                ).hexdigest(),
            }
            for task in suite["tasks"]
        ]
        receipt = {
            "schema": runner.RESULT_SCHEMA,
            "eval_suite_id": suite["eval_suite_id"],
            "eval_suite_sha256": suite_sha256,
            "checkpoint_manifest_sha256": checkpoint_sha,
            "checkpoint_file_sha256s": {
                row["role"]: row["sha256"] for row in manifest["shards"]
            },
            "owned_identity": {
                "seat": "OWNED_ADMITTED",
                "checkpoint_sha256": checkpoint_sha,
                "model_name": f"ember-owned:{checkpoint_sha[:12]}",
                "model_config_sha256": "b" * 64,
                "tokenizer_sha256": "c" * 64,
                "server_source_sha256": "d" * 64,
            },
            "rows": rows,
            "results": runner._probe_results(suite, rows),
            "tool_access": "none",
            "retry_count": 0,
            "execution_claim": True,
            "result_credit": False,
            "claim_boundary": runner._CLAIM_BOUNDARY,
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            runner._canonical_bytes(receipt, omit="receipt_sha256")
        ).hexdigest()
    else:
        receipt = {
            "eval_suite_id": authority.get("suite_id", SUITE_ID),
            "eval_suite_sha256": suite_sha256,
            "checkpoint_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "results": {"invented": {"value": 1.0}},
            "tool_access": "none",
        }
    _write_json(path, receipt)
    return path


def _suite(eval_suite_id: str = SUITE_ID) -> dict:
    suite = deepcopy(CANONICAL_SUITE)
    suite["suite_id"] = eval_suite_id
    return suite


def test_capability_reopens_and_hashes_the_frozen_suite(tmp_path: Path) -> None:
    manifest_path, manifest = _checkpoint(tmp_path)
    suite_path = tmp_path / "frozen-eval-suite.json"
    suite_sha256 = _write_json(
        suite_path,
        _suite(),
    )
    _results(tmp_path, manifest_path, suite_sha256)

    result = frontier.leg_capability(tmp_path, manifest_path, manifest)

    assert result["eval_suite_sha256"] == suite_sha256
    assert result["eval_suite_path"] == str(suite_path)


def test_forged_or_missing_frozen_suite_bytes_refuse(tmp_path: Path) -> None:
    manifest_path, manifest = _checkpoint(tmp_path)
    _results(tmp_path, manifest_path, "f" * 64)

    with pytest.raises(frontier.FrontierRefusal, match="EVAL_SUITE_BYTES_UNBOUND"):
        frontier.leg_capability(tmp_path, manifest_path, manifest)


def test_minimal_self_consistent_result_receipt_refuses(tmp_path: Path) -> None:
    manifest_path, manifest = _checkpoint(tmp_path)
    suite_sha256 = _write_json(tmp_path / "frozen-eval-suite.json", _suite())
    _write_json(
        tmp_path / "frozen-eval-results.json",
        {
            "eval_suite_id": SUITE_ID,
            "eval_suite_sha256": suite_sha256,
            "checkpoint_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "results": {"invented": {"value": 1.0}},
            "tool_access": "none",
        },
    )

    with pytest.raises(frontier.FrontierRefusal, match="RESULT_RECEIPT_SCHEMA_INVALID"):
        frontier.leg_capability(tmp_path, manifest_path, manifest)


def test_hash_matching_but_malformed_or_relabelled_suite_refuses(tmp_path: Path) -> None:
    manifest_path, manifest = _checkpoint(tmp_path)
    suite_path = tmp_path / "frozen-eval-suite.json"
    for suite in (
        {"schema": "r1-cheap-probe-freeze/v1"},
        {
            "schema": "r1-cheap-probe-freeze/v1",
            "issue": 1498,
            "eval_suite_id": "foreign-suite",
            "tool_access": "NONE",
        },
        {
            "schema": "r1-cheap-probe-freeze/v1",
            "issue": 1498,
            "eval_suite_id": "r1-cheap-probe-v1",
            "tool_access": "SHELL",
        },
    ):
        suite_sha256 = _write_json(suite_path, suite)
        _results(tmp_path, manifest_path, suite_sha256)
        with pytest.raises(frontier.FrontierRefusal, match="EVAL_SUITE_SCHEMA_INVALID"):
            frontier.leg_capability(tmp_path, manifest_path, manifest)

    suite_path = tmp_path / "frozen-eval-suite.json"
    _write_json(suite_path, {"schema": "r1-cheap-probe-freeze/v1"})
    with pytest.raises(frontier.FrontierRefusal, match="EVAL_SUITE_SCHEMA_INVALID"):
        frontier.leg_capability(tmp_path, manifest_path, manifest)


def test_r1_battery_independently_rederives_suite_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(battery, "_evidence_excluded", lambda _path, _root: False)
    suite_path = tmp_path / "frozen-eval-suite.json"
    suite_sha256 = _write_json(
        suite_path,
        _suite(),
    )
    capability = {
        "eval_suite_id": SUITE_ID,
        "eval_suite_path": str(suite_path),
        "eval_suite_sha256": suite_sha256,
    }
    eval_doc = {
        "eval_suite_id": SUITE_ID,
        "eval_suite_sha256": suite_sha256,
    }

    assert battery._validate_frozen_eval_suite_binding(
        tmp_path, capability, eval_doc
    ) == []

    capability["eval_suite_sha256"] = "f" * 64
    defects = battery._validate_frozen_eval_suite_binding(
        tmp_path, capability, eval_doc
    )
    assert any("does not match frozen suite bytes" in item for item in defects)

    suite_path.unlink()
    defects = battery._validate_frozen_eval_suite_binding(
        tmp_path, capability, eval_doc
    )
    assert defects == [
        "capability: need exactly one frozen-eval-suite.json under the run root, found 0"
    ]

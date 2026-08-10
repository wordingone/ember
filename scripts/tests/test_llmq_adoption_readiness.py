# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.llmq_adoption_readiness import assess


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "scripts/llmq_adoption_readiness.py"
SOURCE_FILE = REPO_ROOT / SOURCE_PATH
SOURCE_SHA = hashlib.sha256(SOURCE_FILE.read_bytes()).hexdigest()
DESIGN_PATH = "docs/spec/llmq/adoption-design-v1.md"
DESIGN_FILE = REPO_ROOT / DESIGN_PATH
DESIGN_SHA = hashlib.sha256(DESIGN_FILE.read_bytes()).hexdigest()
MECHANISM_PATH = "docs/spec/llmq/mechanism-attribution-v1.md"
MECHANISM_FILE = REPO_ROOT / MECHANISM_PATH
MECHANISM_SHA = hashlib.sha256(MECHANISM_FILE.read_bytes()).hexdigest()


def _write_closed_json(path: Path, payload: dict, self_field: str = "receipt_sha256") -> str:
    unsigned = {key: value for key, value in payload.items() if key != self_field}
    payload[self_field] = hashlib.sha256(
        (json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _closed_packet(tmp_path: Path, include_benchmark: bool = True) -> tuple[Path, dict]:
    root = tmp_path / "llmq-packet"
    source_file = root / SOURCE_PATH
    source_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_FILE, source_file)
    design_file = root / DESIGN_PATH
    design_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DESIGN_FILE, design_file)
    mechanism_file = root / MECHANISM_PATH
    mechanism_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MECHANISM_FILE, mechanism_file)
    source_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
    design_sha = hashlib.sha256(design_file.read_bytes()).hexdigest()
    mechanism_sha = hashlib.sha256(mechanism_file.read_bytes()).hexdigest()
    commit = "0123456789abcdef0123456789abcdef01234567"
    tree_sha = "a" * 64
    source_manifest_path = root / "receipts/source-manifest.json"
    source_manifest_sha = _write_closed_json(
        source_manifest_path,
        {
            "schema": "ember-llmq-source-manifest-v1",
            "commit": commit,
            "tree_sha256": tree_sha,
            "source_path": SOURCE_PATH,
            "source_sha256": source_sha,
            "command": ["git", "archive", commit],
        },
        self_field="manifest_sha256",
    )
    binary_path = root / "artifacts/llmq-trainer.bin"
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_bytes(b"governed-llmq-binary\n")
    binary_sha = hashlib.sha256(binary_path.read_bytes()).hexdigest()
    build_path = root / "receipts/build.json"
    build_receipt = {
        "schema": "ember-llmq-build-receipt-v1",
        "status": "PASS",
        "source_commit": commit,
        "source_tree_sha256": tree_sha,
        "source_sha256": source_sha,
        "binary_path": "artifacts/llmq-trainer.bin",
        "binary_sha256": binary_sha,
        "command": ["llmq-build", "--source-commit", commit],
    }
    build_sha = _write_closed_json(build_path, build_receipt)
    payload = {
        "schema": "ember-llmq-adoption-readiness-v1",
        "llmq_dev_commit": commit,
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": source_sha,
        "source_manifest_path": "receipts/source-manifest.json",
        "source_manifest_sha256": source_manifest_sha,
        "build_receipt_path": "receipts/build.json",
        "build_receipt_sha256": build_sha,
        "adoption_design_sha256": design_sha,
        "adoption_design_path": DESIGN_PATH,
        "mechanism_attribution_sha256": mechanism_sha,
        "mechanism_attribution_path": MECHANISM_PATH,
    }
    if include_benchmark:
        benchmark_path = root / "receipts/benchmark.json"
        benchmark_sha = _write_closed_json(
            benchmark_path,
            {
                "schema": "ember-4090-3b-benchmark-receipt-v1",
                "hardware": "RTX 4090",
                "status": "PASS",
                "model": "Qwen2.5-3B",
                "source_commit": commit,
                "source_tree_sha256": tree_sha,
                "build_receipt_sha256": build_sha,
                "command": ["python", "benchmarks/4090x1.md"],
                "fp8_tok_s": 10568.0,
                "bf16_tok_s": 7001.0,
            },
        )
        payload["benchmark_receipt_path"] = "receipts/benchmark.json"
        payload["benchmark_receipt_sha256"] = benchmark_sha
    return root, payload


def test_missing_pinned_llmq_and_4090_evidence_is_fail_closed():
    result = assess(Path("."), {})
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "llmq_dev_commit" in result["missing"]
    assert "llmq_source_path" in result["missing"]
    assert "build_receipt" in result["missing"]
    assert "adoption_design_sha256" in result["missing"]
    assert "adoption_design_path" in result["missing"]
    assert "mechanism_attribution_sha256" in result["missing"]
    assert "mechanism_attribution_path" in result["missing"]
    assert "benchmark_receipt" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False
    assert result["rollback"] == "discard readiness artifact; no product state changed"
    assert result["external_remainder"] == [
        "pinned LLMQ source commit/tree manifest and source bytes",
        "governed LLMQ build receipt and binary bytes",
        "frozen adoption design bytes",
        "mechanism attribution bytes",
        "owned RTX 4090 x1 3B benchmark receipt",
    ]


def test_partial_source_and_build_receipt_exposes_external_benchmark_remainder(tmp_path):
    root, payload = _closed_packet(tmp_path, include_benchmark=False)
    result = assess(root, payload)
    assert result["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert result["missing"] == ["benchmark_receipt"]
    assert result["source_root"] == "CURRENT_REPOSITORY_SOURCE_ONLY"
    assert result["execution_claim"] is False
    assert result["result_credit"] is False
    assert result["external_remainder"] == ["owned RTX 4090 x1 3B benchmark receipt"]


def test_inline_build_and_benchmark_receipts_are_refused(tmp_path):
    root, payload = _closed_packet(tmp_path)
    payload["build_receipt"] = {"schema": "ember-llmq-build-receipt-v1", "status": "PASS"}
    payload["benchmark_receipt"] = {
        "schema": "ember-4090-3b-benchmark-receipt-v1",
        "hardware": "RTX 4090",
        "status": "PASS",
        "model": "Qwen2.5-3B",
        "fp8_tok_s": 999999,
        "bf16_tok_s": 999999,
    }
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "build_receipt.inline_forbidden" in result["missing"]
    assert "benchmark_receipt.inline_forbidden" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_forged_source_commit_and_tree_lineage_is_refused(tmp_path):
    root, payload = _closed_packet(tmp_path)
    payload["llmq_dev_commit"] = "f" * 40
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "source_manifest.commit" in result["missing"]
    assert "build_receipt.source_commit" in result["missing"]
    assert "benchmark_receipt.source_commit" in result["missing"]
    assert result["execution_claim"] is False


def test_foreign_or_rehashed_receipt_artifacts_are_refused(tmp_path):
    root, payload = _closed_packet(tmp_path)
    payload["build_receipt_path"] = "..\\foreign-build.json"
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "build_receipt_path" in result["missing"]
    payload["build_receipt_path"] = "receipts/build.json"
    payload["build_receipt_sha256"] = "0" * 64
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "build_receipt_sha256" in result["missing"]
    assert result["result_credit"] is False
    payload["benchmark_receipt_path"] = "..\\foreign-benchmark.json"
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "benchmark_receipt_path" in result["missing"]
    payload["benchmark_receipt_path"] = "receipts/benchmark.json"
    payload["benchmark_receipt_sha256"] = "0" * 64
    result = assess(root, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "benchmark_receipt_sha256" in result["missing"]


def test_foreign_readiness_schema_is_refused_before_any_claim():
    result = assess(REPO_ROOT, {"schema": "foreign-readiness-v99"})
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "schema" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_unknown_readiness_field_is_refused_before_any_claim():
    result = assess(
        REPO_ROOT,
        {"schema": "ember-llmq-adoption-readiness-v1", "foreign_authority": True},
    )
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "unknown:foreign_authority" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_cli_writes_path_free_content_addressed_refusal():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/llmq_adoption_readiness.py",
            "--payload",
            "-",
            "--source-root",
            str(REPO_ROOT),
            "--out",
            "-",
        ],
        cwd=REPO_ROOT,
        input=json.dumps({"schema": "foreign-readiness-v99"}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 3
    receipt = json.loads(result.stdout)
    assert receipt["verdict"] == "PRELAUNCH_REJECTED"
    assert receipt["execution_claim"] is False
    assert receipt["result_credit"] is False
    assert "B:" not in result.stdout
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["receipt_sha256"] == hashlib.sha256(
        (json.dumps(unsigned, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


def test_source_bytes_are_reopened_and_rehashed_before_readiness():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": "0" * 64,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": SOURCE_SHA,
        },
        "adoption_design_sha256": DESIGN_SHA,
        "adoption_design_path": DESIGN_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
        "mechanism_attribution_path": MECHANISM_PATH,
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "source_sha256" in result["missing"]
    assert result["execution_claim"] is False


def test_source_path_escape_is_refused_before_readiness():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": "..\\foreign.py",
        "source_sha256": SOURCE_SHA,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": SOURCE_SHA,
        },
        "adoption_design_sha256": DESIGN_SHA,
        "adoption_design_path": DESIGN_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
        "mechanism_attribution_path": MECHANISM_PATH,
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "llmq_source_path" in result["missing"]


def test_design_and_mechanism_bytes_are_reopened_before_readiness():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_sha256": "b" * 64,
        },
        "adoption_design_path": DESIGN_PATH,
        "adoption_design_sha256": "0" * 64,
        "mechanism_attribution_path": MECHANISM_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "adoption_design_sha256" in result["missing"]


def test_binary_bytes_are_reopened_before_readiness():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": "0" * 64,
        },
        "adoption_design_path": DESIGN_PATH,
        "adoption_design_sha256": DESIGN_SHA,
        "mechanism_attribution_path": MECHANISM_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "build_receipt.binary_sha256" in result["missing"]


def test_same_bytes_through_reparse_path_are_refused_before_readiness(monkeypatch):
    from scripts import llmq_adoption_readiness as readiness

    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
    }
    monkeypatch.setattr(readiness, "_has_reparse_component", lambda _path, _root: True)
    result = readiness.assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "llmq_source_path" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_foreign_benchmark_hardware_is_refused_before_any_result_claim():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "source_sha256": "a" * 64,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "binary_sha256": "b" * 64,
        },
        "adoption_design_sha256": DESIGN_SHA,
        "mechanism_attribution_sha256": MECHANISM_SHA,
        "benchmark_receipt": {
            "schema": "ember-4090-3b-benchmark-receipt-v1",
            "hardware": "RTX 3090",
            "status": "PASS",
        },
    }
    result = assess(Path("fixture"), payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "benchmark_receipt.hardware" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_benchmark_receipt_requires_live_3b_measurement_fields():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": SOURCE_SHA,
        },
        "adoption_design_sha256": DESIGN_SHA,
        "adoption_design_path": DESIGN_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
        "mechanism_attribution_path": MECHANISM_PATH,
        "benchmark_receipt": {
            "schema": "ember-4090-3b-benchmark-receipt-v1",
            "hardware": "RTX 4090",
            "status": "REFUSED",
        },
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "benchmark_receipt.status" in result["missing"]
    assert "benchmark_receipt.model" in result["missing"]
    assert "benchmark_receipt.fp8_tok_s" in result["missing"]
    assert "benchmark_receipt.bf16_tok_s" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False


def test_benchmark_receipt_rejects_nonfinite_or_negative_measurements():
    payload = {
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": SOURCE_SHA,
        },
        "adoption_design_sha256": DESIGN_SHA,
        "adoption_design_path": DESIGN_PATH,
        "mechanism_attribution_sha256": MECHANISM_SHA,
        "mechanism_attribution_path": MECHANISM_PATH,
        "benchmark_receipt": {
            "schema": "ember-4090-3b-benchmark-receipt-v1",
            "hardware": "RTX 4090",
            "status": "PASS",
            "model": "Qwen2.5-3B",
            "fp8_tok_s": float("nan"),
            "bf16_tok_s": -1,
        },
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "benchmark_receipt.fp8_tok_s" in result["missing"]
    assert "benchmark_receipt.bf16_tok_s" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False

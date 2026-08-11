# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import hashlib
import os
import subprocess
from pathlib import Path

from scripts.llmq_adoption_readiness import assess


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "scripts/llmq_adoption_readiness.py"
SOURCE_SHA = hashlib.sha256((REPO_ROOT / SOURCE_PATH).read_bytes()).hexdigest()
DESIGN_PATH = "docs/spec/llmq/adoption-design-v1.md"
DESIGN_SHA = hashlib.sha256((REPO_ROOT / DESIGN_PATH).read_bytes()).hexdigest()
MECHANISM_PATH = "docs/spec/llmq/mechanism-attribution-v1.md"
MECHANISM_SHA = hashlib.sha256((REPO_ROOT / MECHANISM_PATH).read_bytes()).hexdigest()


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
    assert result["rollback"] == "discard scratch-only artifact; no product state changed"
    assert result["external_remainder"] == [
        "pinned LLMQ source commit and source bytes",
        "governed LLMQ build receipt and binary bytes",
        "frozen adoption design bytes",
        "mechanism attribution bytes",
        "owned RTX 4090 x1 3B benchmark receipt",
        "independently replayed governed LLMQ source receipt",
        "canonical Ember CLI -> Ember Lab build/dispatch receipt",
        "canonical Ember CLI -> Ember Lab benchmark log receipt",
    ]


def test_malformed_payload_type_is_structured_fail_closed_refusal():
    for payload in (None, [], "not-a-mapping"):
        result = assess(Path("."), payload)
        assert result["verdict"] == "PRELAUNCH_REJECTED"
        assert result["missing"] == ["payload"]
        assert result["execution_claim"] is False
        assert result["result_credit"] is False
        assert result["external_remainder"] == ["closed readiness payload"]


def test_partial_source_and_build_receipt_exposes_external_benchmark_remainder():
    payload = {
        "schema": "ember-llmq-adoption-readiness-v1",
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
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt" in result["missing"]
    assert "ember_lab_build_receipt" in result["missing"]
    assert "ember_lab_benchmark_receipt" in result["missing"]
    assert result["source_root"] == "SCRATCH_ONLY"
    assert result["execution_claim"] is False
    assert result["result_credit"] is False
    assert "owned RTX 4090 x1 3B benchmark receipt" in result["external_remainder"]
    assert "independently replayed governed LLMQ source receipt" in result["external_remainder"]
    assert "canonical Ember CLI -> Ember Lab build/dispatch receipt" in result["external_remainder"]
    assert "canonical Ember CLI -> Ember Lab benchmark log receipt" in result["external_remainder"]


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


def test_self_authored_source_build_and_benchmark_are_not_ready_evidence():
    """Caller-authored hashes/metrics must not mint readiness without authorities."""
    payload = {
        "schema": "ember-llmq-adoption-readiness-v1",
        "llmq_dev_commit": "0123456789abcdef0123456789abcdef01234567",
        "llmq_source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA,
        "source_tree_sha256": "a" * 64,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": "0123456789abcdef0123456789abcdef01234567",
            "source_sha256": SOURCE_SHA,
            "binary_path": SOURCE_PATH,
            "binary_sha256": SOURCE_SHA,
            "command": "invented-build-command",
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
            "fp8_tok_s": 10568,
            "bf16_tok_s": 7001,
            "command": "invented-benchmark-command",
        },
    }
    result = assess(REPO_ROOT, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt" in result["missing"]
    assert "ember_lab_build_receipt" in result["missing"]
    assert "ember_lab_benchmark_receipt" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False

def test_governed_source_and_build_expose_only_the_external_benchmark_remainder(tmp_path):
    """A real governed source/build chain may wait for the owned benchmark, but not fake it."""
    repo = tmp_path / "llmq-repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/IST-DASLab/llmq.git"], check=True)
    source = repo / "llmq.py"
    source.write_bytes(b"governed source bytes")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    subprocess.run(["git", "-C", str(repo), "add", "llmq.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "source"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "llmq-source-manifest-v1",
                "repo": "IST-DASLab/llmq",
                "commit": commit,
                "tree_sha256": tree,
                "source_path": "llmq-repo/llmq.py",
                "source_sha256": source_sha,
            }
        ),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    dispatch = tmp_path / "dispatch.json"
    dispatch.write_text(json.dumps({"schema": "ember-lab-dispatch-terminal-receipt-v1", "job_id": "job-1", "status": "PASS", "source_manifest_sha256": manifest_sha if "manifest_sha" in locals() else ""}), encoding="utf-8")
    dispatch_sha = hashlib.sha256(dispatch.read_bytes()).hexdigest()
    binary_manifest = tmp_path / "binary-manifest.json"
    binary_manifest.write_text(json.dumps({"schema": "ember-lab-binary-manifest-v1", "status": "PASS", "binary_sha256": source_sha}), encoding="utf-8")
    binary_manifest_sha = hashlib.sha256(binary_manifest.read_bytes()).hexdigest()
    design_dir = tmp_path / "fixtures"
    design_dir.mkdir()
    design = design_dir / "design.md"
    design.write_bytes(b"design")
    attribution = design_dir / "attribution.md"
    attribution.write_bytes(b"attribution")
    design_sha = hashlib.sha256(design.read_bytes()).hexdigest()
    attribution_sha = hashlib.sha256(attribution.read_bytes()).hexdigest()
    # Rewrite dispatch after the source manifest hash is known.
    dispatch.write_text(json.dumps({"schema": "ember-lab-dispatch-terminal-receipt-v1", "job_id": "job-1", "status": "PASS", "source_manifest_sha256": manifest_sha}), encoding="utf-8")
    dispatch_sha = hashlib.sha256(dispatch.read_bytes()).hexdigest()
    payload = {
        "schema": "ember-llmq-adoption-readiness-v1",
        "llmq_dev_commit": commit,
        "llmq_source_path": "llmq-repo/llmq.py",
        "source_sha256": source_sha,
        "build_receipt": {
            "schema": "ember-llmq-build-receipt-v1",
            "status": "PASS",
            "source_commit": commit,
            "source_sha256": source_sha,
            "binary_path": "llmq-repo/llmq.py",
            "binary_sha256": source_sha,
        },
        "governed_source_receipt": {
            "schema": "llmq-governed-source-receipt-v1",
            "status": "PASS",
            "authority": "governed-git-source",
            "repo": "IST-DASLab/llmq",
            "commit": commit,
            "tree_sha256": tree,
            "source_sha256": source_sha,
            "source_path": "llmq-repo/llmq.py",
            "source_manifest_path": "source-manifest.json",
            "source_manifest_sha256": manifest_sha,
            "verification": "git-commit-tree-replayed",
            "git_repo_path": "llmq-repo",
        },
        "ember_lab_build_receipt": {
            "schema": "ember-lab-build-receipt-v1",
            "status": "PASS",
            "authority": "ember-cli->ember-lab",
            "job_id": "job-1",
            "host_id": "host-1",
            "toolchain": "cuda-12",
            "exit_code": 0,
            "source_manifest_sha256": manifest_sha,
            "binary_sha256": source_sha,
            "dispatch_receipt_path": "dispatch.json",
            "dispatch_receipt_sha256": dispatch_sha,
            "binary_manifest_path": "binary-manifest.json",
            "binary_manifest_sha256": binary_manifest_sha,
        },
        "adoption_design_path": "fixtures/design.md",
        "adoption_design_sha256": design_sha,
        "mechanism_attribution_path": "fixtures/attribution.md",
        "mechanism_attribution_sha256": attribution_sha,
    }
    result = assess(tmp_path, payload)
    assert result["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert "ember_lab_benchmark_receipt" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False

    # Genuine RED: a caller may currently rewrite the manifest bytes and simply
    # recompute every receipt hash while leaving the rest of the packet unchanged.
    manifest.write_text(json.dumps({"commit": "0" * 40, "tree_sha256": "0" * 40}), encoding="utf-8")
    tampered_manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    dispatch.write_text(
        json.dumps(
            {
                "schema": "ember-lab-dispatch-terminal-receipt-v1",
                "job_id": "job-1",
                "status": "PASS",
                "source_manifest_sha256": tampered_manifest_sha,
            }
        ),
        encoding="utf-8",
    )
    tampered_dispatch_sha = hashlib.sha256(dispatch.read_bytes()).hexdigest()
    payload["governed_source_receipt"]["source_manifest_sha256"] = tampered_manifest_sha
    payload["ember_lab_build_receipt"]["source_manifest_sha256"] = tampered_manifest_sha
    payload["ember_lab_build_receipt"]["dispatch_receipt_sha256"] = tampered_dispatch_sha
    tampered = assess(tmp_path, payload)
    assert tampered["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.source_manifest_binding" in tampered["missing"]

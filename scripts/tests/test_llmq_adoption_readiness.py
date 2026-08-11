# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import json
import hashlib
import os
import shutil
import sqlite3
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


def test_live_daemon_assessment_requires_authenticated_pipe_and_exact_export(monkeypatch, tmp_path):
    from scripts import llmq_adoption_readiness as readiness

    source_sha = hashlib.sha256((REPO_ROOT / "runtime/ember-lab/src/lib.rs").read_bytes()).hexdigest()
    binary_sha = hashlib.sha256(b"resident-ember-lab-binary").hexdigest()
    canonical_binary = tmp_path / "canonical" / "ember-lab.exe"
    canonical_binary.parent.mkdir()
    canonical_binary.write_bytes(b"resident-ember-lab-binary")
    foreign_binary = tmp_path / "foreign" / "ember-lab.exe"
    foreign_binary.parent.mkdir()
    foreign_binary.write_bytes(b"foreign-self-consistent-server")
    identity = {"binary_sha256": binary_sha, "source_sha256": source_sha}
    receipt = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": identity,
        "job_id": "job-1",
        "identity_sha256": "a" * 64,
        "resource_lease": "GPU-1",
        "state": "exited",
        "pid": 123,
        "executable_identity": "llmq.exe",
        "restart_policy": "never",
        "exit_code": 0,
        "logs": {},
        "events": [{"kind": "job_started"}, {"kind": "job_exited"}],
        "outage_events": [],
        "scientific_capability_evidence": False,
    }
    stdout = b'{"mode":"fp8","tokens":1000,"elapsed_ms":100}\n'
    stderr = b""
    receipt["logs"] = {
        "stdout": {"file_name": "daemon.stdout.log", "sealed": True, "sha256": hashlib.sha256(stdout).hexdigest()},
        "stderr": {"file_name": "daemon.stderr.log", "sealed": True, "sha256": hashlib.sha256(stderr).hexdigest()},
    }
    schedule = {
        "schema_version": "ember-lab-schedule-alarm-state-v1",
        "ember_lab_identity": identity,
        "runs": [],
        "alarms": {},
    }

    def fake_rpc(pipe_name, job_id, directory):
        assert pipe_name == r"\\.\pipe\ember-lab-test"
        assert job_id == "job-1"
        directory.mkdir()
        values = {
            "operational_receipt": (json.dumps(receipt, indent=2, sort_keys=True).encode(), ".operational.json"),
            "stdout_log": (stdout, ".stdout.log"),
            "stderr_log": (stderr, ".stderr.log"),
            "schedule_alarm_state": (json.dumps(schedule, indent=2, sort_keys=True).encode(), ".schedule.json"),
        }
        result = {"schema": "ember-lab-assessment-evidence-v1", "ember_lab_identity": identity}
        for field, (raw, suffix) in values.items():
            digest = hashlib.sha256(raw).hexdigest()
            path = directory / f"{digest}{suffix}"
            path.write_bytes(raw)
            result[field] = {"path": str(path), "sha256": digest}
        return result, binary_sha, canonical_binary

    monkeypatch.setenv("EMBER_LAB_PIPE", r"\\.\pipe\ember-lab-test")
    monkeypatch.setattr(readiness, "_canonical_ember_lab_binary", lambda _: canonical_binary)
    monkeypatch.setattr(readiness, "_rpc_export_assessment", fake_rpc)
    live = readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1")
    assert live is not None
    assert live["operational_receipt"]["job_id"] == "job-1"
    assert live["stdout_bytes"] == stdout
    assert live["schedule_alarm_state"]["ember_lab_identity"] == identity

    monkeypatch.delenv("EMBER_LAB_PIPE")
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None
    monkeypatch.setenv("EMBER_LAB_PIPE", r"\\.\pipe\ember-lab-test")
    monkeypatch.setattr(readiness, "_rpc_export_assessment", lambda *_: (_ for _ in ()).throw(OSError("unreachable")))
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None

    def wrong_server(*args):
        result, _, _ = fake_rpc(*args)
        return result, "f" * 64, canonical_binary

    monkeypatch.setattr(readiness, "_rpc_export_assessment", wrong_server)
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None

    def foreign_self_consistent_server(*args):
        result, _, _ = fake_rpc(*args)
        foreign_sha = hashlib.sha256(foreign_binary.read_bytes()).hexdigest()
        result["ember_lab_identity"]["binary_sha256"] = foreign_sha
        return result, foreign_sha, foreign_binary

    monkeypatch.setattr(readiness, "_rpc_export_assessment", foreign_self_consistent_server)
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None

    def forged_file(*args):
        result, server_sha, server_path = fake_rpc(*args)
        Path(result["stdout_log"]["path"]).write_bytes(b"forged after export")
        return result, server_sha, server_path

    monkeypatch.setattr(readiness, "_rpc_export_assessment", forged_file)
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None

    def copied_outside_export(*args):
        result, server_sha, server_path = fake_rpc(*args)
        source = Path(result["stdout_log"]["path"])
        copied = tmp_path / source.name
        copied.write_bytes(source.read_bytes())
        result["stdout_log"]["path"] = str(copied)
        return result, server_sha, server_path

    monkeypatch.setattr(readiness, "_rpc_export_assessment", copied_outside_export)
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None

    def surrogate(*args):
        result, server_sha, server_path = fake_rpc(*args)
        path = Path(result["operational_receipt"]["path"])
        raw = json.dumps({"schema": "caller-operational-json"}, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        replacement = path.with_name(f"{digest}.operational.json")
        replacement.write_bytes(raw)
        result["operational_receipt"] = {"path": str(replacement), "sha256": digest}
        return result, server_sha, server_path

    monkeypatch.setattr(readiness, "_rpc_export_assessment", surrogate)
    assert readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1") is None


def test_live_daemon_rpc_worker_is_hidden_and_deadline_bounded(monkeypatch, tmp_path):
    from scripts import llmq_adoption_readiness as readiness

    def timeout(*argv, **kwargs):
        assert kwargs["timeout"] == 10
        assert kwargs["shell"] is False
        assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        raise subprocess.TimeoutExpired(argv[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    try:
        readiness._rpc_export_assessment(
            r"\\.\pipe\ember-lab-test", "job-1", tmp_path / "fresh-export"
        )
    except OSError as error:
        assert "end-to-end deadline" in str(error)
    else:
        raise AssertionError("hung pipe worker did not fail closed")


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


def test_partial_source_and_build_receipt_exposes_external_benchmark_remainder(monkeypatch):
    # A caller-selected state root is not authority; only a live authenticated
    # Ember Lab export over EMBER_LAB_PIPE can satisfy daemon custody.
    monkeypatch.setenv("EMBER_STATE_ROOT", str(REPO_ROOT))
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

def test_governed_source_and_build_expose_only_the_external_benchmark_remainder(tmp_path, monkeypatch):
    """A real governed source/build chain may wait for the owned benchmark, but not fake it."""
    remote = tmp_path / "llmq-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    from scripts import llmq_adoption_readiness as readiness

    monkeypatch.setattr(readiness, "_GOVERNED_ORIGIN", str(remote))
    authority_root = tmp_path.parent / f"{tmp_path.name}-daemon-state"
    authority_root.mkdir()
    # Legacy environment selection is intentionally ignored; the positive
    # case below supplies the daemon RPC assessment descriptor instead.
    monkeypatch.setenv("EMBER_STATE_ROOT", str(authority_root))
    repo = tmp_path / "llmq-repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    source = repo / "llmq.py"
    source.write_bytes(b"governed source bytes")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    subprocess.run(["git", "-C", str(repo), "add", "llmq.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "source"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    def copy_loose_objects(target: Path = remote) -> None:
        for object_path in (repo / ".git" / "objects").rglob("*"):
            if not object_path.is_file() or object_path.parent.name in {"info", "pack"}:
                continue
            destination = target / "objects" / object_path.relative_to(repo / ".git" / "objects")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(object_path, destination)

    copy_loose_objects()
    subprocess.run(["git", "--git-dir", str(remote), "update-ref", "refs/heads/dev", commit], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/dev", commit], check=True)
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "llmq-source-manifest-v1",
                "repo": "IST-DASLab/llmq",
                "commit": commit,
                "tree_sha256": tree,
                "remote_ref": "refs/heads/dev",
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
    producer_source = tmp_path / "runtime" / "ember-lab" / "src" / "lib.rs"
    producer_source.parent.mkdir(parents=True)
    producer_source.write_bytes((REPO_ROOT / "runtime" / "ember-lab" / "src" / "lib.rs").read_bytes())
    producer_source_sha = hashlib.sha256(producer_source.read_bytes()).hexdigest()
    producer_binary = tmp_path / "runtime" / "ember-lab" / "ember-lab.exe"
    producer_binary.write_bytes(b"governed ember-lab binary")
    producer_binary_sha = hashlib.sha256(producer_binary.read_bytes()).hexdigest()
    operational = tmp_path / "ember-lab-operational.json"
    operational.write_text(
        json.dumps(
            {
                "schema": "ember-lab-operational-receipt-v1",
                "producer": "ember-lab-daemon",
                "status": "PASS",
                "test_only": False,
                "job_id": "job-1",
                "exit_code": 0,
                "source_manifest_sha256": manifest_sha,
                "binary_sha256": source_sha,
                "ember_lab_identity": {
                    "source_sha256": producer_source_sha,
                    "binary_sha256": producer_binary_sha,
                },
            }
        ),
        encoding="utf-8",
    )
    operational_sha = hashlib.sha256(operational.read_bytes()).hexdigest()
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
            "operational_receipt_path": "ember-lab-operational.json",
            "operational_receipt_sha256": operational_sha,
            "producer_source_path": "runtime/ember-lab/src/lib.rs",
            "producer_source_sha256": producer_source_sha,
            "producer_binary_path": "runtime/ember-lab/ember-lab.exe",
            "producer_binary_sha256": producer_binary_sha,
        },
        "governed_source_receipt": {
            "schema": "llmq-governed-source-receipt-v1",
            "status": "PASS",
            "authority": "governed-git-source",
            "repo": "IST-DASLab/llmq",
            "commit": commit,
            "tree_sha256": tree,
            "remote_ref": "refs/heads/dev",
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
            "operational_receipt_path": "ember-lab-operational.json",
            "operational_receipt_sha256": operational_sha,
            "producer_source_path": "runtime/ember-lab/src/lib.rs",
            "producer_source_sha256": producer_source_sha,
            "producer_binary_path": "runtime/ember-lab/ember-lab.exe",
            "producer_binary_sha256": producer_binary_sha,
        },
        "adoption_design_path": "fixtures/design.md",
        "adoption_design_sha256": design_sha,
        "mechanism_attribution_path": "fixtures/attribution.md",
        "mechanism_attribution_sha256": attribution_sha,
    }
    forged_build = json.loads(json.dumps(payload))
    forged_build["ember_lab_build_receipt"].pop("operational_receipt_path")
    forged = assess(tmp_path, forged_build)
    assert forged["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.operational_receipt_path" in forged["missing"]
    assert "ember_lab_build_receipt.daemon_authority" in forged["missing"]
    result = assess(tmp_path, payload)
    assert result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in result["missing"]
    assert result["execution_claim"] is False
    assert result["result_credit"] is False

    raw_log = tmp_path / "benchmark.jsonl"
    raw_log.write_text(
        json.dumps({"mode": "fp8", "tokens": 1000, "elapsed_ms": 100})
        + "\n"
        + json.dumps({"mode": "bf16", "tokens": 2000, "elapsed_ms": 200})
        + "\n",
        encoding="utf-8",
    )
    forged_benchmark = json.loads(json.dumps(payload))
    forged_benchmark["ember_lab_benchmark_receipt"] = {
        "schema": "ember-lab-benchmark-receipt-v1",
        "status": "PASS",
        "authority": "ember-cli->ember-lab",
        "job_id": "job-1",
        "hardware_uuid": "GPU-1",
        "command": "invented-benchmark",
        "config_sha256": "c" * 64,
        "binary_sha256": source_sha,
        "raw_log_path": "benchmark.jsonl",
        "raw_log_sha256": hashlib.sha256(raw_log.read_bytes()).hexdigest(),
        "operational_receipt_path": "ember-lab-operational.json",
        "operational_receipt_sha256": operational_sha,
        "rate_rows": [
            {"mode": "fp8", "tokens": 1000, "elapsed_ms": 100, "tok_s": 10000.0},
            {"mode": "bf16", "tokens": 2000, "elapsed_ms": 200, "tok_s": 10000.0},
        ],
    }
    benchmark_result = assess(tmp_path, forged_benchmark)
    assert benchmark_result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in benchmark_result["missing"]

    # The real authority is outside the caller packet. It mirrors the existing
    # daemon export: terminal job identity plus daemon-sealed stdout/stderr.
    canonical_source = authority_root / "runtime" / "ember-lab" / "src" / "lib.rs"
    canonical_source.parent.mkdir(parents=True)
    canonical_source.write_bytes((REPO_ROOT / "runtime" / "ember-lab" / "src" / "lib.rs").read_bytes())
    canonical_source_sha = hashlib.sha256(canonical_source.read_bytes()).hexdigest()
    canonical_binary = authority_root / "runtime" / "ember-lab" / "ember-lab.exe"
    canonical_binary.write_bytes(b"canonical ember-lab daemon binary")
    canonical_binary_sha = hashlib.sha256(canonical_binary.read_bytes()).hexdigest()
    canonical_log_unaddressed = authority_root / "logs" / "benchmark.stdout.log"
    canonical_log_unaddressed.parent.mkdir()
    canonical_log_unaddressed.write_bytes(raw_log.read_bytes())
    canonical_log_sha = hashlib.sha256(canonical_log_unaddressed.read_bytes()).hexdigest()
    canonical_log = authority_root / "logs" / f"{canonical_log_sha}.stdout.log"
    canonical_log_unaddressed.replace(canonical_log)
    canonical_stderr_unaddressed = authority_root / "logs" / "benchmark.stderr.log"
    canonical_stderr_unaddressed.write_bytes(b"")
    canonical_stderr_sha = hashlib.sha256(canonical_stderr_unaddressed.read_bytes()).hexdigest()
    canonical_stderr = authority_root / "logs" / f"{canonical_stderr_sha}.stderr.log"
    canonical_stderr_unaddressed.replace(canonical_stderr)
    daemon_receipt = {
        "schema": "ember-lab-operational-receipt-v1",
        "ember_lab_identity": {
            "binary_sha256": canonical_binary_sha,
            "source_sha256": canonical_source_sha,
        },
        "job_id": "job-1",
        "identity_sha256": "d" * 64,
        "resource_lease": "GPU-1",
        "state": "exited",
        "pid": 1234,
        "executable_identity": "llmq-benchmark.exe",
        "restart_policy": "never",
        "exit_code": 0,
        "logs": {
            "stdout": {"file_name": canonical_log.name, "sealed": True, "sha256": canonical_log_sha},
            "stderr": {"file_name": canonical_stderr.name, "sealed": True, "sha256": canonical_stderr_sha},
        },
        "events": [
            {"seq": 1, "ts_ms": 100, "kind": "job_started", "payload": {}},
            {"seq": 2, "ts_ms": 200, "kind": "job_exited", "payload": {}},
        ],
        "outage_events": [],
        "scientific_capability_evidence": False,
    }
    # Rust serde_json::to_vec_pretty uses the default lexicographically ordered
    # map representation; the consumer must replay these exact bytes.
    daemon_bytes = json.dumps(
        daemon_receipt, indent=2, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    daemon_sha = hashlib.sha256(daemon_bytes).hexdigest()
    daemon_relative = f"runtime/ember-lab/content-addressed-receipts/{daemon_sha}.json"
    daemon_path = authority_root / daemon_relative
    daemon_path.parent.mkdir()
    daemon_path.write_bytes(daemon_bytes)
    schedule_unaddressed = authority_root / "schedule-state.json"
    schedule_unaddressed.write_text(
        json.dumps(
            {
                "schema_version": "ember-lab-schedule-alarm-state-v1",
                "generated_at_ms": 1,
                "ember_lab_identity": daemon_receipt["ember_lab_identity"],
                "alarms": {
                    "prediction_overrun": False,
                    "zero_schedule_receipts_7d": False,
                    "absolute_deadline_drift": False,
                },
                "runs": [
                    {
                        "job_id": "job-1",
                        "artifact_class": "llmq-4090x1-3b-benchmark",
                        "predicted_at_ms": 1,
                        "predicted_duration_ms": 300,
                        "predicted_tokens": 3000,
                        "predicted_program_completion_ms": 301,
                        "absolute_deadline_ms": 1000,
                        "prediction_daemon_identity": daemon_receipt["ember_lab_identity"],
                        "measured_at_ms": 301,
                        "measured_duration_ms": 300,
                        "measured_tokens": 3000,
                        "measurement_outcome": "COMPLETED",
                        "measurement_receipt_sha256": canonical_log_sha,
                        "measurement_daemon_identity": daemon_receipt["ember_lab_identity"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    schedule_sha = hashlib.sha256(schedule_unaddressed.read_bytes()).hexdigest()
    schedule = authority_root / "logs" / f"{schedule_sha}.schedule.json"
    schedule_unaddressed.replace(schedule)
    state_db_relative = "runtime/ember-lab/ember-lab.sqlite3"
    state_db = authority_root / state_db_relative
    state_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_db) as connection:
        connection.executescript(
            """
                CREATE TABLE jobs(
                    job_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    exit_code INTEGER,
                    pid INTEGER,
                    resource TEXT,
                    executable_identity TEXT,
                    restart_policy TEXT,
                    stdout_log_path TEXT,
                    stderr_log_path TEXT,
                    stdout_log_sha256 TEXT,
                    stderr_log_sha256 TEXT,
                    outage_event_cutoff_seq INTEGER
            );
            CREATE TABLE identities(
                job_id TEXT PRIMARY KEY,
                canonical_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                identity_blob BLOB NOT NULL,
                bound_at_ms INTEGER NOT NULL
            );
            CREATE TABLE events(
                seq INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                ts_ms INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE outage_events(
                seq INTEGER PRIMARY KEY,
                resource TEXT NOT NULL,
                ts_ms INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE schedule_runs(
                job_id TEXT PRIMARY KEY,
                measured_at_ms INTEGER,
                measured_duration_ms INTEGER,
                measured_tokens INTEGER,
                measurement_outcome TEXT,
                measurement_receipt_sha256 TEXT,
                measurement_daemon_binary_sha256 TEXT,
                measurement_daemon_source_sha256 TEXT
            );
            """
        )
        connection.execute(
                    "INSERT INTO jobs(job_id,state,exit_code,pid,resource,executable_identity,restart_policy,stdout_log_path,stderr_log_path,stdout_log_sha256,stderr_log_sha256,outage_event_cutoff_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "job-1",
                    "exited",
                    0,
                    1234,
                        "GPU-1",
                        "llmq-benchmark.exe",
                        "never",
                    str(canonical_log),
                    str(canonical_stderr),
                    canonical_log_sha,
                    canonical_stderr_sha,
                    0,
                ),
        )
        connection.execute(
            "INSERT INTO identities(job_id,canonical_path,sha256,identity_blob,bound_at_ms) VALUES(?,?,?,?,?)",
            ("job-1", "runtime/ember-lab/ember-lab.exe", "d" * 64, b"identity", 1),
        )
        connection.executemany(
            "INSERT INTO events(seq,job_id,ts_ms,kind,payload_json) VALUES(?,?,?,?,?)",
            [
                (1, "job-1", 100, "job_started", "{}"),
                (2, "job-1", 200, "job_exited", "{}"),
            ],
        )
        connection.execute(
            "INSERT INTO schedule_runs(job_id,measured_at_ms,measured_duration_ms,measured_tokens,measurement_outcome,measurement_receipt_sha256,measurement_daemon_binary_sha256,measurement_daemon_source_sha256) VALUES(?,?,?,?,?,?,?,?)",
            (
                "job-1",
                301,
                300,
                3000,
                "COMPLETED",
                canonical_log_sha,
                canonical_binary_sha,
                canonical_source_sha,
            ),
        )
    state_db_sha = hashlib.sha256(state_db.read_bytes()).hexdigest()
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        payload[build_key].update(
            dispatch_receipt_path="dispatch.json",
            binary_manifest_path="binary-manifest.json",
            operational_receipt_path=daemon_relative,
            operational_receipt_sha256=daemon_sha,
            daemon_state_db_path=state_db_relative,
            daemon_state_db_sha256=state_db_sha,
            producer_source_sha256=canonical_source_sha,
            producer_binary_sha256=canonical_binary_sha,
        )
    monkeypatch.setenv("EMBER_LAB_PIPE", r"\\.\pipe\ember-lab-test")

    def live_daemon_rpc(pipe_name, job_id, directory):
        assert pipe_name == r"\\.\pipe\ember-lab-test"
        assert job_id == "job-1"
        directory.mkdir()
        exported = {
            "operational_receipt": (daemon_path.read_bytes(), ".operational.json"),
            "stdout_log": (canonical_log.read_bytes(), ".stdout.log"),
            "stderr_log": (canonical_stderr.read_bytes(), ".stderr.log"),
            "schedule_alarm_state": (schedule.read_bytes(), ".schedule.json"),
        }
        result = {
            "schema": "ember-lab-assessment-evidence-v1",
            "ember_lab_identity": daemon_receipt["ember_lab_identity"],
        }
        for field, (raw, suffix) in exported.items():
            digest = hashlib.sha256(raw).hexdigest()
            path = directory / f"{digest}{suffix}"
            path.write_bytes(raw)
            result[field] = {"path": str(path), "sha256": digest}
        return result, canonical_binary_sha, canonical_binary

    monkeypatch.setattr(readiness, "_rpc_export_assessment", live_daemon_rpc)
    monkeypatch.setattr(readiness, "_canonical_ember_lab_binary", lambda _: canonical_binary)
    daemon_assessment_evidence = {
        "schema": "ember-lab-assessment-evidence-v1",
        "authority": "ember-cli->ember-lab",
        "operational_receipt": {
            "path": str(daemon_path),
            "sha256": daemon_sha,
        },
        "stdout_log": {
            "path": str(canonical_log),
            "sha256": canonical_log_sha,
        },
        "stderr_log": {
            "path": str(canonical_stderr),
            "sha256": canonical_stderr_sha,
        },
        "schedule_alarm_state": {
            "path": str(schedule),
            "sha256": schedule_sha,
        },
        "state_db": {
            "path": str(state_db),
            "sha256": state_db_sha,
        },
        "ember_lab_identity": daemon_receipt["ember_lab_identity"],
    }
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        payload[build_key]["daemon_assessment_evidence"] = daemon_assessment_evidence
        payload[build_key]["daemon_assessment_rpc"] = {
            "pipe": r"\\.\pipe\ember-lab-test-authority",
            "directory": str(authority_root / "assessment-evidence"),
        }
        payload[build_key]["_live_daemon_assessment"] = daemon_assessment_evidence
    live_assessment = readiness._acquire_live_daemon_assessment(REPO_ROOT, "job-1")
    assert live_assessment is not None
    daemon_assessment_evidence = live_assessment["response"]
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        payload[build_key]["daemon_assessment_evidence"] = daemon_assessment_evidence
        payload[build_key]["_live_daemon_assessment"] = daemon_assessment_evidence
    assert readiness._ember_lab_build_missing(
        tmp_path,
        payload,
        payload["governed_source_receipt"],
        payload["build_receipt"],
        live_assessment,
    ) == []
    trusted_build = assess(tmp_path, payload)
    assert trusted_build["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert "ember_lab_build_receipt.daemon_authority" not in trusted_build["missing"]
    assert "ember_lab_benchmark_receipt" in trusted_build["missing"]

    # Caller packet descriptors are inert: removing one cannot affect the
    # authenticated live-pipe result.
    env_only_payload = json.loads(json.dumps(payload))
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        env_only_payload[build_key].pop("daemon_assessment_evidence", None)
        env_only_payload[build_key].pop("daemon_assessment_rpc", None)
    monkeypatch.setenv("EMBER_STATE_ROOT", str(authority_root))
    env_only_result = assess(tmp_path, env_only_payload)
    assert env_only_result["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert not any("locator" in field for field in env_only_result["missing"])

    # A caller-authored operational JSON with the old producer/status/source
    # shape is not a daemon receipt, even when it is content-addressed.
    surrogate_bytes = json.dumps(
        {
            "schema": "ember-lab-operational-receipt-v1",
            "producer": "ember-lab-daemon",
            "status": "PASS",
            "source_manifest_sha256": manifest_sha,
            "binary_sha256": canonical_binary_sha,
        },
        indent=2,
    ).encode("utf-8")
    surrogate_sha = hashlib.sha256(surrogate_bytes).hexdigest()
    surrogate_relative = f"runtime/ember-lab/content-addressed-receipts/{surrogate_sha}.json"
    (authority_root / surrogate_relative).write_bytes(surrogate_bytes)
    surrogate_payload = json.loads(json.dumps(payload))
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        surrogate_payload[build_key].update(
            operational_receipt_path=surrogate_relative,
            operational_receipt_sha256=surrogate_sha,
        )
    surrogate_result = assess(tmp_path, surrogate_payload)
    assert surrogate_result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in surrogate_result["missing"]

    # A self-consistent content-addressed rewrite cannot replace the daemon's
    # canonical schema, identity, or DB/event-derived bytes.
    forged_receipt = json.loads(json.dumps(daemon_receipt))
    forged_receipt["ember_lab_identity"]["source_sha256"] = "e" * 64
    forged_bytes = json.dumps(forged_receipt, indent=2, ensure_ascii=False).encode("utf-8")
    forged_sha = hashlib.sha256(forged_bytes).hexdigest()
    forged_relative = f"runtime/ember-lab/content-addressed-receipts/{forged_sha}.json"
    (authority_root / forged_relative).write_bytes(forged_bytes)
    forged_identity_payload = json.loads(json.dumps(payload))
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        forged_identity_payload[build_key].update(
            operational_receipt_path=forged_relative,
            operational_receipt_sha256=forged_sha,
        )
    forged_identity_result = assess(tmp_path, forged_identity_payload)
    assert forged_identity_result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in forged_identity_result["missing"]

    malformed_schema = json.loads(json.dumps(daemon_receipt))
    malformed_schema["schema"] = "ember-lab-operational-receipt-v0"
    malformed_bytes = json.dumps(malformed_schema, indent=2, ensure_ascii=False).encode("utf-8")
    malformed_sha = hashlib.sha256(malformed_bytes).hexdigest()
    malformed_relative = f"runtime/ember-lab/content-addressed-receipts/{malformed_sha}.json"
    (authority_root / malformed_relative).write_bytes(malformed_bytes)
    malformed_payload = json.loads(json.dumps(payload))
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        malformed_payload[build_key].update(
            operational_receipt_path=malformed_relative,
            operational_receipt_sha256=malformed_sha,
        )
    malformed_result = assess(tmp_path, malformed_payload)
    assert malformed_result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in malformed_result["missing"]

    wrong_address_payload = json.loads(json.dumps(payload))
    for build_key in ("build_receipt", "ember_lab_build_receipt"):
        wrong_address_payload[build_key]["operational_receipt_sha256"] = "0" * 64
    wrong_address_result = assess(tmp_path, wrong_address_payload)
    assert wrong_address_result["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_build_receipt.daemon_authority" in wrong_address_result["missing"]

    trusted_benchmark = json.loads(json.dumps(payload))
    trusted_benchmark["ember_lab_benchmark_receipt"] = {
        "schema": "ember-lab-benchmark-receipt-v1",
        "status": "PASS",
        "authority": "ember-cli->ember-lab",
        "job_id": "job-1",
        "hardware_uuid": "GPU-1",
        "command": "llmq 4090x1 3B benchmark",
        "config_sha256": "c" * 64,
        "binary_sha256": source_sha,
            "raw_log_path": f"logs/{canonical_log.name}",
        "raw_log_sha256": canonical_log_sha,
        "operational_receipt_path": daemon_relative,
        "operational_receipt_sha256": daemon_sha,
            "schedule_alarm_state_path": f"logs/{schedule.name}",
        "schedule_alarm_state_sha256": schedule_sha,
        "measurement_receipt_sha256": canonical_log_sha,
        "rate_rows": [
            {"mode": "fp8", "tokens": 1000, "elapsed_ms": 100, "tok_s": 10000.0},
            {"mode": "bf16", "tokens": 2000, "elapsed_ms": 200, "tok_s": 10000.0},
        ],
    }
    trusted_benchmark["benchmark_receipt"] = {
        "schema": "ember-4090-3b-benchmark-receipt-v1",
        "hardware": "RTX 4090",
        "status": "PASS",
        "model": "Qwen2.5-3B",
        "fp8_tok_s": 10000.0,
        "bf16_tok_s": 10000.0,
    }
    trusted_result = assess(tmp_path, trusted_benchmark)
    assert trusted_result["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert trusted_result["missing"] == []

    foreign_hardware = json.loads(json.dumps(trusted_benchmark))
    foreign_hardware["ember_lab_benchmark_receipt"]["hardware_uuid"] = "GPU-FOREIGN"
    refused_hardware = assess(tmp_path, foreign_hardware)
    assert refused_hardware["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_benchmark_receipt.hardware_run_authority" in refused_hardware["missing"]

    substituted_log = authority_root / "logs" / "caller-selected.log"
    substituted_log.write_bytes(canonical_log.read_bytes())
    substituted_samples = json.loads(json.dumps(trusted_benchmark))
    substituted_samples["ember_lab_benchmark_receipt"]["raw_log_path"] = "logs/caller-selected.log"
    ignored_samples = assess(tmp_path, substituted_samples)
    assert ignored_samples["verdict"] == "READY_FOR_EXTERNAL_EXECUTION"
    assert ignored_samples["missing"] == []

    schedule_bytes = schedule.read_bytes()
    altered_schedule = json.loads(schedule_bytes)
    altered_schedule["runs"][0]["measured_tokens"] = 3001
    schedule.write_text(json.dumps(altered_schedule), encoding="utf-8")
    altered_totals = json.loads(json.dumps(trusted_benchmark))
    altered_totals["ember_lab_benchmark_receipt"]["schedule_alarm_state_sha256"] = hashlib.sha256(
        schedule.read_bytes()
    ).hexdigest()
    refused_totals = assess(tmp_path, altered_totals)
    assert refused_totals["verdict"] == "PRELAUNCH_REJECTED"
    assert "ember_lab_benchmark_receipt.hardware_run_sample_authority" in refused_totals["missing"]
    schedule.write_bytes(schedule_bytes)

    # Multiple origin URLs are ambiguous: single-value config lookup can report
    # the canonical last value while transport selects an attacker-controlled first.
    attacker_remote = tmp_path / "attacker.git"
    subprocess.run(["git", "init", "--bare", "-q", str(attacker_remote)], check=True)
    copy_loose_objects(attacker_remote)
    subprocess.run(["git", "--git-dir", str(attacker_remote), "update-ref", "refs/heads/dev", commit], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "--unset-all", "remote.origin.url"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "--add", "remote.origin.url", str(attacker_remote)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "--add", "remote.origin.url", str(remote)], check=True)
    ambiguous_origin = assess(tmp_path, payload)
    assert ambiguous_origin["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.git_origin" in ambiguous_origin["missing"]
    subprocess.run(["git", "-C", str(repo), "config", "--unset-all", "remote.origin.url"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "--add", "remote.origin.url", str(remote)], check=True)

    # pushInsteadOf is also transport authority drift and must be rejected even
    # though this read-only probe does not itself push.
    push_rewrite_key = f"url.{attacker_remote.as_uri()}.pushinsteadof"
    subprocess.run(["git", "-C", str(repo), "config", push_rewrite_key, str(remote)], check=True)
    push_redirected = assess(tmp_path, payload)
    assert push_redirected["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.git_url_rewrite" in push_redirected["missing"]
    subprocess.run(["git", "-C", str(repo), "config", "--unset-all", push_rewrite_key], check=True)

    # Raw remote.origin.url can remain canonical while Git silently redirects
    # ls-remote through a caller-controlled insteadOf mapping.
    rewrite_key = f"url.{attacker_remote.as_uri()}.insteadof"
    subprocess.run(
        ["git", "-C", str(repo), "config", rewrite_key, str(remote)],
        check=True,
    )
    redirected = assess(tmp_path, payload)
    assert redirected["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.git_url_rewrite" in redirected["missing"]
    subprocess.run(["git", "-C", str(repo), "config", "--unset-all", rewrite_key], check=True)

    # A local commit in a repository with a spoofable origin URL is not governed
    # source unless it is reachable from the previously fetched origin object set.
    source.write_bytes(b"foreign local source bytes")
    foreign_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    subprocess.run(["git", "-C", str(repo), "add", "llmq.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "foreign"], check=True)
    foreign_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    foreign_tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    manifest.write_text(
        json.dumps(
            {
                "schema": "llmq-source-manifest-v1",
                "repo": "IST-DASLab/llmq",
                "commit": foreign_commit,
                "tree_sha256": foreign_tree,
                "remote_ref": "refs/heads/dev",
                "source_path": "llmq-repo/llmq.py",
                "source_sha256": foreign_source_sha,
            }
        ),
        encoding="utf-8",
    )
    foreign_manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    dispatch.write_text(json.dumps({"schema": "ember-lab-dispatch-terminal-receipt-v1", "job_id": "job-1", "status": "PASS", "source_manifest_sha256": foreign_manifest_sha}), encoding="utf-8")
    binary_manifest.write_text(json.dumps({"schema": "ember-lab-binary-manifest-v1", "status": "PASS", "binary_sha256": foreign_source_sha}), encoding="utf-8")
    payload["llmq_dev_commit"] = foreign_commit
    payload["source_sha256"] = foreign_source_sha
    payload["build_receipt"].update(source_commit=foreign_commit, source_sha256=foreign_source_sha, binary_sha256=foreign_source_sha)
    payload["governed_source_receipt"].update(commit=foreign_commit, tree_sha256=foreign_tree, source_sha256=foreign_source_sha, source_manifest_sha256=foreign_manifest_sha)
    payload["ember_lab_build_receipt"].update(
        source_manifest_sha256=foreign_manifest_sha,
        binary_sha256=foreign_source_sha,
        dispatch_receipt_sha256=hashlib.sha256(dispatch.read_bytes()).hexdigest(),
        binary_manifest_sha256=hashlib.sha256(binary_manifest.read_bytes()).hexdigest(),
    )
    foreign = assess(tmp_path, payload)
    assert foreign["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.git_remote_commit" in foreign["missing"]

    # Even a governed commit cannot borrow dirty worktree bytes and remint every
    # local hash; the reopened bytes must equal the exact <commit>:<path> blob.
    copy_loose_objects()
    subprocess.run(["git", "--git-dir", str(remote), "update-ref", "refs/heads/dev", foreign_commit], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/origin/dev", foreign_commit], check=True)
    source.write_bytes(b"dirty worktree source bytes")
    dirty_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_value["source_sha256"] = dirty_source_sha
    manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
    dirty_manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    dispatch.write_text(json.dumps({"schema": "ember-lab-dispatch-terminal-receipt-v1", "job_id": "job-1", "status": "PASS", "source_manifest_sha256": dirty_manifest_sha}), encoding="utf-8")
    binary_manifest.write_text(json.dumps({"schema": "ember-lab-binary-manifest-v1", "status": "PASS", "binary_sha256": dirty_source_sha}), encoding="utf-8")
    payload["source_sha256"] = dirty_source_sha
    payload["build_receipt"].update(source_sha256=dirty_source_sha, binary_sha256=dirty_source_sha)
    payload["governed_source_receipt"].update(source_sha256=dirty_source_sha, source_manifest_sha256=dirty_manifest_sha)
    payload["ember_lab_build_receipt"].update(
        source_manifest_sha256=dirty_manifest_sha,
        binary_sha256=dirty_source_sha,
        dispatch_receipt_sha256=hashlib.sha256(dispatch.read_bytes()).hexdigest(),
        binary_manifest_sha256=hashlib.sha256(binary_manifest.read_bytes()).hexdigest(),
    )
    dirty = assess(tmp_path, payload)
    assert dirty["verdict"] == "PRELAUNCH_REJECTED"
    assert "governed_source_receipt.git_source_blob" in dirty["missing"]

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

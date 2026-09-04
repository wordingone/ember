from __future__ import annotations

# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = (
    ROOT
    / "src"
    / "ember"
    / "infrastructure"
    / "tools"
    / "ember-restart-3b"
    / "issue2071_qk_rope_matched_loss_canary_v1.py"
)
SPEC = importlib.util.spec_from_file_location("issue2071_canary", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PeakMemoryCudaFake:
    def __init__(self, *, reset_error: Exception | None = None, allocated: int = 0, maximum: int = 0):
        self.reset_error = reset_error
        self.allocated = allocated
        self.maximum = maximum
        self.reset_devices: list[object] = []

    def reset_peak_memory_stats(self, device: object) -> None:
        self.reset_devices.append(device)
        if self.reset_error is not None:
            raise self.reset_error

    def memory_allocated(self, device: object) -> int:
        return self.allocated

    def max_memory_allocated(self, device: object) -> int:
        return self.maximum


class InterpreterCudaFake:
    def __init__(self, *, available: bool = True, count: int = 1, name: str = "Fake GPU"):
        self.available = available
        self.count = count
        self.name = name

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count

    def get_device_name(self, device: int) -> str:
        assert device == 0
        return self.name


def test_interpreter_binding_preflight_records_exact_gpu_identity(tmp_path: Path, monkeypatch):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"packet-bound-python")
    monkeypatch.setattr(MODULE.sys, "executable", str(executable))
    expected_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    torch = type("Torch", (), {
        "__version__": "2.10.0+cu126",
        "cuda": InterpreterCudaFake(),
    })

    assert MODULE.interpreter_binding_preflight(
        torch, expected_python_sha256=expected_sha, expected_torch_version="2.10.0+cu126",
    ) == {
        "result": "PASS",
        "sys_executable": str(executable.resolve()),
        "sys_executable_sha256": expected_sha,
        "torch_version": "2.10.0+cu126",
        "cuda_available": True,
        "cuda_device_count": 1,
        "cuda_device_name": "Fake GPU",
    }


def test_interpreter_binding_preflight_refuses_cpu_interpreter(tmp_path: Path, monkeypatch):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"cpu-python")
    monkeypatch.setattr(MODULE.sys, "executable", str(executable))
    torch = type("Torch", (), {
        "__version__": "2.13.0+cpu",
        "cuda": InterpreterCudaFake(available=False, count=0),
    })

    with pytest.raises(RuntimeError, match="^INTERPRETER_BINDING_REFUSED:"):
        MODULE.interpreter_binding_preflight(
            torch,
            expected_python_sha256="0" * 64,
            expected_torch_version="2.10.0+cu126",
        )


def test_peak_memory_reset_uses_backend_when_present():
    cuda = PeakMemoryCudaFake()
    result = MODULE.prepare_peak_memory_accounting(type("Torch", (), {"cuda": cuda}), "cuda:0")
    assert result == {
        "backend_present": True,
        "mode": "reset_peak_memory_stats",
        "baseline_memory_allocated_bytes": 0,
        "baseline_max_memory_allocated_bytes": 0,
    }
    assert cuda.reset_devices == ["cuda:0"]


def test_peak_memory_reset_missing_backend_accepts_only_zero_counters():
    cuda = PeakMemoryCudaFake(
        reset_error=AttributeError("module 'torch._C' has no attribute '_cuda_resetPeakMemoryStats'")
    )
    result = MODULE.prepare_peak_memory_accounting(type("Torch", (), {"cuda": cuda}), "cuda:0")
    assert result["backend_present"] is False
    assert result["mode"] == "zero-baseline-max-memory-allocated"
    assert result["baseline_memory_allocated_bytes"] == 0
    assert result["baseline_max_memory_allocated_bytes"] == 0


def test_peak_memory_reset_missing_backend_refuses_nonzero_counters():
    cuda = PeakMemoryCudaFake(
        reset_error=AttributeError("module 'torch._C' has no attribute '_cuda_resetPeakMemoryStats'"),
        allocated=1,
        maximum=2,
    )
    with pytest.raises(RuntimeError, match="CUDA_PEAK_RESET_BACKEND_ABSENT_NONZERO_REFUSED"):
        MODULE.prepare_peak_memory_accounting(type("Torch", (), {"cuda": cuda}), "cuda:0")


def row(arm: str, pair: int, *, rate: float = 100.0) -> dict[str, object]:
    return {
        "arm": arm,
        "pair": pair,
        "loss": 2.0,
        "processed_tokens": 960,
        "event_seconds": 960.0 / rate,
        "tokens_per_second": rate,
        "start_identity": f"start-{pair}",
        "post_model_identity": f"model-{pair}",
        "post_optimizer_identity": f"optimizer-{pair}",
        "optimizer_structure_census": {
            "param_groups": [{"params": ["parameter-0"]}],
            "state": {"parameter-0": {"exp_avg": {"dtype": "torch.float32", "shape": [2, 2]}}},
        },
        "post_scheduler_identity": "scheduler-none-v1",
        "post_scaler_identity": "scaler-none-v1",
        "post_cursor": {"global_step": 101 + pair, "selected_ordinal": 64 * (pair + 1)},
        "post_rng_identity": f"rng-{pair}",
        "backend_identity": ["operator:aten::_scaled_dot_product_flash_attention"],
        "sampled_parameters": {"layer.0.qkv.weight:0": 1.0},
        "event_ids": [f"start-event-{arm}-{pair}", f"end-event-{arm}-{pair}"],
    }


def pairs(*, control_rate: float = 100.0, treatment_rate: float = 102.0):
    result = []
    for pair_index, pair_order in enumerate(MODULE.PAIR_ORDERS):
        result.append([
            row(pair_order[0], pair_index, rate=control_rate if pair_order[0] == "control" else treatment_rate),
            row(pair_order[1], pair_index, rate=control_rate if pair_order[1] == "control" else treatment_rate),
        ])
    return result


def test_frozen_order_is_four_abba_blocks_and_eight_pairs():
    assert MODULE.MEASURED_ORDER == ("control", "treatment", "treatment", "control") * 4
    assert MODULE.PAIR_ORDERS == (("control", "treatment"), ("treatment", "control")) * 4
    assert sum(arm == "control" for arm in MODULE.MEASURED_ORDER) == 8
    assert sum(arm == "treatment" for arm in MODULE.MEASURED_ORDER) == 8


def test_batch_order_or_cursor_drift_refuses():
    planted = pairs()
    planted[2][1]["start_identity"] = "wrong"
    with pytest.raises(ValueError, match="PAIR_START_IDENTITY_DRIFT_REFUSED"):
        MODULE.adjudicate_pairs(planted)
    planted = pairs()
    planted[2][1]["post_cursor"] = {"global_step": 103, "selected_ordinal": 999}
    with pytest.raises(ValueError, match="POST_CURSOR_DRIFT_REFUSED"):
        MODULE.adjudicate_pairs(planted)


def test_checkpoint_or_optimizer_start_mismatch_refuses():
    MODULE.validate_initial_identity({"model": "a", "optimizer": "b"}, {"model": "a", "optimizer": "b"})
    with pytest.raises(ValueError, match="INITIAL_STATE_IDENTITY_DRIFT_REFUSED"):
        MODULE.validate_initial_identity({"model": "a", "optimizer": "b"}, {"model": "a", "optimizer": "c"})


def test_wddm_gpu_accounting_uses_conservative_device_fallback():
    process_rows = "1234, [N/A]\n5678, [N/A]\n"
    assert MODULE.external_gpu_bytes(process_rows, "2048\n") == 2048 * 1024**2
    with pytest.raises(ValueError, match="EXTERNAL_GPU_ACCOUNTING_UNAVAILABLE_REFUSED"):
        MODULE.external_gpu_bytes(process_rows)
    with pytest.raises(ValueError, match="EXTERNAL_GPU_DEVICE_CENSUS_REFUSED"):
        MODULE.external_gpu_bytes(process_rows, "100\n200\n")


def test_loss_divergence_refuses():
    planted = pairs()
    planted[0][1]["loss"] = 2.003
    with pytest.raises(ValueError, match="LOSS_DIVERGENCE_REFUSED"):
        MODULE.adjudicate_pairs(planted)


def test_sampled_parameter_divergence_refuses():
    planted = pairs()
    planted[0][1]["sampled_parameters"] = {"layer.0.qkv.weight:0": 1.02}
    with pytest.raises(ValueError, match="SAMPLED_PARAMETER_DIVERGENCE_REFUSED"):
        MODULE.adjudicate_pairs(planted)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("post_rng_identity", "POST_RNG_DRIFT_REFUSED"),
        ("backend_identity", "BACKEND_IDENTITY_DRIFT_REFUSED"),
    ],
)
def test_rng_backend_or_optimizer_drift_refuses(field: str, message: str):
    planted = pairs()
    planted[4][1][field] = "planted" if field != "backend_identity" else ["operator:math"]
    with pytest.raises(ValueError, match=message):
        MODULE.adjudicate_pairs(planted)


def test_cross_arm_optimizer_identity_is_structural_not_raw():
    planted = pairs()
    planted[0][1]["post_optimizer_identity"] = "different-valid-serialization"
    assert MODULE.adjudicate_pairs(planted)["disposition"] == "PASS_POSITIVE"


def test_cross_arm_optimizer_structure_drift_refuses():
    planted = pairs()
    planted[0][1]["optimizer_structure_census"]["state"]["parameter-0"]["exp_avg"]["shape"] = [3, 2]
    with pytest.raises(ValueError, match="OPTIMIZER_STRUCTURE_DRIFT_REFUSED:0"):
        MODULE.adjudicate_pairs(planted)


def test_same_arm_same_start_requires_exact_post_identities():
    planted = pairs()
    planted[2][0]["start_identity"] = planted[0][0]["start_identity"]
    planted[2][1]["start_identity"] = planted[0][1]["start_identity"]
    with pytest.raises(ValueError, match="WITHIN_ARM_POST_MODEL_IDENTITY_DRIFT_REFUSED"):
        MODULE.adjudicate_pairs(planted)


def test_fixed_negative_and_positive_timing_dispositions():
    negative = MODULE.adjudicate_pairs(pairs(treatment_rate=101.999))
    positive = MODULE.adjudicate_pairs(pairs(treatment_rate=102.0))
    assert negative["disposition"] == "REJECTED"
    assert positive["disposition"] == "PASS_POSITIVE"
    assert positive["aggregate_p10_ratio"] == pytest.approx(1.02)


def test_event_identity_and_accounting_are_closed():
    planted = pairs()
    planted[0][1]["event_ids"] = planted[0][0]["event_ids"]
    with pytest.raises(ValueError, match="CUDA_EVENT_IDENTITY_REFUSED"):
        MODULE.adjudicate_pairs(planted)
    planted = pairs()
    planted[1][0]["tokens_per_second"] = 7.0
    with pytest.raises(ValueError, match="TOKEN_ACCOUNTING_REFUSED"):
        MODULE.adjudicate_pairs(planted)


def test_receipt_self_hash_and_no_overwrite(tmp_path: Path):
    receipt = {"schema_version": MODULE.SCHEMA_VERSION, "result": "PASS_POSITIVE"}
    raw_sha, self_sha = MODULE.write_receipt(tmp_path / "terminal.json", receipt)
    parsed = json.loads((tmp_path / "terminal.json").read_text(encoding="utf-8"))
    body = dict(parsed)
    assert body.pop("self_sha256") == self_sha
    assert hashlib.sha256(MODULE.canonical(body)).hexdigest() == self_sha
    assert hashlib.sha256((tmp_path / "terminal.json").read_bytes()).hexdigest() == raw_sha
    with pytest.raises(FileExistsError, match="OUTPUT_EXISTS_REFUSED"):
        MODULE.write_receipt(tmp_path / "terminal.json", copy.deepcopy(receipt))


def test_progress_and_exception_refusal_are_durable(tmp_path: Path):
    output = tmp_path / "terminal.json"
    MODULE.emit_progress(output, "FIRST", value=1)
    MODULE.emit_progress(output, "SECOND", value=2)
    rows = [json.loads(line) for line in (tmp_path / "terminal.progress.jsonl").read_text().splitlines()]
    assert [row["phase"] for row in rows] == ["FIRST", "SECOND"]
    for row in rows:
        claimed = row.pop("row_sha256")
        assert claimed == hashlib.sha256(MODULE.canonical(row)).hexdigest()
    raw_sha, self_sha = MODULE.write_refusal_from_exception(output, ValueError("PLANTED"))
    refusal = json.loads((tmp_path / "terminal.refusal.json").read_text())
    assert refusal["result"] == "REFUSED"
    assert refusal["refusal_class"] == "ValueError"
    assert refusal["refusal_message"] == "PLANTED"
    assert len(raw_sha) == len(self_sha) == 64
    assert MODULE.write_refusal_from_exception(output, ValueError("LATE")) is None


def test_full_measurement_rows_are_fsynced_and_offline_adjudicable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output = tmp_path / "terminal.json"
    fsync_calls: list[int] = []
    monkeypatch.setattr(MODULE.os, "fsync", lambda fd: fsync_calls.append(fd))
    for pair_rows in pairs():
        for measured_row in pair_rows:
            MODULE.append_measurement_row(output, measured_row, runner_source_sha256="a" * 64)
    measurements = tmp_path / "terminal.measurements.jsonl"
    assert len(measurements.read_text(encoding="utf-8").splitlines()) == 16
    assert len(fsync_calls) == 16
    decision = MODULE.adjudicate_measurement_file(measurements)
    assert decision["disposition"] == "PASS_POSITIVE"


def test_offline_measurement_hash_tamper_refuses(tmp_path: Path):
    output = tmp_path / "terminal.json"
    for pair_rows in pairs():
        for measured_row in pair_rows:
            MODULE.append_measurement_row(output, measured_row, runner_source_sha256="b" * 64)
    measurements = tmp_path / "terminal.measurements.jsonl"
    raw = measurements.read_text(encoding="utf-8")
    measurements.write_text(raw.replace('"loss":2.0', '"loss":2.1', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="MEASUREMENT_ROW_HASH_DRIFT_REFUSED"):
        MODULE.adjudicate_measurement_file(measurements)


def test_refusal_writes_terminal_and_success_exit_does_not(tmp_path: Path):
    refused = tmp_path / "refused" / "terminal.json"
    MODULE.write_terminal_refusal(refused, ValueError("PLANTED"))
    terminal = json.loads(refused.read_text(encoding="utf-8"))
    assert terminal["result"] == "REFUSED"
    assert terminal["refusal_message"] == "PLANTED"
    assert len(terminal["runner_source_sha256"]) == 64
    success = tmp_path / "success" / "terminal.json"
    assert MODULE.write_terminal_refusal(success, SystemExit(0)) is None
    assert not success.exists()
    assert MODULE.write_refusal_from_exception(success, SystemExit(0)) is None
    assert not success.with_name("terminal.refusal.json").exists()


def test_offline_adjudication_writes_bound_terminal(tmp_path: Path):
    output = tmp_path / "terminal.json"
    for pair_rows in pairs():
        for measured_row in pair_rows:
            MODULE.append_measurement_row(output, measured_row, runner_source_sha256="c" * 64)
    assert MODULE.run_offline_adjudication(tmp_path) == 0
    terminal = json.loads(output.read_text(encoding="utf-8"))
    assert terminal["result"] == "PASS_POSITIVE"
    assert terminal["offline_adjudication"] is True
    assert terminal["measurement_row_count"] == 16
    assert terminal["runner_source_sha256"] == "c" * 64
    assert len(terminal["adjudicator_source_sha256"]) == 64


def test_optimizer_structure_census_records_keys_shapes_and_dtypes():
    class Tensor:
        shape = (2, 3)
        dtype = "float32"

    census = MODULE.optimizer_structure_census({"state": {"p0": {"exp_avg": Tensor()}}})
    encoded = json.dumps(census, sort_keys=True)
    assert '"p0"' in encoded
    assert '"shape": [2, 3]' in encoded
    assert '"dtype": "float32"' in encoded


def test_prestart_contract_refuses_each_floor():
    good = {"external_gpu_bytes": 0, "commit_free_bytes": 45 * 1024**3, "c_free_bytes": 150 * 1024**3, "b_free_bytes": 250 * 1024**3}
    MODULE.validate_prestart(good)
    cases = {
        "external_gpu_bytes": 3072 * 1024**2 + 1,
        "commit_free_bytes": 45 * 1024**3 - 1,
        "c_free_bytes": 150 * 1024**3 - 1,
        "b_free_bytes": 1,
    }
    for field, value in cases.items():
        planted = dict(good)
        planted[field] = value
        with pytest.raises(ValueError, match="PRESTART_.*_REFUSED"):
            MODULE.validate_prestart(planted)


def designation_fixture(tmp_path: Path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    manifest = checkpoint / "checkpoint-manifest.json"
    manifest.write_bytes(b"manifest")
    shards = []
    for index in range(7):
        shard = checkpoint / f"shard-{index}.pt"
        shard.write_bytes(f"shard-{index}".encode())
        shards.append({"path": shard.name, "bytes": shard.stat().st_size, "raw_sha256": hashlib.sha256(shard.read_bytes()).hexdigest()})
    value = {
        "schema_version": "ember-issue1947-release-candidate-checkpoint-designation-v1",
        "result": "DESIGNATED",
        "candidate_custody": str(checkpoint),
        "checkpoint_identity": {"admitted_row_set_sha256": MODULE.ADMITTED_ROW_SET_SHA256},
        "manifest": {"path": manifest.name, "bytes": manifest.stat().st_size, "raw_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
        "shards": shards,
    }
    value["self_sha256"] = hashlib.sha256(MODULE.canonical(value)).hexdigest()
    path = tmp_path / "designation.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    published = {"checkpoint_manifest_sha256": value["manifest"]["raw_sha256"]}
    return path, checkpoint, value, published


def test_designation_self_mismatch_refuses(tmp_path: Path):
    path, checkpoint, value, published = designation_fixture(tmp_path)
    with pytest.raises(ValueError, match="DESIGNATION_SELF_HASH_DRIFT_REFUSED"):
        MODULE.validate_designation(
            path, hashlib.sha256(path.read_bytes()).hexdigest(), "0" * 64, checkpoint, published
        )


def test_designation_shard_byte_count_drift_refuses(tmp_path: Path):
    path, checkpoint, value, published = designation_fixture(tmp_path)
    value["shards"][3]["bytes"] += 1
    value.pop("self_sha256")
    value["self_sha256"] = hashlib.sha256(MODULE.canonical(value)).hexdigest()
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="DESIGNATION_SHARD_BYTES_DRIFT_REFUSED"):
        MODULE.validate_designation(
            path, hashlib.sha256(path.read_bytes()).hexdigest(), value["self_sha256"], checkpoint, published
        )


def test_semantic_legacy_cursor_is_exact_and_third_shape_refuses():
    legacy = {
        "global_step": 100, "governor": {}, "receipt_sha256": "a" * 64, "record_index": 100,
        "shard": "TOKEN-SHARDS-V0:" + "a" * 12, "shard_index": 0, "token_offset": 51200,
        "tokenizer_sha256": "b" * 64, "tokens_seen": 51200,
    }
    classified = MODULE.classify_cursor(legacy, "a" * 64, "b" * 64)
    assert classified["cursor_schema"] == "legacy-record-index"
    assert classified["selection_start"] == "semantic-resume"
    assert classified["initial_data_cursor"] == legacy
    runtime = copy.deepcopy(legacy)
    runtime.pop("governor")
    assert MODULE.classify_cursor(runtime, "a" * 64, "b" * 64)["cursor_schema"] == "runtime-bound-record-index"
    with pytest.raises(ValueError, match="DATA_CURSOR_SCHEMA_REFUSED"):
        MODULE.classify_cursor({"global_step": 100, "tokens_seen": 51200}, "a" * 64, "b" * 64)


def test_cursor_that_does_not_restore_exactly_refuses():
    cursor = {
        "global_step": 100, "governor": {}, "receipt_sha256": "a" * 64, "record_index": 100,
        "shard": "TOKEN-SHARDS-V0:" + "a" * 12, "shard_index": 0, "token_offset": 51200,
        "tokenizer_sha256": "b" * 64, "tokens_seen": 51200,
    }
    restored = copy.deepcopy(cursor)
    restored["token_offset"] += 1
    with pytest.raises(ValueError, match="DATA_CURSOR_RESTORE_DRIFT_REFUSED"):
        MODULE.validate_cursor_restoration(cursor, restored, "a" * 64, "b" * 64)


def test_self_hashed_authority_requires_exact_claim():
    value = {"schema_version": "authority-v1", "field": 1}
    value["self_sha256"] = hashlib.sha256(MODULE.canonical(value)).hexdigest()
    MODULE.validate_self_hashed_authority(value, value["self_sha256"], "RUN_SPEC")
    with pytest.raises(ValueError, match="RUN_SPEC_SELF_HASH_DRIFT_REFUSED"):
        MODULE.validate_self_hashed_authority(value, "0" * 64, "RUN_SPEC")


def test_cpu_checkpoint_preflight_executes_loader_and_cursor_contract():
    cursor = {
        "global_step": 100, "governor": {}, "receipt_sha256": "a" * 64, "record_index": 100,
        "shard": "TOKEN-SHARDS-V0:" + "a" * 12, "shard_index": 0, "token_offset": 51200,
        "tokenizer_sha256": "b" * 64, "tokens_seen": 51200,
    }

    class Config:
        def structural_parameter_count(self):
            return 3_839_161_856

    class Model:
        def _activate_expert(self, name):
            assert name == "shared"

    class Packed:
        class RestartDecoderConfig:
            @staticmethod
            def from_contract(path):
                return Config()

        @staticmethod
        def UnifiedDecoder(config, device, allow_production_allocation, genesis_seed):
            assert device == "meta"
            assert allow_production_allocation
            return Model()

        @staticmethod
        def measure_parameter_counts(model):
            return {"unique_parameters": 3_839_161_856, "active_parameters": 1_020_589_568}

    class Torch:
        bfloat16 = "bfloat16"

        @staticmethod
        def get_default_dtype():
            return "float32"

        @staticmethod
        def set_default_dtype(value):
            pass

    called = {"value": False}

    def safe_loader(torch, model, root, receipt):
        called["value"] = True
        return {"data_cursor": copy.deepcopy(cursor), "shards_loaded": 7}

    class Stream:
        receipt_sha256 = "a" * 64
        tokenizer_sha256 = "b" * 64

        @staticmethod
        def next_episode(*, shard_index, token_offset, sequence_length):
            return ({"token_ids": [1] * sequence_length}, {
                "shard_index": shard_index, "token_offset": token_offset + sequence_length,
                "tokens_seen": sequence_length,
            })

    stream = Stream()
    evidence = MODULE.cpu_checkpoint_preflight(
        Packed, Torch, None, Path("checkpoint"), {"data_cursor": cursor}, stream, 2071, Path("config"),
        checkpoint_loader=safe_loader,
    )
    assert called["value"]
    assert evidence["result"] == "PASS"
    assert evidence["cursor_schema"] == "legacy-record-index"
    assert evidence["successor_cursor_schema"] == "runtime-bound-record-index"


def admitted_fixtures():
    designation = {"checkpoint_identity": {"admitted_row_set_sha256": MODULE.ADMITTED_ROW_SET_SHA256}}
    admitted = {
        "result": "VERIFIED_ADMITTED_SUBSET",
        "admitted_row_set_sha256": MODULE.ADMITTED_ROW_SET_SHA256,
        "admitted_row_count": 28,
        "run_manifest_row_count": 28,
    }
    run_spec = {
        "schema_version": "ember-certified-train-run-v1",
        "admitted_row_set_sha256": MODULE.ADMITTED_ROW_SET_SHA256,
    }
    certificate = {
        "schema_version": "ember-spine-certified-declaration-v1",
        "execution_scope": {"allowed_admitted_row_set_sha256": MODULE.ADMITTED_ROW_SET_SHA256},
    }
    return designation, admitted, run_spec, certificate


def test_admitted_set_mismatch_refuses():
    designation, admitted, run_spec, certificate = admitted_fixtures()
    assert MODULE.validate_admitted_set(designation, admitted, run_spec, certificate) == MODULE.ADMITTED_ROW_SET_SHA256
    admitted["admitted_row_set_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="ADMITTED_ROW_SET_IDENTITY_REFUSED"):
        MODULE.validate_admitted_set(designation, admitted, run_spec, certificate)


def test_admitted_count_not_28_refuses():
    designation, admitted, run_spec, certificate = admitted_fixtures()
    admitted["run_manifest_row_count"] = 27
    with pytest.raises(ValueError, match="ADMITTED_ROW_COUNT_REFUSED"):
        MODULE.validate_admitted_set(designation, admitted, run_spec, certificate)


def test_text_lab_corpus_sha_drift_refuses(tmp_path: Path):
    corpus = tmp_path / "owned-text-lab-corpus-v4.json"
    corpus.write_bytes(b"drift")
    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        MODULE.validate_text_lab_corpus(corpus, "0" * 64)


def test_treatment_checkout_accepts_only_exact_four_file_cascade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    status = "\n".join(f" M {path}" for path in sorted(MODULE.CASCADE_ARTIFACT_SHA256)) + "\n"
    monkeypatch.setattr(
        MODULE,
        "sha256_path",
        lambda path: MODULE.CASCADE_ARTIFACT_SHA256[path.relative_to(tmp_path).as_posix()],
    )
    MODULE.validate_treatment_checkout(tmp_path, MODULE.TREATMENT_HEAD, status.encode())
    with pytest.raises(ValueError, match="SOURCE_HEAD_OR_CLEANLINESS_REFUSED"):
        MODULE.validate_treatment_checkout(tmp_path, MODULE.TREATMENT_HEAD, (status + "?? extra.txt\n").encode())


def test_treatment_checkout_refuses_cascade_hash_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    status = "\n".join(f" M {path}" for path in sorted(MODULE.CASCADE_ARTIFACT_SHA256)) + "\n"
    monkeypatch.setattr(MODULE, "sha256_path", lambda path: "0" * 64)
    with pytest.raises(ValueError, match="CASCADE_ARTIFACT_HASH_DRIFT_REFUSED"):
        MODULE.validate_treatment_checkout(tmp_path, MODULE.TREATMENT_HEAD, status.encode())


def test_disk_budget_adapter_binding_is_mandatory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EMBER_DISK_BUDGET_ENV_ASSERTION", raising=False)
    monkeypatch.delenv("EMBER_DISK_BUDGET_ENV_NONCE", raising=False)
    with pytest.raises(ValueError, match="DISK_BUDGET_ADAPTER_BINDING_REFUSED"):
        MODULE.disk_budget_child_binding()
    assertion = tmp_path / "child-env-startup.json"
    payload = {
        "schema_version": 1,
        "nonce": "bound-nonce",
        "bindings": {name: f"B:\\custody\\{name.lower()}" for name in ("TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME")},
    }
    assertion.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("EMBER_DISK_BUDGET_ENV_ASSERTION", str(assertion))
    monkeypatch.setenv("EMBER_DISK_BUDGET_ENV_NONCE", "bound-nonce")
    result = MODULE.disk_budget_child_binding()
    assert result["assertion_sha256"] == hashlib.sha256(assertion.read_bytes()).hexdigest()


def test_real_cuda_measurement_path_writes_control_treatment_pair(tmp_path: Path):
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("real CUDA device is unavailable")

    device = torch.device("cuda")
    accounting = MODULE.prepare_peak_memory_accounting(torch, device)
    assert accounting["mode"] in {
        "reset_peak_memory_stats",
        "zero-baseline-max-memory-allocated",
    }
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    assert 0 < free_bytes <= total_bytes
    torch.cuda.manual_seed_all(2071)

    model = torch.nn.Linear(4, 4, device=device)
    optimizer = torch.optim.SGD(model.parameters(), lr=1e-4)
    census = MODULE.frozen_parameter_census(model)
    receipt_sha256 = "a" * 64
    tokenizer_sha256 = "b" * 64
    cursor = {
        "global_step": 100,
        "receipt_sha256": receipt_sha256,
        "record_index": 100,
        "shard": "TOKEN-SHARDS-V0:" + receipt_sha256[:12],
        "shard_index": 0,
        "token_offset": 51200,
        "tokenizer_sha256": tokenizer_sha256,
        "tokens_seen": 51200,
    }

    class Stream:
        pass

    stream = Stream()
    stream.receipt_sha256 = receipt_sha256
    stream.tokenizer_sha256 = tokenizer_sha256

    class SharedAttention:
        def forward(self):
            return None

    class ModelModule:
        pass

    model_module = ModelModule()
    model_module.SharedAttention = SharedAttention
    methods = {"control": SharedAttention.forward, "treatment": SharedAttention.forward}

    class Pretrain:
        @staticmethod
        def run_manifest_bound_semantic_segment(**kwargs):
            active_model = kwargs["model"]
            active_optimizer = kwargs["optimizer"]
            active_optimizer.zero_grad(set_to_none=True)
            loss = active_model(torch.ones((4, 4), device=kwargs["device"])).square().mean()
            loss.backward()
            active_optimizer.step()
            prior = dict(kwargs["initial_data_cursor"])
            processed = int(kwargs["sequence_length"])
            prior["global_step"] = int(kwargs["initial_global_step"]) + 1
            prior["record_index"] = prior["global_step"]
            prior["token_offset"] = int(prior["token_offset"]) + processed
            prior["tokens_seen"] = int(kwargs["initial_tokens_seen"]) + processed
            return {
                "losses": [float(loss.detach().cpu())],
                "tokens_seen": prior["tokens_seen"],
                "data_cursor": prior,
            }

    initial = MODULE.snapshot_runtime(model, optimizer, cursor)
    rows = []
    output = tmp_path / "terminal.json"
    for arm in ("control", "treatment"):
        restored_cursor = MODULE.restore_runtime(model, optimizer, initial)
        measured, _ = MODULE.run_one_update(
            arm=arm,
            pair=0,
            model=model,
            optimizer=optimizer,
            stream=stream,
            config=None,
            pretrain=Pretrain,
            model_module=model_module,
            methods=methods,
            cursor=restored_cursor,
            census=census,
            backend_identity=("real-cuda-smoke",),
            sequence_length=16,
        )
        measured["start_identity"] = MODULE.state_identity(initial)
        MODULE.append_measurement_row(output, measured, runner_source_sha256="c" * 64)
        rows.append(measured)

    assert [row["arm"] for row in rows] == ["control", "treatment"]
    assert all(row["event_seconds"] > 0 for row in rows)
    assert len(output.with_name("terminal.measurements.jsonl").read_bytes().splitlines()) == 2
    assert torch.cuda.max_memory_allocated(device) >= accounting["baseline_max_memory_allocated_bytes"]
    assert torch.cuda.max_memory_reserved(device) >= 0

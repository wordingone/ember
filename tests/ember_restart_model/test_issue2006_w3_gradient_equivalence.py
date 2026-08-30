# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
from pathlib import Path

import pytest

LOCAL_PATH = Path(__file__).with_name("issue2006_w3_gradient_gate.py")
PATH = LOCAL_PATH if LOCAL_PATH.exists() else Path(__file__).resolve().parents[2] / "tools" / "ember-restart-3b" / "w3_gradient_equivalence.py"
SPEC = importlib.util.spec_from_file_location("issue2006_w3_gradient_gate", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def metric():
    return {
        "shape_equal": True, "dtype_equal": True, "finite_mask_equal": True,
        "zero_mask_equal": True, "cosine_similarity": 1.0, "relative_l2_error": 0.0,
        "elementwise_close": True, "control_sha256": "a" * 64, "treatment_sha256": "a" * 64,
    }


def receipt():
    cases = []
    for case_id, layer, shape, input_seed, upstream_seed, parameter_seed in subject.CASES:
        cases.append({
            "case_id": case_id, "layer": layer, "shape": list(shape), "input_seed": input_seed,
            "upstream_seed": upstream_seed, "parameter_seed": parameter_seed, "expert": "reasoning",
            "forward_byte_identical": True,
            "input_hashes": {
                "cpu_fp32": "1" * 64, "upstream_cpu_fp32": "2" * 64,
                "cuda_bf16": "3" * 64, "upstream_cuda_bf16": "4" * 64,
            },
            "forward_hashes": {"control": "5" * 64, "treatment": "5" * 64},
            "parameter_hashes": {"cpu_fp32": {"up_gate.weight": "b" * 64, "down.weight": "c" * 64}, "cuda_bf16": {"up_gate.weight": "d" * 64, "down.weight": "e" * 64}},
            "gradients": {name: metric() for name in subject.SUBJECTS},
        })
    return {
        "schema": "ember-issue2006-w3-gradient-equivalence/v1", "goal_id": subject.GOAL_ID,
        "workstream_id": subject.WORKSTREAM_ID, "next_executed_outcome": subject.NEXT_OUTCOME,
        "treatment_id": subject.TREATMENT_ID, "dependencies": subject.DEPENDENCIES, "thresholds": subject.THRESHOLDS,
        "cases": cases, "resource": {"wall_seconds": 1.0, "additional_process_commit_bytes": 1, "peak_reserved_vram_bytes": 1},
        "result": "PASS",
    }


def test_exact_contract_accepts():
    assert subject.validate_receipt(receipt()) == []


def test_seed_layer_expert_and_case_count_drift_refuse():
    for mutate in (
        lambda value: value["cases"][0].__setitem__("parameter_seed", 7),
        lambda value: value["cases"][1].__setitem__("layer", 8),
        lambda value: value["cases"][2].__setitem__("expert", "audio"),
        lambda value: value["cases"].pop(),
    ):
        value = receipt(); mutate(value)
        assert subject.validate_receipt(value)


def test_missing_extra_and_bad_gradient_subjects_refuse():
    for mutate in (
        lambda value: value["cases"][0]["gradients"].pop("input_gradient"),
        lambda value: value["cases"][0]["gradients"].__setitem__("extra", metric()),
        lambda value: value["cases"][0]["gradients"]["input_gradient"].__setitem__("zero_mask_equal", False),
        lambda value: value["cases"][0].__setitem__("forward_byte_identical", False),
        lambda value: value["cases"][0]["input_hashes"].pop("upstream_cuda_bf16"),
        lambda value: value["cases"][0]["forward_hashes"].__setitem__("control", "not-a-hash"),
        lambda value: value["cases"][0]["parameter_hashes"]["cpu_fp32"].pop("down.weight"),
    ):
        value = receipt(); mutate(value)
        assert subject.validate_receipt(value)


def test_threshold_treatment_parameter_and_resource_drift_refuse():
    mutations = (
        lambda value: value.__setitem__("thresholds", {**subject.THRESHOLDS, "rtol": 1.0}),
        lambda value: value.__setitem__("treatment_id", "0" * 64),
        lambda value: value["cases"][0].__setitem__("parameter_hashes", {"cpu_fp32": {}}),
        lambda value: value["resource"].__setitem__("wall_seconds", subject.MAX_WALL_SECONDS + 1),
        lambda value: value["resource"].__setitem__("additional_process_commit_bytes", subject.MAX_ADDITIONAL_PROCESS_COMMIT_BYTES + 1),
        lambda value: value["resource"].__setitem__("peak_reserved_vram_bytes", subject.MAX_RESERVED_VRAM_BYTES + 1),
    )
    for mutate in mutations:
        value = receipt(); mutate(value)
        assert subject.validate_receipt(value)


def test_self_hash_ignores_only_self_field():
    value = receipt()
    left = subject.self_hash(value)
    value["self_sha256"] = "x"
    assert subject.self_hash(value) == left
    value["treatment_id"] = "0" * 64
    assert subject.self_hash(value) != left


def test_dependency_files_are_recomputed_and_cross_bound(tmp_path, monkeypatch):
    spec = {"schema_version": "spec", "result": "READY"}
    spec["self_sha256"] = subject.self_hash(spec)
    spec_path = tmp_path / "spec.json"
    spec_path.write_bytes(json.dumps(spec, indent=2, sort_keys=True).encode() + b"\n")

    measurement = {
        "schema_version": "measurement",
        "result": "MEASUREMENT_COMPLETE_PENDING_RESOURCE_FINALIZATION",
        "spec_raw_sha256": subject.file_sha256(spec_path),
        "spec_self_sha256": spec["self_sha256"],
    }
    measurement["self_sha256"] = subject.self_hash(measurement)
    measurement_path = tmp_path / "measurement.json"
    measurement_path.write_bytes(json.dumps(measurement, indent=2, sort_keys=True).encode() + b"\n")

    disk = {"schema_version": 7, "outcome": "PASS"}
    disk_path = tmp_path / "disk.json"
    disk_path.write_bytes(json.dumps(disk, indent=2, sort_keys=True).encode() + b"\n")

    terminal = {
        "schema_version": "terminal",
        "result": "PASS",
        "resource_failures": [],
        "spec_raw_sha256": subject.file_sha256(spec_path),
        "spec_self_sha256": spec["self_sha256"],
        "disk_receipt_raw_sha256": subject.file_sha256(disk_path),
        "measurement": {
            "raw_sha256": subject.file_sha256(measurement_path),
            "self_sha256": measurement["self_sha256"],
        },
    }
    terminal["self_sha256"] = subject.self_hash(terminal)
    terminal_path = tmp_path / "terminal.json"
    terminal_path.write_bytes(json.dumps(terminal, indent=2, sort_keys=True).encode() + b"\n")

    expected = {
        "w3_spec_raw_sha256": subject.file_sha256(spec_path),
        "w3_spec_self_sha256": spec["self_sha256"],
        "w3_measurement_raw_sha256": subject.file_sha256(measurement_path),
        "w3_measurement_self_sha256": measurement["self_sha256"],
        "w3_disk_raw_sha256": subject.file_sha256(disk_path),
        "w3_terminal_raw_sha256": subject.file_sha256(terminal_path),
        "w3_terminal_self_sha256": terminal["self_sha256"],
    }
    monkeypatch.setattr(subject, "DEPENDENCIES", expected)
    paths = {"spec": spec_path, "measurement": measurement_path, "disk": disk_path, "terminal": terminal_path}
    verified = subject.verify_dependency_files(paths)
    assert verified["terminal"]["raw_sha256"] == expected["w3_terminal_raw_sha256"]

    disk_path.write_bytes(disk_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="w3_disk_raw_sha256"):
        subject.verify_dependency_files(paths)

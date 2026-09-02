# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "ember-restart-3b" / "issue898_job_memory_ceiling_probe_verify.py"
SPEC = importlib.util.spec_from_file_location("probe_verify", PATH)
assert SPEC and SPEC.loader
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def _verification() -> dict:
    return {
        "job_object_membership": {"verified": True},
        "process_identity": {"verified": True},
        "lease": {"verified": True},
    }


def _observation(pid: int, maximum: int, target: int, peak: int) -> dict:
    return {
        "schema_version": verify.OBSERVATION_SCHEMA,
        "scope": "windows_job_object",
        "root_pid": pid,
        "offending_pid": pid,
        "maximum_job_memory_bytes": maximum,
        "simulated_peak_commit_bytes": target,
        "peak_job_memory_used_bytes": peak,
        "verification": _verification(),
    }


def _receipt(path: pathlib.Path, *, job: str, delta: int, valid: bool = True) -> pathlib.Path:
    maximum = 1024 * 1024 * 1024
    target = maximum + delta
    pid = 4100 if delta < 0 else 4200
    peak = target if delta < 0 else maximum
    accounting = _observation(pid, maximum, target, peak)
    accounting["limit_signal_observed"] = delta > 0
    events = [{"kind": "job_memory_accounting", "payload": accounting}]
    if delta > 0:
        limit = _observation(pid, maximum, target, peak)
        limit["kernel_message_code"] = verify.JOB_OBJECT_MSG_JOB_MEMORY_LIMIT
        limit["signal_latched"] = valid
        events.insert(0, {"kind": "job_memory_limit_reached", "payload": limit})
    path.write_text(
        json.dumps(
            {
                "schema": verify.OPERATIONAL_SCHEMA,
                "job_id": job,
                "pid": pid,
                "state": "exited",
                "exit_code": 0 if delta < 0 else 137,
                "logs": {
                    "stdout": {"sealed": True, "sha256": "a" * 64},
                    "stderr": {"sealed": True, "sha256": "b" * 64},
                },
                "events": events,
                "scientific_capability_evidence": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_paired_control_and_death_leg_pass(tmp_path: pathlib.Path) -> None:
    maximum = 1024 * 1024 * 1024
    negative = _receipt(tmp_path / "negative.json", job="negative", delta=-(32 * 1024 * 1024))
    positive = _receipt(tmp_path / "positive.json", job="positive", delta=32 * 1024 * 1024)
    verdict = verify.compose_verdict(
        negative,
        positive,
        maximum=maximum,
        maximum_absolute_delta=64 * 1024 * 1024,
        negative_delta=-(32 * 1024 * 1024),
        positive_delta=32 * 1024 * 1024,
    )
    assert verdict["verdict"] == "PASS"
    assert [leg["leg"] for leg in verdict["legs"]] == ["negative_control", "positive_death"]


@pytest.mark.parametrize("defect", ["noop", "signal", "custody", "same_job"])
def test_any_missing_discriminator_is_inconclusive(tmp_path: pathlib.Path, defect: str) -> None:
    maximum = 1024 * 1024 * 1024
    negative_delta = -(32 * 1024 * 1024)
    positive_delta = 32 * 1024 * 1024
    negative = _receipt(tmp_path / "negative.json", job="negative", delta=negative_delta)
    positive = _receipt(tmp_path / "positive.json", job="positive", delta=positive_delta)
    if defect == "noop":
        data = json.loads(negative.read_text(encoding="utf-8"))
        data["events"][0]["payload"]["peak_job_memory_used_bytes"] = 1
        negative.write_text(json.dumps(data), encoding="utf-8")
    elif defect == "signal":
        data = json.loads(positive.read_text(encoding="utf-8"))
        data["events"][0]["payload"]["signal_latched"] = False
        positive.write_text(json.dumps(data), encoding="utf-8")
    elif defect == "custody":
        data = json.loads(positive.read_text(encoding="utf-8"))
        data["events"][0]["payload"]["verification"]["lease"]["verified"] = False
        positive.write_text(json.dumps(data), encoding="utf-8")
    else:
        data = json.loads(positive.read_text(encoding="utf-8"))
        data["job_id"] = "negative"
        positive.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(verify.Inconclusive):
        verify.compose_verdict(
            negative,
            positive,
            maximum=maximum,
            maximum_absolute_delta=64 * 1024 * 1024,
            negative_delta=negative_delta,
            positive_delta=positive_delta,
        )


def test_cli_refuses_overwrite(tmp_path: pathlib.Path) -> None:
    maximum = 1024 * 1024 * 1024
    negative_delta = -(32 * 1024 * 1024)
    positive_delta = 32 * 1024 * 1024
    negative = _receipt(tmp_path / "negative.json", job="negative", delta=negative_delta)
    positive = _receipt(tmp_path / "positive.json", job="positive", delta=positive_delta)
    output = tmp_path / "verdict.json"
    output.write_text("custody", encoding="utf-8")
    assert verify.main([
        "--negative-receipt", str(negative),
        "--positive-receipt", str(positive),
        "--maximum-job-memory-bytes", str(maximum),
        "--maximum-absolute-delta-bytes", str(64 * 1024 * 1024),
        "--negative-delta-bytes", str(negative_delta),
        "--positive-delta-bytes", str(positive_delta),
        "--output", str(output),
    ]) == 2
    assert output.read_text(encoding="utf-8") == "custody"

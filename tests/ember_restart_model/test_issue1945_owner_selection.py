# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "issue1945_owner_selection.py"


def load_subject():
    spec = importlib.util.spec_from_file_location("issue1945_owner_selection", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_self(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> str:
    body = dict(payload)
    body["self_sha256"] = canonical_self(body)
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path: Path) -> dict[str, Path | str]:
    ledger = tmp_path / "ledger.json"
    ledger_raw = write_json(
        ledger,
        {
            "schema_version": "ember-issue2024-union-measurement-v1",
            "mode": "issue2024-union-one-shot",
            "result": "PASS",
            "identity": {"execution_source_commit": "5" * 40},
            "kernel_trace": {
                "full_precision_unmapped_event_ledger": {
                    "schema_version": "ember-issue2024-full-precision-event-ledger-v2",
                    "declared_self_device_time_total_us": "100.0",
                    "ledger_self_device_time_total_us": "100.0",
                    "excluded_self_device_time_total_us": "0",
                    "excluded_zero_device_time_events": [],
                    "reconciliation_gap_ns": 0,
                    "events": [
                        {
                            "event_id": 1,
                            "event_ordinal": 0,
                            "self_device_time_us": "60.0",
                            "source_stack": [
                                "model.py(272): apply",
                                "model.py(299): forward",
                                "packed_specialist_run.py(2874): main",
                            ],
                        },
                        {
                            "event_id": 2,
                            "event_ordinal": 1,
                            "self_device_time_us": "40.0",
                            "source_stack": [
                                "model.py(299): forward",
                                "packed_specialist_run.py(2874): main",
                            ],
                        },
                    ],
                }
            },
        },
    )
    offline = tmp_path / "offline.json"
    offline_raw = write_json(
        offline,
        {
            "schema_version": "ember-issue2024-union-measurement-v1",
            "mode": "issue2024-union-one-shot",
            "result": "PASS",
            "identity": {"execution_source_commit": "5" * 40},
            "kernel_trace": {
                "offline_trace_derivation": {
                    "parent_measurement_raw_sha256": ledger_raw,
                    "parent_measurement_self_sha256": json.loads(ledger.read_text())["self_sha256"],
                }
            },
        },
    )
    comparison = tmp_path / "comparison.json"
    comparison_raw = write_json(
        comparison,
        {
            "schema_version": "ember-issue2024-union-comparison-v1",
            "execution_source_commit": "5" * 40,
            "one_shot_raw_sha256": offline_raw,
            "one_shot_self_sha256": json.loads(offline.read_text())["self_sha256"],
            "one_shot_only_structural_count": 0,
            "sharded_only_structural_count": 0,
            "result": "PASS",
        },
    )
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "schema_version": "ember-issue1945-source-owner-allowlist-v1",
                "source_rules": [
                    {"basename": "model.py", "class": "non_overhead"},
                    {"basename": "pretrain.py", "class": "overhead"},
                    {"basename": "packed_specialist_run.py", "class": "overhead"},
                ],
                "mapping_rule": "FIRST_STACK_FRAME_MATCHING_EXACTLY_ONE_DECLARED_BASENAME",
                "selection_rule": "MAX_ATTRIBUTED_NON_OVERHEAD_DEVICE_TIME_THEN_LEXICAL_SOURCE_SITE",
                "minimum_named_attribution_ratio": "0.99",
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return {
        "ledger": ledger,
        "ledger_raw": ledger_raw,
        "offline": offline,
        "comparison": comparison,
        "comparison_raw": comparison_raw,
        "allowlist": allowlist,
    }


def build(subject, fx: dict[str, Path | str]) -> dict[str, object]:
    return subject.build_receipt(
        ledger_path=fx["ledger"],
        ledger_raw_sha256=fx["ledger_raw"],
        offline_path=fx["offline"],
        comparison_path=fx["comparison"],
        comparison_raw_sha256=fx["comparison_raw"],
        allowlist_path=fx["allowlist"],
        source_master="9" * 40,
        argv=["issue1945-owner-select", "--fixture"],
    )


def test_exact_terminal_fixture_maps_every_event_and_selects_deterministically(tmp_path: Path) -> None:
    subject = load_subject()
    receipt = build(subject, fixture(tmp_path))

    assert receipt["result"] == "PASS"
    assert receipt["event_count"] == 2
    assert receipt["mapped_event_count"] == 2
    assert receipt["unmapped_device_time_us"] == "0"
    assert receipt["named_attribution_ratio"] == "1"
    assert receipt["selected_source_site"] == "model.py(272): apply"
    assert receipt["selected_source_device_time_us"] == "60.0"
    assert receipt["claim_boundary"] == "ATTRIBUTION_AND_SELECTION_ONLY_NO_TREATMENT_SPEEDUP_20K_CREDIT"
    assert receipt["self_sha256"] == canonical_self({k: v for k, v in receipt.items() if k != "self_sha256"})


@pytest.mark.parametrize("drift", ["ledger_hash", "comparison_hash", "link", "count", "gap"])
def test_hash_link_count_and_gap_drift_are_deliberate_red(tmp_path: Path, drift: str) -> None:
    subject = load_subject()
    fx = fixture(tmp_path)
    if drift == "ledger_hash":
        fx["ledger_raw"] = "0" * 64
    elif drift == "comparison_hash":
        fx["comparison_raw"] = "0" * 64
    elif drift == "link":
        body = json.loads(Path(fx["offline"]).read_text())
        body["kernel_trace"]["offline_trace_derivation"]["parent_measurement_raw_sha256"] = "0" * 64
        write_json(Path(fx["offline"]), {k: v for k, v in body.items() if k != "self_sha256"})
    else:
        body = json.loads(Path(fx["ledger"]).read_text())
        event_ledger = body["kernel_trace"]["full_precision_unmapped_event_ledger"]
        if drift == "count":
            event_ledger["declared_self_device_time_total_us"] = "101.0"
        else:
            event_ledger["reconciliation_gap_ns"] = 2
        fx["ledger_raw"] = write_json(Path(fx["ledger"]), {k: v for k, v in body.items() if k != "self_sha256"})
    with pytest.raises(ValueError):
        build(subject, fx)


@pytest.mark.parametrize("drift", ["zero_candidate", "ambiguous_site", "threshold", "unmapped_time"])
def test_mapping_threshold_and_unmapped_time_are_deliberate_red(tmp_path: Path, drift: str) -> None:
    subject = load_subject()
    fx = fixture(tmp_path)
    if drift == "ambiguous_site":
        allowlist = json.loads(Path(fx["allowlist"]).read_text())
        allowlist["source_rules"].append({"basename": "model.py", "class": "non_overhead"})
        Path(fx["allowlist"]).write_text(json.dumps(allowlist, separators=(",", ":")))
    else:
        body = json.loads(Path(fx["ledger"]).read_text())
        event_ledger = body["kernel_trace"]["full_precision_unmapped_event_ledger"]
        if drift == "zero_candidate":
            event_ledger["events"][0]["source_stack"] = ["torch/nn/functional.py(1): x"]
        elif drift == "threshold":
            event_ledger["events"][0]["self_device_time_us"] = "0.1"
            event_ledger["ledger_self_device_time_total_us"] = "100.0"
            event_ledger["declared_self_device_time_total_us"] = "100.0"
        else:
            event_ledger["excluded_self_device_time_total_us"] = "1.0"
        fx["ledger_raw"] = write_json(Path(fx["ledger"]), {k: v for k, v in body.items() if k != "self_sha256"})
        offline = json.loads(Path(fx["offline"]).read_text())
        offline["kernel_trace"]["offline_trace_derivation"]["parent_measurement_raw_sha256"] = fx["ledger_raw"]
        offline["kernel_trace"]["offline_trace_derivation"]["parent_measurement_self_sha256"] = json.loads(Path(fx["ledger"]).read_text())["self_sha256"]
        offline_raw = write_json(Path(fx["offline"]), {k: v for k, v in offline.items() if k != "self_sha256"})
        comparison = json.loads(Path(fx["comparison"]).read_text())
        comparison["one_shot_raw_sha256"] = offline_raw
        comparison["one_shot_self_sha256"] = json.loads(Path(fx["offline"]).read_text())["self_sha256"]
        fx["comparison_raw"] = write_json(Path(fx["comparison"]), {k: v for k, v in comparison.items() if k != "self_sha256"})
    with pytest.raises(ValueError):
        build(subject, fx)


def test_selection_uses_lexical_source_site_tie_break(tmp_path: Path) -> None:
    subject = load_subject()
    fx = fixture(tmp_path)
    body = json.loads(Path(fx["ledger"]).read_text())
    events = body["kernel_trace"]["full_precision_unmapped_event_ledger"]["events"]
    events[0]["self_device_time_us"] = "50.0"
    events[1]["self_device_time_us"] = "50.0"
    fx["ledger_raw"] = write_json(Path(fx["ledger"]), {k: v for k, v in body.items() if k != "self_sha256"})
    offline = json.loads(Path(fx["offline"]).read_text())
    offline["kernel_trace"]["offline_trace_derivation"]["parent_measurement_raw_sha256"] = fx["ledger_raw"]
    offline["kernel_trace"]["offline_trace_derivation"]["parent_measurement_self_sha256"] = json.loads(Path(fx["ledger"]).read_text())["self_sha256"]
    offline_raw = write_json(Path(fx["offline"]), {k: v for k, v in offline.items() if k != "self_sha256"})
    comparison = json.loads(Path(fx["comparison"]).read_text())
    comparison["one_shot_raw_sha256"] = offline_raw
    comparison["one_shot_self_sha256"] = json.loads(Path(fx["offline"]).read_text())["self_sha256"]
    fx["comparison_raw"] = write_json(Path(fx["comparison"]), {k: v for k, v in comparison.items() if k != "self_sha256"})

    receipt = build(subject, fx)
    assert receipt["selected_source_site"] == "model.py(272): apply"

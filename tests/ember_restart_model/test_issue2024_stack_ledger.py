# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import packed_specialist_run as subject  # noqa: E402


def _event(
    *,
    event_id: int = 7,
    parent_id: int = 3,
    device_time_us: str = "10.000001",
    stack: tuple[str, ...] = ("src/ember/model/model.py:41",),
    parent_stack: tuple[str, ...] = (),
    has_parent: bool = True,
    has_shapes: bool = True,
) -> SimpleNamespace:
    parent = SimpleNamespace(id=parent_id, stack=list(parent_stack), cpu_parent=None)
    return SimpleNamespace(
        id=event_id,
        key="aten::mm",
        cpu_parent=parent if has_parent else None,
        input_shapes=[[2, 3], [3, 4]] if has_shapes else None,
        self_device_time_total=float(device_time_us),
        stack=list(stack),
    )


def test_issue2024_profiler_configuration_enables_source_stacks() -> None:
    configuration = subject.issue2024_profiler_configuration()
    assert configuration["profile_memory"] is True
    assert configuration["record_shapes"] is True
    assert configuration["with_stack"] is True
    assert isinstance(
        configuration["experimental_config"],
        subject.torch._C._profiler._ExperimentalConfig,
    )


def test_issue2024_profiler_configuration_emits_runtime_source_stacks() -> None:
    torch = subject.torch
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        **subject.issue2024_profiler_configuration(),
    ) as profiler:
        value = torch.ones((2, 2))
        value @ value

    assert any(event.stack for event in profiler.events())


def test_issue2024_live_schedule_streams_each_frozen_update_as_one_trace_callback() -> None:
    callback_count = 0

    def count_trace(_profiler: object) -> None:
        nonlocal callback_count
        callback_count += 1

    torch = subject.torch
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        schedule=subject.issue2024_streaming_profiler_schedule(list(range(16, 24))),
        on_trace_ready=count_trace,
        profile_memory=True,
        record_shapes=True,
        with_stack=True,
    ) as profiler:
        for _ in range(24):
            value = torch.ones((2, 2))
            value @ value
            profiler.step()

    assert callback_count == 8


def test_issue2024_streaming_ledger_union_preserves_shard_identity_and_exact_sum() -> None:
    first = subject.build_issue2024_event_ledger(
        [_event(event_id=7, device_time_us="10.000001")],
        declared_self_device_time_total_us="10.000001",
    )
    second = subject.build_issue2024_event_ledger(
        [_event(event_id=7, device_time_us="2.000002")],
        declared_self_device_time_total_us="2.000002",
    )
    merged = subject.merge_issue2024_event_ledger_shards([(16, first), (17, second)])
    assert merged["profile_update_indexes"] == [16, 17]
    assert merged["declared_self_device_time_total_us"] == "12.000003"
    assert merged["ledger_self_device_time_total_us"] == "12.000003"
    assert merged["reconciliation_gap_ns"] == 0
    assert [(row["profile_update_index"], row["event_id"]) for row in merged["events"]] == [
        (16, 7),
        (17, 7),
    ]


def test_issue2024_offline_trace_parser_preserves_union_structural_key(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps({"traceEvents": [
        {
            "ph": "X", "cat": "user_annotation", "name": subject.COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
            "pid": 4, "tid": 8, "ts": 10, "dur": 100, "args": {"External id": 1},
        },
        {
            "ph": "X", "cat": "cpu_op", "name": "aten::gather",
            "pid": 4, "tid": 8, "ts": 20, "dur": 20,
            "args": {
                "External id": 7,
                "Input Dims": [[32000, 2048], [], [960, 2048]],
                "Call stack": "model.py(1): forward;packed_specialist_run.py(2): main;",
            },
        },
        {
            "ph": "X", "cat": "kernel", "name": "gather_kernel",
            "pid": 0, "tid": 7, "ts": 25, "dur": 4.544,
            "args": {"External id": 7},
        },
    ]}), encoding="utf-8")

    ledger = subject.build_issue2024_event_ledger_from_trace(
        trace, hidden=2048, vocab_size=32000,
    )

    assert ledger["reconciliation_gap_ns"] == 0
    assert ledger["events"] == [{
        "ancestry_depth": 1,
        "cpu_parent_id": 7,
        "event_id": 7,
        "event_ordinal": 0,
        "input_shapes": [[32000, 2048], [], [960, 2048]],
        "key": "aten::gather",
        "self_device_time_us": "4.544",
        "source_stack": ["model.py(1): forward", "packed_specialist_run.py(2): main"],
    }]
def test_issue2024_union_proof_modes_bind_same_two_updates_to_distinct_collection_paths() -> None:
    assert subject.issue2024_profile_mode("issue2024-union-one-shot") == {
        "policy_mode": "issue1946-arm-a",
        "output_name": "issue2024-union-one-shot-stack-ledger.json",
    }
    assert subject.issue2024_profile_mode("issue2024-union-sharded") == {
        "policy_mode": "issue1946-arm-a",
        "output_name": "issue2024-union-sharded-stack-ledger.json",
    }
    expected = {"packs": 2, "wait": 0, "active": 2, "update_indexes": [0, 1]}
    assert subject.issue2024_profile_schedule(
        "issue2024-union-one-shot", "issue1946-arm-a"
    ) == expected
    assert subject.issue2024_profile_schedule(
        "issue2024-union-sharded", "issue1946-arm-a"
    ) == expected
    assert subject.issue2024_uses_streaming_schedule("issue2024-union-one-shot") is False
    assert subject.issue2024_uses_streaming_schedule("issue2024-union-sharded") is True


def test_issue2024_ledger_preserves_event_identity_and_reconciles_within_one_ns() -> None:
    ledger = subject.build_issue2024_event_ledger(
        [_event(), _event(event_id=8, parent_id=7, device_time_us="2.000002")],
        declared_self_device_time_total_us="12.000003",
    )
    assert ledger == {
        "schema_version": "ember-issue2024-full-precision-event-ledger-v1",
        "declared_self_device_time_total_us": "12.000003",
        "ledger_self_device_time_total_us": "12.000003",
        "excluded_self_device_time_total_us": "0",
        "excluded_zero_device_time_events": [],
        "reconciliation_gap_ns": 0,
        "events": [
            {
                "ancestry_depth": 1,
                "cpu_parent_id": 3,
                "event_id": 7,
                "event_ordinal": 0,
                "input_shapes": [[2, 3], [3, 4]],
                "key": "aten::mm",
                "self_device_time_us": "10.000001",
                "source_stack": ["src/ember/model/model.py:41"],
            },
            {
                "ancestry_depth": 1,
                "cpu_parent_id": 7,
                "event_id": 8,
                "event_ordinal": 1,
                "input_shapes": [[2, 3], [3, 4]],
                "key": "aten::mm",
                "self_device_time_us": "2.000002",
                "source_stack": ["src/ember/model/model.py:41"],
            },
        ],
    }


def test_issue2024_ledger_refuses_event_without_source_stack() -> None:
    with pytest.raises(ValueError, match="ISSUE2024_EVENT_SOURCE_STACK_REQUIRED"):
        subject.build_issue2024_event_ledger(
            [_event(stack=())], declared_self_device_time_total_us="10.000001"
        )


def test_issue2024_ledger_accounts_for_zero_device_time_events_without_metadata() -> None:
    ledger = subject.build_issue2024_event_ledger(
        [
            _event(
                event_id=6,
                device_time_us="0",
                stack=(),
                has_parent=False,
                has_shapes=False,
            ),
            _event(),
        ],
        declared_self_device_time_total_us="10.000001",
    )
    assert ledger["excluded_zero_device_time_events"] == [
        {
            "event_id": 6,
            "event_ordinal": 0,
            "key": "aten::mm",
            "reason": "ZERO_SELF_DEVICE_TIME",
            "self_device_time_us": "0.0",
        }
    ]
    assert ledger["excluded_self_device_time_total_us"] == "0"


def test_issue2024_ledger_reports_every_positive_time_metadata_violation_together() -> None:
    with pytest.raises(ValueError) as caught:
        subject.build_issue2024_event_ledger(
            [
                _event(event_id=11, stack=()),
                _event(event_id=12, has_parent=False),
                _event(event_id=13, has_shapes=False),
            ],
            declared_self_device_time_total_us="30.000003",
        )
    message = str(caught.value)
    assert message.startswith("ISSUE2024_EVENT_METADATA_REFUSED:")
    assert '"event_id":11' in message
    assert '"failure_class":"ISSUE2024_EVENT_SOURCE_STACK_REQUIRED"' in message
    assert '"ancestry_depth":2' in message
    assert '"event_id":12' in message
    assert '"failure_class":"ISSUE2024_EVENT_CPU_PARENT_REQUIRED"' in message
    assert '"event_id":13' in message
    assert '"failure_class":"ISSUE2024_EVENT_INPUT_SHAPES_REQUIRED"' in message


def test_issue2024_ledger_inherits_source_stack_from_cpu_parent_for_device_event() -> None:
    ledger = subject.build_issue2024_event_ledger(
        [_event(stack=(), parent_stack=("src/ember/model/model.py:99",))],
        declared_self_device_time_total_us="10.000001",
    )
    assert ledger["events"][0]["source_stack"] == [
        "src/ember/model/model.py:99"
    ]


def test_issue2024_ledger_refuses_reconciliation_gap_above_one_ns() -> None:
    with pytest.raises(ValueError, match="ISSUE2024_EVENT_RECONCILIATION_MISS"):
        subject.build_issue2024_event_ledger(
            [_event()], declared_self_device_time_total_us="10.002001"
        )


def test_issue2024_live_modes_bind_predecessor_policy_and_unique_outputs() -> None:
    assert subject.issue2024_profile_mode("issue2024-smoke") == {
        "policy_mode": "issue1946-arm-a",
        "output_name": "issue2024-smoke-stack-ledger.json",
    }
    assert subject.issue2024_profile_mode("issue2024-arm-a") == {
        "policy_mode": "issue1946-arm-a",
        "output_name": "issue2024-arm-a-stack-ledger.json",
    }
    assert subject.issue2024_profile_mode("issue2024-arm-b") == {
        "policy_mode": "issue1946-arm-b",
        "output_name": "issue2024-arm-b-stack-ledger.json",
    }
    with pytest.raises(ValueError, match="unknown #2024 profile mode"):
        subject.issue2024_profile_mode("issue2024-preflight")


def test_every_profile_mode_is_reachable_from_the_argument_parser() -> None:
    parser = subject._build_argument_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, subject.argparse._SubParsersAction)
    )
    assert set(subject.ISSUE_PROFILE_MODES) <= set(subparsers.choices)
    assert "issue2024-smoke" in subparsers.choices
    for mode in subject.ISSUE_PROFILE_MODES:
        policy_mode = (
            subject.issue2024_profile_mode(mode)["policy_mode"]
            if mode.startswith("issue2024-")
            else mode
        )
        options = {
            option
            for action in subparsers.choices[mode]._actions
            for option in action.option_strings
        }
        assert ("--preflight-receipt" in options) is (
            policy_mode == "issue1946-arm-a"
        )
        assert ("--arm-a-receipt" in options) is (
            policy_mode == "issue1946-arm-b"
        )


def test_main_dispatches_every_mode_from_the_profile_mode_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic_mode = "issue2099-smoke"
    monkeypatch.setattr(
        subject,
        "ISSUE_PROFILE_MODES",
        (*subject.ISSUE_PROFILE_MODES, synthetic_mode),
    )
    args = SimpleNamespace(command=synthetic_mode, artifact_root=Path("unused"))
    parser = SimpleNamespace(parse_args=lambda: args)
    calls: list[tuple[SimpleNamespace, str]] = []
    monkeypatch.setattr(subject, "_build_argument_parser", lambda: parser)
    monkeypatch.setattr(
        subject,
        "run_issue1946_profile",
        lambda parsed, *, mode: calls.append((parsed, mode)) or {"result": "PASS"},
    )

    assert subject.main() == 0
    assert calls == [(args, synthetic_mode)]


def test_issue2024_profile_configuration_is_selected_only_for_successor_modes() -> None:
    assert subject.profiler_configuration_for_mode("issue2024-smoke")["with_stack"] is True
    assert subject.profiler_configuration_for_mode("issue2024-arm-a")["with_stack"] is True
    assert subject.profiler_configuration_for_mode("issue2024-arm-b")["with_stack"] is True
    assert subject.profiler_configuration_for_mode("issue1946-arm-a")["with_stack"] is False


def test_issue2024_smoke_reaches_trace_callback_on_the_first_update() -> None:
    assert subject.issue2024_profile_schedule("issue2024-smoke", "issue1946-arm-a") == {
        "packs": 1,
        "wait": 0,
        "active": 1,
        "update_indexes": [0],
    }
    assert subject.issue2024_profile_schedule("issue2024-arm-a", "issue1946-arm-a") == {
        "packs": 64,
        "wait": 16,
        "active": 8,
        "update_indexes": list(range(16, 24)),
    }


def test_issue2024_ledger_preserves_duplicate_profiler_correlation_ids_by_ordinal() -> None:
    ledger = subject.build_issue2024_event_ledger(
        [_event(), _event()], declared_self_device_time_total_us="20.000002"
    )
    assert [(row["event_id"], row["event_ordinal"]) for row in ledger["events"]] == [
        (7, 0),
        (7, 1),
    ]


def test_issue2024_ledger_refuses_doubly_enumerated_events_by_reconciliation() -> None:
    events = [_event(), _event(event_id=8, device_time_us="2.000002")]
    with pytest.raises(ValueError, match="ISSUE2024_EVENT_RECONCILIATION_MISS"):
        subject.build_issue2024_event_ledger(
            [*events, *events], declared_self_device_time_total_us="12.000003"
        )


def _union_receipt(mode: str, events: list[dict[str, object]]) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "ember-issue2024-union-measurement-v1",
        "result": "PASS",
        "mode": mode,
        "claim_boundary": "UNION_COMPLETENESS_PROOF_ONLY_NO_FULL_ARM_OR_CLOSE_CREDIT",
        "identity": {
            "execution_source_commit": "a" * 40,
            "execution_record_order_sha256": "b" * 64,
            "execution_tokens_sha256": "c" * 64,
            "seed": 83,
        },
        "profiler_update_indexes": [0, 1],
        "kernel_trace": {
            "full_precision_unmapped_event_ledger": {
                "schema_version": "ember-issue2024-full-precision-event-ledger-v1",
                "events": events,
            },
            "offline_trace_derivation": {"parser_source_sha256": "f" * 64},
        },
        "runtime_custody": {
            "preflight_raw_sha256": "d" * 64,
            "preflight_self_sha256": "e" * 64,
        },
    }
    receipt["self_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return receipt


def _union_event(*, time: str = "10.0", stack: str = "model.py:41") -> dict[str, object]:
    return {
        "ancestry_depth": 2,
        "cpu_parent_id": 3,
        "event_id": 7,
        "input_shapes": [[2, 3], [3, 4]],
        "key": "aten::mm",
        "profile_update_index": 0,
        "self_device_time_us": time,
        "source_stack": [stack],
    }


def _offline_trace_and_parent(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps({"traceEvents": [
        {
            "ph": "X", "cat": "user_annotation",
            "name": subject.COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
            "pid": 4, "tid": 8, "ts": 10, "dur": 100,
            "args": {"External id": 1},
        },
        {
            "ph": "X", "cat": "cpu_op", "name": "aten::gather",
            "pid": 4, "tid": 8, "ts": 20, "dur": 20,
            "args": {
                "External id": 7,
                "Input Dims": [[32000, 2048], [], [960, 2048]],
                "Call stack": "model.py(1): forward;packed_specialist_run.py(2): main;",
            },
        },
        {
            "ph": "X", "cat": "kernel", "name": "gather_kernel",
            "pid": 0, "tid": 7, "ts": 25, "dur": 4.544,
            "args": {"External id": 7},
        },
    ]}), encoding="utf-8")
    parent = _union_receipt("issue2024-union-one-shot", [_union_event()])
    parent["kernel_trace"] = {
        "sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "material_linear_shapes": [
            {"fprop": [64, 15, 2048, 6144]},
            {"fprop": [64, 15, 2048, 6144]},
            {"fprop": [64, 15, 2048, 6144]},
            {"fprop": [64, 15, 2048, 6144]},
            {"fprop": [64, 15, 2048, 32000]},
        ],
    }
    parent["self_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in parent.items() if key != "self_sha256"},
            sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return trace, parent


def test_issue2024_offline_derive_uses_real_material_linear_shape_ordering(
    tmp_path: Path,
) -> None:
    trace, parent = _offline_trace_and_parent(tmp_path)
    receipt = subject.derive_issue2024_offline_measurement_receipt(
        parent, parent_raw_sha256="a" * 64, trace_path=trace,
    )

    derivation = receipt["kernel_trace"]["offline_trace_derivation"]
    assert derivation["parser_source_sha256"] == hashlib.sha256(
        Path(subject.__file__).read_bytes()
    ).hexdigest()
    assert receipt["kernel_trace"]["full_precision_unmapped_event_ledger"]["events"][0][
        "input_shapes"
    ] == [[32000, 2048], [], [960, 2048]]


def test_issue2024_offline_derive_refuses_trace_sha_binding_mismatch(tmp_path: Path) -> None:
    trace, parent = _offline_trace_and_parent(tmp_path)
    parent["kernel_trace"]["sha256"] = "0" * 64
    parent["self_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in parent.items() if key != "self_sha256"},
            sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="ISSUE2024_OFFLINE_TRACE_BINDING_MISMATCH"):
        subject.derive_issue2024_offline_measurement_receipt(
            parent, parent_raw_sha256="a" * 64, trace_path=trace,
        )


def _shard_receipt(
    index: int,
    *,
    parser_source_sha256: str = "f" * 64,
    stack: tuple[str, ...] = ("src/ember/model/model.py:41",),
    key: str = "aten::mm",
    input_shapes: list[list[int]] | None = None,
) -> dict[str, object]:
    event = _event(event_id=7 + index, device_time_us="1.0", stack=stack)
    event.key = key
    if input_shapes is not None:
        event.input_shapes = input_shapes
    ledger = subject.build_issue2024_event_ledger(
        [event],
        declared_self_device_time_total_us="1.0",
    )
    return subject.build_issue2024_union_shard_receipt(
        profile_update_index=index,
        identity={"execution_source_commit": "a" * 40},
        update_seconds=[1.0, 2.0],
        phase_seconds=[{"index": 0}, {"index": 1}],
        allocator_rows=[{"index": 0}, {"index": 1}],
        power_rows=[{"index": 0}, {"index": 1}],
        kernel_trace={
            "sha256": str(index + 1) * 64,
            "layer_count": 12,
            "material_linear_shapes": [{"fprop": [64, 15, 2048, 6144]}] * 5,
            "observed_kernels": [],
            "full_precision_unmapped_event_ledger": ledger,
        },
        checkpoint_cadence={
            "in_measured_window": "NONE",
            "checkpoint_every_updates": 3,
            "callback_identity": "NO_OP",
            "final_callback_timed": False,
        },
        runtime_custody={
            "preflight_raw_sha256": "d" * 64,
            "preflight_self_sha256": "e" * 64,
            "ledger_derivation": {
                "method": "STREAMING_OFFLINE_CHROME_TRACE_PARSER_V1",
                "parser_source_sha256": parser_source_sha256,
            },
        },
    )


def test_issue2024_two_fresh_process_shards_merge_to_terminal_union_receipt() -> None:
    shard_0 = _shard_receipt(0)
    shard_1 = _shard_receipt(1)
    merged = subject.merge_issue2024_union_shard_receipts([
        (shard_0, "8" * 64),
        (shard_1, "9" * 64),
    ])
    assert merged["result"] == "PASS"
    assert merged["mode"] == "issue2024-union-sharded"
    assert merged["profiler_update_indexes"] == [0, 1]
    assert merged["update_seconds"] == [1.0, 2.0]
    assert [row["profile_update_index"] for row in merged["kernel_trace"]["full_precision_unmapped_event_ledger"]["events"]] == [0, 1]
    assert [row["receipt_raw_sha256"] for row in merged["runtime_custody"]["offline_trace_shards"]] == ["8" * 64, "9" * 64]
    assert merged["kernel_trace"]["offline_trace_derivation"] == {
        "method": "MERGED_TWO_SHARD_STREAMING_OFFLINE_CHROME_TRACE_PARSER_V1",
        "parser_source_sha256": "f" * 64,
        "shard_trace_raw_sha256": ["1" * 64, "2" * 64],
    }


def test_issue2024_shard_merge_refuses_offline_parser_identity_drift() -> None:
    with pytest.raises(ValueError, match="ISSUE2024_SHARD_PARSER_MISMATCH"):
        subject.merge_issue2024_union_shard_receipts([
            (_shard_receipt(0, parser_source_sha256="f" * 64), "8" * 64),
            (_shard_receipt(1, parser_source_sha256="0" * 64), "9" * 64),
        ])


def test_issue2024_real_merge_output_compares_with_offline_derived_one_shot(
    tmp_path: Path,
) -> None:
    parser_source_sha256 = hashlib.sha256(Path(subject.__file__).read_bytes()).hexdigest()
    sharded = subject.merge_issue2024_union_shard_receipts([
        (
            _shard_receipt(
                0,
                parser_source_sha256=parser_source_sha256,
                stack=("model.py(1): forward",),
                key="aten::gather",
                input_shapes=[[32000, 2048], [], [960, 2048]],
            ),
            "8" * 64,
        ),
        (
            _shard_receipt(
                1,
                parser_source_sha256=parser_source_sha256,
                stack=("model.py(1): forward",),
                key="aten::gather",
                input_shapes=[[32000, 2048], [], [960, 2048]],
            ),
            "9" * 64,
        ),
    ])
    trace = tmp_path / "one-shot-two-events.json"
    trace.write_text(json.dumps({"traceEvents": [
        {
            "ph": "X", "cat": "user_annotation",
            "name": subject.COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
            "pid": 4, "tid": 8, "ts": 10, "dur": 100,
            "args": {"External id": 1},
        },
        *[
            event
            for external_id in (7, 8)
            for event in (
                {
                    "ph": "X", "cat": "cpu_op", "name": "aten::gather",
                    "pid": 4, "tid": 8, "ts": 20 + external_id, "dur": 20,
                    "args": {
                        "External id": external_id,
                        "Input Dims": [[32000, 2048], [], [960, 2048]],
                        "Call stack": "model.py(1): forward;",
                    },
                },
                {
                    "ph": "X", "cat": "kernel", "name": "mm_kernel",
                    "pid": 0, "tid": 7, "ts": 25 + external_id, "dur": 1.0,
                    "args": {"External id": external_id},
                },
            )
        ],
    ]}), encoding="utf-8")
    parent = _union_receipt("issue2024-union-one-shot", [_union_event()])
    parent["identity"] = {"execution_source_commit": "a" * 40}
    parent["kernel_trace"] = {
        "sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "material_linear_shapes": [{"fprop": [64, 15, 2048, 6144]}] * 5,
    }
    parent["self_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in parent.items() if key != "self_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    one_shot = subject.derive_issue2024_offline_measurement_receipt(
        parent,
        parent_raw_sha256="a" * 64,
        trace_path=trace,
    )

    comparison = subject.build_issue2024_union_comparison_receipt(
        one_shot,
        sharded,
        one_shot_raw_sha256="b" * 64,
        sharded_raw_sha256="c" * 64,
    )
    assert comparison["result"] == "PASS"
    assert sharded["kernel_trace"]["offline_trace_derivation"][
        "parser_source_sha256"
    ] == parser_source_sha256


def test_issue2024_union_comparison_matches_structural_multiset_not_physical_time() -> None:
    one_shot = _union_receipt("issue2024-union-one-shot", [_union_event(time="10.0")])
    sharded = _union_receipt("issue2024-union-sharded", [_union_event(time="12.5")])
    receipt = subject.build_issue2024_union_comparison_receipt(
        one_shot,
        sharded,
        one_shot_raw_sha256="1" * 64,
        sharded_raw_sha256="2" * 64,
    )
    assert receipt["result"] == "PASS"
    assert receipt["execution_source_commit"] == "a" * 40
    assert receipt["structural_multiset_rows"] == 1
    assert receipt["structural_event_count"] == 1
    assert receipt["one_shot_only_structural_count"] == 0
    assert receipt["sharded_only_structural_count"] == 0
    assert receipt["structural_key_fields"] == [
        "key", "input_shapes", "source_stack", "ancestry_depth",
    ]
    assert receipt["physical_times"]["one_shot"] == ["10.0"]
    assert receipt["physical_times"]["sharded"] == ["12.5"]


def test_issue2024_shared_offline_parser_negative_detects_planted_union_asymmetry(
    tmp_path: Path,
) -> None:
    def parsed_events(name: str, external_ids: list[int]) -> list[dict[str, object]]:
        events: list[dict[str, object]] = [{
            "ph": "X", "cat": "user_annotation",
            "name": subject.COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
            "pid": 4, "tid": 8, "ts": 10, "dur": 100,
            "args": {"External id": 1},
        }]
        for external_id in external_ids:
            events.extend((
                {
                    "ph": "X", "cat": "cpu_op", "name": "aten::gather",
                    "pid": 4, "tid": 8, "ts": 20 + external_id, "dur": 20,
                    "args": {
                        "External id": external_id,
                        "Input Dims": [[32000, 2048], [], [960, 2048]],
                        "Call stack": "model.py(1): forward;packed_specialist_run.py(2): main;",
                    },
                },
                {
                    "ph": "X", "cat": "kernel", "name": "gather_kernel",
                    "pid": 0, "tid": 7, "ts": 25 + external_id, "dur": 4.544,
                    "args": {"External id": external_id},
                },
            ))
        trace = tmp_path / f"{name}.json"
        trace.write_text(json.dumps({"traceEvents": events}), encoding="utf-8")
        return subject.build_issue2024_event_ledger_from_trace(
            trace, hidden=2048, vocab_size=32000,
        )["events"]

    one_shot_events = parsed_events("one-shot", [7])
    sharded_events = parsed_events("sharded-planted-extra", [7, 8])
    with pytest.raises(ValueError, match="STRUCTURAL_MULTISET_MISMATCH"):
        subject.build_issue2024_union_comparison_receipt(
            _union_receipt("issue2024-union-one-shot", one_shot_events),
            _union_receipt("issue2024-union-sharded", sharded_events),
            one_shot_raw_sha256="1" * 64,
            sharded_raw_sha256="2" * 64,
        )


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"stack": "other.py:9"}, "STRUCTURAL_MULTISET_MISMATCH"),
        ({"ancestry_depth": 3}, "STRUCTURAL_MULTISET_MISMATCH"),
    ],
)
def test_issue2024_union_comparison_refuses_structural_drift(
    mutation: dict[str, object], match: str
) -> None:
    left_event = _union_event()
    right_event = _union_event()
    if "stack" in mutation:
        right_event["source_stack"] = [mutation["stack"]]
    if "ancestry_depth" in mutation:
        right_event["ancestry_depth"] = mutation["ancestry_depth"]
    with pytest.raises(ValueError, match=match):
        subject.build_issue2024_union_comparison_receipt(
            _union_receipt("issue2024-union-one-shot", [left_event]),
            _union_receipt("issue2024-union-sharded", [right_event]),
            one_shot_raw_sha256="1" * 64,
            sharded_raw_sha256="2" * 64,
        )


def test_issue2024_union_comparison_normalizes_only_process_local_stack_addresses() -> None:
    left_event = _union_event()
    right_event = _union_event()
    left_event["source_stack"] = [
        "<built-in method eq of Tensor object at 0x00000229C3B457B0>",
        "pretrain.py(1430): run_packed_selection_pretraining_segment",
        "packed_specialist_run.py(2358): run_issue1946_profile",
    ]
    right_event["source_stack"] = [
        "<built-in method eq of Tensor object at 0x0000022144C37BA0>",
        "pretrain.py(1730): run_packed_selection_pretraining_segment",
        "packed_specialist_run.py(2363): run_issue1946_profile",
    ]
    receipt = subject.build_issue2024_union_comparison_receipt(
        _union_receipt("issue2024-union-one-shot", [left_event]),
        _union_receipt("issue2024-union-sharded", [right_event]),
        one_shot_raw_sha256="1" * 64,
        sharded_raw_sha256="2" * 64,
    )
    assert receipt["result"] == "PASS"
    assert receipt["source_stack_normalization"] == {
        "process_address_pattern": "(?<= at )0x[0-9A-Fa-f]+(?=>)",
        "process_address_replacement": "0x<PROCESS_LOCAL_ADDRESS>",
        "mode_entry_frame_equivalence_groups": [
            {
                "canonical": "pretrain.py(<UNION_MODE_ENTRY>): run_packed_selection_pretraining_segment",
                "members": [
                    "pretrain.py(1430): run_packed_selection_pretraining_segment",
                    "pretrain.py(1730): run_packed_selection_pretraining_segment",
                ],
            },
            {
                "canonical": "packed_specialist_run.py(<UNION_MODE_ENTRY>): run_issue1946_profile",
                "members": [
                    "packed_specialist_run.py(2358): run_issue1946_profile",
                    "packed_specialist_run.py(2363): run_issue1946_profile",
                ],
            },
        ],
    }


def test_issue2024_union_comparison_refuses_unlisted_same_function_line_drift() -> None:
    left_event = _union_event()
    right_event = _union_event()
    left_event["source_stack"] = ["model.py(442): _inject_modality"]
    right_event["source_stack"] = ["model.py(777): _inject_modality"]
    with pytest.raises(ValueError, match="STRUCTURAL_MULTISET_MISMATCH"):
        subject.build_issue2024_union_comparison_receipt(
            _union_receipt("issue2024-union-one-shot", [left_event]),
            _union_receipt("issue2024-union-sharded", [right_event]),
            one_shot_raw_sha256="1" * 64,
            sharded_raw_sha256="2" * 64,
        )


def test_issue2024_union_comparison_refuses_identity_or_preflight_drift() -> None:
    one_shot = _union_receipt("issue2024-union-one-shot", [_union_event()])
    sharded = _union_receipt("issue2024-union-sharded", [_union_event()])
    sharded["identity"]["execution_source_commit"] = "f" * 40
    sharded["self_sha256"] = hashlib.sha256(
        json.dumps({k: v for k, v in sharded.items() if k != "self_sha256"}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        subject.build_issue2024_union_comparison_receipt(
            one_shot,
            sharded,
            one_shot_raw_sha256="1" * 64,
            sharded_raw_sha256="2" * 64,
        )


def test_issue2024_union_comparison_refuses_offline_parser_identity_drift() -> None:
    one_shot = _union_receipt("issue2024-union-one-shot", [_union_event()])
    sharded = _union_receipt("issue2024-union-sharded", [_union_event()])
    sharded["kernel_trace"]["offline_trace_derivation"]["parser_source_sha256"] = "0" * 64
    sharded["self_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in sharded.items() if key != "self_sha256"},
            sort_keys=True, separators=(",", ":"),
        ).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="ISSUE2024_UNION_OFFLINE_PARSER_MISMATCH"):
        subject.build_issue2024_union_comparison_receipt(
            one_shot,
            sharded,
            one_shot_raw_sha256="a" * 64,
            sharded_raw_sha256="b" * 64,
        )


def test_issue2024_union_comparison_refuses_same_set_with_different_multiplicity() -> None:
    event = _union_event()
    with pytest.raises(ValueError, match="STRUCTURAL_MULTISET_MISMATCH"):
        subject.build_issue2024_union_comparison_receipt(
            _union_receipt("issue2024-union-one-shot", [event, dict(event)]),
            _union_receipt("issue2024-union-sharded", [event]),
            one_shot_raw_sha256="1" * 64,
            sharded_raw_sha256="2" * 64,
        )


def test_issue2024_union_modes_reach_two_update_builder_not_64_update_arm_builder() -> None:
    source = inspect.getsource(subject.run_issue1946_profile)
    branch = source.index(
        'elif mode in {"issue2024-union-one-shot", "issue2024-union-sharded"}:'
    )
    union_builder = source.index("receipt = build_issue2024_union_measurement_receipt(", branch)
    arm_builder = source.index("receipt = build_issue1946_arm_receipt(", branch)
    assert branch < union_builder < arm_builder


def test_issue2024_union_comparison_cli_is_no_overwrite() -> None:
    parser = subject._build_argument_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, subject.argparse._SubParsersAction)
    )
    options = {
        option
        for action in subparsers.choices["issue2024-union-compare"]._actions
        for option in action.option_strings
    }
    assert options == {"-h", "--help", "--one-shot", "--sharded", "--output"}


@pytest.mark.parametrize(
    "mode", ["issue2024-union-one-shot", "issue2024-union-sharded"]
)
def test_issue2024_union_terminal_builder_accepts_exact_two_update_contract(mode: str) -> None:
    event = _union_event()
    receipt = subject.build_issue2024_union_measurement_receipt(
        mode=mode,
        identity={"execution_source_commit": "a" * 40},
        update_seconds=[1.0, 2.0],
        phase_seconds=[{}, {}],
        profiler_update_indexes=[0, 1],
        allocator_rows=[{}, {}],
        power_rows=[{}, {}],
        kernel_trace={
            "full_precision_unmapped_event_ledger": {
                "schema_version": "ember-issue2024-full-precision-event-ledger-v2",
                "events": [event],
                "reconciliation_gap_ns": 0,
            }
        },
        checkpoint_cadence={
            "in_measured_window": "NONE",
            "checkpoint_every_updates": 3,
            "callback_identity": "NO_OP",
            "final_callback_timed": False,
        },
        runtime_custody={
            "preflight_raw_sha256": "d" * 64,
            "preflight_self_sha256": "e" * 64,
        },
    )
    assert receipt["schema_version"] == "ember-issue2024-union-measurement-v1"
    assert receipt["counts"] == {"complete_updates": 2, "profiler": 2}
    assert subject._validate_self(receipt, mode) == receipt

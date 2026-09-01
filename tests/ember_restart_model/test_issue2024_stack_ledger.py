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
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import packed_specialist_run as subject  # noqa: E402


def _event(
    *,
    event_id: int = 7,
    parent_id: int = 3,
    device_time_us: str = "10.000001",
    stack: tuple[str, ...] = ("tools/ember-restart-3b/model.py:41",),
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
                "source_stack": ["tools/ember-restart-3b/model.py:41"],
            },
            {
                "ancestry_depth": 1,
                "cpu_parent_id": 7,
                "event_id": 8,
                "event_ordinal": 1,
                "input_shapes": [[2, 3], [3, 4]],
                "key": "aten::mm",
                "self_device_time_us": "2.000002",
                "source_stack": ["tools/ember-restart-3b/model.py:41"],
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
        [_event(stack=(), parent_stack=("tools/ember-restart-3b/model.py:99",))],
        declared_self_device_time_total_us="10.000001",
    )
    assert ledger["events"][0]["source_stack"] == [
        "tools/ember-restart-3b/model.py:99"
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
            }
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
    assert receipt["physical_times"]["one_shot"] == ["10.0"]
    assert receipt["physical_times"]["sharded"] == ["12.5"]


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

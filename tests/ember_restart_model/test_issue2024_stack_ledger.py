# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
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


def test_issue2024_live_schedule_emits_exactly_one_trace_callback() -> None:
    callback_count = 0

    def count_trace(_profiler: object) -> None:
        nonlocal callback_count
        callback_count += 1

    torch = subject.torch
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU],
        schedule=torch.profiler.schedule(wait=16, warmup=0, active=8, repeat=1),
        on_trace_ready=count_trace,
        profile_memory=True,
        record_shapes=True,
        with_stack=True,
    ) as profiler:
        for _ in range(24):
            value = torch.ones((2, 2))
            value @ value
            profiler.step()

    assert callback_count == 1


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
                "cpu_parent_id": 3,
                "event_id": 7,
                "input_shapes": [[2, 3], [3, 4]],
                "key": "aten::mm",
                "self_device_time_us": "10.000001",
                "source_stack": ["tools/ember-restart-3b/model.py:41"],
            },
            {
                "cpu_parent_id": 7,
                "event_id": 8,
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


def test_issue2024_ledger_refuses_duplicate_event_identity() -> None:
    with pytest.raises(ValueError, match="ISSUE2024_EVENT_ID_DUPLICATE"):
        subject.build_issue2024_event_ledger(
            [_event(), _event()], declared_self_device_time_total_us="20.000002"
        )

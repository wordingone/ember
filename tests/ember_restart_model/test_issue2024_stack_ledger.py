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
) -> SimpleNamespace:
    parent = SimpleNamespace(id=parent_id, stack=list(parent_stack), cpu_parent=None)
    return SimpleNamespace(
        id=event_id,
        key="aten::mm",
        cpu_parent=parent,
        input_shapes=[[2, 3], [3, 4]],
        self_device_time_total=float(device_time_us),
        stack=list(stack),
    )


def test_issue2024_profiler_configuration_enables_source_stacks() -> None:
    assert subject.issue2024_profiler_configuration() == {
        "profile_memory": True,
        "record_shapes": True,
        "with_stack": True,
    }


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

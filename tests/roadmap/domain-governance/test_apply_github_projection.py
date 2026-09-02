# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
MODULE_PATH = REPO / "scripts" / "roadmap" / "apply_github_projection.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apply_github_projection", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def projection() -> dict:
    return {
        "source_master_sha": "a" * 40,
        "issue_closures": [],
        "labels": [
            {"name": "roadmap:tracked", "color": "112233", "description": "tracked"},
            {"name": "affects:EMBER-00", "color": "445566", "description": "m0"},
        ],
        "milestones": [
            {
                "milestone_id": "EMBER-00",
                "title": "EMBER-00 — Zero",
                "description": "contract",
                "state": "open",
                "due_on": None,
            }
        ],
        "parent_issues": [
            {
                "tracking_key": "roadmap-parent:EMBER-00",
                "milestone_id": "EMBER-00",
                "title": "[ROADMAP][EMBER-00] Zero",
                "body": "<!-- ember-roadmap-parent: EMBER-00 -->\nbody",
                "labels": ["affects:EMBER-00"],
                "depends_on": [],
            }
        ],
        "issue_mutations": [
            {
                "number": 7,
                "expected_body_sha256": "b" * 64,
                "expected_updated_at": "2026-01-01T00:00:00Z",
                "expected_labels": [],
                "expected_milestone_id": None,
                "add_labels": ["roadmap:tracked", "affects:EMBER-00"],
                "set_milestone": "EMBER-00",
                "add_as_subissue_of": "roadmap-parent:EMBER-00",
                "close": False,
            }
        ],
    }


def empty_live() -> dict:
    return {
        "master_sha": "a" * 40,
        "labels": {},
        "milestones": {},
        "parents": {},
        "open_issue_numbers": [7],
        "issues": {
            7: {
                "id": 700,
                "state": "open",
                "body_sha256": "b" * 64,
                "updated_at": "2026-01-01T00:00:00Z",
                "labels": [],
                "milestone_id": None,
                "parent_tracking_key": None,
            }
        },
        "dependencies": {},
    }


def test_new_projection_has_deterministic_create_and_link_plan() -> None:
    module = load_module()
    plan = module.build_mutation_plan(projection(), empty_live())
    assert [row["op"] for row in plan] == [
        "create_label",
        "create_label",
        "create_milestone",
        "create_parent_issue",
        "add_issue_labels",
        "set_issue_milestone",
        "add_subissue",
    ]


def test_exact_live_state_is_a_zero_mutation_second_run() -> None:
    module = load_module()
    live = empty_live()
    live["labels"] = {
        "roadmap:tracked": {"color": "112233", "description": "tracked"},
        "affects:EMBER-00": {"color": "445566", "description": "m0"},
    }
    live["milestones"] = {
        "EMBER-00": {
            "number": 10,
            "title": "EMBER-00 — Zero",
            "description": "contract",
            "state": "open",
            "due_on": None,
        }
    }
    live["parents"] = {
        "roadmap-parent:EMBER-00": {
            "id": 900,
            "number": 9,
            "title": "[ROADMAP][EMBER-00] Zero",
            "body": "<!-- ember-roadmap-parent: EMBER-00 -->\nbody",
            "labels": ["affects:EMBER-00"],
            "milestone_id": "EMBER-00",
        }
    }
    live["open_issue_numbers"].append(9)
    live["issues"][7]["labels"] = ["roadmap:tracked", "affects:EMBER-00"]
    live["issues"][7]["milestone_id"] = "EMBER-00"
    live["issues"][7]["parent_tracking_key"] = "roadmap-parent:EMBER-00"
    live["issues"][7]["updated_at"] = "2026-01-02T00:00:00Z"
    assert module.build_mutation_plan(projection(), live) == []


def test_landed_carrier_can_bind_new_master_with_proven_ancestry() -> None:
    module = load_module()
    live = empty_live()
    live["master_sha"] = "c" * 40
    live["projection_source_is_ancestor"] = True
    plan = module.build_mutation_plan(
        projection(), live, publication_master_sha="c" * 40
    )
    assert plan


def test_partial_exact_projection_state_is_resumable() -> None:
    module = load_module()
    live = empty_live()
    live["issues"][7]["labels"] = ["roadmap:tracked"]
    live["issues"][7]["updated_at"] = "2026-01-02T00:00:00Z"
    plan = module.build_mutation_plan(projection(), live)
    assert "add_issue_labels" in [row["op"] for row in plan]


def test_unaccounted_open_issue_refuses_before_mutation() -> None:
    module = load_module()
    live = empty_live()
    live["open_issue_numbers"].append(8)
    with pytest.raises(module.ProjectionError, match="open issue population drift"):
        module.build_mutation_plan(projection(), live)


def test_unproven_publication_ancestry_refuses() -> None:
    module = load_module()
    live = empty_live()
    live["master_sha"] = "c" * 40
    with pytest.raises(module.ProjectionError, match="proven ancestor"):
        module.build_mutation_plan(
            projection(), live, publication_master_sha="c" * 40
        )


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("master", "public master drift"),
        ("issue", "issue 7 drift"),
        ("closed", "issue closure mutation is forbidden"),
        ("duplicate_parent", "duplicate parent tracking key"),
    ],
)
def test_planner_refuses_drift_and_unsafe_projection(mutation: str, expected: str) -> None:
    module = load_module()
    desired = projection()
    live = empty_live()
    if mutation == "master":
        live["master_sha"] = "c" * 40
    elif mutation == "issue":
        live["issues"][7]["body_sha256"] = "d" * 64
    elif mutation == "closed":
        desired["issue_mutations"][0]["close"] = True
    elif mutation == "duplicate_parent":
        live["parents"] = {
            "roadmap-parent:EMBER-00": [
                {"id": 1, "number": 1},
                {"id": 2, "number": 2},
            ]
        }
    with pytest.raises(module.ProjectionError, match=expected):
        module.build_mutation_plan(desired, live)


def test_partial_apply_stops_and_records_only_completed_operations() -> None:
    module = load_module()
    operations = module.build_mutation_plan(projection(), empty_live())

    class Client:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, operation):
            if len(self.calls) == 2:
                raise RuntimeError("injected failure")
            self.calls.append(deepcopy(operation))
            return {"ok": True}

    client = Client()
    with pytest.raises(module.ProjectionApplyError) as caught:
        module.apply_plan(operations, client)
    assert len(caught.value.completed) == 2
    assert len(client.calls) == 2

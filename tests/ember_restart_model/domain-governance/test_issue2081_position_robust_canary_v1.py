from __future__ import annotations

# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RUNNER_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("issue2081_runner", "issue2081_position_robust_canary_v1.py")


def row(arm: str, pair: int, *, rate: float) -> dict[str, object]:
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
            "state": {
                "parameter-0": {
                    "exp_avg": {"dtype": "torch.float32", "shape": [2, 2]}
                }
            },
        },
        "post_scheduler_identity": "scheduler-none-v1",
        "post_scaler_identity": "scaler-none-v1",
        "post_cursor": {
            "global_step": 101 + pair,
            "selected_ordinal": 64 * (pair + 1),
        },
        "post_rng_identity": f"rng-{pair}",
        "backend_identity": ["operator:aten::_scaled_dot_product_flash_attention"],
        "sampled_parameters": {"layer.0.qkv.weight:0": 1.0},
        "event_ids": [f"start-event-{arm}-{pair}", f"end-event-{arm}-{pair}"],
    }


def predecessor_pairs(*, control_rate: float = 100.0, treatment_rate: float = 102.0):
    result = []
    for pair_index, pair_order in enumerate(MODULE.BASE.PAIR_ORDERS):
        result.append([
            row(
                arm,
                pair_index,
                rate=control_rate if arm == "control" else treatment_rate,
            )
            for arm in pair_order
        ])
    return result


def warmed_pairs(*, ratios: list[float] | None = None, measured_warm: float = 1.0):
    ratios = ratios or [1.02] * 8
    pairs = predecessor_pairs(control_rate=100.0, treatment_rate=102.0)
    for pair_index, rows in enumerate(pairs):
        for row in rows:
            rate = 100.0 if row["arm"] == "control" else 100.0 * ratios[pair_index]
            row["tokens_per_second"] = rate
            row["event_seconds"] = row["processed_tokens"] / rate
            row["warm_tokens_per_second"] = rate / measured_warm
            row["warm_processed_tokens"] = row["processed_tokens"]
            row["warm_event_seconds"] = row["warm_processed_tokens"] / row["warm_tokens_per_second"]
            row["warm_event_ids"] = [
                f"warm-start-{row['arm']}-{pair_index}",
                f"warm-end-{row['arm']}-{pair_index}",
            ]
            row["warm_loss"] = 2.0
            row["warm_update"] = {
                "loss": row["warm_loss"],
                "processed_tokens": row["warm_processed_tokens"],
                "event_seconds": row["warm_event_seconds"],
                "tokens_per_second": row["warm_tokens_per_second"],
                "event_ids": row["warm_event_ids"],
            }
    return pairs


@pytest.mark.parametrize(
    ("ratios", "expected", "expected_median"),
    [
        (
            [1.50, 1.50, 1.019, 1.019, 1.019, 1.019, 1.019, 1.019],
            "REJECTED",
            1.019,
        ),
        ([1.02] * 8, "PASS_POSITIVE", 1.02),
    ],
)
def test_median_of_eight_paired_ratios_controls_verdict(
    ratios, expected, expected_median
):
    planted = warmed_pairs(ratios=ratios)
    decision = MODULE.adjudicate_pairs(planted)
    assert decision["disposition"] == expected
    assert decision["median_paired_treatment_control_ratio"] == pytest.approx(
        expected_median
    )


def test_position_effect_guard_refuses_before_verdict():
    with pytest.raises(ValueError, match="TIMING_POSITION_EFFECT_REFUSED"):
        MODULE.adjudicate_pairs(warmed_pairs(measured_warm=2.0))


def test_position_effect_on_one_arm_refuses_before_verdict():
    planted = warmed_pairs()
    for rows in planted:
        treatment = next(row for row in rows if row["arm"] == "treatment")
        treatment["warm_tokens_per_second"] = treatment["tokens_per_second"] / 2.0
        treatment["warm_event_seconds"] = (
            treatment["warm_processed_tokens"]
            / treatment["warm_tokens_per_second"]
        )
        treatment["warm_update"]["tokens_per_second"] = treatment[
            "warm_tokens_per_second"
        ]
        treatment["warm_update"]["event_seconds"] = treatment[
            "warm_event_seconds"
        ]
    with pytest.raises(ValueError, match="TIMING_POSITION_EFFECT_REFUSED:treatment"):
        MODULE.adjudicate_pairs(planted)


def test_warm_record_must_match_flat_adjudicated_fields():
    planted = warmed_pairs()
    planted[0][0]["warm_update"]["tokens_per_second"] = 999.0
    with pytest.raises(ValueError, match="WARM_RECORD_DRIFT_REFUSED"):
        MODULE.adjudicate_pairs(planted)


def test_both_arms_in_the_same_post_warm_position_remove_order_effect():
    planted = warmed_pairs(ratios=[1.0] * 8)
    for rows in planted:
        for row in rows:
            # In the successor procedure each measured arm occupies the same
            # position immediately after its own warm update.  A shared
            # position multiplier therefore cancels inside the paired ratio.
            factor = 4.0
            row["tokens_per_second"] *= factor
            row["event_seconds"] = row["processed_tokens"] / row["tokens_per_second"]
            row["warm_tokens_per_second"] *= factor
            row["warm_event_seconds"] = row["warm_processed_tokens"] / row["warm_tokens_per_second"]
            row["warm_update"]["tokens_per_second"] = row["warm_tokens_per_second"]
            row["warm_update"]["event_seconds"] = row["warm_event_seconds"]
    decision = MODULE.adjudicate_pairs(planted)
    assert decision["median_paired_treatment_control_ratio"] == pytest.approx(1.0)
    assert decision["disposition"] == "REJECTED"


def test_one_arm_executes_warm_then_measure_from_the_warm_cursor(monkeypatch):
    calls = []

    def fake_update(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        ordinal = len(calls)
        return ({
            "loss": float(ordinal),
            "processed_tokens": 960,
            "event_seconds": float(ordinal),
            "tokens_per_second": 960.0 / ordinal,
            "event_ids": [f"start-{ordinal}", f"end-{ordinal}"],
        }, {"cursor": ordinal})

    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update)
    measured, cursor = MODULE.run_warm_then_measure(
        arm="control", pair=3, cursor={"cursor": 0}
    )
    assert [call["cursor"] for call in calls] == [{"cursor": 0}, {"cursor": 1}]
    assert cursor == {"cursor": 2}
    assert measured["warm_tokens_per_second"] == pytest.approx(960.0)
    assert measured["tokens_per_second"] == pytest.approx(480.0)
    assert measured["warm_event_ids"] == ["warm-start-1", "warm-end-1"]
    assert measured["event_ids"] == ["measured-start-2", "measured-end-2"]


def test_burn_in_indices_remain_exactly_one_update(monkeypatch):
    calls = []

    def fake_update(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return ({"loss": 2.0}, {"cursor": 1})

    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update)
    row, cursor = MODULE.run_warm_then_measure(
        arm="control", pair=-1, cursor={"cursor": 0}
    )
    assert len(calls) == 1
    assert row == {"loss": 2.0}
    assert cursor == {"cursor": 1}


def test_old_position_multiplier_cancels_when_both_measurements_are_second(
    monkeypatch,
):
    calls = []

    def fake_update(**kwargs):
        calls.append((kwargs["pair"], kwargs["arm"]))
        position = 1 if len(calls) % 2 else 2
        true_rate = 100.0 if kwargs["arm"] == "control" else 102.0
        rate = true_rate * (4.0 if position == 2 else 1.0)
        return ({
            "loss": 2.0,
            "processed_tokens": 960,
            "event_seconds": 960.0 / rate,
            "tokens_per_second": rate,
            "event_ids": [
                f"start-{kwargs['pair']}-{kwargs['arm']}-{position}",
                f"end-{kwargs['pair']}-{kwargs['arm']}-{position}",
            ],
        }, {"cursor": len(calls)})

    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update)
    pairs = []
    for pair_index, order in enumerate(MODULE.BASE.PAIR_ORDERS):
        rows = []
        for arm in order:
            measured, _ = MODULE.run_warm_then_measure(
                arm=arm, pair=pair_index, cursor={"cursor": 0}
            )
            measured.update({"arm": arm, "pair": pair_index})
            rows.append(measured)
        pairs.append(rows)
    assert all(
        row["tokens_per_second"] / row["warm_tokens_per_second"] == 4.0
        for rows in pairs
        for row in rows
    )
    ratios, median_ratio = MODULE.paired_median_ratio(pairs)
    assert ratios == pytest.approx([1.02] * 8)
    assert 0.98 <= median_ratio / 1.02 <= 1.02


def test_terminal_receipt_is_rebound_to_issue2081_and_rebased_heads():
    receipt = {
        "schema_version": "old",
        "issue": 2071,
        "campaign_issue": 1945,
        "control_source_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_source_head": MODULE.BASE.TREATMENT_HEAD,
    }
    rebound = MODULE.rebind_receipt(
        receipt,
        control_rebased_head="a" * 40,
        treatment_rebased_head="b" * 40,
    )
    assert rebound["schema_version"] == MODULE.SCHEMA_VERSION
    assert rebound["issue"] == 2081
    assert rebound["control_source_head"] == "a" * 40
    assert rebound["treatment_source_head"] == "b" * 40
    assert rebound["source_lineage"] == {
        "control_predecessor_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_predecessor_head": MODULE.BASE.TREATMENT_HEAD,
    }


def test_pre_spine_hash_paths_translate_to_canonical_locations(tmp_path: Path):
    canonical = tmp_path / "src" / "ember" / "model" / "model.py"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("model-bytes", encoding="utf-8")
    old = tmp_path / "tools" / "ember-restart-3b" / "model.py"
    assert MODULE.translate_pre_spine_path(tmp_path, old) == canonical
    canonical_test = (
        tmp_path / "tests" / "ember_restart_model" / "domain-governance" / "test_model.py"
    )
    old_test = tmp_path / "tests" / "ember_restart_model" / "test_model.py"
    assert MODULE.translate_pre_spine_path(tmp_path, old_test) == canonical_test
    unrelated = tmp_path / "tools" / "ember-restart-3b" / "checkpoint_artifacts.py"
    assert MODULE.translate_pre_spine_path(tmp_path, unrelated) == unrelated


def test_configured_base_adjudication_calls_frozen_predecessor_once(tmp_path: Path):
    names = (
        "__file__",
        "SCHEMA_VERSION",
        "sha256_path",
        "git",
        "validate_treatment_checkout",
        "run_one_update",
        "load_measurement_pairs",
        "adjudicate_pairs",
        "write_receipt",
    )
    saved = {name: getattr(MODULE.BASE, name) for name in names}
    saved_sys_path = list(MODULE.sys.path)
    try:
        MODULE.configure_base(
            root=tmp_path,
            control_rebased_head="a" * 40,
            treatment_rebased_head="b" * 40,
        )
        decision = MODULE.BASE.adjudicate_pairs(warmed_pairs())
    finally:
        for name, value in saved.items():
            setattr(MODULE.BASE, name, value)
        MODULE.sys.path[:] = saved_sys_path
    assert decision["median_paired_treatment_control_ratio"] == pytest.approx(1.02)


def test_warmed_measurement_rows_are_offline_adjudicable(tmp_path: Path):
    path = tmp_path / "measurements.jsonl"
    raw_rows = []
    for rows in warmed_pairs():
        for original in rows:
            measured = copy.deepcopy(original)
            measured["warm_update"] = {
                "loss": measured["warm_loss"] if "warm_loss" in measured else 2.0,
                "processed_tokens": measured["warm_processed_tokens"],
                "event_seconds": measured["warm_event_seconds"],
                "tokens_per_second": measured["warm_tokens_per_second"],
                "event_ids": measured["warm_event_ids"],
            }
            measured["warm_loss"] = 2.0
            measured["runner_source_sha256"] = "d" * 64
            measured["row_sha256"] = MODULE.BASE.sha256_bytes(
                MODULE.BASE.canonical(measured)
            )
            raw_rows.append(MODULE.BASE.canonical(measured))
    path.write_bytes(b"\n".join(raw_rows) + b"\n")
    loaded = MODULE.load_measurement_pairs(path)
    assert len(loaded) == 8
    assert MODULE.adjudicate_pairs(loaded)["disposition"] == "PASS_POSITIVE"


def test_offline_main_derives_repo_root_without_conflicting_cli_argument(
    monkeypatch, tmp_path: Path
):
    configured = {}

    def fake_configure_base(**kwargs):
        configured.update(kwargs)

    monkeypatch.setattr(MODULE, "configure_base", fake_configure_base)
    monkeypatch.setattr(MODULE.BASE, "main", lambda: 0)
    monkeypatch.setattr(MODULE.sys, "argv", [
        str(MODULE.Path(MODULE.__file__).resolve()),
        "--control-rebased-head",
        "a" * 40,
        "--treatment-rebased-head",
        "b" * 40,
        "--adjudicate",
        str(tmp_path),
    ])
    assert MODULE.main() == 0
    assert configured["root"] == ROOT
    assert MODULE.sys.argv[1:] == ["--adjudicate", str(tmp_path)]


def test_successor_refusal_sidecar_and_terminal_are_mutually_exclusive(tmp_path: Path):
    output = tmp_path / "terminal.json"
    MODULE.write_exclusive_refusal(output, ValueError("PLANTED"))
    assert not output.exists()
    refusal = json.loads(output.with_name("terminal.refusal.json").read_text())
    assert refusal["result"] == "REFUSED"
    assert refusal["issue"] == 2081
    assert refusal["schema_version"] == MODULE.SCHEMA_VERSION

    completed = tmp_path / "completed.json"
    MODULE.BASE.write_receipt(completed, {"result": "REJECTED", "issue": 2081})
    assert MODULE.write_exclusive_refusal(completed, ValueError("LATE")) is None
    assert completed.is_file()
    assert not completed.with_name("completed.refusal.json").exists()

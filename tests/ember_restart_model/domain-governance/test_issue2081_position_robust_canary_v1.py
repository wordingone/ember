from __future__ import annotations

# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import importlib.util
import json
import statistics
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

ISSUE2081_MEASUREMENTS_RAW_SHA256 = (
    "d15a926c3af03d7bb01ca8f4a155b67c0867d72892b2cf5ba2c875b1b5d780eb"
)
ISSUE2081_REAL_TIMINGS = (
    (0, "control", 1945.7892940402694, 1753.7675935058019),
    (0, "treatment", 1407.5302612593212, 5933.965368965198),
    (1, "treatment", 2067.4725273506506, 1307.412247015052),
    (1, "control", 1863.7143258322124, 6008.493508819052),
    (2, "control", 1883.4276887360643, 1782.5855838846223),
    (2, "treatment", 1768.541325852364, 5691.260633449473),
    (3, "treatment", 1286.2639026570587, 1464.6438888679857),
    (3, "control", 2131.5226698308556, 5965.766357930883),
    (4, "control", 2226.5615673772386, 1264.6355922231755),
    (4, "treatment", 1750.1386625657808, 5653.660387944888),
    (5, "treatment", 1562.0425111793488, 1667.3922716165625),
    (5, "control", 1368.456907498496, 5974.101639607531),
    (6, "control", 1449.6323820392713, 1368.4065686910944),
    (6, "treatment", 1249.2181597362892, 5757.980377575808),
    (7, "treatment", 1556.2207539869933, 1547.1203524626212),
    (7, "control", 1828.1960273398797, 5884.667852622834),
)
ISSUE2099_REAL_TIMINGS = (
    (0, "control", 2078.5426774994303, 1202.48119198705),
    (0, "treatment", 1606.9000512799196, 5055.495301910687),
    (1, "treatment", 1578.9889970061993, 1905.4655047834212),
    (1, "control", 1364.303111281772, 5524.636914238418),
    (2, "control", 1419.4036246484213, 1784.9294612448577),
    (2, "treatment", 2175.562114014352, 5216.147245367491),
    (3, "treatment", 1704.2603420463456, 1395.5689571631478),
    (3, "control", 2088.259018453726, 5600.3405491964995),
    (4, "control", 1342.0968615560555, 1277.733317939093),
    (4, "treatment", 1383.2793795086168, 5326.70697019859),
    (5, "treatment", 1398.0449455205305, 1882.1065096802658),
    (5, "control", 2193.1014207786134, 5691.948983124709),
    (6, "control", 1322.1143533417612, 1214.351792975264),
    (6, "treatment", 1972.1101118447214, 5498.359108164329),
    (7, "treatment", 1400.8450050127346, 1561.4432624129977),
    (7, "control", 2150.5217675197587, 5573.794433719146),
)

ISSUE2103_REAL_TIMINGS = (
    (0, "control", 1897.209372910094),
    (0, "treatment", 1930.6942952901195),
    (1, "treatment", 1737.8733953208643),
    (1, "control", 1884.0725764565718),
    (2, "control", 1347.0319832676967),
    (2, "treatment", 1584.4580240191942),
    (3, "treatment", 1191.0771388760172),
    (3, "control", 2175.360421929171),
    (4, "control", 2032.5517876369934),
    (4, "treatment", 1683.5894141852598),
    (5, "treatment", 1765.4388411748453),
    (5, "control", 1166.4257530586735),
    (6, "control", 1790.8176439112183),
    (6, "treatment", 1231.1481084321001),
    (7, "treatment", 1625.94012233014),
    (7, "control", 1543.24592770266),
)


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


def issue2081_real_timing_pairs():
    pairs = warmed_pairs()
    for pair_index, arm, measured_rate, warm_rate in ISSUE2081_REAL_TIMINGS:
        measured = next(row for row in pairs[pair_index] if row["arm"] == arm)
        measured["tokens_per_second"] = measured_rate
        measured["event_seconds"] = measured["processed_tokens"] / measured_rate
        measured["warm_tokens_per_second"] = warm_rate
        measured["warm_event_seconds"] = measured["warm_processed_tokens"] / warm_rate
        measured["warm_update"]["tokens_per_second"] = warm_rate
        measured["warm_update"]["event_seconds"] = measured["warm_event_seconds"]
    return pairs


def issue2099_real_timing_pairs():
    pairs = warmed_pairs()
    for pair_index, arm, measured_rate, warm_rate in ISSUE2099_REAL_TIMINGS:
        measured = next(row for row in pairs[pair_index] if row["arm"] == arm)
        measured["tokens_per_second"] = measured_rate
        measured["event_seconds"] = measured["processed_tokens"] / measured_rate
        measured["warm_tokens_per_second"] = warm_rate
        measured["warm_event_seconds"] = measured["warm_processed_tokens"] / warm_rate
        measured["warm_update"]["tokens_per_second"] = warm_rate
        measured["warm_update"]["event_seconds"] = measured["warm_event_seconds"]
    return pairs


def issue2103_real_timing_pairs():
    pairs = warmed_pairs()
    for pair_index, arm, measured_rate in ISSUE2103_REAL_TIMINGS:
        measured = next(row for row in pairs[pair_index] if row["arm"] == arm)
        measured["tokens_per_second"] = measured_rate
        measured["event_seconds"] = measured["processed_tokens"] / measured_rate
    return pairs


# Five disjoint W=8 windows whose consecutive window medians move by < 10 %.
STABLE_WARM_RATES = (100.0, 102.0, 101.0, 100.0, 99.0, 101.0, 100.0, 102.0) * 5
# 2f4532c0 pre-merge probe, control arm, the 24 warm updates that the summed
# window rate refused (1677 / 1872 / 1733 tokens/s: 11.6 % then 7.4 %).
PROBE_2F4532C0_CONTROL_WARM_RATES = (
    1941.2, 4804.9, 1512.3, 1702.9, 1565.9, 1431.7, 1247.4, 1517.5,
    1274.0, 1395.7, 5447.5, 1647.4, 4968.6, 1888.6, 1517.7, 1691.3,
    1539.1, 2209.1, 1617.0, 1763.1, 2001.3, 1736.7, 1704.2, 1501.3,
)


def update_record(rate: float, event_ids: list[str], *, tokens: int = 960) -> dict[str, object]:
    return {
        "loss": 2.0,
        "processed_tokens": tokens,
        "event_seconds": tokens / rate,
        "tokens_per_second": rate,
        "event_ids": event_ids,
    }


def fake_update_from_rates(rates, calls):
    ordinal_rates = iter(rates)

    def fake_update(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        ordinal = len(calls)
        rate = next(ordinal_rates)
        return (
            update_record(rate, [f"start-{ordinal}", f"end-{ordinal}"]),
            {"cursor": ordinal},
        )

    return fake_update


def cured_pairs(*, control_by_slot=(100.0, 90.0), treatment_by_slot=(100.0, 90.0)):
    pairs = warmed_pairs()
    for pair_index, rows in enumerate(pairs):
        expected_order = MODULE.AA_PAIR_ORDERS[pair_index]
        for executed_slot, measured in enumerate(rows):
            measured["tokens_per_second"] = (
                control_by_slot[executed_slot]
                if measured["arm"] == "control"
                else treatment_by_slot[executed_slot]
            )
            measured["event_seconds"] = (
                measured["processed_tokens"] / measured["tokens_per_second"]
            )
            measured["executed_slot"] = executed_slot
            measured["pair_order"] = list(expected_order)
            arm = measured["arm"]
            measured["excluded_updates"] = [
                update_record(
                    5_000.0, [f"excluded-1-start-{arm}-{pair_index}", f"excluded-1-end-{arm}-{pair_index}"]
                )
            ]
            warm_updates = [
                update_record(
                    warm_rate,
                    [
                        f"warm-{warm_index}-start-{arm}-{pair_index}",
                        f"warm-{warm_index}-end-{arm}-{pair_index}",
                    ],
                )
                for warm_index, warm_rate in enumerate(STABLE_WARM_RATES, 1)
            ]
            measured["warm_updates"] = warm_updates
            measured["warm_updates_to_stability"] = len(warm_updates)
            measured["warm_window_rates"] = MODULE.warm_window_rates(warm_updates)
            measured["warm_window_median_rates"] = MODULE.warm_window_median_rates(
                warm_updates
            )
            measured["fast_update_census"] = MODULE.fast_update_census(warm_updates)
            measured["warm_update"] = copy.deepcopy(warm_updates[-1])
            measured["warm_loss"] = warm_updates[-1]["loss"]
            measured["warm_processed_tokens"] = warm_updates[-1]["processed_tokens"]
            measured["warm_event_seconds"] = warm_updates[-1]["event_seconds"]
            measured["warm_tokens_per_second"] = warm_updates[-1]["tokens_per_second"]
            measured["warm_event_ids"] = warm_updates[-1]["event_ids"]
            measured_rate = measured["tokens_per_second"]
            measured_updates = [
                update_record(
                    measured_rate,
                    [
                        f"measured-{measured_index}-start-{arm}-{pair_index}",
                        f"measured-{measured_index}-end-{arm}-{pair_index}",
                    ],
                )
                for measured_index in range(1, MODULE.AA_MEASURED_WINDOW_UPDATES + 1)
            ]
            measured["measured_updates"] = measured_updates
            measured["processed_tokens"] = sum(
                item["processed_tokens"] for item in measured_updates
            )
            measured["event_seconds"] = sum(item["event_seconds"] for item in measured_updates)
            measured["tokens_per_second"] = (
                measured["processed_tokens"] / measured["event_seconds"]
            )
            measured["device_synchronized_before_window"] = {
                "warm": True,
                "measured": True,
            }
    return pairs


def legacy_warm_position_ratios(pairs):
    by_arm = {"control": [], "treatment": []}
    for rows in pairs:
        for measured in rows:
            by_arm[measured["arm"]].append(
                measured["tokens_per_second"] / measured["warm_tokens_per_second"]
            )
    return {arm: statistics.median(values) for arm, values in by_arm.items()}


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


def test_measured_slot_effect_guard_refuses_before_verdict():
    planted = warmed_pairs()
    for rows in planted:
        for position, measured in enumerate(rows):
            if measured["arm"] == "treatment":
                measured["tokens_per_second"] = 200.0 if position == 1 else 100.0
                measured["event_seconds"] = (
                    measured["processed_tokens"] / measured["tokens_per_second"]
                )
    with pytest.raises(ValueError, match="TIMING_POSITION_EFFECT_REFUSED:treatment"):
        MODULE.adjudicate_pairs(planted)


def test_warm_slot_artifact_does_not_drive_the_position_gate():
    planted = warmed_pairs()
    for rows in planted:
        for position, measured in enumerate(rows):
            measured["warm_tokens_per_second"] *= 4.0 if position == 1 else 1.0
            measured["warm_event_seconds"] = (
                measured["warm_processed_tokens"]
                / measured["warm_tokens_per_second"]
            )
            measured["warm_update"]["tokens_per_second"] = measured[
                "warm_tokens_per_second"
            ]
            measured["warm_update"]["event_seconds"] = measured[
                "warm_event_seconds"
            ]
    assert MODULE.adjudicate_pairs(planted)["disposition"] == "PASS_POSITIVE"


def test_issue2081_real_rows_pass_new_gate_reject_and_reproduce_old_gate():
    assert ISSUE2081_MEASUREMENTS_RAW_SHA256.startswith("d15a926c")
    pairs = issue2081_real_timing_pairs()
    decision = MODULE.adjudicate_pairs(pairs)
    assert decision["measured_slot_gate_by_arm"]["control"][
        "measured_slot_ratio"
    ] == pytest.approx(1.037, rel=1e-3)
    assert decision["measured_slot_gate_by_arm"]["treatment"][
        "measured_slot_ratio"
    ] == pytest.approx(0.988, rel=1e-3)
    assert decision["median_paired_treatment_control_ratio"] == pytest.approx(
        0.856, rel=1e-3
    )
    assert decision["disposition"] == "REJECTED"
    old_ratio = legacy_warm_position_ratios(pairs)["treatment"]
    assert (
        f"TIMING_POSITION_EFFECT_REFUSED:treatment:{old_ratio}"
        == "TIMING_POSITION_EFFECT_REFUSED:treatment:0.5944780822437837"
    )


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


def test_aa_identical_arms_are_position_independent():
    decision = MODULE.adjudicate_pairs(
        warmed_pairs(ratios=[1.0] * 8), aa_mode=True
    )
    assert decision["aa_paired_median_ratio"] == pytest.approx(1.0)
    assert decision["aa_position_gate_pass"] is True
    assert decision["aa_result"] == "HARNESS_POSITION_INDEPENDENT"
    assert decision["disposition"] == "HARNESS_POSITION_INDEPENDENT"


def test_aa_planted_point_95_median_is_position_dependent():
    decision = MODULE.adjudicate_pairs(
        warmed_pairs(ratios=[0.95] * 8), aa_mode=True
    )
    assert decision["aa_paired_median_ratio"] == pytest.approx(0.95)
    assert decision["aa_position_gate_pass"] is True
    assert decision["aa_result"] == "HARNESS_CURE_INSUFFICIENT"
    assert decision["disposition"] == "HARNESS_CURE_INSUFFICIENT"


def test_aa_cure_alternates_pair_order_and_preserves_slot_ratio_orientation():
    planted = cured_pairs()
    decision = MODULE.adjudicate_pairs(planted, aa_mode=True)
    assert MODULE.AA_PAIR_ORDERS == (
        ("control", "treatment"),
        ("treatment", "control"),
    ) * 4
    assert decision["aa_pair_order_alternated"] is True
    assert decision["measured_slot_gate_by_arm"]["control"][
        "measured_slot_ratio"
    ] == pytest.approx(100.0 / 90.0)
    assert decision["measured_slot_gate_by_arm"]["treatment"][
        "measured_slot_ratio"
    ] == pytest.approx(100.0 / 90.0)
    assert decision["warm_updates_to_stability_by_arm"] == {
        "control": [MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT] * 8,
        "treatment": [MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT] * 8,
    }
    assert all(
        len(rates) == MODULE.AA_WARM_HORIZON_WINDOWS
        for rates in decision["warm_window_rates_by_arm"]["control"]
    )
    assert decision["device_synchronized_before_window_by_arm"]["treatment"] == [
        {"warm": True, "measured": True}
    ] * 8
    assert decision["aa_warm_window_updates"] == 8
    assert decision["aa_post_switch_excluded_updates"] == 1
    assert decision["disposition"] == "HARNESS_POSITION_INDEPENDENT"


def test_aa_unstable_warm_sequence_refuses_at_readiness_update_deadline(
    monkeypatch,
):
    MODULE._AA_ARM_PROGRESS.clear()
    calls = []
    # A monotone ramp: every disjoint window median differs from its predecessor
    # by far more than 10 %, so readiness is never reached inside the horizon.
    ramp = [5_000.0] + [100.0 + 10.0 * ordinal for ordinal in range(1, 60)]
    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update_from_rates(ramp, calls))
    with pytest.raises(ValueError, match="^AA_WARM_STABILITY_NOT_REACHED_REFUSED$"):
        MODULE.run_warm_then_measure(
            aa_mode=True,
            arm="treatment",
            pair=1,
            cursor={"cursor": 0},
        )
    assert len(calls) == (
        MODULE.AA_POST_SWITCH_EXCLUDED_UPDATES
        + MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT
    )
    progress = MODULE._AA_ARM_PROGRESS["pair-1-treatment"]
    assert len(progress["excluded_updates"]) == 1
    assert progress["excluded_updates"][0]["tokens_per_second"] == 5_000.0
    assert len(progress["warm_updates"]) == MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT
    assert len(progress["warm_window_rates"]) == MODULE.AA_WARM_HORIZON_WINDOWS
    assert progress["measured_updates"] == []


def test_aa_refusal_sidecar_persists_every_arm_sequence(monkeypatch, tmp_path: Path):
    MODULE._AA_ARM_PROGRESS.clear()
    calls = []
    ramp = [5_000.0] + [100.0 + 10.0 * ordinal for ordinal in range(1, 60)]
    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update_from_rates(ramp, calls))
    with pytest.raises(ValueError):
        MODULE.run_warm_then_measure(aa_mode=True, arm="treatment", pair=0, cursor={"cursor": 0})
    output = tmp_path / "terminal.json"
    MODULE.write_exclusive_refusal(output, ValueError("AA_WARM_STABILITY_NOT_REACHED_REFUSED"))
    refusal = json.loads(output.with_name("terminal.refusal.json").read_text())
    sequence = refusal["aa_arm_progress"]["pair-0-treatment"]
    assert len(sequence["warm_updates"]) == MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT
    assert [round(item["tokens_per_second"], 6) for item in sequence["warm_updates"]][:3] == [
        110.0,
        120.0,
        130.0,
    ]
    assert len(sequence["excluded_updates"]) == 1
    assert len(sequence["warm_window_rates"]) == MODULE.AA_WARM_HORIZON_WINDOWS
    assert len(sequence["warm_window_median_rates"]) == MODULE.AA_WARM_HORIZON_WINDOWS
    assert sequence["fast_update_census"]["count"] == 0
    assert refusal["aa_warm_window_updates"] == MODULE.AA_WARM_WINDOW_UPDATES
    MODULE._AA_ARM_PROGRESS.clear()


def _issue2110_overlapping_median_criterion(rates, *, k=3, epsilon=0.06):
    """The predecessor's readiness rule, retained here only as the planted negative."""
    if len(rates) < k + 1:
        return False
    previous = statistics.median(rates[-k - 1 : -1])
    current = statistics.median(rates[-k:])
    return abs(current - previous) / previous < epsilon


def test_aa_disjoint_windows_refuse_the_issue2110_overlapping_median_false_positive():
    # #2110 control arm, governed run at 00716f6b: four warm updates spanning
    # 1,253 to 5,753 tokens/s passed the overlapping K=3 median rule with
    # relative change exactly 0.0.
    issue2110_control_warm = [5752.6, 1595.7, 1253.0, 1770.6]
    assert _issue2110_overlapping_median_criterion(issue2110_control_warm)
    # Under the cure the post-switch spike is the EXCLUDED update and never
    # enters a window; what remains is whether consecutive whole windows agree.
    # A first window still warming (~1,370 tokens/s) against a steady second
    # window (~1,700) is refused; two steady windows in a row are accepted.
    still_warming = [1253.0, 1595.7, 1770.6, 1364.3, 1300.0, 1350.0, 1250.0, 1400.0]
    steady = [1650.0, 1700.0, 1750.0, 1700.0] * 2
    warm = [
        update_record(rate, [f"s-{index}", f"e-{index}"])
        for index, rate in enumerate(still_warming + steady * 4)
    ]
    medians = MODULE.warm_window_median_rates(warm)
    assert len(medians) == 5
    assert abs(medians[1] - medians[0]) / medians[0] > MODULE.AA_WARM_STABILITY_EPSILON
    assert not MODULE.warm_stability_reached(warm[:16])
    assert MODULE.warm_stability_reached(warm)
    # The old rule, applied to the same still-warming tail, would have accepted it.
    assert MODULE.AA_WARM_WINDOW_UPDATES == 8
    assert MODULE.AA_WARM_STABILITY_EPSILON == 0.10
    assert MODULE.AA_WARM_HORIZON_WINDOWS == 5
    assert MODULE.AA_FAST_UPDATE_SECONDS_FRACTION == 0.5
    assert MODULE.AA_POST_SWITCH_EXCLUDED_UPDATES == 1
    assert MODULE.AA_WARM_STABILITY_READINESS_UPDATE_LIMIT == 40


def test_aa_median_windows_accept_the_2f4532c0_probe_tail_the_summed_rate_refused():
    # The v1 cure's summed-token window rate refused this real control arm at
    # epsilon 0.06 although the arm was steady: three ~0.10 s applied updates
    # (real: optimizer identity advanced, loss finite, no scaler) sat inside a
    # 0.23-0.41 s population and moved the summed rate 11.6 % then 7.4 %.
    warm = [
        update_record(rate, [f"s-{index}", f"e-{index}"], tokens=512)
        for index, rate in enumerate(PROBE_2F4532C0_CONTROL_WARM_RATES)
    ]
    summed = MODULE.warm_window_rates(warm)
    assert [round(rate, 1) for rate in summed] == [1677.3, 1872.3, 1733.0]
    assert abs(summed[1] - summed[0]) / summed[0] > 0.06
    assert abs(summed[2] - summed[1]) / summed[1] > 0.06
    medians = MODULE.warm_window_median_rates(warm)
    assert [round(rate, 1) for rate in medians] == [1541.7, 1669.3, 1720.5]
    assert abs(medians[2] - medians[1]) / medians[1] < MODULE.AA_WARM_STABILITY_EPSILON
    assert MODULE.warm_stability_reached(warm)
    census = MODULE.fast_update_census(warm)
    assert census["count"] == 3
    assert census["indices"] == [1, 10, 12]
    assert census["threshold_seconds"] == pytest.approx(0.5 * census["median_seconds"])
    # A still-warming pair of final windows is refused even under the median.
    slow_tail = warm[:16] + [
        update_record(1200.0, [f"t-{index}", f"u-{index}"], tokens=512) for index in range(8)
    ]
    assert not MODULE.warm_stability_reached(slow_tail)


def test_aa_disjoint_windows_share_no_sample():
    warm = [update_record(100.0 + index, [f"s-{index}", f"e-{index}"]) for index in range(24)]
    first = MODULE.window_rate(warm[0:8])
    second = MODULE.window_rate(warm[8:16])
    third = MODULE.window_rate(warm[16:24])
    assert MODULE.warm_window_rates(warm) == [first, second, third]
    # An incomplete trailing window is never scored.
    assert MODULE.warm_window_rates(warm[:23]) == [first, second]


def test_aa_measured_window_starts_only_after_disjoint_windows_stabilize(monkeypatch):
    MODULE._AA_ARM_PROGRESS.clear()
    calls = []
    synchronizations = []
    rates = [5_500.0] + list(STABLE_WARM_RATES) + [99.0] * 8
    monkeypatch.setattr(MODULE, "_BASE_RUN_ONE_UPDATE", fake_update_from_rates(rates, calls))
    monkeypatch.setattr(
        MODULE,
        "synchronize_device_before_window",
        lambda: synchronizations.append(len(calls)) or True,
    )
    measured, cursor = MODULE.run_warm_then_measure(
        aa_mode=True,
        arm="control",
        pair=0,
        cursor={"cursor": 0},
    )
    assert len(calls) == 1 + 40 + 8
    # Synchronized after the excluded switch update and again after the last
    # warm update: immediately before each timing window opens.
    assert synchronizations == [1, 41]
    assert measured["device_synchronized_before_window"] == {"warm": True, "measured": True}
    assert [item["tokens_per_second"] for item in measured["excluded_updates"]] == [5_500.0]
    assert measured["warm_updates_to_stability"] == 40
    assert [item["tokens_per_second"] for item in measured["warm_updates"]] == list(
        STABLE_WARM_RATES
    )
    assert measured["warm_window_rates"] == MODULE.warm_window_rates(measured["warm_updates"])
    assert measured["warm_window_median_rates"] == MODULE.warm_window_median_rates(
        measured["warm_updates"]
    )
    assert measured["fast_update_census"] == MODULE.fast_update_census(measured["warm_updates"])
    assert len(measured["measured_updates"]) == 8
    assert measured["processed_tokens"] == 8 * 960
    assert measured["tokens_per_second"] == pytest.approx(99.0)
    assert measured["event_ids"] == [
        "measured-window-measured-1-start-42",
        "measured-window-measured-8-end-49",
    ]
    assert measured["executed_slot"] == 0
    assert measured["pair_order"] == ["control", "treatment"]
    assert cursor == {"cursor": 49}
    # The excluded update never enters a window.
    assert 5_500.0 not in [item["tokens_per_second"] for item in measured["warm_updates"]]
    MODULE._AA_ARM_PROGRESS.clear()


def test_aa_adjudication_refuses_a_row_whose_excluded_update_leaked_into_warm():
    planted = cured_pairs()
    row = planted[0][0]
    row["warm_updates"][0] = copy.deepcopy(row["excluded_updates"][0])
    row["warm_window_rates"] = MODULE.warm_window_rates(row["warm_updates"])
    row["warm_window_median_rates"] = MODULE.warm_window_median_rates(row["warm_updates"])
    row["fast_update_census"] = MODULE.fast_update_census(row["warm_updates"])
    # The leaked update carries the excluded update's CUDA event identities.
    with pytest.raises(ValueError, match="^WARM_CUDA_EVENT_IDENTITY_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_stale_window_rates():
    planted = cured_pairs()
    row = planted[1][1]
    row["warm_window_rates"] = [rate * 1.01 for rate in row["warm_window_rates"]]
    with pytest.raises(ValueError, match="^AA_WARM_STABILITY_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_stale_median_window_rates():
    planted = cured_pairs()
    row = planted[0][1]
    row["warm_window_median_rates"] = [rate * 1.01 for rate in row["warm_window_median_rates"]]
    with pytest.raises(ValueError, match="^AA_WARM_STABILITY_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_a_stale_fast_update_census():
    planted = cured_pairs()
    row = planted[2][0]
    row["fast_update_census"] = dict(row["fast_update_census"], count=7)
    with pytest.raises(ValueError, match="^AA_WARM_STABILITY_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_a_warm_count_short_of_the_horizon():
    planted = cured_pairs()
    row = planted[3][0]
    row["warm_updates"] = row["warm_updates"][:16]
    row["warm_updates_to_stability"] = 16
    row["warm_window_rates"] = MODULE.warm_window_rates(row["warm_updates"])
    row["warm_update"] = copy.deepcopy(row["warm_updates"][-1])
    for key, field in (
        ("warm_loss", "loss"),
        ("warm_processed_tokens", "processed_tokens"),
        ("warm_event_seconds", "event_seconds"),
        ("warm_tokens_per_second", "tokens_per_second"),
        ("warm_event_ids", "event_ids"),
    ):
        row[key] = row["warm_update"][field]
    with pytest.raises(ValueError, match="^AA_WARM_STABILITY_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_a_measured_window_whose_sum_does_not_match():
    planted = cured_pairs()
    row = planted[2][1]
    row["measured_updates"] = row["measured_updates"][:-1]
    with pytest.raises(ValueError, match="^AA_MEASURED_WINDOW_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_aa_adjudication_refuses_a_row_without_the_synchronization_record():
    planted = cured_pairs()
    del planted[5][0]["device_synchronized_before_window"]
    with pytest.raises(ValueError, match="^AA_DEVICE_SYNCHRONIZATION_RECORD_REFUSED$"):
        MODULE.adjudicate_pairs(planted, aa_mode=True)


def test_issue2103_sixteen_real_rows_replay_under_unchanged_estimator():
    decision = MODULE.adjudicate_pairs(issue2103_real_timing_pairs(), aa_mode=True)
    assert decision["aa_paired_median_ratio"] == pytest.approx(
        0.970026070405825
    )
    assert decision["disposition"] == "HARNESS_CURE_INSUFFICIENT"


def test_issue2099_real_rows_reproduce_refused_metrics_under_aa_adjudication():
    decision = MODULE.adjudicate_pairs(issue2099_real_timing_pairs(), aa_mode=True)
    assert decision["measured_slot_gate_by_arm"]["control"][
        "measured_slot_ratio"
    ] == pytest.approx(0.6514846191958159)
    assert decision["measured_slot_gate_by_arm"]["treatment"][
        "measured_slot_ratio"
    ] == pytest.approx(0.832586068830104)
    assert decision["aa_paired_median_ratio"] == pytest.approx(0.9234003022297244)
    assert decision["aa_position_gate_pass"] is False
    assert decision["aa_result"] == "HARNESS_CURE_INSUFFICIENT"


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


def test_terminal_receipt_is_rebound_to_issue2099_and_rebased_heads():
    receipt = {
        "schema_version": "old",
        "issue": 2071,
        "campaign_issue": 1945,
        "control_source_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_source_head": MODULE.BASE.TREATMENT_HEAD,
        "source_model_sha256": "c" * 64,
        "source_test_sha256": "d" * 64,
    }
    rebound = MODULE.rebind_receipt(
        receipt,
        control_rebased_head="a" * 40,
        treatment_rebased_head="b" * 40,
        control_source_model_sha256="e" * 64,
        treatment_source_model_sha256="f" * 64,
    )
    assert rebound["schema_version"] == MODULE.SCHEMA_VERSION
    assert rebound["issue"] == 2099
    assert rebound["control_source_head"] == "a" * 40
    assert rebound["treatment_source_head"] == "b" * 40
    assert rebound["control_source_model_sha256"] == "e" * 64
    assert rebound["treatment_source_model_sha256"] == "f" * 64
    assert rebound["source_lineage"] == {
        "control_predecessor_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_predecessor_head": MODULE.BASE.TREATMENT_HEAD,
    }
    assert rebound["current_canonical_model_sha256"] == "c" * 64
    assert rebound["current_canonical_test_sha256"] == "d" * 64
    assert (
        rebound["historical_microprofile_model_sha256"]
        == MODULE.HISTORICAL_TREATMENT_MODEL_SHA256
    )
    assert (
        rebound["historical_microprofile_test_sha256"]
        == MODULE.HISTORICAL_TREATMENT_TEST_SHA256
    )


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


def test_dual_source_identity_accepts_post_spine_bytes_and_historical_microprofile(
    tmp_path: Path,
):
    model = tmp_path / "model.py"
    test_model = tmp_path / "test_model.py"
    model.write_bytes(b"post-spine-treatment-model")
    test_model.write_bytes(b"post-spine-treatment-test")
    current_model_sha256 = MODULE.BASE.sha256_path(model)
    current_test_sha256 = MODULE.BASE.sha256_path(test_model)
    microprofile = {
        "control_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_head": MODULE.BASE.TREATMENT_HEAD,
        "treatment_model_sha256": MODULE.HISTORICAL_TREATMENT_MODEL_SHA256,
        "treatment_test_sha256": MODULE.HISTORICAL_TREATMENT_TEST_SHA256,
    }

    bindings = MODULE.validate_source_identity_bindings(
        microprofile=microprofile,
        current_model_path=model,
        current_test_path=test_model,
        current_model_sha256=current_model_sha256,
        current_test_sha256=current_test_sha256,
    )

    assert bindings == {
        "current_canonical_model_sha256": current_model_sha256,
        "current_canonical_test_sha256": current_test_sha256,
        "historical_microprofile_model_sha256": (
            MODULE.HISTORICAL_TREATMENT_MODEL_SHA256
        ),
        "historical_microprofile_test_sha256": (
            MODULE.HISTORICAL_TREATMENT_TEST_SHA256
        ),
    }


def test_dual_source_identity_refuses_wrong_historical_microprofile_binding(
    tmp_path: Path,
):
    model = tmp_path / "model.py"
    test_model = tmp_path / "test_model.py"
    model.write_bytes(b"post-spine-treatment-model")
    test_model.write_bytes(b"post-spine-treatment-test")
    microprofile = {
        "control_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_head": MODULE.BASE.TREATMENT_HEAD,
        "treatment_model_sha256": MODULE.BASE.sha256_path(model),
        "treatment_test_sha256": MODULE.HISTORICAL_TREATMENT_TEST_SHA256,
    }

    with pytest.raises(ValueError, match="MICROPROFILE_SOURCE_IDENTITY_REFUSED"):
        MODULE.validate_source_identity_bindings(
            microprofile=microprofile,
            current_model_path=model,
            current_test_path=test_model,
            current_model_sha256=MODULE.BASE.sha256_path(model),
            current_test_sha256=MODULE.BASE.sha256_path(test_model),
        )


def test_dual_source_identity_refuses_wrong_current_canonical_binding(tmp_path: Path):
    model = tmp_path / "model.py"
    test_model = tmp_path / "test_model.py"
    model.write_bytes(b"post-spine-treatment-model")
    test_model.write_bytes(b"post-spine-treatment-test")
    microprofile = {
        "control_head": MODULE.BASE.CONTROL_HEAD,
        "treatment_head": MODULE.BASE.TREATMENT_HEAD,
        "treatment_model_sha256": MODULE.HISTORICAL_TREATMENT_MODEL_SHA256,
        "treatment_test_sha256": MODULE.HISTORICAL_TREATMENT_TEST_SHA256,
    }

    with pytest.raises(ValueError, match="INPUT_HASH_DRIFT_REFUSED"):
        MODULE.validate_source_identity_bindings(
            microprofile=microprofile,
            current_model_path=model,
            current_test_path=test_model,
            current_model_sha256="0" * 64,
            current_test_sha256=MODULE.BASE.sha256_path(test_model),
        )


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


def test_aa_main_binds_control_head_into_both_arms(monkeypatch, tmp_path: Path):
    configured = {}

    def fake_configure_base(**kwargs):
        configured.update(kwargs)

    head = "a" * 40
    monkeypatch.setattr(MODULE, "configure_base", fake_configure_base)
    monkeypatch.setattr(MODULE.BASE, "main", lambda: 0)
    monkeypatch.setattr(MODULE.sys, "argv", [
        str(MODULE.Path(MODULE.__file__).resolve()),
        "--aa",
        "--control-rebased-head",
        head,
        "--treatment-rebased-head",
        head,
        "--adjudicate",
        str(tmp_path),
    ])
    assert MODULE.main() == 0
    assert configured["aa_mode"] is True
    assert configured["control_rebased_head"] == head
    assert configured["treatment_rebased_head"] == head
    assert MODULE.sys.argv[1:] == ["--adjudicate", str(tmp_path)]


def test_successor_refusal_sidecar_and_terminal_are_mutually_exclusive(tmp_path: Path):
    output = tmp_path / "terminal.json"
    MODULE.write_exclusive_refusal(output, ValueError("PLANTED"))
    assert not output.exists()
    refusal = json.loads(output.with_name("terminal.refusal.json").read_text())
    assert refusal["result"] == "REFUSED"
    assert refusal["issue"] == 2099
    assert refusal["schema_version"] == MODULE.SCHEMA_VERSION

    completed = tmp_path / "completed.json"
    MODULE.BASE.write_receipt(completed, {"result": "REJECTED", "issue": 2099})
    assert MODULE.write_exclusive_refusal(completed, ValueError("LATE")) is None
    assert completed.is_file()
    assert not completed.with_name("completed.refusal.json").exists()


def test_configured_refusal_rebind_hashes_both_models_and_writes_sidecar(
    monkeypatch, tmp_path: Path
):
    module = _load(
        "issue2081_runner_configured_refusal",
        "issue2081_position_robust_canary_v1.py",
    )
    control_head = "a" * 40
    treatment_head = "b" * 40
    control_model = b"control-model-bytes"
    treatment_model = b"treatment-model-bytes"

    def fake_git(repo_root: Path, *args: str) -> bytes:
        assert repo_root == tmp_path
        if args == ("show", f"{control_head}:src/ember/model/model.py"):
            return control_model
        if args == ("show", f"{treatment_head}:src/ember/model/model.py"):
            return treatment_model
        raise AssertionError(args)

    monkeypatch.setattr(module.BASE, "git", fake_git)
    module.configure_base(
        root=tmp_path,
        control_rebased_head=control_head,
        treatment_rebased_head=treatment_head,
    )
    output = tmp_path / "terminal.json"
    module.write_exclusive_refusal(output, ValueError("PLANTED_REBOUND_REFUSAL"))

    refusal_path = output.with_name("terminal.refusal.json")
    assert refusal_path.is_file()
    refusal = json.loads(refusal_path.read_text())
    assert refusal["result"] == "REFUSED"
    assert refusal["refusal_message"] == "PLANTED_REBOUND_REFUSAL"
    assert refusal["control_source_model_sha256"] == module.BASE.sha256_bytes(
        control_model
    )
    assert refusal["treatment_source_model_sha256"] == module.BASE.sha256_bytes(
        treatment_model
    )


def test_configured_aa_refusal_binds_control_bytes_into_both_arms(
    monkeypatch, tmp_path: Path
):
    module = _load(
        "issue2081_runner_configured_aa_refusal",
        "issue2081_position_robust_canary_v1.py",
    )
    head = "a" * 40
    control_model = b"aa-control-model-bytes"
    corpus_bytes = b"m7-corpus-bytes"
    corpus = tmp_path / "data" / "ember-restart-3b" / "owned-text-lab-corpus-v4.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_bytes(corpus_bytes)

    def fake_git(repo_root: Path, *args: str) -> bytes:
        assert repo_root == tmp_path
        if args == ("show", f"{head}:src/ember/model/model.py"):
            return control_model
        if args == (
            "show",
            f"{head}:data/ember-restart-3b/owned-text-lab-corpus-v4.json",
        ):
            return corpus_bytes
        raise AssertionError(args)

    monkeypatch.setattr(module.BASE, "git", fake_git)
    module.configure_base(
        root=tmp_path,
        control_rebased_head=head,
        treatment_rebased_head=head,
        aa_mode=True,
    )
    output = tmp_path / "terminal.json"
    module.write_exclusive_refusal(output, ValueError("PLANTED_AA_REFUSAL"))

    refusal = json.loads(
        output.with_name("terminal.refusal.json").read_text()
    )
    expected = module.BASE.sha256_bytes(control_model)
    assert refusal["result"] == "REFUSED"
    assert refusal["issue"] == module.AA_ISSUE == 2112
    assert refusal["schema_version"] == module.AA_SCHEMA_VERSION
    assert refusal["aa_mode"] is True
    assert refusal["aa_pair_order_alternated"] is True
    assert refusal["aa_warm_window_updates"] == module.AA_WARM_WINDOW_UPDATES
    assert refusal["aa_warm_stability_epsilon"] == module.AA_WARM_STABILITY_EPSILON
    assert refusal["aa_warm_horizon_windows"] == module.AA_WARM_HORIZON_WINDOWS
    assert (
        refusal["aa_post_switch_excluded_updates"]
        == module.AA_POST_SWITCH_EXCLUDED_UPDATES
    )
    assert refusal["control_source_head"] == head
    assert refusal["treatment_source_head"] == head
    assert refusal["source_lineage"] == {
        "control_predecessor_head": head,
        "treatment_predecessor_head": head,
    }
    assert refusal["control_source_model_sha256"] == expected
    assert refusal["treatment_source_model_sha256"] == expected
    assert (
        refusal["text_lab_corpus_sha256"]
        == module.BASE.sha256_bytes(corpus_bytes)
    )
    assert refusal["aa_source_head"] == head
    assert (
        refusal["predecessor_text_lab_corpus_sha256"]
        == module.PREDECESSOR_TEXT_LAB_CORPUS_SHA256
    )


def test_configured_aa_derives_corpus_authority_from_source_head(
    monkeypatch, tmp_path: Path
):
    module = _load(
        "issue2081_runner_configured_aa_corpus",
        "issue2081_position_robust_canary_v1.py",
    )
    head = "a" * 40
    corpus = tmp_path / "data" / "ember-restart-3b" / "owned-text-lab-corpus-v4.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_bytes(b"m7-corpus")
    expected = module.BASE.sha256_path(corpus)

    monkeypatch.setattr(
        module.BASE,
        "git",
        lambda root, *args: corpus.read_bytes()
        if args == (
            "show",
            f"{head}:data/ember-restart-3b/owned-text-lab-corpus-v4.json",
        )
        else b"model",
    )

    module.configure_base(
        root=tmp_path,
        control_rebased_head=head,
        treatment_rebased_head=head,
        aa_mode=True,
    )

    assert module.BASE.TEXT_LAB_CORPUS_SHA256 == expected
    assert module.BASE.validate_text_lab_corpus(corpus, expected) == expected
    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        module.BASE.validate_text_lab_corpus(corpus, "0" * 64)


def test_configured_aa_refuses_repo_root_corpus_drift(
    monkeypatch, tmp_path: Path
):
    module = _load(
        "issue2081_runner_configured_aa_refuses_predecessor_corpus",
        "issue2081_position_robust_canary_v1.py",
    )
    head = "a" * 40
    corpus = tmp_path / "data" / "ember-restart-3b" / "owned-text-lab-corpus-v4.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_bytes(b"repo-root-drift")
    monkeypatch.setattr(
        module.BASE,
        "git",
        lambda root, *args: b"source-head-corpus"
        if args == (
            "show",
            f"{head}:data/ember-restart-3b/owned-text-lab-corpus-v4.json",
        )
        else b"model",
    )
    module.configure_base(
        root=tmp_path,
        control_rebased_head=head,
        treatment_rebased_head=head,
        aa_mode=True,
    )

    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        module.BASE.validate_text_lab_corpus(corpus, module.BASE.TEXT_LAB_CORPUS_SHA256)


def test_configured_aa_refuses_missing_source_head_corpus_blob(
    monkeypatch, tmp_path: Path
):
    module = _load(
        "issue2081_runner_configured_aa_missing_corpus_blob",
        "issue2081_position_robust_canary_v1.py",
    )
    monkeypatch.setattr(
        module.BASE,
        "git",
        lambda root, *args: (_ for _ in ()).throw(RuntimeError("GIT_REFUSED:missing")),
    )

    with pytest.raises(ValueError, match="AA_CORPUS_BLOB_MISSING_REFUSED"):
        module.configure_base(
            root=tmp_path,
            control_rebased_head="a" * 40,
            treatment_rebased_head="a" * 40,
            aa_mode=True,
        )


def test_configured_non_aa_refuses_control_corpus_pin(tmp_path: Path):
    module = _load(
        "issue2081_runner_configured_non_aa_refuses_control_corpus",
        "issue2081_position_robust_canary_v1.py",
    )
    corpus = tmp_path / "owned-text-lab-corpus-v4.json"
    corpus.write_bytes(b"predecessor-corpus")
    module.PREDECESSOR_TEXT_LAB_CORPUS_SHA256 = module.BASE.sha256_path(corpus)
    module.configure_base(
        root=tmp_path,
        control_rebased_head="a" * 40,
        treatment_rebased_head="b" * 40,
        aa_mode=False,
    )

    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        module.BASE.validate_text_lab_corpus(corpus, "0" * 64)

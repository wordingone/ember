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
    assert decision["aa_result"] == "HARNESS_POSITION_DEPENDENT"
    assert decision["disposition"] == "HARNESS_POSITION_DEPENDENT"


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
    assert decision["aa_result"] == "HARNESS_POSITION_DEPENDENT"


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

    def fake_git(repo_root: Path, *args: str) -> bytes:
        assert repo_root == tmp_path
        if args == ("show", f"{head}:src/ember/model/model.py"):
            return control_model
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
    assert refusal["issue"] == 2103
    assert refusal["schema_version"] == module.AA_SCHEMA_VERSION
    assert refusal["aa_mode"] is True
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
        == module.AA_CONTROL_TEXT_LAB_CORPUS_SHA256
    )
    assert (
        refusal["predecessor_text_lab_corpus_sha256"]
        == module.PREDECESSOR_TEXT_LAB_CORPUS_SHA256
    )


def test_configured_aa_rebinds_frozen_c1a7_corpus_authority(tmp_path: Path):
    module = _load(
        "issue2081_runner_configured_aa_corpus",
        "issue2081_position_robust_canary_v1.py",
    )
    corpus = tmp_path / "owned-text-lab-corpus-v4.json"
    corpus.write_bytes(b"c1a7-corpus")
    expected = module.BASE.sha256_path(corpus)
    module.AA_CONTROL_TEXT_LAB_CORPUS_SHA256 = expected

    module.configure_base(
        root=tmp_path,
        control_rebased_head="a" * 40,
        treatment_rebased_head="a" * 40,
        aa_mode=True,
    )

    assert module.BASE.TEXT_LAB_CORPUS_SHA256 == expected
    assert module.BASE.validate_text_lab_corpus(corpus, expected) == expected
    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        module.BASE.validate_text_lab_corpus(corpus, "0" * 64)


def test_configured_aa_refuses_predecessor_corpus_pin(tmp_path: Path):
    module = _load(
        "issue2081_runner_configured_aa_refuses_predecessor_corpus",
        "issue2081_position_robust_canary_v1.py",
    )
    corpus = tmp_path / "owned-text-lab-corpus-v4.json"
    corpus.write_bytes(b"c1a7-corpus")
    module.AA_CONTROL_TEXT_LAB_CORPUS_SHA256 = module.BASE.sha256_path(corpus)
    module.configure_base(
        root=tmp_path,
        control_rebased_head="a" * 40,
        treatment_rebased_head="a" * 40,
        aa_mode=True,
    )

    with pytest.raises(ValueError, match="TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED"):
        module.BASE.validate_text_lab_corpus(
            corpus, module.PREDECESSOR_TEXT_LAB_CORPUS_SHA256
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
        module.BASE.validate_text_lab_corpus(
            corpus, module.AA_CONTROL_TEXT_LAB_CORPUS_SHA256
        )

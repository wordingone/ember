#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the Ember MVP A/B/C equal-budget wheel fixture."""
from __future__ import annotations

import tempfile
import json
from pathlib import Path

import ember_wheel_harness as wheel


def _write_benchmark(path: Path, arm: str, improvement: float, *, executed: bool = True) -> Path:
    contracts = {
        "A": {
            "id": "A",
            "name": "direct-benchmark-iteration",
            "uses_dream_loop": False,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
        },
        "B": {
            "id": "B",
            "name": "dream-loop-only",
            "uses_dream_loop": True,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
        },
        "C": {
            "id": "C",
            "name": "full-mvp-loop",
            "uses_dream_loop": True,
            "uses_latent_branch": True,
            "uses_state_commit": True,
            "uses_replay": True,
        },
    }
    receipt = {
        "ticket": "EMBER-MLE-MICRO-REAL-RUN",
        "ts": "20260617T000000Z",
        "cycle_id": f"cycle-{arm}",
        "benchmark_subset": {
            "id": "mle-low-micro-v0",
            "task_ids": wheel.MLE_LOW_MICRO_TASK_IDS,
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "real_mle_tasks_executed": executed,
        "frozen_before_execution": True,
        "wheel_arm": contracts[arm],
        "score": {
            "baseline_score": 0.5,
            "candidate_score": 0.5 + (0.5 * improvement),
            "mean_normalized_improvement": improvement,
        },
        "verdict": "PASS" if executed else "BLOCKED",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _write_heldout_benchmark(
    path: Path,
    arm: str,
    improvement: float,
    *,
    external_source_certified: bool = False,
    ticket: str = "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA",
) -> Path:
    contracts = {
        "A": {
            "id": "A",
            "name": "direct-benchmark-iteration",
            "uses_dream_loop": False,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
        },
        "B": {
            "id": "B",
            "name": "dream-loop-only",
            "uses_dream_loop": True,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
        },
        "C": {
            "id": "C",
            "name": "full-mvp-loop",
            "uses_dream_loop": True,
            "uses_latent_branch": True,
            "uses_state_commit": True,
            "uses_replay": True,
        },
    }
    receipt = {
        "ticket": ticket,
        "ts": "20260618T000000Z",
        "cycle_id": f"cycle-{arm}",
        "lane": "kaggle_dataset_external_heldout"
        if ticket == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA"
        else "kaggle_benchmarks",
        "benchmark_family": "livecodebench/code_generation_lite",
        "question_id": "1873_A",
        "heldout_source": "local-frozen-fixture",
        "external_source_certified": external_source_certified,
        "frozen_heldout_sha256": "sha256:" + arm.lower() * 64,
        "heldout_case_count": 2,
        "heldout_delta_ready": True,
        "benchmark_delta_claimed": True,
        "external_benchmark_delta_claimed": external_source_certified,
        "wheel_arm": contracts[arm],
        "score": {
            "baseline_score": 0.0,
            "candidate_score": improvement,
            "mean_normalized_improvement": improvement,
        },
        "verdict": "EXTERNAL_HELDOUT_DELTA_RECEIPTED"
        if ticket == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA"
        else "HELDOUT_DELTA_RECEIPTED",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def test_fixture_wheel_receipts_equal_budget_and_ordering() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        receipt = wheel.run_fixture_wheel(Path(td), cycle_id="cycle-test-0001")

        assert receipt["ticket"] == "EMBER-WHEEL-FIXTURE"
        assert receipt["cycle_id"] == "cycle-test-0001"
        assert receipt["fixture_only"] is True
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["benchmark_subset"]["official_leaderboard_comparable"] is False
        assert receipt["equal_budget"] is True
        assert receipt["ordering"] == "C>B>A"
        assert receipt["growth_gate"]["growth_allowed"] is False
        assert receipt["growth_gate"]["blocked_until_repeated_positive_cycles"] == 3

        budgets = {arm["budget_seconds"] for arm in receipt["arms"]}
        assert budgets == {3600}
        improvements = {arm["id"]: arm["normalized_improvement"] for arm in receipt["arms"]}
        assert improvements["C"] > improvements["B"] > improvements["A"]

        wheel.validate_wheel_receipt(receipt)


def test_wheel_rejects_unequal_budget() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        receipt = wheel.run_fixture_wheel(Path(td), cycle_id="cycle-test-0001")
        broken = dict(receipt)
        broken["arms"] = [dict(arm) for arm in receipt["arms"]]
        broken["arms"][0]["budget_seconds"] = 1800

        try:
            wheel.validate_wheel_receipt(broken)
        except wheel.WheelValidationError as exc:
            assert "arms must use equal budget" in str(exc)
        else:
            raise AssertionError("unequal budget wheel receipt must fail")


def test_wheel_rejects_non_c_b_a_ordering() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        receipt = wheel.run_fixture_wheel(Path(td), cycle_id="cycle-test-0001")
        broken = dict(receipt)
        broken["arms"] = [dict(arm) for arm in receipt["arms"]]
        broken["arms"][2]["normalized_improvement"] = broken["arms"][1]["normalized_improvement"]

        try:
            wheel.validate_wheel_receipt(broken)
        except wheel.WheelValidationError as exc:
            assert "expected C>B>A normalized improvement" in str(exc)
        else:
            raise AssertionError("non C>B>A wheel receipt must fail")


def test_real_wheel_accepts_equal_budget_c_b_a_benchmark_receipts() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_benchmark(root / "bench" / "a.json", "A", 0.1)
        b = _write_benchmark(root / "bench" / "b.json", "B", 0.2)
        c = _write_benchmark(root / "bench" / "c.json", "C", 0.4)

        receipt = wheel.run_real_wheel(
            root / "out",
            cycle_id="cycle-wheel-real",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["ticket"] == "EMBER-WHEEL-REAL-RUN"
        assert receipt["fixture_only"] is False
        assert receipt["real_mle_tasks_executed"] is True
        assert receipt["equal_budget"] is True
        assert receipt["ordering"] == "C>B>A"
        assert receipt["verdict"] == "PASS"
        assert receipt["growth_gate"]["growth_allowed"] is False
        wheel.validate_real_wheel_receipt(receipt)


def test_real_wheel_blocks_non_executed_benchmark_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_benchmark(root / "bench" / "a.json", "A", 0.1)
        b = _write_benchmark(root / "bench" / "b.json", "B", 0.2, executed=False)
        c = _write_benchmark(root / "bench" / "c.json", "C", 0.4)

        receipt = wheel.run_real_wheel(
            root / "out",
            cycle_id="cycle-wheel-real",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["blocked_reason"] == "benchmark_receipts_not_real"
        assert "B" in receipt["blocked_arms"]
        wheel.validate_real_wheel_receipt(receipt)


def test_real_wheel_blocks_benchmark_receipt_without_arm_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_benchmark(root / "bench" / "a.json", "A", 0.1)
        b = _write_benchmark(root / "bench" / "b.json", "B", 0.2)
        c = _write_benchmark(root / "bench" / "c.json", "C", 0.4)
        c_obj = json.loads(c.read_text(encoding="utf-8"))
        c_obj.pop("wheel_arm")
        c.write_text(json.dumps(c_obj, indent=2) + "\n", encoding="utf-8", newline="\n")

        receipt = wheel.run_real_wheel(
            root / "out",
            cycle_id="cycle-wheel-real",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "arm_contract_mismatch"
        assert "C" in receipt["blocked_arms"]
        wheel.validate_real_wheel_receipt(receipt)


def test_real_wheel_blocks_b_arm_that_claims_state_commit() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_benchmark(root / "bench" / "a.json", "A", 0.1)
        b = _write_benchmark(root / "bench" / "b.json", "B", 0.2)
        c = _write_benchmark(root / "bench" / "c.json", "C", 0.4)
        b_obj = json.loads(b.read_text(encoding="utf-8"))
        b_obj["wheel_arm"]["uses_state_commit"] = True
        b.write_text(json.dumps(b_obj, indent=2) + "\n", encoding="utf-8", newline="\n")

        receipt = wheel.run_real_wheel(
            root / "out",
            cycle_id="cycle-wheel-real",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["verdict"] == "BLOCKED"
        assert receipt["blocked_reason"] == "arm_contract_mismatch"
        assert "B" in receipt["blocked_arms"]
        wheel.validate_real_wheel_receipt(receipt)


def test_public_test_proxy_wheel_records_candidate_vs_baseline_without_real_wheel_claim() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        proxy = root / "proxy.json"
        proxy.write_text(
            json.dumps(
                {
                    "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE",
                    "ts": "20260618T000000Z",
                    "cycle_id": "cycle-wheel-proxy",
                    "lane": "kaggle_benchmarks",
                    "benchmark_family": "livecodebench/code_generation_lite",
                    "question_id": "1873_A",
                    "frozen_public_test_sha256": "sha256:" + "a" * 64,
                    "baseline_public_pass": False,
                    "candidate_public_pass": True,
                    "public_test_delta": 1.0,
                    "candidate_vs_baseline_ready": True,
                    "benchmark_delta_claimed": False,
                    "score": {"mean_normalized_improvement": None},
                    "verdict": "PUBLIC_TEST_DELTA_RECEIPTED",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        receipt = wheel.run_public_test_proxy_wheel(
            root / "out",
            cycle_id="cycle-wheel-proxy",
            proxy_receipt_path=proxy,
        )

        assert receipt["ticket"] == "EMBER-WHEEL-PUBLIC-TEST-PROXY"
        assert receipt["verdict"] == "PROXY_DELTA_RECEIPTED"
        assert receipt["fixture_only"] is False
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["equal_budget"] is True
        assert receipt["ordering"] == "public-test-candidate>baseline"
        assert receipt["benchmark_delta_claimed"] is False
        assert receipt["public_test_proxy"]["ready"] is True
        assert receipt["public_test_proxy"]["public_test_delta"] == 1.0
        assert [arm["id"] for arm in receipt["arms"]] == ["A", "B", "C"]
        assert receipt["arms"][0]["public_test_pass"] is False
        assert receipt["arms"][1]["public_test_pass"] is None
        assert receipt["arms"][2]["public_test_pass"] is True
        wheel.validate_public_test_proxy_wheel_receipt(receipt)


def test_heldout_wheel_accepts_c_b_a_but_preserves_non_external_boundary() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_heldout_benchmark(root / "heldout" / "a.json", "A", 0.1)
        b = _write_heldout_benchmark(root / "heldout" / "b.json", "B", 0.2)
        c = _write_heldout_benchmark(root / "heldout" / "c.json", "C", 0.4)

        receipt = wheel.run_heldout_wheel(
            root / "out",
            cycle_id="cycle-heldout-wheel",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["ticket"] == "EMBER-WHEEL-HELDOUT-RUN"
        assert receipt["verdict"] == "HELDOUT_WHEEL_RECEIPTED"
        assert receipt["fixture_only"] is False
        assert receipt["real_mle_tasks_executed"] is False
        assert receipt["heldout_delta_ready"] is True
        assert receipt["benchmark_delta_claimed"] is True
        assert receipt["external_benchmark_delta_claimed"] is False
        assert receipt["equal_budget"] is True
        assert receipt["ordering"] == "C>B>A"
        assert receipt["blocked_reason"] is None
        assert [arm["id"] for arm in receipt["arms"]] == ["A", "B", "C"]
        assert [arm["normalized_improvement"] for arm in receipt["arms"]] == [0.1, 0.2, 0.4]
        assert all(arm["arm_contract_ok"] is True for arm in receipt["arms"])
        wheel.validate_heldout_wheel_receipt(receipt)


def test_heldout_wheel_claims_external_only_when_all_arms_are_external() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
        root = Path(td)
        a = _write_heldout_benchmark(
            root / "heldout" / "a.json",
            "A",
            0.1,
            external_source_certified=True,
            ticket="EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
        )
        b = _write_heldout_benchmark(
            root / "heldout" / "b.json",
            "B",
            0.2,
            external_source_certified=True,
            ticket="EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
        )
        c = _write_heldout_benchmark(
            root / "heldout" / "c.json",
            "C",
            0.4,
            external_source_certified=True,
            ticket="EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
        )

        receipt = wheel.run_heldout_wheel(
            root / "out",
            cycle_id="cycle-heldout-wheel",
            arm_receipts={"A": a, "B": b, "C": c},
        )

        assert receipt["verdict"] == "HELDOUT_WHEEL_RECEIPTED"
        assert receipt["external_benchmark_delta_claimed"] is True
        assert all(arm["external_benchmark_delta_claimed"] is True for arm in receipt["arms"])
        wheel.validate_heldout_wheel_receipt(receipt)


def main() -> int:
    tests = [
        test_fixture_wheel_receipts_equal_budget_and_ordering,
        test_wheel_rejects_unequal_budget,
        test_wheel_rejects_non_c_b_a_ordering,
        test_real_wheel_accepts_equal_budget_c_b_a_benchmark_receipts,
        test_real_wheel_blocks_non_executed_benchmark_receipt,
        test_real_wheel_blocks_benchmark_receipt_without_arm_contract,
        test_real_wheel_blocks_b_arm_that_claims_state_commit,
        test_public_test_proxy_wheel_records_candidate_vs_baseline_without_real_wheel_claim,
        test_heldout_wheel_accepts_c_b_a_but_preserves_non_external_boundary,
        test_heldout_wheel_claims_external_only_when_all_arms_are_external,
    ]
    for test in tests:
        test()
    print("EMBER_WHEEL_HARNESS_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

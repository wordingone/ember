#!/usr/bin/env python3
"""Equal-budget A/B/C wheel fixture for Ember MVP v0.

This records the first wheel contract before real long runs are attempted. It
is a fixture-only receipt: no real MLE-bench task is hydrated or executed here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
MLE_LOW_MICRO_TASK_IDS = [
    "detecting-insults-in-social-commentary",
    "random-acts-of-pizza",
    "spooky-author-identification",
    "nomad2018-predict-transparent-conductors",
    "leaf-classification",
]
ARM_BUDGET_SECONDS = 3600
ARM_CONTRACTS = {
    "A": {
        "name": "direct-benchmark-iteration",
        "uses_dream_loop": False,
        "uses_latent_branch": False,
        "uses_state_commit": False,
        "uses_replay": False,
    },
    "B": {
        "name": "dream-loop-only",
        "uses_dream_loop": True,
        "uses_latent_branch": False,
        "uses_state_commit": False,
        "uses_replay": False,
    },
    "C": {
        "name": "full-mvp-loop",
        "uses_dream_loop": True,
        "uses_latent_branch": True,
        "uses_state_commit": True,
        "uses_replay": True,
    },
}
REAL_BENCHMARK_TICKETS = {
    "EMBER-MLE-MICRO-REAL-RUN",
    "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN",
}
PUBLIC_TEST_PROXY_TICKET = "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE"
HELDOUT_BENCHMARK_TICKET = "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA"
HELDOUT_BENCHMARK_TICKETS = {
    HELDOUT_BENCHMARK_TICKET,
    "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
}


class WheelValidationError(ValueError):
    pass


def load_receipt(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _arms() -> list[dict[str, Any]]:
    return [
        {
            "id": "A",
            "name": "direct-benchmark-iteration",
            "budget_seconds": ARM_BUDGET_SECONDS,
            "uses_dream_loop": False,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
            "score": 0.5,
            "normalized_improvement": 0.0,
        },
        {
            "id": "B",
            "name": "dream-loop-only",
            "budget_seconds": ARM_BUDGET_SECONDS,
            "uses_dream_loop": True,
            "uses_latent_branch": False,
            "uses_state_commit": False,
            "uses_replay": False,
            "score": 0.625,
            "normalized_improvement": 0.25,
        },
        {
            "id": "C",
            "name": "full-mvp-loop",
            "budget_seconds": ARM_BUDGET_SECONDS,
            "uses_dream_loop": True,
            "uses_latent_branch": True,
            "uses_state_commit": True,
            "uses_replay": True,
            "requires": [
                "observation",
                "latent_branch",
                "sandbox",
                "verifier",
                "local_diff",
                "commit_or_revert",
                "governed_artifact",
                "replay",
            ],
            "score": 0.75,
            "normalized_improvement": 0.5,
        },
    ]


def run_fixture_wheel(root: Path, cycle_id: str) -> dict[str, Any]:
    root = Path(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "EMBER-WHEEL-FIXTURE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "fixture_only": True,
        "real_mle_tasks_executed": False,
        "benchmark_subset": {
            "id": "mle-low-micro-v0",
            "task_ids": MLE_LOW_MICRO_TASK_IDS,
            "official_leaderboard_comparable": False,
        },
        "wheel": {
            "id": "abc-equal-budget-v0",
            "description": "A direct iteration vs B dream-loop-only vs C full MVP loop",
        },
        "arms": _arms(),
        "equal_budget": True,
        "ordering": "C>B>A",
        "growth_gate": {
            "growth_allowed": False,
            "blocked_until_repeated_positive_cycles": 3,
            "next_cycle_ceiling_hours": 24,
            "reason": "fixture receipt only; real repeated external benchmark deltas required",
        },
        "verdict": "fixture-pass",
    }
    out = root / "receipts" / "wheel" / f"wheel-fixture-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_wheel_receipt(receipt)
    return receipt


def run_real_wheel(root: Path, cycle_id: str, arm_receipts: dict[str, Path]) -> dict[str, Any]:
    root = Path(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    loaded = {arm: load_receipt(Path(path)) for arm, path in arm_receipts.items()}
    arms = []
    blocked_arms = []
    contract_blocked_arms = []
    for arm_id, name in (
        ("A", "direct-benchmark-iteration"),
        ("B", "dream-loop-only"),
        ("C", "full-mvp-loop"),
    ):
        bench = loaded.get(arm_id, {})
        score = bench.get("score", {})
        contract_ok, contract_errors = _arm_contract_result(arm_id, bench.get("wheel_arm"))
        real = (
            bench.get("ticket") in REAL_BENCHMARK_TICKETS
            and bench.get("fixture_only") is False
            and bench.get("real_mle_tasks_executed") is True
            and isinstance(score.get("mean_normalized_improvement"), (int, float))
        )
        if not real:
            blocked_arms.append(arm_id)
        if not contract_ok:
            contract_blocked_arms.append(arm_id)
        arms.append(
            {
                "id": arm_id,
                "name": name,
                "budget_seconds": ARM_BUDGET_SECONDS,
                "benchmark_receipt": str(arm_receipts.get(arm_id)),
                "real_mle_tasks_executed": bool(bench.get("real_mle_tasks_executed")),
                "normalized_improvement": score.get("mean_normalized_improvement"),
                "arm_contract": bench.get("wheel_arm"),
                "arm_contract_ok": contract_ok,
                "arm_contract_errors": contract_errors,
            }
        )

    improvements = {arm["id"]: arm["normalized_improvement"] for arm in arms}
    ordering_ok = (
        isinstance(improvements.get("A"), (int, float))
        and isinstance(improvements.get("B"), (int, float))
        and isinstance(improvements.get("C"), (int, float))
        and improvements["C"] > improvements["B"] > improvements["A"]
    )
    blocked_reason = None
    verdict = "PASS"
    if contract_blocked_arms:
        verdict = "BLOCKED"
        blocked_reason = "arm_contract_mismatch"
    elif blocked_arms:
        verdict = "BLOCKED"
        blocked_reason = "benchmark_receipts_not_real"
    elif not ordering_ok:
        verdict = "FAIL"
        blocked_reason = "ordering_not_c_b_a"

    receipt = {
        "ticket": "EMBER-WHEEL-REAL-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "fixture_only": False,
        "real_mle_tasks_executed": verdict == "PASS",
        "benchmark_subset": {
            "id": "mle-low-micro-v0",
            "task_ids": MLE_LOW_MICRO_TASK_IDS,
            "official_leaderboard_comparable": False,
        },
        "wheel": {
            "id": "abc-equal-budget-v0",
            "description": "A direct iteration vs B dream-loop-only vs C full MVP loop",
        },
        "arms": arms,
        "equal_budget": True,
        "ordering": "C>B>A" if ordering_ok else "not-C>B>A",
        "blocked_reason": blocked_reason,
        "blocked_arms": sorted(set(blocked_arms + contract_blocked_arms)),
        "growth_gate": {
            "growth_allowed": False,
            "blocked_until_repeated_positive_cycles": 3,
            "next_cycle_ceiling_hours": 24,
            "reason": "real repeated positive external benchmark deltas required",
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "wheel" / f"wheel-real-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_real_wheel_receipt(receipt)
    return receipt


def run_public_test_proxy_wheel(root: Path, cycle_id: str, proxy_receipt_path: Path) -> dict[str, Any]:
    root = Path(root)
    proxy_receipt_path = Path(proxy_receipt_path)
    proxy = load_receipt(proxy_receipt_path)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    proxy_ready = _public_test_proxy_ready(proxy)
    public_test_proxy = {
        "ready": proxy_ready,
        "source_receipt": str(proxy_receipt_path),
        "lane": proxy.get("lane"),
        "benchmark_family": proxy.get("benchmark_family"),
        "question_id": proxy.get("question_id"),
        "baseline_public_pass": proxy.get("baseline_public_pass"),
        "candidate_public_pass": proxy.get("candidate_public_pass"),
        "public_test_delta": proxy.get("public_test_delta"),
        "benchmark_delta_claimed": proxy.get("benchmark_delta_claimed"),
        "frozen_public_test_sha256": proxy.get("frozen_public_test_sha256"),
    }
    receipt = {
        "ticket": "EMBER-WHEEL-PUBLIC-TEST-PROXY",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "benchmark_delta_claimed": False,
        "benchmark_subset": {
            "id": "kaggle-benchmarks-livecodebench-public-test-proxy-v0",
            "task_ids": [proxy.get("question_id")],
            "official_leaderboard_comparable": False,
        },
        "wheel": {
            "id": "abc-public-test-proxy-v0",
            "description": "A baseline vs C candidate public-test proxy; B is intentionally not evaluated",
        },
        "arms": [
            {
                "id": "A",
                "name": "public-test-baseline",
                "budget_seconds": ARM_BUDGET_SECONDS,
                "public_test_pass": proxy.get("baseline_public_pass"),
                "normalized_improvement": None,
            },
            {
                "id": "B",
                "name": "dream-loop-only",
                "budget_seconds": ARM_BUDGET_SECONDS,
                "public_test_pass": None,
                "normalized_improvement": None,
                "not_evaluated_reason": "candidate-vs-baseline proxy has no B arm",
            },
            {
                "id": "C",
                "name": "public-test-candidate",
                "budget_seconds": ARM_BUDGET_SECONDS,
                "public_test_pass": proxy.get("candidate_public_pass"),
                "normalized_improvement": None,
            },
        ],
        "public_test_proxy": public_test_proxy,
        "equal_budget": True,
        "ordering": "public-test-candidate>baseline" if proxy_ready else "not-public-test-candidate>baseline",
        "blocked_reason": None if proxy_ready else "public_test_proxy_not_ready",
        "blocked_arms": [] if proxy_ready else ["A", "C"],
        "growth_gate": {
            "growth_allowed": False,
            "blocked_until_repeated_positive_cycles": 3,
            "next_cycle_ceiling_hours": 24,
            "reason": "public-test proxy is not a full external benchmark wheel",
        },
        "verdict": "PROXY_DELTA_RECEIPTED" if proxy_ready else "BLOCKED",
    }
    out = root / "receipts" / "wheel" / f"wheel-public-test-proxy-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_public_test_proxy_wheel_receipt(receipt)
    return receipt


def _equal_arm_budget(arms: list[dict[str, Any]]) -> int | None:
    budgets = {arm.get("budget_seconds") for arm in arms}
    if len(budgets) == 1:
        value = next(iter(budgets))
        if isinstance(value, int) and value > 0:
            return value
    return None


def run_heldout_wheel(
    root: Path,
    cycle_id: str,
    arm_receipts: dict[str, Path],
    *,
    budget_seconds: int = ARM_BUDGET_SECONDS,
) -> dict[str, Any]:
    root = Path(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    loaded = {arm: load_receipt(Path(path)) for arm, path in arm_receipts.items()}
    arms = []
    blocked_arms = []
    contract_blocked_arms = []
    external_claims = []
    for arm_id, name in (
        ("A", "direct-benchmark-iteration"),
        ("B", "dream-loop-only"),
        ("C", "full-mvp-loop"),
    ):
        bench = loaded.get(arm_id, {})
        score = bench.get("score", {})
        contract_ok, contract_errors = _arm_contract_result(arm_id, bench.get("wheel_arm"))
        heldout_ready = (
            bench.get("ticket") in HELDOUT_BENCHMARK_TICKETS
            and bench.get("heldout_delta_ready") is True
            and bench.get("benchmark_delta_claimed") is True
            and isinstance(score.get("mean_normalized_improvement"), (int, float))
        )
        if not heldout_ready:
            blocked_arms.append(arm_id)
        if not contract_ok:
            contract_blocked_arms.append(arm_id)
        external_claims.append(bool(bench.get("external_benchmark_delta_claimed")))
        arms.append(
            {
                "id": arm_id,
                "name": name,
                "budget_seconds": budget_seconds,
                "benchmark_receipt": str(arm_receipts.get(arm_id)),
                "heldout_delta_ready": bool(bench.get("heldout_delta_ready")),
                "heldout_source": bench.get("heldout_source"),
                "external_source_certified": bool(bench.get("external_source_certified")),
                "external_benchmark_delta_claimed": bool(bench.get("external_benchmark_delta_claimed")),
                "normalized_improvement": score.get("mean_normalized_improvement"),
                "arm_contract": bench.get("wheel_arm"),
                "arm_contract_ok": contract_ok,
                "arm_contract_errors": contract_errors,
            }
        )

    improvements = {arm["id"]: arm["normalized_improvement"] for arm in arms}
    ordering_ok = (
        isinstance(improvements.get("A"), (int, float))
        and isinstance(improvements.get("B"), (int, float))
        and isinstance(improvements.get("C"), (int, float))
        and improvements["C"] > improvements["B"] > improvements["A"]
    )
    blocked_reason = None
    verdict = "HELDOUT_WHEEL_RECEIPTED"
    if contract_blocked_arms:
        verdict = "BLOCKED"
        blocked_reason = "arm_contract_mismatch"
    elif blocked_arms:
        verdict = "BLOCKED"
        blocked_reason = "heldout_benchmark_receipts_not_ready"
    elif not ordering_ok:
        verdict = "FAIL"
        blocked_reason = "ordering_not_c_b_a"

    external_benchmark_delta_claimed = verdict == "HELDOUT_WHEEL_RECEIPTED" and all(external_claims)
    c_receipt = loaded.get("C", {})
    if c_receipt.get("ticket") == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA":
        benchmark_subset = {
            "id": "kaggle-dataset-external-heldout-v0",
            "dataset_ref": c_receipt.get("dataset_ref"),
            "heldout_source": c_receipt.get("heldout_source"),
            "heldout_case_count": c_receipt.get("heldout_case_count"),
            "frozen_heldout_sha256": c_receipt.get("frozen_heldout_sha256"),
            "official_leaderboard_comparable": False,
        }
    else:
        benchmark_subset = {
            "id": "kaggle-benchmarks-livecodebench-frozen-heldout-v0",
            "task_ids": [c_receipt.get("question_id")],
            "official_leaderboard_comparable": False,
        }
    receipt = {
        "ticket": "EMBER-WHEEL-HELDOUT-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "heldout_delta_ready": verdict == "HELDOUT_WHEEL_RECEIPTED",
        "benchmark_delta_claimed": verdict == "HELDOUT_WHEEL_RECEIPTED",
        "external_benchmark_delta_claimed": external_benchmark_delta_claimed,
        "benchmark_subset": benchmark_subset,
        "wheel": {
            "id": "abc-heldout-equal-budget-v0",
            "description": "A/B/C equal-budget wheel over frozen heldout Kaggle Benchmarks-style receipts",
        },
        "arms": arms,
        "equal_budget": True,
        "ordering": "C>B>A" if ordering_ok else "not-C>B>A",
        "blocked_reason": blocked_reason,
        "blocked_arms": sorted(set(blocked_arms + contract_blocked_arms)),
        "growth_gate": {
            "growth_allowed": False,
            "blocked_until_repeated_positive_cycles": 3,
            "next_cycle_ceiling_hours": 24,
            "reason": "heldout wheel is not growth-ready without repeated external-certified cycles",
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "wheel" / f"wheel-heldout-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_heldout_wheel_receipt(receipt)
    return receipt


def _public_test_proxy_ready(receipt: dict[str, Any]) -> bool:
    return bool(
        receipt.get("ticket") == PUBLIC_TEST_PROXY_TICKET
        and receipt.get("lane") == "kaggle_benchmarks"
        and receipt.get("candidate_vs_baseline_ready") is True
        and receipt.get("benchmark_delta_claimed") is False
        and receipt.get("baseline_public_pass") is False
        and receipt.get("candidate_public_pass") is True
        and isinstance(receipt.get("public_test_delta"), (int, float))
        and receipt.get("public_test_delta") > 0
        and isinstance(receipt.get("frozen_public_test_sha256"), str)
        and receipt.get("frozen_public_test_sha256", "").startswith("sha256:")
    )


def _arm_contract_result(arm_id: str, actual: Any) -> tuple[bool, list[str]]:
    expected = ARM_CONTRACTS[arm_id]
    errors = []
    if not isinstance(actual, dict):
        return False, ["missing wheel_arm contract"]
    if actual.get("id") != arm_id:
        errors.append("id mismatch")
    for key, value in expected.items():
        if actual.get(key) != value:
            errors.append(f"{key} mismatch")
    return not errors, errors


def validate_public_test_proxy_wheel_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-WHEEL-PUBLIC-TEST-PROXY":
        errors.append("bad ticket")
    if receipt.get("fixture_only") is not False:
        errors.append("public-test proxy wheel must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("public-test proxy wheel cannot claim real MLE task execution")
    if receipt.get("benchmark_delta_claimed") is not False:
        errors.append("public-test proxy wheel cannot claim benchmark delta")
    proxy = receipt.get("public_test_proxy", {})
    if proxy.get("ready") is True:
        if receipt.get("verdict") != "PROXY_DELTA_RECEIPTED":
            errors.append("ready public-test proxy wheel must use proxy delta verdict")
        if receipt.get("ordering") != "public-test-candidate>baseline":
            errors.append("ready public-test proxy wheel must record candidate-over-baseline ordering")
        if proxy.get("benchmark_delta_claimed") is not False:
            errors.append("ready public-test proxy must preserve no benchmark delta claim")
    elif receipt.get("verdict") != "BLOCKED":
        errors.append("unready public-test proxy wheel must be blocked")
    arms = receipt.get("arms", [])
    if [arm.get("id") for arm in arms] != ["A", "B", "C"]:
        errors.append("arms must be ordered A, B, C")
    if _equal_arm_budget(arms) is None:
        errors.append("arms must use equal budget")
    if len(arms) == 3 and arms[1].get("public_test_pass") is not None:
        errors.append("B arm must remain unevaluated for candidate-vs-baseline proxy")
    if receipt.get("growth_gate", {}).get("growth_allowed") is not False:
        errors.append("public-test proxy wheel cannot allow growth")
    if errors:
        raise WheelValidationError("; ".join(errors))


def validate_heldout_wheel_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-WHEEL-HELDOUT-RUN":
        errors.append("bad ticket")
    if receipt.get("fixture_only") is not False:
        errors.append("heldout wheel must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("heldout wheel cannot claim real MLE task execution")
    arms = receipt.get("arms", [])
    if [arm.get("id") for arm in arms] != ["A", "B", "C"]:
        errors.append("arms must be ordered A, B, C")
    if _equal_arm_budget(arms) is None:
        errors.append("arms must use equal budget")
    if receipt.get("verdict") == "HELDOUT_WHEEL_RECEIPTED":
        if receipt.get("heldout_delta_ready") is not True:
            errors.append("heldout wheel verdict requires heldout_delta_ready")
        if receipt.get("benchmark_delta_claimed") is not True:
            errors.append("heldout wheel verdict requires benchmark delta claim")
        if receipt.get("ordering") != "C>B>A":
            errors.append("heldout wheel verdict requires C>B>A")
        improvements = {arm.get("id"): arm.get("normalized_improvement") for arm in arms}
        if not (
            isinstance(improvements.get("A"), (int, float))
            and isinstance(improvements.get("B"), (int, float))
            and isinstance(improvements.get("C"), (int, float))
            and improvements["C"] > improvements["B"] > improvements["A"]
        ):
            errors.append("heldout wheel verdict requires numeric C>B>A improvements")
        if not all(arm.get("arm_contract_ok") is True for arm in arms):
            errors.append("heldout wheel verdict requires valid arm contracts")
        expected_external = all(arm.get("external_benchmark_delta_claimed") is True for arm in arms)
        if receipt.get("external_benchmark_delta_claimed") is not expected_external:
            errors.append("external benchmark delta claim must equal all arm external claims")
    else:
        if receipt.get("heldout_delta_ready") is True:
            errors.append("non-passing heldout wheel cannot claim heldout readiness")
        if receipt.get("benchmark_delta_claimed") is True:
            errors.append("non-passing heldout wheel cannot claim benchmark delta")
        if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
            errors.append("blocked heldout wheel must record blocked_reason")
    if receipt.get("growth_gate", {}).get("growth_allowed") is not False:
        errors.append("heldout wheel cannot allow growth")
    if errors:
        raise WheelValidationError("; ".join(errors))


def validate_real_wheel_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-WHEEL-REAL-RUN":
        errors.append("bad ticket")
    if receipt.get("fixture_only") is not False:
        errors.append("real wheel must not be marked fixture_only")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("real wheel must not claim official leaderboard comparability")
    arms = receipt.get("arms", [])
    if [arm.get("id") for arm in arms] != ["A", "B", "C"]:
        errors.append("arms must be ordered A, B, C")
    if _equal_arm_budget(arms) is None:
        errors.append("arms must use equal budget")
    for arm in arms:
        if arm.get("arm_contract_ok") is not True and receipt.get("verdict") == "PASS":
            errors.append(f"passing real wheel requires valid arm contract for {arm.get('id')}")
        if arm.get("arm_contract_ok") is False and not arm.get("arm_contract_errors"):
            errors.append(f"invalid arm contract must record errors for {arm.get('id')}")
    if receipt.get("verdict") == "PASS":
        if receipt.get("real_mle_tasks_executed") is not True:
            errors.append("passing real wheel must mark real MLE task execution")
        if receipt.get("ordering") != "C>B>A":
            errors.append("passing real wheel requires C>B>A")
    else:
        if receipt.get("real_mle_tasks_executed") is not False:
            errors.append("non-passing wheel cannot claim real MLE task execution")
        if not receipt.get("blocked_reason") and receipt.get("verdict") == "BLOCKED":
            errors.append("blocked wheel must record blocked_reason")
    if receipt.get("growth_gate", {}).get("growth_allowed") is not False:
        errors.append("real wheel cannot allow growth on first run")
    if errors:
        raise WheelValidationError("; ".join(errors))


def validate_wheel_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-WHEEL-FIXTURE":
        errors.append("bad ticket")
    if not receipt.get("cycle_id"):
        errors.append("missing cycle_id")
    if receipt.get("fixture_only") is not True:
        errors.append("wheel fixture must be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("fixture wheel must not claim real MLE task execution")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("wheel fixture must not claim official leaderboard comparability")

    arms = receipt.get("arms", [])
    if [arm.get("id") for arm in arms] != ["A", "B", "C"]:
        errors.append("arms must be ordered A, B, C")
    if _equal_arm_budget(arms) is None:
        errors.append("arms must use equal budget")

    improvements = {arm.get("id"): arm.get("normalized_improvement") for arm in arms}
    if not (
        isinstance(improvements.get("A"), (int, float))
        and isinstance(improvements.get("B"), (int, float))
        and isinstance(improvements.get("C"), (int, float))
        and improvements["C"] > improvements["B"] > improvements["A"]
    ):
        errors.append("expected C>B>A normalized improvement")
    if receipt.get("ordering") != "C>B>A":
        errors.append("ordering field must be C>B>A")
    if receipt.get("growth_gate", {}).get("growth_allowed") is not False:
        errors.append("fixture wheel cannot allow growth")
    if errors:
        raise WheelValidationError("; ".join(errors))


def main() -> int:
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture-out", help="write a fixture wheel receipt under this directory")
    ap.add_argument("--cycle-id", default="cycle-20260617T000000Z-0001")
    ap.add_argument("--real", action="store_true", help="write a real A/B/C wheel receipt")
    ap.add_argument("--arm-a", help="benchmark receipt for arm A")
    ap.add_argument("--arm-b", help="benchmark receipt for arm B")
    ap.add_argument("--arm-c", help="benchmark receipt for arm C")
    ap.add_argument("--budget-seconds", type=int, default=ARM_BUDGET_SECONDS)
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-wheel-") as td:
            run_fixture_wheel(Path(td), cycle_id=args.cycle_id)
        print("EMBER_WHEEL_HARNESS_SELFTEST_PASS")
        return 0

    if args.fixture_out:
        if args.real:
            if not (args.arm_a and args.arm_b and args.arm_c):
                raise SystemExit("--arm-a, --arm-b, and --arm-c are required with --real")
            receipt = run_real_wheel(
                Path(args.fixture_out),
                cycle_id=args.cycle_id,
                arm_receipts={"A": Path(args.arm_a), "B": Path(args.arm_b), "C": Path(args.arm_c)},
            )
        elif args.arm_a or args.arm_b or args.arm_c:
            if not (args.arm_a and args.arm_b and args.arm_c):
                raise SystemExit("--arm-a, --arm-b, and --arm-c must be supplied together")
            receipt = run_heldout_wheel(
                Path(args.fixture_out),
                cycle_id=args.cycle_id,
                arm_receipts={"A": Path(args.arm_a), "B": Path(args.arm_b), "C": Path(args.arm_c)},
                budget_seconds=args.budget_seconds,
            )
        else:
            receipt = run_fixture_wheel(Path(args.fixture_out), cycle_id=args.cycle_id)
        print(json.dumps(receipt, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

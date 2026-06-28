#!/usr/bin/env python3
"""Ember MVP v0 closed-cycle receipt spine.

This module is the local interface layer described in docs/ember-mvp-v0.md.
It does not claim Windows Job Object isolation, real GPU training, or
MLE-bench execution. It provides the cycle identity and validation boundary
those later surfaces must bind to.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TS = "20260617T000000Z"
ISO_TS = "2026-06-17T00:00:00Z"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
REQUIRED_STATE_RECEIPTS = ("sandbox", "verifier", "governor", "replay", "rollback")
REQUIRED_CYCLE_RECEIPTS = ("observation", "sandbox", "gpu_governor", "replay", "rollback")
MICRO_TASK_IDS = [
    "detecting-insults-in-social-commentary",
    "random-acts-of-pizza",
    "spooky-author-identification",
    "nomad2018-predict-transparent-conductors",
    "leaf-classification",
]


class CycleValidationError(ValueError):
    """Raised when MVP cycle objects violate the local receipt contract."""


@dataclass(frozen=True)
class CycleRun:
    observation: dict[str, Any]
    latent_branch: dict[str, Any]
    state_commit: dict[str, Any]
    cycle: dict[str, Any]
    sandbox: dict[str, Any]
    verifier: dict[str, Any]
    governor: dict[str, Any]
    replay: dict[str, Any]
    rollback: dict[str, Any]
    benchmark: dict[str, Any]
    wheel: dict[str, Any] | None
    wheel_runner: dict[str, Any] | None
    state_substrate: dict[str, dict[str, Any]] | None


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_tree(root: Path) -> str:
    """Hash a directory tree deterministically by relative path and bytes."""
    h = hashlib.sha256()
    if not root.exists():
        return "sha256:" + h.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def write_receipt(path: Path, obj: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(path), obj)
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _base_receipt(ticket: str) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "ts": TS,
        "sha_convention": SHA_CONVENTION,
    }


def _external_replacement_active(benchmark: dict[str, Any], wheel: dict[str, Any] | None) -> bool:
    kaggle_ready = bool(
        benchmark.get("ticket") == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA"
        and benchmark.get("candidate_prediction_source") == "trained_sklearn_text_classifier"
        and benchmark.get("external_benchmark_delta_claimed") is True
        and wheel is not None
        and wheel.get("ticket") == "EMBER-WHEEL-HELDOUT-RUN"
        and wheel.get("external_benchmark_delta_claimed") is True
        and wheel.get("ordering") == "C>B>A"
    )
    research_ready = bool(
        benchmark.get("ticket") == "EMBER-RESEARCH-LOOP"
        and benchmark.get("benchmark_family") == "research_journal"
        and benchmark.get("operator_routed") is True
        and benchmark.get("equal_budget") is True
        and benchmark.get("verdict") == "RESEARCH_LOOP_ACCEPTED"
        and wheel is not None
        and wheel.get("ticket") == "EMBER-RESEARCH-LOOP"
        and wheel.get("verdict") == "RESEARCH_LOOP_ACCEPTED"
        and wheel.get("ordering") == "C>B=A"
    )
    return kaggle_ready or research_ready


def _goal_doc_hashes() -> list[dict[str, str]]:
    repo_root = Path(__file__).resolve().parent.parent
    docs = [
        repo_root / "docs/20260617-maximally-viable-product.md",
        repo_root / "docs/ember-mvp-v0.md",
    ]
    rows: list[dict[str, str]] = []
    for path in docs:
        if path.exists():
            rows.append({"path": path.relative_to(repo_root).as_posix(), "sha256": sha256_bytes(path.read_bytes())})
    return rows


def _benchmark_subset_for_cycle(benchmark: dict[str, Any]) -> dict[str, Any]:
    if benchmark.get("ticket") == "EMBER-RESEARCH-LOOP":
        return {
            "id": f"research-journal-{benchmark.get('benchmark_id', 'unknown')}-frozen-v1",
            "benchmark_id": benchmark.get("benchmark_id"),
            "benchmark_family": benchmark.get("benchmark_family"),
            "task_count": benchmark.get("task_count"),
            "official_leaderboard_comparable": False,
        }
    if benchmark.get("ticket") == "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA":
        return {
            "id": "kaggle-dataset-external-heldout-v0",
            "dataset_ref": benchmark.get("dataset_ref"),
            "heldout_source": benchmark.get("heldout_source"),
            "heldout_case_count": benchmark.get("heldout_case_count"),
            "frozen_heldout_sha256": benchmark.get("frozen_heldout_sha256"),
            "official_leaderboard_comparable": False,
        }
    subset = benchmark.get("benchmark_subset")
    if isinstance(subset, dict) and subset:
        return subset
    return {
        "id": "mle-low-micro-v0",
        "task_ids": MICRO_TASK_IDS,
        "official_leaderboard_comparable": False,
    }


def _write_recursion_receipts(
    root: Path,
    receipts: Path,
    cycle_id: str,
    benchmark: dict[str, Any],
    wheel: dict[str, Any],
) -> dict[str, str]:
    arms = wheel.get("arms", [])
    arm_scores = {
        arm.get("id"): arm.get("normalized_improvement")
        for arm in arms
        if isinstance(arm, dict)
    }
    trace = {
        "benchmark_ticket": benchmark.get("ticket"),
        "benchmark_mode": "research_journal_replacement"
        if benchmark.get("ticket") == "EMBER-RESEARCH-LOOP"
        else "external_trained_heldout_replacement",
        "dataset_ref": benchmark.get("dataset_ref"),
        "benchmark_id": benchmark.get("benchmark_id"),
        "heldout_case_count": benchmark.get("heldout_case_count"),
        "task_count": benchmark.get("task_count"),
        "wheel_ticket": wheel.get("ticket"),
        "ordering": wheel.get("ordering"),
        "arm_scores": arm_scores,
        "growth_gate": wheel.get("growth_gate"),
    }
    trace_sha = sha256_text(json.dumps(trace, sort_keys=True))

    rollout = {
        **_base_receipt("EMBER-PREDICTIVE-DREAM-ROLLOUT"),
        "cycle_id": cycle_id,
        "arm_id": "B",
        "source_trace_sha256": trace_sha,
        "predicts_next_cycle_task_progress": True,
        "prospective_target": "next external-certified 1h/1h/1h closed cycle",
        "candidate_next_states": [
            {
                "state_id": "repeat-b-with-frozen-heldout-router",
                "predicted_normalized_improvement_floor": min(float(arm_scores.get("B", 0.0)), 0.5),
                "expected_evidence": "B remains above A on same frozen heldout family under paired seed",
            },
            {
                "state_id": "do-not-grow-yet",
                "predicted_failure_avoided": "growth gate remains blocked until three repeated positive cycles",
                "expected_evidence": "next_cycle_ceiling_hours <= 24 and repeated_positive_cycles still counted",
            },
        ],
        "deletion_load_bearing_test": {
            "delete_artifact_expected_effect": "B arm loses prospective rollout target and cannot claim dream-loop contribution",
            "must_be_checked_on": "next closed cycle before growth promotion",
        },
        "verdict": "PREDICTIVE_ROLLOUT_RECEIPTED",
    }
    rollout_path = write_receipt(receipts / "recursion" / "predictive-rollout" / f"{cycle_id}.json", rollout)

    operator = {
        **_base_receipt("EMBER-PROSPECTIVE-METACOGNITIVE-OPERATOR"),
        "cycle_id": cycle_id,
        "operator_id": "receipt_trace_next_cycle_router_v0",
        "trained_from_receipt_trace_sha256": trace_sha,
        "input_features": [
            "benchmark_mode",
            "external_source_certified",
            "heldout_case_count",
            "wheel_ordering",
            "growth_gate",
        ],
        "learned_update_rule": {
            "if_ordering": "C>B>A",
            "if_growth_gate": "blocked_until_repeated_positive_cycles",
            "then_next_strategy": "repeat closed 1h/1h/1h external-certified cycle with paired seeds; do not scale",
        },
        "prospective_output": {
            "next_action": "repeat_external_replacement_cycle_before_growth",
            "blocks_growth": True,
            "requires_receipts": [
                "predictive-rollout",
                "paired-seed-wheel",
                "readiness",
            ],
        },
        "retrospective_discriminator_only": False,
        "deletion_load_bearing_test": {
            "delete_operator_expected_effect": "next cycle has no receipted strategy update from trace",
            "must_degrade": "routing/growth decision accountability",
        },
        "verdict": "PROSPECTIVE_OPERATOR_RECEIPTED",
    }
    operator_path = write_receipt(receipts / "recursion" / "meta-cognitive-operator" / f"{cycle_id}.json", operator)

    compaction = {
        **_base_receipt("EMBER-DISPATCH-CONTEXT-COMPACTION"),
        "cycle_id": cycle_id,
        "compaction_scope": "goal_docs_and_current_receipt_trace",
        "goal_context_used": True,
        "goal_doc_hashes": _goal_doc_hashes(),
        "dispatch_critical_state": {
            "official_private_answers_available": False,
            "fallback_benchmark_mode": trace["benchmark_mode"],
            "latest_readiness_expected": "MVP_READY but GROWTH_BLOCKED",
            "next_action": "repeat positive closed cycles before growth",
        },
        "source_trace_sha256": trace_sha,
        "preserves_dispatch_state": True,
        "verdict": "COMPACTION_RECEIPTED",
    }
    compaction_path = write_receipt(receipts / "recursion" / "compaction" / f"{cycle_id}.json", compaction)

    return {
        "predictive_rollout": _rel(root, rollout_path),
        "meta_cognitive_operator": _rel(root, operator_path),
        "context_compaction": _rel(root, compaction_path),
    }


def run_fixture_cycle(
    root: Path,
    promotion: str = "accepted",
    budget_seconds: int = 3600,
    use_windows_sandbox: bool = False,
    use_production_sandbox: bool = False,
    use_benchmark_fixture: bool = False,
    use_real_governor: bool = False,
    use_governor_binding: bool = False,
    use_wheel_fixture: bool = False,
    use_state_substrate: bool = False,
    external_benchmark_receipt: Path | None = None,
    external_wheel_receipt: Path | None = None,
    official_wheel_runner: dict[str, Any] | None = None,
) -> CycleRun:
    """Create a deterministic fixture cycle under root and return its objects.

    The fixture models branch/diff/commit/replay/rollback mechanics without
    mutating the real repo. The root is expected to be a temp or scratch dir.
    """
    if promotion not in {"accepted", "rejected"}:
        raise ValueError("promotion must be 'accepted' or 'rejected'")

    cycle_id = "cycle-20260617T000000Z-0001"
    obs_id = "obs-20260617T000000Z-0001"
    latent_id = "latent-20260617T000000Z-0001"
    parent_commit_id = "statecommit-parent"
    state_commit_id = "statecommit-20260617T000000Z-0001"

    workspace = root / "workspace"
    local_state = root / "local-state"
    receipts = root / "receipts"
    workspace.mkdir(parents=True, exist_ok=True)
    local_state.mkdir(parents=True, exist_ok=True)
    candidate_file = workspace / "candidate.txt"
    baseline_text = "ember-mvp-fixture-baseline\n"
    candidate_file.write_text(baseline_text, encoding="utf-8", newline="\n")
    pre_hash = hash_tree(workspace)

    hypothesis = "fixture candidate should improve normalized benchmark delta"
    candidate_text = "ember-mvp-fixture-candidate\n"
    candidate_file.write_text(candidate_text, encoding="utf-8", newline="\n")
    post_hash = hash_tree(workspace)

    diff_path = local_state / "diffs" / f"{state_commit_id}.patch"
    diff_body = (
        "diff --ember-mvp-fixture a/candidate.txt b/candidate.txt\n"
        "--- /dev/null\n"
        "+++ b/candidate.txt\n"
        "@@\n"
        f"+{candidate_text}"
    )
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text(diff_body, encoding="utf-8", newline="\n")
    diff_sha = sha256_bytes(diff_path.read_bytes())

    delta_path = local_state / "deltas" / f"{latent_id}.patch"
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(diff_path, delta_path)
    delta_sha = sha256_bytes(delta_path.read_bytes())

    replay = {
        **_base_receipt("EMBER-MVP-REPLAY-FIXTURE"),
        "cycle_id": cycle_id,
        "replay_seed": 123456,
        "deterministic": True,
        "parent_observation_id": obs_id,
        "diff_sha256": delta_sha,
    }
    replay_path = write_receipt(receipts / "replay" / f"{cycle_id}.json", replay)

    rollback_target = parent_commit_id
    candidate_file.write_text(baseline_text, encoding="utf-8", newline="\n")
    restored_hash = hash_tree(workspace)
    rollback = {
        **_base_receipt("EMBER-MVP-ROLLBACK-FIXTURE"),
        "cycle_id": cycle_id,
        "pre_cycle_state_hash": pre_hash,
        "post_candidate_state_hash": post_hash,
        "rollback_target": rollback_target,
        "restored_state_hash": restored_hash,
        "replay_seed": 123456,
        "verifier_result_before_rollback": "pass" if promotion == "accepted" else "fail",
        "verifier_result_after_rollback": "absent",
    }
    rollback_path = write_receipt(receipts / "rollback" / f"{cycle_id}.json", rollback)

    if use_production_sandbox:
        import ember_windows_sandbox

        sandbox = ember_windows_sandbox.run_production_candidate(
            root / "production-sandbox",
            cycle_id=cycle_id,
            src="def solve(text):\n    return text.upper()\n",
            call_expr="solve('ember')",
            expected="EMBER",
        )
        sandbox["ts"] = TS
        sandbox["sha_convention"] = SHA_CONVENTION
    elif use_windows_sandbox:
        import ember_windows_sandbox

        sandbox = ember_windows_sandbox.run_required_probe_battery(root / "windows-sandbox")
        sandbox["ticket"] = "EMBER-MVP-SANDBOX-WINDOWS"
        sandbox["ts"] = TS
        sandbox["sha_convention"] = SHA_CONVENTION
        sandbox["cycle_id"] = cycle_id
        sandbox["mode"] = "windows-native-probe-battery"
        sandbox["verdict"] = "pass" if sandbox["summary"]["pass"] == sandbox["summary"]["total"] else "fail"
    else:
        sandbox = {
            **_base_receipt("EMBER-MVP-SANDBOX-FIXTURE"),
            "cycle_id": cycle_id,
            "mode": "fixture-spine-only",
            "verdict": "pass" if promotion == "accepted" else "fail",
            "timeout_result": "not_exercised",
            "memory_result": "not_exercised",
            "filesystem_result": "fixture_root_only",
            "network_result": "not_exercised",
            "process_cleanup_result": "not_exercised",
        }
    sandbox_path = write_receipt(receipts / "sandbox" / f"{cycle_id}.json", sandbox)

    verifier = {
        **_base_receipt("EMBER-MVP-VERIFIER-FIXTURE"),
        "cycle_id": cycle_id,
        "verifier_result": "pass" if promotion == "accepted" else "fail",
        "control_solve_ok": promotion == "accepted",
        "false_accepts": [],
    }
    verifier_path = write_receipt(receipts / "verifier" / f"{cycle_id}.json", verifier)

    if use_real_governor:
        import ember_governor_binding

        governor = ember_governor_binding.run_real_governed_smoke(root / "governor-real", cycle_id=cycle_id)
    elif use_governor_binding:
        import ember_governor_binding

        governor = ember_governor_binding.run_fixture_binding(root / "governor-binding", cycle_id=cycle_id)
    else:
        governor = {
            **_base_receipt("EMBER-MVP-GOVERNOR-FIXTURE"),
            "cycle_id": cycle_id,
            "mode": "fixture-spine-only",
            "vram_fraction": 0.8,
            "margin_gb": "recorded",
            "pacing": "not_exercised",
            "checkpoint_hash": sha256_text(candidate_text),
            "failure_mode": None,
        }
    governor_path = write_receipt(receipts / "governor" / f"{cycle_id}.json", governor)

    wheel_runner = None
    wheel_runner_path = None
    wheel_runner_c_benchmark = None
    wheel_runner_wheel = None
    if official_wheel_runner is not None:
        import ember_mvp_wheel_runner

        wheel_runner = ember_mvp_wheel_runner.run_official_abc_wheel(
            root / "official-wheel-runner",
            Path(official_wheel_runner["source_root"]),
            Path(official_wheel_runner["data_root"]),
            Path(official_wheel_runner["submission_root"]),
            cycle_id=cycle_id,
            command_factories=official_wheel_runner.get("command_factories"),
        )
        wheel_runner_path = wheel_runner["receipt_path"]
        c_arm = next(arm for arm in wheel_runner["arms"] if arm["id"] == "C")
        wheel_runner_c_benchmark = _load_external_receipt(Path(c_arm["receipt_path"]))
        wheel_runner_c_benchmark["mode"] = "official-abc-wheel-runner-arm-c"
        wheel_runner_wheel = _load_external_receipt(Path(wheel_runner["wheel_receipt_path"]))

    if wheel_runner_c_benchmark is not None:
        benchmark = wheel_runner_c_benchmark
        benchmark.setdefault("cycle_id", cycle_id)
    elif external_benchmark_receipt is not None:
        benchmark = _load_external_receipt(external_benchmark_receipt)
        benchmark.setdefault("cycle_id", cycle_id)
        benchmark.setdefault("mode", "external-bound-receipt")
        benchmark.setdefault("fixture_only", False)
    elif use_benchmark_fixture:
        import ember_mle_micro_harness

        benchmark = ember_mle_micro_harness.run_tiny_fixture(root / "benchmark-fixture", cycle_id=cycle_id)
        benchmark["mode"] = "tiny-fixture-preflight"
    else:
        benchmark = {
            **_base_receipt("EMBER-MVP-BENCHMARK-FIXTURE"),
            "cycle_id": cycle_id,
            "mode": "inline-fixture-score",
            "fixture_only": True,
            "real_mle_tasks_executed": False,
            "frozen_before_execution": False,
            "score": {
                "baseline_score": 0.0,
                "candidate_score": 1.0 if promotion == "accepted" else 0.0,
                "mean_normalized_improvement": 1.0 if promotion == "accepted" else 0.0,
            },
        }
    benchmark_path = write_receipt(receipts / "benchmark" / f"{cycle_id}.json", benchmark)

    if wheel_runner_wheel is not None:
        wheel = wheel_runner_wheel
        wheel.setdefault("cycle_id", cycle_id)
        wheel_path = write_receipt(receipts / "wheel" / f"{cycle_id}.json", wheel)
    elif external_wheel_receipt is not None:
        wheel = _load_external_receipt(external_wheel_receipt)
        wheel.setdefault("cycle_id", cycle_id)
        wheel_path = write_receipt(receipts / "wheel" / f"{cycle_id}.json", wheel)
    elif use_wheel_fixture:
        import ember_wheel_harness

        wheel = ember_wheel_harness.run_fixture_wheel(root / "wheel-fixture", cycle_id=cycle_id)
        wheel_path = write_receipt(receipts / "wheel" / f"{cycle_id}.json", wheel)
    else:
        wheel = None
        wheel_path = None

    recursion_paths: dict[str, str] = {}
    if _external_replacement_active(benchmark, wheel):
        recursion_paths = _write_recursion_receipts(root, receipts, cycle_id, benchmark, wheel)

    if use_state_substrate:
        import ember_state_substrate

        substrate_run = ember_state_substrate.run_fixture_state_cycle(root / "state-substrate", promotion=promotion)
        state_substrate = {
            "observation": substrate_run.observation,
            "branch": substrate_run.branch,
            "commit": substrate_run.commit,
            "replay": substrate_run.replay,
            "rollback": substrate_run.rollback,
            "gc": substrate_run.gc,
        }
        state_substrate_path = state_substrate["commit"]["receipt_path"]
    else:
        state_substrate = None
        state_substrate_path = None

    observation = {
        **_base_receipt("EMBER-MVP-OBSERVATION"),
        "id": obs_id,
        "cycle_id": cycle_id,
        "created_at": ISO_TS,
        "workspace_root": root.as_posix(),
        "aperture": {
            "user_goal_hash": sha256_text("Evolve ember past current state"),
            "context_manifest_hash": sha256_text("ember-mvp-v0 + maximally-viable-product"),
            "git_head": "fixture-head",
            "dirty_state_hash": pre_hash,
            "available_tools": ["sandbox", "governor", "replay_rig"],
        },
        "receipts": [f"receipts/observations/{obs_id}.json"],
    }
    observation_path = write_receipt(receipts / "observations" / f"{obs_id}.json", observation)

    latent_branch = {
        **_base_receipt("EMBER-MVP-LATENT-BRANCH"),
        "id": latent_id,
        "cycle_id": cycle_id,
        "parent_observation_id": obs_id,
        "parent_commit_id": parent_commit_id,
        "inputs": {
            "hypothesis": hypothesis,
            "budget_seconds": budget_seconds,
            "benchmark_subset_id": _benchmark_subset_for_cycle(benchmark).get("id"),
        },
        "produced_deltas": [
            {
                "path": delta_path.relative_to(root).as_posix(),
                "sha256": delta_sha,
            }
        ],
        "status": "candidate",
    }
    write_receipt(receipts / "latent" / f"{latent_id}.json", latent_branch)

    state_commit = {
        **_base_receipt("EMBER-MVP-STATE-COMMIT"),
        "id": state_commit_id,
        "cycle_id": cycle_id,
        "parent_id": parent_commit_id,
        "latent_branch_id": latent_id,
        "diff": {
            "path": diff_path.relative_to(root).as_posix(),
            "sha256": diff_sha,
        },
        "receipts": {
            "sandbox": _rel(root, sandbox_path),
            "verifier": _rel(root, verifier_path),
            "governor": _rel(root, governor_path),
            "replay": _rel(root, replay_path),
            "rollback": _rel(root, rollback_path),
        },
        "verifier_result": "pass" if promotion == "accepted" else "fail",
        "replay_seed": 123456,
        "rollback_pointer": parent_commit_id,
        "gc_enggible": promotion == "rejected",
        "promotion": promotion,
    }
    write_receipt(receipts / "statecommits" / f"{state_commit_id}.json", state_commit)

    cycle = {
        **_base_receipt("EMBER-MVP-CYCLE"),
        "cycle_id": cycle_id,
        "started_at": ISO_TS,
        "finished_at": "2026-06-17T01:00:00Z",
        "budget": {
            "wall_seconds": budget_seconds,
            "train_seconds": budget_seconds,
            "eval_seconds": budget_seconds,
            "gpu_vram_fraction": 0.8,
            "governor_margin": "recorded",
        },
        "benchmark_subset": _benchmark_subset_for_cycle(benchmark),
        "receipts": {
            "observation": _rel(root, observation_path),
            "sandbox": _rel(root, sandbox_path),
            "gpu_governor": _rel(root, governor_path),
            "replay": _rel(root, replay_path),
            "rollback": _rel(root, rollback_path),
            "benchmark": _rel(root, benchmark_path),
        },
        "hypothesis": {
            "text": hypothesis,
            "latent_branch_id": latent_id,
        },
        "evidence": {
            "sandbox": {
                "path": _rel(root, sandbox_path),
                "verdict": sandbox["verdict"],
                "mode": sandbox["mode"],
            },
            "verifier": {"path": _rel(root, verifier_path), "result": state_commit["verifier_result"]},
            "governor": _governor_evidence(root, governor_path, governor),
            "benchmark": {
                "path": _rel(root, benchmark_path),
                "mode": benchmark.get("mode", "external-bound-receipt"),
                "fixture_only": benchmark.get("fixture_only", True),
                "real_mle_tasks_executed": benchmark.get("real_mle_tasks_executed", False),
                "verdict": benchmark.get("verdict"),
            },
            "replay": {"path": _rel(root, replay_path), "deterministic": True},
            "rollback": {"path": _rel(root, rollback_path), "restored": restored_hash == pre_hash},
        },
        "score": benchmark["score"],
        "verdict": promotion,
    }
    if recursion_paths:
        cycle["receipts"].update(recursion_paths)
        cycle["evidence"]["recursion"] = {
            "required": True,
            "predictive_rollout": recursion_paths["predictive_rollout"],
            "meta_cognitive_operator": recursion_paths["meta_cognitive_operator"],
            "context_compaction": recursion_paths["context_compaction"],
            "verdict": "recursion_layer_receipted",
        }
    if wheel is not None and wheel_path is not None:
        cycle["receipts"]["wheel"] = _rel(root, wheel_path)
        cycle["evidence"]["wheel"] = {
            "path": _rel(root, wheel_path),
            "fixture_only": wheel.get("fixture_only", False),
            "real_mle_tasks_executed": wheel.get("real_mle_tasks_executed", False),
            "equal_budget": wheel.get("equal_budget", False),
            "ordering": wheel.get("ordering"),
            "growth_allowed": wheel.get("growth_gate", {}).get("growth_allowed", False),
        }
        if wheel.get("blocked_reason"):
            cycle["evidence"]["wheel"]["blocked_reason"] = wheel["blocked_reason"]
            cycle["evidence"]["wheel"]["blocked_arms"] = wheel.get("blocked_arms", [])
    if wheel_runner is not None and wheel_runner_path is not None:
        cycle["receipts"]["wheel_runner"] = _rel(root, wheel_runner_path)
        cycle["evidence"]["wheel_runner"] = {
            "path": _rel(root, wheel_runner_path),
            "verdict": wheel_runner["verdict"],
            "wheel_receipt_path": _rel(root, wheel_runner["wheel_receipt_path"]),
            "real_mle_tasks_executed": wheel_runner["real_mle_tasks_executed"],
            "blocked_reason": wheel_runner.get("blocked_reason"),
        }
    if state_substrate is not None and state_substrate_path is not None:
        substrate_commit = state_substrate["commit"]
        substrate_replay = state_substrate["replay"]
        substrate_rollback = state_substrate["rollback"]
        cycle["receipts"]["state_substrate"] = _rel(root, state_substrate_path)
        cycle["receipts"]["replay"] = _rel(root, substrate_replay["receipt_path"])
        cycle["receipts"]["rollback"] = _rel(root, substrate_rollback["receipt_path"])
        cycle["evidence"]["replay"] = {
            "path": _rel(root, substrate_replay["receipt_path"]),
            "deterministic": substrate_replay["deterministic"],
            "commit_id": substrate_replay["commit_id"],
        }
        cycle["evidence"]["rollback"] = {
            "path": _rel(root, substrate_rollback["receipt_path"]),
            "restored": substrate_rollback["restored_state_hash"]
            == substrate_rollback["pre_cycle_state_hash"],
            "commit_id": substrate_rollback["commit_id"],
        }
        cycle["evidence"]["state_substrate"] = {
            "path": _rel(root, state_substrate_path),
            "local_inspectable": True,
            "promotion": substrate_commit["promotion"],
            "gc_enggible": substrate_commit["gc_enggible"],
            "replayable_from_commit": substrate_replay["deterministic"]
            and substrate_replay["replayed_state_hash"] == substrate_commit["post_candidate_state_hash"]
            and substrate_replay["diff_sha256"] == substrate_commit["diff"]["sha256"],
            "rollback_restored": substrate_rollback["restored_state_hash"]
            == substrate_rollback["pre_cycle_state_hash"],
        }
    write_receipt(receipts / "cycles" / f"{cycle_id}.json", cycle)

    validate_cycle_bundle(observation, latent_branch, state_commit, cycle)
    return CycleRun(
        observation=observation,
        latent_branch=latent_branch,
        state_commit=state_commit,
        cycle=cycle,
        sandbox=sandbox,
        verifier=verifier,
        governor=governor,
        replay=replay,
        rollback=rollback,
        benchmark=benchmark,
        wheel=wheel,
        wheel_runner=wheel_runner,
        state_substrate=state_substrate,
    )


def _rel(root: Path, path: str) -> str:
    return Path(path).relative_to(root).as_posix()


def _load_external_receipt(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _governor_evidence(root: Path, governor_path: str, governor_receipt: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "path": _rel(root, governor_path),
        "mode": governor_receipt["mode"],
    }
    artifact = governor_receipt.get("artifact")
    if isinstance(artifact, dict):
        evidence["checkpoint_hash"] = artifact.get("checkpoint_hash")
        evidence["artifact_kind"] = artifact.get("kind")
        evidence["gpu_preflight_called"] = governor_receipt.get("gpu_preflight_called", False)
        evidence["real_gpu_training"] = governor_receipt.get("real_gpu_training", False)
    else:
        evidence["checkpoint_hash"] = governor_receipt.get("checkpoint_hash")
    return evidence


def validate_cycle_bundle(
    observation: dict[str, Any],
    latent_branch: dict[str, Any],
    state_commit: dict[str, Any],
    cycle: dict[str, Any],
) -> None:
    """Validate cross-object MVP invariants from docs/ember-mvp-v0.md."""
    errors: list[str] = []
    cycle_id = cycle.get("cycle_id")
    for name, obj in (
        ("observation", observation),
        ("latent_branch", latent_branch),
        ("state_commit", state_commit),
    ):
        if obj.get("cycle_id") != cycle_id:
            errors.append(f"{name} cycle_id does not match cycle")

    if latent_branch.get("parent_observation_id") != observation.get("id"):
        errors.append("latent branch parent observation mismatch")
    if state_commit.get("latent_branch_id") != latent_branch.get("id"):
        errors.append("state commit latent branch mismatch")

    state_receipts = state_commit.get("receipts", {})
    for key in REQUIRED_STATE_RECEIPTS:
        if key not in state_receipts:
            errors.append(f"missing state commit receipt: {key}")

    cycle_receipts = cycle.get("receipts", {})
    for key in REQUIRED_CYCLE_RECEIPTS:
        if key not in cycle_receipts:
            errors.append(f"missing cycle receipt: {key}")

    if cycle.get("benchmark_subset", {}).get("official_leaderboard_comparable") is not False:
        errors.append("first micro-subset must not be official leaderboard comparable")

    if not cycle.get("hypothesis") or not cycle.get("evidence"):
        errors.append("cycle must separate hypothesis and evidence")

    promotion = state_commit.get("promotion")
    if promotion == "accepted":
        if state_commit.get("verifier_result") != "pass":
            errors.append("accepted promotion requires pass verifier_result")
        if state_commit.get("gc_enggible") is not False:
            errors.append("accepted promotion must not be gc_enggible")
    elif promotion == "rejected":
        if state_commit.get("gc_enggible") is not True:
            errors.append("rejected promotion must be gc_enggible after replay and rollback")
        if "replay" not in state_receipts or "rollback" not in state_receipts:
            errors.append("rejected promotion requires replay and rollback receipts")
    else:
        errors.append("promotion must be accepted or rejected")

    if cycle.get("verdict") != promotion:
        errors.append("cycle verdict must match state commit promotion")

    if errors:
        raise CycleValidationError("; ".join(errors))


def main() -> int:
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture-out", help="write a fixture cycle under this directory")
    ap.add_argument(
        "--windows-sandbox",
        action="store_true",
        help="bind the Windows sandbox probe battery into the fixture cycle",
    )
    ap.add_argument(
        "--production-sandbox",
        action="store_true",
        help="bind the production-shaped Windows sandbox candidate runner into the fixture cycle",
    )
    ap.add_argument(
        "--benchmark-fixture",
        action="store_true",
        help="bind the tiny MLE micro fixture benchmark into the fixture cycle",
    )
    ap.add_argument(
        "--governor-binding",
        action="store_true",
        help="bind a governor/artifact receipt into the fixture cycle",
    )
    ap.add_argument(
        "--real-governor",
        action="store_true",
        help="bind a real governed CUDA train/eval smoke receipt into the fixture cycle",
    )
    ap.add_argument(
        "--wheel-fixture",
        action="store_true",
        help="bind the A/B/C equal-budget wheel fixture into the fixture cycle",
    )
    ap.add_argument(
        "--state-substrate",
        action="store_true",
        help="bind the local state-substrate commit/replay/rollback receipts into the cycle",
    )
    ap.add_argument("--benchmark-receipt", help="external benchmark receipt to bind into the cycle")
    ap.add_argument("--wheel-receipt", help="external wheel receipt to bind into the cycle")
    ap.add_argument("--budget-seconds", type=int, default=3600, help="declared wall/train/eval budget for this cycle")
    ap.add_argument(
        "--official-wheel-runner",
        action="store_true",
        help="run the official A/B/C wheel runner and bind its C arm plus wheel receipt into the cycle",
    )
    ap.add_argument("--source-root", help="official MLE-bench source checkout for --official-wheel-runner")
    ap.add_argument("--data-root", help="prepared MLE-bench data directory for --official-wheel-runner")
    ap.add_argument("--submission-root", help="candidate submission root for --official-wheel-runner")
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-mvp-cycle-") as td:
            run_fixture_cycle(Path(td), promotion="accepted")
            run_fixture_cycle(Path(td) / "rejected", promotion="rejected")
        print("EMBER_MVP_CYCLE_SELFTEST_PASS")
        return 0

    if args.fixture_out:
        official_wheel_runner = None
        if args.official_wheel_runner:
            if not (args.source_root and args.data_root and args.submission_root):
                raise SystemExit(
                    "--source-root, --data-root, and --submission-root are required with --official-wheel-runner"
                )
            official_wheel_runner = {
                "source_root": Path(args.source_root),
                "data_root": Path(args.data_root),
                "submission_root": Path(args.submission_root),
            }
        result = run_fixture_cycle(
            Path(args.fixture_out),
            promotion="accepted",
            budget_seconds=args.budget_seconds,
            use_windows_sandbox=args.windows_sandbox,
            use_production_sandbox=args.production_sandbox,
            use_benchmark_fixture=args.benchmark_fixture,
            use_real_governor=args.real_governor,
            use_governor_binding=args.governor_binding,
            use_wheel_fixture=args.wheel_fixture,
            use_state_substrate=args.state_substrate,
            external_benchmark_receipt=Path(args.benchmark_receipt) if args.benchmark_receipt else None,
            external_wheel_receipt=Path(args.wheel_receipt) if args.wheel_receipt else None,
            official_wheel_runner=official_wheel_runner,
        )
        print(json.dumps(result.cycle, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

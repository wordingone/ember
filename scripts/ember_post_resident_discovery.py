"""Emit post-resident-gate discovery receipts for the Ember goal.

This script is intentionally data/static-source driven. It records the first
post-gate blocker after resident_training_gate_status=PASS:
1. exact benchmark/dataset discovery for self-improvement-by-experimentation;
2. past-Ember technique mining into an executable next-loop packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def checked_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def inspect_bitnet_receipt(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "verdict": None, "status": "MISSING"}
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256_file(path) if path.exists() else None,
        "verdict": data.get("verdict"),
        "resident_gate_receipt_status": data.get("resident_gate_receipt_status"),
        "quality_delta": data.get("quality_delta"),
        "next_executable_command": data.get("next_executable_command"),
        "status": "PASS" if data.get("verdict") == "BITNET_COMPARISON_PASS" else "BLOCKED",
    }


def build_benchmark_receipt(repo: Path, ts: str, source_path: Path | None, bitnet_receipt: Path | None) -> dict[str, Any]:
    goal = repo / "docs/authority/GOAL.md"
    d3_tasks = source_path or Path(
        r"<local-path>"
    )
    d3_task_hash = sha256_file(d3_tasks) if d3_tasks.exists() else None
    bitnet = inspect_bitnet_receipt(bitnet_receipt)

    candidates = [
        {
            "id": "d3-gym",
            "name": "D3-Gym",
            "primary_sources": [
                "https://arxiv.org/abs/2604.27977",
                "https://huggingface.co/datasets/osunlp/D3-Gym",
                "https://github.com/OSU-NLP-Group/D3-Gym",
            ],
            "dataset_or_task_count": "565 tasks from 239 real scientific repositories",
            "license_or_access_basis": "Hugging Face dataset card lists MIT for the metadata dataset; underlying repository license distribution includes MIT/GPL/BSD/Apache/CC/custom/no-license rows.",
            "task_evaluator_form": "natural language task, input dataset/artifact previews, reference implementation, executable or synthesized evaluation script, Docker environments for full tasks",
            "local_status": "FROZEN_EIGHT_ROW_METADATA_SLICE_AVAILABLE",
            "local_task_rows_path": str(d3_tasks),
            "local_task_rows_sha256": d3_task_hash,
            "fit_to_goal": [
                "world is an external scientific data/code environment",
                "agent must infer task/evaluator constraints from previews and scripts",
                "candidate can act by emitting code/artifacts",
                "evaluation script supplies verifier pressure",
                "training on task trajectories has published transfer signal to ScienceAgentBench",
            ],
            "limits": [
                "metadata slice is not the full Docker environment",
                "some underlying repositories lack explicit licenses",
                "using only the first local rows risks chemistry-domain narrowing",
            ],
            "recommended_use": "immediate small post-gate heldout loop while full environments are admitted",
        },
        {
            "id": "scienceagentbench",
            "name": "ScienceAgentBench",
            "primary_sources": [
                "https://arxiv.org/abs/2410.05080",
                "https://github.com/OSU-NLP-Group/ScienceAgentBench",
            ],
            "dataset_or_task_count": "102 tasks from 44 peer-reviewed publications across four disciplines",
            "license_or_access_basis": "public paper and code repository; exact task-data licenses must be admitted before local run",
            "task_evaluator_form": "self-contained Python program output, execution results, cost metrics, contamination mitigations",
            "local_status": "ADMISSION_REQUIRED",
            "fit_to_goal": [
                "closest modern external evaluation for data-driven scientific discovery",
                "requires programmatic work against real publication-derived tasks",
                "good candidate for field-level validation after small-loop proof",
            ],
            "limits": [
                "heavier setup than current frozen D3-Gym slice",
                "must verify downloadable task/data availability and license before execution",
            ],
            "recommended_use": "primary stronger post-D3 validation target",
        },
        {
            "id": "paperbench",
            "name": "PaperBench",
            "primary_sources": [
                "https://arxiv.org/abs/2504.01848",
                "https://github.com/openai/frontier-evals/tree/main/project/paperbench",
            ],
            "dataset_or_task_count": "20 ICML 2024 Spotlight/Oral paper replications decomposed into 8316 gradable tasks",
            "license_or_access_basis": "OpenAI frontier-evals repository plus paper; task artifact access must be admitted before local run",
            "task_evaluator_form": "hierarchical rubrics and judge over research replication subtasks",
            "local_status": "ADMISSION_REQUIRED",
            "fit_to_goal": [
                "best match for proof-like replication recipe and reusable research engineering",
                "directly pressures understanding, implementation, experiment execution, and reporting",
            ],
            "limits": [
                "long-horizon and expensive; not suitable as first small post-gate loop",
                "judge/rubric evaluation may be less direct than executable pass/fail rows",
            ],
            "recommended_use": "field-level validation track once Ember has a durable proposer",
        },
        {
            "id": "re-bench",
            "name": "RE-Bench",
            "primary_sources": [
                "https://metr.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/",
                "https://github.com/METR/RE-Bench",
            ],
            "dataset_or_task_count": "7 open-ended AI R&D environments",
            "license_or_access_basis": "public METR repository/blog; task assets must be admitted before local run",
            "task_evaluator_form": "continuous optimization objectives over runtime, loss, win-rate, and ML/Rust scaffolding tasks under compute budgets",
            "local_status": "ADMISSION_REQUIRED",
            "fit_to_goal": [
                "directly targets AI R&D capability and budget-sensitive experimentation",
                "supports temporal-growth milestones with load-bearing longer attempts",
            ],
            "limits": [
                "small number of environments",
                "some tasks may require larger compute than current safe loop",
            ],
            "recommended_use": "duration-growth and AI-R&D breakthrough validation track",
        },
        {
            "id": "mlagentbench",
            "name": "MLAgentBench",
            "primary_sources": [
                "https://arxiv.org/abs/2310.03302",
                "https://github.com/snap-stanford/MLAgentBench",
            ],
            "dataset_or_task_count": "13 machine-learning experimentation tasks",
            "license_or_access_basis": "public paper and GitHub repository; task-specific data licenses must be checked",
            "task_evaluator_form": "agent reads/writes files, executes code, inspects outputs, and iterates toward ML metrics",
            "local_status": "ADMISSION_REQUIRED",
            "fit_to_goal": [
                "historically important benchmark for ML experimentation loops",
                "contains explicit experiment-design/run/analyze/iterate pressure",
            ],
            "limits": [
                "some tasks are old or saturated",
                "less direct scientific-world-rule pressure than D3-Gym/ScienceAgentBench",
            ],
            "recommended_use": "secondary comparison baseline for ML-experiment loop mechanics",
        },
        {
            "id": "core-bench",
            "name": "CORE-Bench",
            "primary_sources": [
                "https://arxiv.org/abs/2409.11363",
                "https://github.com/siegelz/core-bench",
            ],
            "dataset_or_task_count": "270 tasks from 90 papers across computer science, social science, and medicine",
            "license_or_access_basis": "public paper and code repository; paper/data artifact licenses must be admitted before run",
            "task_evaluator_form": "computational reproducibility tasks across difficulty levels, language-only and vision-language variants",
            "local_status": "ADMISSION_REQUIRED",
            "fit_to_goal": [
                "strong match for reusable/recreatable recipe and proof discipline",
                "less focused on new self-improvement but strong for verification substrate",
            ],
            "limits": [
                "reproduction is necessary but not sufficient for self-growth",
                "may reward environment recovery more than new method formation",
            ],
            "recommended_use": "verification/reproducibility transfer check",
        },
    ]

    selected = {
        "immediate_next_loop": "d3-gym",
        "stronger_validation_after_first_loop": ["scienceagentbench", "re-bench", "paperbench"],
        "why": "D3-Gym is already locally frozen with external task rows, evaluator scripts, and a source URL, so it can support the next bounded A/B/C heldout loop without another credential/data blocker. ScienceAgentBench, RE-Bench, and PaperBench are stronger field-level validation tracks but require admission receipts first.",
    }

    return {
        "ticket": "EMBER-POST-RESIDENT-BENCHMARK-DISCOVERY",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "git_head": git_head(repo),
        "goal_path": str(goal),
        "goal_source_sha256": sha256_file(goal),
        "resident_training_gate_required_status": "PASS",
        "bitnet_comparison_receipt": bitnet,
        "benchmark_discovery_status": "PASS" if bitnet["status"] == "PASS" else "BLOCKED",
        "selection": selected,
        "candidates": candidates,
        "historical_kaggle_position": {
            "kaggle_cli_public_dataset_access": "works per existing Kaggle CLI decision receipt",
            "mle_bench_downloads": "blocked by prior 403 receipts; MLE is not the active path",
            "downloadable_kaggle_fallback": "allowed only if docs/research/journal admission remains blocked and the loop still proves a reusable field-level technique",
        },
        "next_blocker": "past_ember_technique_mining_receipt" if bitnet["status"] == "PASS" else "bitnet_comparison_receipt",
    }


def build_technique_receipt(
    repo: Path,
    ts: str,
    benchmark_receipt_path: Path,
    technique_receipt_path: Path,
) -> dict[str, Any]:
    goal = repo / "docs/authority/GOAL.md"
    goal_text = goal.read_text(encoding="utf-8", errors="replace")
    compact_goal_text = " ".join(goal_text.split())
    required_markers = [
        "R15 shifts from named failed-row family patching toward reusable public-I/O shape candidates",
        "R16 updates the native goal organ",
        "R17 implements that first native proposer policy",
        "candidate/proposer expressivity on fresh rows under the native no-private-leakage contract",
    ]
    missing = [m for m in required_markers if " ".join(m.split()) not in compact_goal_text]
    status = "PASS" if not missing else "BLOCKED"

    mined = [
        {
            "id": "receipt_conditioned_repair",
            "source": "R12-R14 chronology in docs/authority/GOAL.md",
            "keep": "Failed fresh-transfer receipts must become training signals for the next proposer.",
            "forbidden_regression": "same-slice family patching or manual row-specific fixes",
        },
        {
            "id": "public_io_shape_growth",
            "source": "R15 chronology in docs/authority/GOAL.md",
            "keep": "Mine public examples into reusable candidate shapes selected by public tests only.",
            "forbidden_regression": "private-label leakage or fixed template victory laps",
        },
        {
            "id": "native_goal_organ_selection",
            "source": "R16 chronology in docs/authority/GOAL.md",
            "keep": "The native organ must select the next action from receipts; deletion must block or degrade selection.",
            "forbidden_regression": "Codex prose selecting the next loop after the fact",
        },
        {
            "id": "learned_proposer_policy",
            "source": "R17 chronology in docs/authority/GOAL.md",
            "keep": "A learned candidate-space policy must be integrated and deletion-sensitive even when it fails on fresh transfer.",
            "forbidden_regression": "unchanged prefix-policy reruns after a zero-score transfer",
        },
        {
            "id": "failure_as_next_loop",
            "source": "docs/authority/GOAL.md lines around R17 blocker",
            "keep": "A failed fresh row must become the next executable loop input, not a prose postmortem.",
            "forbidden_regression": "duration growth, readiness, or harness hardening unless the receipt names them as blockers",
        },
    ]

    script_path = repo / "scripts" / "ember_post_resident_discovery.py"
    next_loop_path = repo / "receipts" / "ember-d3-native-loop" / f"d3-native-loop-{ts}.json"
    next_packet = {
        "current_blocker": "candidate/proposer expressivity on fresh externally heldout rows under the native no-private-leakage contract",
        "current_executable_command": f"python scripts\\ember_d3_native_proposer_loop.py --benchmark-receipt {benchmark_receipt_path.relative_to(repo)} --technique-receipt {technique_receipt_path.relative_to(repo)} --out {next_loop_path.relative_to(repo)}",
        "required_receipt": "receipts\\ember-d3-native-loop\\d3-native-loop-<timestamp>.json",
        "kill_ablate_test": "delete or disable native goal organ, learned proposer policy, public-I/O shape miner, and receipt-conditioned update; C must degrade or block versus matched A/B controls",
        "next_blocker_if_pass": "admit and run stronger ScienceAgentBench/RE-Bench/PaperBench validation or scale the D3 loop to fuller environments with field-level contribution claim",
        "next_blocker_if_fail": "repair candidate/proposer expressivity using the failed-row receipt as training signal; do not rerun unchanged policy",
    }

    return {
        "ticket": "EMBER-POST-RESIDENT-PAST-TECHNIQUE-MINING",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "repo": str(repo),
        "git_head": git_head(repo),
        "goal_path": str(goal),
        "goal_source_sha256": sha256_file(goal),
        "benchmark_discovery_receipt_path": str(benchmark_receipt_path),
        "benchmark_discovery_receipt_sha256": sha256_file(benchmark_receipt_path),
        "technique_mining_status": status,
        "missing_required_markers": missing,
        "mined_techniques": mined,
        "compressed_current_blocker_packet": next_packet,
        "code_vs_docs_metric": {
            "this_receipt_generator_code_lines": len(script_path.read_text(encoding="utf-8").splitlines()),
            "benchmark_receipt_lines_generated": len(benchmark_receipt_path.read_text(encoding="utf-8").splitlines()),
            "technique_receipt_lines_predicted": 0,
            "classification": "during-project experiment/control receipt, not before-project planning",
        },
        "next_blocker": "first_external_heldout_a_b_c_loop_using_resident_trained_organ",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out-dir", default="receipts/ember-post-resident-discovery")
    parser.add_argument("--d3-task-rows", default=None)
    parser.add_argument("--after-bitnet-receipt", default=None)
    parser.add_argument("--timestamp", default=None)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    ts = args.timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (repo / args.out_dir).resolve()

    d3_task_rows = Path(args.d3_task_rows) if args.d3_task_rows else None
    bitnet_receipt = Path(args.after_bitnet_receipt) if args.after_bitnet_receipt else None
    bench_path = out_dir / f"benchmark-discovery-{ts}.json"
    tech_path = out_dir / f"past-ember-technique-mining-{ts}.json"

    bench = build_benchmark_receipt(repo, ts, d3_task_rows, bitnet_receipt)
    checked_write(bench_path, bench)
    if bench["benchmark_discovery_status"] != "PASS":
        print(json.dumps({
            "benchmark_receipt": str(bench_path),
            "technique_receipt": None,
            "benchmark_status": bench["benchmark_discovery_status"],
            "technique_status": "NOT_RUN",
            "next_blocker": bench["next_blocker"],
        }, indent=2, sort_keys=True))
        return 2
    tech = build_technique_receipt(repo, ts, bench_path, tech_path)
    tech["code_vs_docs_metric"]["technique_receipt_lines_predicted"] = len(
        json.dumps(tech, indent=2, sort_keys=True).splitlines()
    )
    checked_write(tech_path, tech)

    print(json.dumps({
        "benchmark_receipt": str(bench_path),
        "technique_receipt": str(tech_path),
        "benchmark_status": bench["benchmark_discovery_status"],
        "technique_status": tech["technique_mining_status"],
        "next_blocker": tech["next_blocker"],
    }, indent=2, sort_keys=True))
    return 0 if tech["technique_mining_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

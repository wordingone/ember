# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Selftest for ScienceAgentBench admission receipt generation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_scienceagentbench_admission as sab


FAKE_ROWS = [
    {
        "row_idx": 0,
        "row": {
            "instance_id": 1,
            "domain": "Computational Chemistry",
            "github_name": "deepchem/deepchem",
            "task_inst": "Train a multitask model and save pred_results/clintox_test_pred.csv",
            "output_fname": "pred_results/clintox_test_pred.csv",
            "eval_script_name": "clintox_nn_eval.py",
            "dataset_folder_tree": "|-- clintox/ |---- clintox_train.csv |---- clintox_test.csv",
            "dataset_preview": "smiles,FDA_APPROVED,CT_TOX\nCCC,1,0",
        },
    },
    {
        "row_idx": 1,
        "row": {
            "instance_id": 4,
            "domain": "Geographical Information Science",
            "github_name": "geopandas/geopandas",
            "task_inst": "Analyze and visualize Elk movements; save pred_results/Elk_Analysis.png",
            "output_fname": "pred_results/Elk_Analysis.png",
            "eval_script_name": "eval_elk_analysis.py",
            "dataset_folder_tree": "|-- ElkMovement/ |---- Elk.geojson",
            "dataset_preview": "{\"type\":\"FeatureCollection\"}",
        },
    },
    {
        "row_idx": 2,
        "row": {
            "instance_id": 11,
            "domain": "Bioinformatics",
            "github_name": "deepchem/deepchem",
            "task_inst": "Train a cell counting model; save pred_results/cell-count_pred.csv",
            "output_fname": "pred_results/cell-count_pred.csv",
            "eval_script_name": "BBBC002_cell_count_eval.py",
            "dataset_folder_tree": "|-- BBBC002/ |---- train/ |---- test/",
            "dataset_preview": "file name,human counter 1,human counter #2",
        },
    },
]


def test_selector_is_deleted_sensitive() -> None:
    facts = sab.BenchmarkFacts(
        hf_valid=True,
        verified_rows=102,
        domains=4,
        has_docker_eval=True,
        has_full_artifact_access=False,
        full_artifact_local_path=None,
    )
    selected = sab.select_benchmark_route(facts, deleted=False)
    deleted = sab.select_benchmark_route(facts, deleted=True)
    assert selected["selected"] == "scienceagentbench"
    assert selected["admission_state"] == "BLOCKED_ARTIFACTS_REQUIRED"
    assert deleted["selected"] is None
    assert deleted["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"


def test_freezes_diverse_rows_without_gold_programs() -> None:
    frozen = sab.freeze_candidate_rows(FAKE_ROWS, limit=3)
    assert [row["instance_id"] for row in frozen] == [1, 4, 11]
    assert {row["domain"] for row in frozen} == {"Computational Chemistry", "Geographical Information Science", "Bioinformatics"}
    assert all("gold_program" not in json.dumps(row).lower() for row in frozen)
    assert all(row["output_fname"].startswith("pred_results/") for row in frozen)


def test_receipt_blocks_without_full_artifacts_and_records_next_command() -> None:
    with tempfile.TemporaryDirectory(prefix="sab-admission-selftest-") as td:
        out_dir = Path(td)
        receipt = sab.build_receipt_from_materialized(
            repo=Path.cwd(),
            out_dir=out_dir,
            source_payloads={
                "github_readme": "verified split benchmark_verified.zip dockerized evaluation 102 SAB instances",
                "github_license": "MIT License",
                "hf_rows": {"rows": FAKE_ROWS, "num_rows_total": 102},
            },
            source_meta={
                "github_readme_url": "https://raw.githubusercontent.com/OSU-NLP-Group/ScienceAgentBench/main/README.md",
                "github_license_url": "https://raw.githubusercontent.com/OSU-NLP-Group/ScienceAgentBench/main/LICENSE",
                "hf_rows_url": "https://datasets-server.huggingface.co/rows?...",
                "sharepoint_artifact_url": "https://example.invalid/benchmark_verified.zip",
                "sharepoint_head_status": "not_checked",
            },
            full_artifact_local_path=None,
        )
        assert receipt["verdict"] == "SCIENCEAGENTBENCH_BLOCKED"
        assert receipt["blocked_reasons"] == ["full_benchmark_artifacts_not_local"]
        assert receipt["native_operator_routing"]["selected"] == "scienceagentbench"
        assert receipt["deleted_selector_routing"]["admission_state"] == "ROUTING_BLOCKED_DELETED_SELECTOR"
        assert receipt["deletion_sensitive"] is True
        assert "benchmark_verified.zip" in receipt["next_executable_command"]
        assert (out_dir / "scienceagentbench-admission-receipt.json").exists()


def main() -> int:
    for test in [
        test_selector_is_deleted_sensitive,
        test_freezes_diverse_rows_without_gold_programs,
        test_receipt_blocks_without_full_artifacts_and_records_next_command,
    ]:
        test()
    print("EMBER_SCIENCEAGENTBENCH_ADMISSION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

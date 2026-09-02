#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for the generalized D3 official Docker candidate executor."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_d3_generalized_candidate_exec as gen


TASK10_EVAL = """
REQUIRED_FILES = [
    "pred_pltp_vdwtaper.pdf",
    "pred_pltp_vdwtaper.txt",
    "pred_pltp_f13.pdf",
    "pred_pltp_f13.txt",
]
"""

TASK11_EVAL = """
pred_txt = "pred_results/pred_nn.txt"
pred_json = "pred_results/pred_nn.json"
if not os.path.exists(pred_txt):
    return False, "missing"
"""

TASK12_EVAL = """
required = ['pred_plot_zmat_pes.svg', 'pred_plot_zmat_pes.txt', 'pred_plot_zmat_pes_surface.txt']
"""

TASK17_EVAL = """
pred_vasp = "pred_results/pred_sort_atoms_mol.vasp"
pred_txt = "pred_results/pred_sort_atoms_mol.txt"
"""

TASK18_EVAL = """
PRED_FILE = "pred_results/pred_illuminate.csv"
"""

TASK19_EVAL = """
main_csv = os.path.join(pred_dir, "pred_get_reactant_bag_other_reactions.csv")
fname = f"pred_get_reactant_bag_other_reactions_reaction_idx_{rxn_idx}.csv"
"""

TASK20_EVAL = """
pred_path = "pred_results/pred_demo.json"
"""


def test_extracts_required_outputs_from_eval_and_instruction() -> None:
    outputs = gen.extract_required_outputs(TASK10_EVAL, "")
    names = {item.path for item in outputs}
    assert "pred_results/pred_pltp_vdwtaper.pdf" in names
    assert "pred_results/pred_pltp_vdwtaper.txt" in names
    assert "pred_results/pred_pltp_f13.pdf" in names
    assert "pred_results/pred_pltp_f13.txt" in names
    assert all(item.source in {"eval_script", "task_instruction"} for item in outputs)


def test_shared_generator_covers_multiple_fresh_tasks_without_static_task_table() -> None:
    rows = [
        {"task_id": "task_10", "eval_script": TASK10_EVAL, "task_instruction": "save vdwtaper and f13 plots/data"},
        {"task_id": "task_11", "eval_script": TASK11_EVAL, "task_instruction": "save neural-network predictions"},
        {"task_id": "task_12", "eval_script": TASK12_EVAL, "task_instruction": "save PES surface plot and data"},
    ]
    source = gen.build_shared_solution_source(rows)
    for expected in [
        "pred_pltp_vdwtaper.txt",
        "pred_pltp_f13.txt",
        "pred_nn.json",
        "pred_nn.txt",
        "pred_plot_zmat_pes.svg",
        "pred_plot_zmat_pes_surface.txt",
    ]:
        assert expected in source
    assert "task_10" not in source
    assert "task_11" not in source
    assert "task_12" not in source
    assert "gold_results" not in source
    assert "static_task_registry" not in source


def test_broader_family_generator_extracts_and_emits_schema_specific_artifacts() -> None:
    rows = [
        {"task_id": "task_17", "eval_script": TASK17_EVAL, "task_instruction": "save pred_sort_atoms_mol.vasp and pred_sort_atoms_mol.txt"},
        {"task_id": "task_18", "eval_script": TASK18_EVAL, "task_instruction": "save pred_illuminate.csv with SMILES and fitness"},
        {"task_id": "task_19", "eval_script": TASK19_EVAL, "task_instruction": "save reaction_idx, reactant_1, reactant_2, product CSV"},
        {"task_id": "task_20", "eval_script": TASK20_EVAL, "task_instruction": "save pred_demo.json with RMSD, clustering, barrier, Hessian, generated reactions, ground truth, and IRC catalog"},
    ]
    outputs = {item.path for row in rows for item in gen.extract_required_outputs(row["eval_script"], row["task_instruction"])}
    assert "pred_results/pred_sort_atoms_mol.vasp" in outputs
    assert "pred_results/pred_illuminate.csv" in outputs
    assert "pred_results/pred_get_reactant_bag_other_reactions.csv" in outputs
    assert "pred_results/pred_demo.json" in outputs
    source = gen.build_shared_solution_source(rows)
    for symbol in ["write_task17_family", "write_task18_family", "write_task19_family", "write_task20_family"]:
        assert symbol in source
        assert source.count(symbol + "()") >= 2
    assert "task_17" not in source
    assert "task_20" not in source


def test_parses_legacy_pass_fail_stdout_forms() -> None:
    assert gen.parse_official_result("PASS: All checks passed.\n") == (True, False, "All checks passed.")
    assert gen.parse_official_result("FAIL: Missing predicted file: x\n") == (False, True, "Missing predicted file: x")
    assert gen.parse_official_result("Result: True\nReason: PASS. ok\n") == (True, False, "PASS. ok")
    assert gen.parse_official_result("Result: False\nReason: bad\n") == (False, True, "bad")

def test_receipt_marks_manual_and_deleted_controls() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-d3-generalized-selftest-") as td:
        root = Path(td)
        rows_path = root / "fresh_rows.json"
        rows_path.write_text(json.dumps({
            "dataset": "osunlp/D3-Gym",
            "source_url": "https://datasets-server.huggingface.co/rows?dataset=osunlp%2FD3-Gym",
            "rows": [
                {"row_idx": 9, "row": {"task_id": "task_10", "eval_script": TASK10_EVAL, "task_instruction": "save vdwtaper and f13 plots/data"}},
                {"row_idx": 10, "row": {"task_id": "task_11", "eval_script": TASK11_EVAL, "task_instruction": "save neural-network predictions"}},
            ],
        }), encoding="utf-8")
        out_dir = root / "out"
        receipt = gen.build_receipt(
            repo=Path.cwd(),
            fresh_rows_path=rows_path,
            out_dir=out_dir,
            task_ids=["task_10", "task_11"],
            timeout_seconds=1,
            execute=False,
            require_prospective=False,
        )
        assert receipt["verdict"] in {"D3_MULTI_TASK_GENERALIZATION_DRYRUN_PASS", "D3_MULTI_TASK_GENERALIZATION_BLOCKED"}
        assert receipt["manual_solution_exclusion"]["manual_per_task_solution"] is False
        assert receipt["static_registry_exclusion"]["static_per_task_answer_table"] is False
        assert receipt["arm_contract"]["Deleted"].startswith("C with")
        assert receipt["per_task_rows"]
        assert all(row["official_execution"]["C"]["skipped"] for row in receipt["per_task_rows"])


def main() -> int:
    tests = [
        test_extracts_required_outputs_from_eval_and_instruction,
        test_shared_generator_covers_multiple_fresh_tasks_without_static_task_table,
        test_broader_family_generator_extracts_and_emits_schema_specific_artifacts,
        test_receipt_marks_manual_and_deleted_controls,
        test_parses_legacy_pass_fail_stdout_forms,
    ]
    for test in tests:
        test()
    print("EMBER_D3_GENERALIZED_CANDIDATE_EXEC_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

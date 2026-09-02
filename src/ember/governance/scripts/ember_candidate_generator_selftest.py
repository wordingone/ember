#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for Ember-owned candidate generation artifacts."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_candidate_generator as gen


def _write(path: Path, payload: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        path.write_text(payload, encoding="utf-8", newline="\n")
    return path


def _tasks(root: Path) -> Path:
    return _write(
        root / "tasks.json",
        {
            "benchmark_id": "D3-Gym",
            "tasks": [
                {
                    "id": "task_1",
                    "task_instruction": "Analyze a molecular structure to compute bond orders.",
                    "eval_script": "required_files = ['pred_plotatoms_bondorder.png', 'pred_bond_orders.csv']",
                    "dataset_previews": "Preview of I-ReaxFF/test/poscar.gen",
                },
                {
                    "id": "task_2",
                    "task_instruction": "Analyze ozone ignition chemistry data and save pred_csv_plot.eps.",
                    "eval_script": "eps_file = os.path.join(pred_dir, 'pred_csv_plot.eps')",
                    "dataset_previews": "Preview of plug_O3ign_adiabatic.csv",
                },
                {
                    "id": "task_4",
                    "task_instruction": "Emit ReaxFF debug gradient, bond order, species, and log files.",
                    "eval_script": "required_files = ['pred_reax_debug_grad.txt', 'pred_reax_debug_bo.txt', 'pred_reax_debug_species.txt', 'pred_reax_debug.log']",
                    "dataset_previews": "Preview of ReaxFF debug input files",
                },
                {
                    "id": "task_5",
                    "task_instruction": "Generate PLBO diagnostic PDF plots.",
                    "eval_script": "required_files = ['pred_plbo_bo_si.pdf', 'pred_plbo_bo_pi.pdf', 'pred_plbo_bo_pp.pdf', 'pred_plbo_nn_bo_si.pdf', 'pred_plbo_nn_bo_pi.pdf', 'pred_plbo_nn_bo_pp.pdf', 'pred_plbo_bop.pdf', 'pred_plbo_bo.pdf', 'pred_plbo_bo_pi_CC.pdf', 'pred_plbo_bo_pi_CH.pdf']",
                    "dataset_previews": "Preview of PLBO bond order data",
                },
                {
                    "id": "task_6",
                    "task_instruction": "Generate scaled molecule trajectory and summary.",
                    "eval_script": "required_files = ['pred_scale_mol.traj', 'pred_scale_mol_summary.txt']",
                    "dataset_previews": "Preview of scale molecule coordinates",
                },
                {
                    "id": "task_7",
                    "task_instruction": "Generate DEB e-over CSV, PDF, and PNG.",
                    "eval_script": "required_files = ['pred_deb_eover.csv', 'pred_deb_eover.pdf', 'pred_deb_eover.png']",
                    "dataset_previews": "Preview of dissociation energy barrier data",
                },
                {
                    "id": "task_8",
                    "task_instruction": "Compare energies with GULP and DFT baselines.",
                    "eval_script": "required_files = ['pred_compare_energies.csv', 'pred_compare_energies_gulp.csv', 'pred_compare_energies.pdf']",
                    "dataset_previews": "Preview of energy comparison data",
                },
            ],
        },
    )


def _admission(root: Path, tasks: Path) -> Path:
    evaluator = _write(root / "eval_adapter.py", "print('adapter')\n")
    return _write(
        root / "admission.json",
        {
            "ticket": "EMBER-RESEARCH-BENCHMARK-ADMISSION",
            "verdict": "RESEARCH_BENCHMARK_ADMITTED",
            "benchmark_id": "D3-Gym",
            "tasks_path": str(tasks),
            "evaluator_path": str(evaluator),
            "operator_routed": True,
        },
    )


def test_generator_emits_d3_task1_solution_and_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-candidate-gen-") as td:
        root = Path(td)
        out_solution = root / "generated" / "arm_c.py"
        receipt = gen.build_candidate_receipt(_admission(root, _tasks(root)), out_solution, task_id="task_1")

        assert receipt["verdict"] == "CANDIDATE_GENERATED"
        assert receipt["generator_id"] == "d3_gym_poscar_distance_strategy_v1"
        assert receipt["manual_solution"] is False
        assert receipt["deletion_load_bearing_test"]["degrades_without_generator"] is True
        assert out_solution.exists()
        text = out_solution.read_text(encoding="utf-8")
        assert "pred_bond_orders.csv" in text
        assert "gold_results" not in text
        assert gen.validate_candidate_receipt(receipt) == []


def test_generator_emits_d3_task2_eps_strategy() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-candidate-gen-") as td:
        root = Path(td)
        out_solution = root / "generated" / "arm_c.py"
        receipt = gen.build_candidate_receipt(_admission(root, _tasks(root)), out_solution, task_id="task_2")

        text = out_solution.read_text(encoding="utf-8")
        assert receipt["verdict"] == "CANDIDATE_GENERATED"
        assert "pred_csv_plot.eps" in text
        assert "write_eps_plot" in text
        assert gen.validate_candidate_receipt(receipt) == []


def test_generator_emits_d3_task4_to_task8_output_families() -> None:
    required = {
        "task_4": [
            "pred_reax_debug_grad.txt",
            "pred_reax_debug_bo.txt",
            "pred_reax_debug_species.txt",
            "pred_reax_debug.log",
        ],
        "task_5": [
            "pred_plbo_bo_si.pdf",
            "pred_plbo_bo_pi.pdf",
            "pred_plbo_bo_pp.pdf",
            "pred_plbo_nn_bo_si.pdf",
            "pred_plbo_nn_bo_pi.pdf",
            "pred_plbo_nn_bo_pp.pdf",
            "pred_plbo_bop.pdf",
            "pred_plbo_bo.pdf",
            "pred_plbo_bo_pi_CC.pdf",
            "pred_plbo_bo_pi_CH.pdf",
        ],
        "task_6": ["pred_scale_mol.traj", "pred_scale_mol_summary.txt"],
        "task_7": ["pred_deb_eover.csv", "pred_deb_eover.pdf", "pred_deb_eover.png"],
        "task_8": ["pred_compare_energies.csv", "pred_compare_energies_gulp.csv", "pred_compare_energies.pdf"],
    }
    with tempfile.TemporaryDirectory(prefix="ember-candidate-gen-") as td:
        root = Path(td)
        admission = _admission(root, _tasks(root))
        for task_id, names in required.items():
            out_solution = root / "generated" / f"arm_c_{task_id}.py"
            receipt = gen.build_candidate_receipt(admission, out_solution, task_id=task_id)
            text = out_solution.read_text(encoding="utf-8")
            assert receipt["verdict"] == "CANDIDATE_GENERATED"
            for name in names:
                assert name in text
            assert "write_minimal_pdf" in text
            assert gen.validate_candidate_receipt(receipt) == []


def test_generator_matches_d3_task7_and_task8_evaluator_shape() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-candidate-gen-") as td:
        root = Path(td)
        out_solution = root / "generated" / "arm_c.py"
        gen.build_candidate_receipt(_admission(root, _tasks(root)), out_solution, task_id="task_8")

        text = out_solution.read_text(encoding="utf-8")
        assert "for i in range(1):" in text
        assert 'read(Path("benchmark/datasets/I-ReaxFF/test/md.traj")' in text
        assert "IRFF_NP" in text
        assert "calculate_Delta" in text
        assert "ir.eover[0]" in text
        assert "ir.eover[1]" in text
        assert "gulp_classical_total_energy" in text


def test_deleted_generator_blocks_candidate_generation() -> None:
    with tempfile.TemporaryDirectory(prefix="ember-candidate-gen-") as td:
        root = Path(td)
        receipt = gen.build_candidate_receipt(
            _admission(root, _tasks(root)),
            root / "generated" / "arm_c.py",
            task_id="task_1",
            generator_deleted=True,
        )

        assert receipt["verdict"] == "CANDIDATE_GENERATION_BLOCKED"
        assert "generator.deleted" in receipt["errors"]
        assert receipt["candidate_path"] is None


def main() -> int:
    tests = [
        test_generator_emits_d3_task1_solution_and_receipt,
        test_generator_emits_d3_task2_eps_strategy,
        test_generator_emits_d3_task4_to_task8_output_families,
        test_generator_matches_d3_task7_and_task8_evaluator_shape,
        test_deleted_generator_blocks_candidate_generation,
    ]
    for test in tests:
        test()
    print("EMBER_CANDIDATE_GENERATOR_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

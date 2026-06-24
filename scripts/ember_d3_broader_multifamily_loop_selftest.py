#!/usr/bin/env python3
"""Selftest for broader D3 loop wrapper."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import ember_d3_broader_multifamily_loop as loop


def test_materializes_full_rows_from_admission_receipt() -> None:
    with tempfile.TemporaryDirectory(prefix="d3-broader-loop-") as td:
        root = Path(td)
        frozen = root / "frozen.json"
        frozen.write_text(
            json.dumps(
                {
                    "source_url": "https://huggingface.co/datasets/osunlp/D3-Gym",
                    "split": {"dataset": "osunlp/D3-Gym", "config": "default", "split": "train", "offset": 16, "length": 2},
                    "tasks": [
                        {"id": "task_17", "source_row_idx": 16, "task_instruction": "write 'pred_results/a.txt'", "eval_script": "'pred_results/a.txt'", "discipline": "Chemistry", "original_repo": "repo/a"},
                        {"id": "task_18", "source_row_idx": 17, "task_instruction": "write 'pred_results/b.txt'", "eval_script": "'pred_results/b.txt'", "discipline": "Chemistry", "original_repo": "repo/b"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        admission = root / "admission.json"
        admission.write_text(
            json.dumps(
                {
                    "verdict": "D3_BROADER_MULTIFAMILY_ADMITTED",
                    "frozen_heldout_slice": {
                        "rows": [
                            {"task_id": "task_17", "source_path": str(frozen), "source_row_idx": 16},
                            {"task_id": "task_18", "source_path": str(frozen), "source_row_idx": 17},
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        out_dir = root / "out"
        bundle = loop.materialize_fresh_rows_from_admission(admission, out_dir, task_ids=["task_17"])
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        assert payload["dataset"] == "osunlp/D3-Gym"
        assert payload["rows"][0]["row_idx"] == 16
        assert payload["rows"][0]["row"]["task_id"] == "task_17"
        assert payload["rows"][0]["row"]["eval_script"] == "'pred_results/a.txt'"
        assert len(payload["rows"]) == 1


def main() -> int:
    test_materializes_full_rows_from_admission_receipt()
    print("EMBER_D3_BROADER_MULTIFAMILY_LOOP_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for issue #804's board-output evidence contamination."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))


def _load(name: str):
    path = PACKAGE_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"issue804_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _board_payload() -> dict:
    return {
        "receipt_type": "ember_totality_board",
        "ticket": "EMBER-TOTALITY-BOARD",
        "ts": "20990101T000000Z",
        "rows": [
            {
                "condition": "C-FED",
                "status": "GREEN",
                "reason": (
                    "federation design checkpoint portability work sharding "
                    "receipt merge kaggle colab hf egress manifest design only"
                ),
            },
            {
                "condition": "C12",
                "status": "RED",
                "reason": "invalid_timer_artifact_modes",
            },
        ],
    }


class Issue804EvidenceScanHygieneTests(unittest.TestCase):
    def test_c_fed_never_treats_board_output_as_positive_or_negative_evidence(self):
        module = _load("test_c_fed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            board = root / "receipts" / "ember-totality-20990101T000000Z.json"
            _write_json(board, _board_payload())
            module.ROOT = str(root)

            self.assertNotIn(str(board), module.candidate_files())
            self.assertNotIn(str(board), module.negative_scan_files())

    def test_c12_never_treats_board_output_as_invalid_token_evidence(self):
        module = _load("test_c12")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            board = root / "receipts" / "ember-totality-20990101T000000Z.json"
            _write_json(board, _board_payload())

            self.assertNotIn(str(board), module.find_receipts(str(root)))

    def test_real_receipts_remain_visible(self):
        c_fed = _load("test_c_fed")
        c12 = _load("test_c12")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / "receipts" / "real-evidence.json"
            _write_json(
                real,
                {
                    "verdict": "PASS",
                    "note": "federation design and selector ablation evidence",
                },
            )
            c_fed.ROOT = str(root)

            self.assertIn(str(real), c_fed.candidate_files())
            self.assertIn(str(real), c_fed.negative_scan_files())
            self.assertIn(str(real), c12.find_receipts(str(root)))


if __name__ == "__main__":
    unittest.main()

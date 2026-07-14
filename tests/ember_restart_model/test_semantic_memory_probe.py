# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD receipt contract for the no-step shared-FFN semantic memory probe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from probe_semantic_memory import probe_receipt


class SemanticMemoryProbeTests(unittest.TestCase):
    def test_receipt_binds_no_step_shared_route_and_memory_measurement(self) -> None:
        receipt = probe_receipt(
            model_config_sha256="a" * 64,
            stream_receipt_sha256="b" * 64,
            tokenizer_sha256="c" * 64,
            selected_expert="shared",
            sequence_length=1024,
            total_parameters=3_839_158_272,
            active_parameters=1_020_585_984,
            elapsed_seconds=1.5,
            peak_memory_bytes=123,
            reserved_memory_bytes=456,
        )
        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["operation"], "NO_STEP_SEMANTIC_FORWARD")
        self.assertEqual(receipt["selected_expert"], "shared")
        self.assertEqual(receipt["sequence_length"], 1024)
        self.assertEqual(receipt["stream_receipt_sha256"], "b" * 64)
        self.assertEqual(receipt["peak_memory_bytes"], 123)


if __name__ == "__main__":
    unittest.main()
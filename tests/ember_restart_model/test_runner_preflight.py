# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute runner preflight helpers without allocating the production model."""

from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice


class RunnerPreflightTests(unittest.TestCase):
    def test_production_optimizer_uses_declared_paged_8bit_adamw_state(self) -> None:
        calls: dict[str, object] = {}

        class Subject:
            def parameters(self) -> list[str]:
                return ["parameter"]

        def make_adamw(parameters: object, **kwargs: object) -> object:
            calls["parameters"] = parameters
            calls.update(kwargs)
            return "optimizer"

        fake = SimpleNamespace(optim=SimpleNamespace(PagedAdamW8bit=make_adamw))
        with patch.dict(sys.modules, {"bitsandbytes": fake}):
            contract = run_vertical_slice.load_optimizer_contract(ROOT / "configs" / "ember-restart-3b.json")
            optimizer = run_vertical_slice.build_production_optimizer(Subject(), optimizer_contract=contract)
        self.assertEqual(optimizer, "optimizer")
        self.assertEqual(contract["implementation"], "bitsandbytes.optim.PagedAdamW8bit")
        self.assertEqual(contract["hyperparameters"]["learning_rate"], 1e-5)
        self.assertEqual(calls["parameters"], ["parameter"])
        self.assertEqual(calls["percentile_clipping"], 5)
        self.assertEqual(calls["lr"], 1e-5)
    def test_contract_retention_limit_is_used_as_the_runner_limit(self) -> None:
        contract = ROOT / "configs" / "ember-restart-3b.json"
        self.assertEqual(run_vertical_slice.checkpoint_retention_limit(contract), 8)
    def test_rng_preflight_hashes_cpu_and_cuda_without_allocation(self) -> None:
        with patch.object(run_vertical_slice.torch.cuda, "get_rng_state", return_value=torch.tensor([1, 2, 3], dtype=torch.uint8)):
            hashes = run_vertical_slice._rng_state_hash(torch.device("cuda"))
        self.assertEqual(set(hashes), {"cpu", "cuda"})
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))


if __name__ == "__main__":
    unittest.main()
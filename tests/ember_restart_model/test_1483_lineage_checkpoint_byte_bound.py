# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1483: the specialist checkpoint byte bound and the storage projection must budget
the same optimizer coverage.

The first credited specialist run (specialist-canary-20260805) trained 204/204 and
then refused publication: the runner budgeted shared-plus-one-expert optimizer bytes
while the episode had exact-resumed a full-coverage parent, whose moments
load_checkpoint_artifacts restores verbatim (#1473's second closed admissible shape).
The projection correctly measured the inherited full set at factor 1 and its floor
exceeded the under-declared bound. These tests pin the cure: the bound derives its
coverage decision from the same live optimizer the projection measures.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import EXPERT_NAMES, optimizer_covers_every_expert_route
from model import RestartDecoderConfig, UnifiedDecoder
from run_vertical_slice import (
    checkpoint_serialization_byte_bound,
    specialist_checkpoint_bound_active_parameters,
)

_CONFIG_PATH = ROOT / "configs" / "ember-restart-3b.json"
_TOTAL_PARAMETERS = 3_839_161_856
_SHARED_PLUS_ONE_PARAMETERS = 1_725_232_640
_CONTRACT_BYTES_PER_PARAMETER = 2  # model_parameter_bytes == optimizer bytes per active
_CONTRACT_FORMAT_OVERHEAD = 1024**3


def _small_model() -> UnifiedDecoder:
    config = RestartDecoderConfig.small_for_tests(
        hidden_size=32, layers=2, attention_heads=4, vocab_size=64
    )
    return UnifiedDecoder(config, genesis_seed=1483)


def _step_route(model: UnifiedDecoder, optimizer: torch.optim.Optimizer, expert: str) -> None:
    model._activate_expert(expert)
    loss = (
        model(torch.tensor([[1, 2, 3]], dtype=torch.long), active_expert=expert)
        .float()
        .square()
        .mean()
    )
    loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)


class OptimizerRouteCoverage(unittest.TestCase):
    def test_single_route_optimizer_does_not_cover_every_expert(self) -> None:
        model = _small_model()
        optimizer = torch.optim.AdamW(
            (p for p in model.parameters() if p.requires_grad), lr=1e-4
        )
        _step_route(model, optimizer, "vision")
        self.assertFalse(optimizer_covers_every_expert_route(model, optimizer))

    def test_full_route_optimizer_covers_every_expert(self) -> None:
        model = _small_model()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        for expert in EXPERT_NAMES:
            _step_route(model, optimizer, expert)
        self.assertTrue(optimizer_covers_every_expert_route(model, optimizer))

    def test_fresh_optimizer_covers_nothing(self) -> None:
        model = _small_model()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        self.assertFalse(optimizer_covers_every_expert_route(model, optimizer))


class BoundCoverageSelection(unittest.TestCase):
    """All four combinations of (lineage?, full coverage?) select a closed shape."""

    def test_lineage_with_full_coverage_budgets_total(self) -> None:
        self.assertEqual(
            specialist_checkpoint_bound_active_parameters(
                specialist_lineage={"v": 4},
                optimizer_full_route_coverage=True,
                active_parameters=_SHARED_PLUS_ONE_PARAMETERS,
                total_parameters=_TOTAL_PARAMETERS,
            ),
            _TOTAL_PARAMETERS,
        )

    def test_lineage_single_route_budgets_shared_plus_one(self) -> None:
        self.assertEqual(
            specialist_checkpoint_bound_active_parameters(
                specialist_lineage={"v": 4},
                optimizer_full_route_coverage=False,
                active_parameters=_SHARED_PLUS_ONE_PARAMETERS,
                total_parameters=_TOTAL_PARAMETERS,
            ),
            _SHARED_PLUS_ONE_PARAMETERS,
        )

    def test_governed_vertical_always_budgets_total(self) -> None:
        for coverage in (True, False):
            self.assertEqual(
                specialist_checkpoint_bound_active_parameters(
                    specialist_lineage=None,
                    optimizer_full_route_coverage=coverage,
                    active_parameters=_SHARED_PLUS_ONE_PARAMETERS,
                    total_parameters=_TOTAL_PARAMETERS,
                ),
                _TOTAL_PARAMETERS,
            )


class ProjectionConsistencyAtContractNumbers(unittest.TestCase):
    """The two contracts, evaluated at the frozen architecture, can no longer cross."""

    def test_full_coverage_bound_admits_the_factor_one_full_floor(self) -> None:
        # The projection's factor-1 floor for a full-coverage checkpoint is the
        # model bytes plus every route's optimizer bytes (specialist-canary-20260805
        # staged exactly this: 7.678 GB model shards + 7.80 GB optimizer).
        full_floor = _TOTAL_PARAMETERS * _CONTRACT_BYTES_PER_PARAMETER * 2
        bound = checkpoint_serialization_byte_bound(
            _CONFIG_PATH, active_parameters=_TOTAL_PARAMETERS
        )
        self.assertEqual(
            bound,
            _TOTAL_PARAMETERS * _CONTRACT_BYTES_PER_PARAMETER * 2
            + _CONTRACT_FORMAT_OVERHEAD,
        )
        self.assertLessEqual(full_floor, bound)

    def test_shared_plus_one_bound_cannot_admit_the_full_floor(self) -> None:
        # The refusal shape #1483 cures, kept visible: an inherited full-coverage
        # optimizer can never publish under the shared-plus-one budget, so the
        # selection above is load-bearing, not an optimization.
        full_floor = _TOTAL_PARAMETERS * _CONTRACT_BYTES_PER_PARAMETER * 2
        shared_plus_one_bound = checkpoint_serialization_byte_bound(
            _CONFIG_PATH, active_parameters=_SHARED_PLUS_ONE_PARAMETERS
        )
        self.assertGreater(full_floor, shared_plus_one_bound)


if __name__ == "__main__":
    unittest.main()

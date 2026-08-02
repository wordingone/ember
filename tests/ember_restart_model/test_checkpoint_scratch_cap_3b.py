# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Class-kill for #1305: the transient checkpoint scratch cap must clear 3B.

The 2026-08-02 certified launch train-5 died at its FIRST checkpoint write:
the 3B optimizer state's tensor-storage lower bound (7,798,675,456 bytes,
quarantine receipt sha256 d09e090b...) exceeded the then-4-GiB
_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES. These tests pin the cap above the
observed 3B bound and to the certified launch scope, so a cap reduction or
a config growth past the cap fails here instead of mid-run.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLICE_SOURCE = ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"

# Observed tensor-storage lower bound of the 3B config's optimizer-state.pt,
# from the ember-checkpoint-write-failure-v1 quarantine receipt
# checkpoint-write-failed-d09e090b...json (certified launch train-5,
# master 9b18f1a6, 2026-08-02); also recorded in
# receipts/failure-classes/checkpoint-transient-scratch-cap-3b.json.
OBSERVED_3B_OPTIMIZER_LOWER_BOUND = 7_798_675_456

# The certified launch scope's max_transient_checkpoint_gib (launch-authority
# certificate, execution_scope) — the cap and the scope must agree.
CERTIFIED_TRANSIENT_CHECKPOINT_BYTES = 8 * 1024**3


def _eval_int_expr(node: ast.expr) -> int:
    """Evaluate an integer arithmetic literal like `8 * 1024**3` — nothing else."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Mult, ast.Pow, ast.Add, ast.Sub)
    ):
        left = _eval_int_expr(node.left)
        right = _eval_int_expr(node.right)
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Add):
            return left + right
        return left - right
    raise AssertionError(
        "_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES must be integer literal"
        f" arithmetic, got {ast.dump(node)}"
    )


def _read_cap_constant() -> int:
    tree = ast.parse(SLICE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES"
                ):
                    value = _eval_int_expr(node.value)
                    if value < 1:
                        raise AssertionError(
                            "_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES must be"
                            f" positive, got {value!r}"
                        )
                    return value
    raise AssertionError(
        "_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES not found in run_vertical_slice.py"
    )


class CheckpointScratchCap3BTests(unittest.TestCase):
    def test_cap_exceeds_observed_3b_optimizer_lower_bound(self) -> None:
        cap = _read_cap_constant()
        self.assertGreater(
            cap,
            OBSERVED_3B_OPTIMIZER_LOWER_BOUND,
            "transient scratch cap is at or below the observed 3B"
            " optimizer-state lower bound: every 3B governed run dies at its"
            " first checkpoint write (#1305 class)",
        )

    def test_cap_matches_certified_launch_scope(self) -> None:
        cap = _read_cap_constant()
        self.assertEqual(
            cap,
            CERTIFIED_TRANSIENT_CHECKPOINT_BYTES,
            "transient scratch cap must equal the certified launch scope's"
            " max_transient_checkpoint_gib (8 GiB); change both together or"
            " the runner enforces a bound the certificate never authorized",
        )


if __name__ == "__main__":
    unittest.main()

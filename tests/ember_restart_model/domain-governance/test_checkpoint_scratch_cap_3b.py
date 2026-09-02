# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The owner-sharded v5 first-checkpoint scratch bound must clear 3B.

The 2026-08-02 train-5 receipt recorded a superseded monolithic optimizer
payload (7,798,675,456 bytes). It is retained as historical evidence only;
the live v5 contract writes one optimizer shard per closed owner, so this test
derives the per-owner floors from the checked-in 3B ownership/config contract.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SLICE_SOURCE = ROOT / "tools" / "ember-restart-3b" / "run_vertical_slice.py"
CONFIG_PATH = ROOT / "configs" / "ember-restart-3b.json"

# Observed tensor-storage lower bound of the 3B config's optimizer-state.pt,
# from the ember-checkpoint-write-failure-v1 quarantine receipt
# checkpoint-write-failed-d09e090b...json (certified launch train-5,
# master 9b18f1a6, 2026-08-02); also recorded in
# receipts/failure-classes/checkpoint-transient-scratch-cap-3b.json.
OBSERVED_3B_OPTIMIZER_LOWER_BOUND = 7_798_675_456

# The certified launch scope's max_transient_checkpoint_gib (launch-authority
# certificate, execution_scope) — the cap and the scope must agree.
CERTIFIED_TRANSIENT_CHECKPOINT_BYTES = 4 * 1024**3


def _owner_sharded_v5_projection() -> dict[str, object]:
    """Derive the closed 3B owner-sharded-v5 lower-bound inventory.

    This is the checked-in owner route used by checkpoint_artifacts: shared
    parameters are owned by ``shared`` and each named expert owns exactly one
    ``12*hidden_size**2`` slice. The result is a lower-bound projection, not
    a monolithic receipt or a model allocation.
    """
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    model = config["model"]
    serialization = config["checkpoints"]["serialization"]
    hidden_size = int(model["hidden_size"])
    layers = int(model["layers"])
    expert_names = tuple(model["expert_routing"]["expert_names"])
    bytes_per_parameter = int(
        serialization["optimizer_state_bytes_per_active_parameter"]
    )
    if model["expert_routing"].get("expert_parameter_formula") != "12*hidden_size^2":
        raise AssertionError("3B owner projection formula drifted from checkpoint ownership")
    if model["expert_routing"].get("active_experts_per_episode_or_batch") != 1:
        raise AssertionError("3B owner projection requires one active expert per episode")
    if model["expert_routing"].get("inactive_experts_frozen") is not True:
        raise AssertionError("3B owner projection requires inactive experts to be frozen")
    expert_parameters = layers * 12 * hidden_size**2
    shared_parameters = int(model["total_unique_trainable_parameters"]) - (
        len(expert_names) * expert_parameters
    )
    if len(expert_names) != 4 or len(set(expert_names)) != len(expert_names):
        raise AssertionError("3B owner-sharded v5 expert owner set is not closed")
    if shared_parameters < 1 or bytes_per_parameter < 1:
        raise AssertionError("owner-sharded 3B optimizer projection is invalid")
    owner_parameter_counts = {
        "shared": shared_parameters,
        **{name: expert_parameters for name in expert_names},
    }
    owner_storage_lower_bounds = {
        owner: parameters * bytes_per_parameter
        for owner, parameters in owner_parameter_counts.items()
    }
    return {
        "optimizer_state_layout": "owner-sharded-v1",
        "owner_ids": ("shared", *expert_names),
        "owner_parameter_counts": owner_parameter_counts,
        "owner_storage_lower_bounds": owner_storage_lower_bounds,
        "max_owner_storage_lower_bound": max(owner_storage_lower_bounds.values()),
    }


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
    def test_cap_covers_every_owner_sharded_optimizer_write(self) -> None:
        cap = _read_cap_constant()
        projection = _owner_sharded_v5_projection()
        owner_bounds = projection["owner_storage_lower_bounds"]
        self.assertEqual(projection["optimizer_state_layout"], "owner-sharded-v1")
        self.assertEqual(
            projection["owner_ids"],
            ("shared", "vision", "audio", "reasoning", "tool"),
        )
        self.assertLessEqual(
            projection["max_owner_storage_lower_bound"],
            cap,
            "an owner-sharded 3B optimizer write exceeds the transient scratch"
            " cap: the first-checkpoint #1305 failure class remains reachable",
        )
        self.assertEqual(
            projection["max_owner_storage_lower_bound"],
            max(owner_bounds.values()),
        )
        self.assertGreater(
            OBSERVED_3B_OPTIMIZER_LOWER_BOUND,
            cap,
            "the historical monolithic receipt must remain distinct from the"
            " active owner-sharded write bound",
        )

    def test_cap_matches_certified_launch_scope(self) -> None:
        cap = _read_cap_constant()
        self.assertEqual(
            cap,
            CERTIFIED_TRANSIENT_CHECKPOINT_BYTES,
            "transient scratch cap must equal the certified launch scope's"
            " max_transient_checkpoint_gib (4 GiB); change both together or"
            " the runner enforces a bound the certificate never authorized",
        )


if __name__ == "__main__":
    unittest.main()

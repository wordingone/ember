# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #580 PR-B regressions for the three remaining stabilize-path sites.

These tests are CPU-only and use tiny state dictionaries. They exercise exact
function bodies without bypassing the historical module execution interlock.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import torch


ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "scripts" / "timeshare_pretrain.py").is_file():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load_functions(path: Path, names: set[str], namespace: dict) -> SimpleNamespace:
    """Compile named functions without bypassing the historical module gate."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


timeshare = _load_functions(
    ROOT / "scripts" / "timeshare_pretrain.py",
    {"split_param_groups_from_state_dict", "build_optimizer_id_maps"},
    {},
)
shared_audit = _load_functions(
    ROOT / "src" / "ember" / "governance" / "scripts" / "p5_ratio_audit" / "run_p5_audit.py",
    {"enumerate_missing_optimizer_state_ids"},
    {"ts": timeshare},
)


class StagedCheckpointVerificationFailure(RuntimeError):
    pass


stabilize_source = (
    ROOT / "src" / "ember" / "governance" / "scripts" / "cbase_grow_rung2_stabilize.py"
).read_text(encoding="utf-8")
stabilize = _load_functions(
    ROOT / "src" / "ember" / "governance" / "scripts" / "cbase_grow_rung2_stabilize.py",
    {
        "_enumerate_missing_optimizer_state_ids",
        "_write_transplanted_muon_buffers",
        "momentum_norm_by_group",
    },
    {
        "ts": timeshare,
        "enumerate_missing_optimizer_state_ids": (
            shared_audit.enumerate_missing_optimizer_state_ids
        ),
        "StagedCheckpointVerificationFailure": (
            StagedCheckpointVerificationFailure
        ),
        "TRUNCATED_PARAM_ID_START": 140,
    },
)


def _tensor(rows: int = 2, cols: int = 2) -> torch.Tensor:
    return torch.ones(rows, cols)


class TestStabilizeOptimizerIdConvention(unittest.TestCase):
    def test_missing_state_checker_uses_each_optimizers_local_id_space(self) -> None:
        model_state = OrderedDict(
            [
                ("embed.weight", _tensor()),
                ("layer.0.attn.weight", _tensor()),
                ("layer.0.norm.weight", torch.ones(2)),
                ("layer.0.mlp.gate_proj.weight", _tensor()),
                ("head.weight", _tensor()),
            ]
        )
        optimizer_state = {
            "muon": {
                "state": {
                    0: {"momentum_buffer": _tensor()},
                    1: {"momentum_buffer": _tensor()},
                }
            },
            "adamw": {
                "state": {
                    0: {"exp_avg": _tensor()},
                    1: {"exp_avg": torch.ones(2)},
                    2: {"exp_avg": _tensor()},
                }
            },
        }

        self.assertEqual(
            stabilize._enumerate_missing_optimizer_state_ids(
                model_state, optimizer_state
            ),
            set(),
        )

    def test_transplanted_buffers_are_written_by_muon_local_id(self) -> None:
        model_state = OrderedDict(
            [
                ("embed.weight", _tensor()),
                ("layer.0.mlp.gate_proj.weight", _tensor()),
                ("layer.0.norm.weight", torch.ones(2)),
                ("layer.0.mlp.up_proj.weight", _tensor()),
            ]
        )
        muon_state = {
            0: {"momentum_buffer": torch.zeros(2, 2)},
            1: {"momentum_buffer": torch.zeros(2, 2)},
        }
        gate = torch.full((2, 2), 3.0)
        up = torch.full((2, 2), 5.0)

        written = stabilize._write_transplanted_muon_buffers(
            model_state,
            muon_state,
            {
                "layer.0.mlp.gate_proj.weight": gate,
                "layer.0.mlp.up_proj.weight": up,
            },
        )

        self.assertIs(muon_state[0]["momentum_buffer"], gate)
        self.assertIs(muon_state[1]["momentum_buffer"], up)
        self.assertEqual(
            written,
            [
                {"key": "layer.0.mlp.gate_proj.weight", "muon_local_id": 0},
                {"key": "layer.0.mlp.up_proj.weight", "muon_local_id": 1},
            ],
        )

    def test_transplanted_buffer_write_rejects_non_muon_name(self) -> None:
        model_state = OrderedDict(
            [
                ("embed.weight", _tensor()),
                ("layer.0.mlp.gate_proj.weight", _tensor()),
            ]
        )
        with self.assertRaisesRegex(
            StagedCheckpointVerificationFailure, "not Muon-routed"
        ):
            stabilize._write_transplanted_muon_buffers(
                model_state,
                {0: {"momentum_buffer": torch.zeros(2, 2)}},
                {"embed.weight": torch.ones(2, 2)},
            )

    def test_transplanted_buffer_write_rejects_missing_local_slot(self) -> None:
        model_state = OrderedDict(
            [("layer.0.mlp.gate_proj.weight", _tensor())]
        )
        with self.assertRaisesRegex(
            StagedCheckpointVerificationFailure, "optimizer slot 0.*missing"
        ):
            stabilize._write_transplanted_muon_buffers(
                model_state,
                {},
                {"layer.0.mlp.gate_proj.weight": torch.ones(2, 2)},
            )

    def test_momentum_group_receipt_rejects_unknown_local_slot(self) -> None:
        model_state = OrderedDict(
            [("layer.0.mlp.gate_proj.weight", _tensor())]
        )
        optimizer_state = {
            "muon": {"state": {9: {"momentum_buffer": torch.ones(1)}}},
            "adamw": {"state": {}},
        }
        original = getattr(timeshare, "load_checkpoint", None)
        timeshare.load_checkpoint = lambda _path: (
            model_state,
            optimizer_state,
            {},
            {"step": 1},
        )
        try:
            with self.assertRaisesRegex(
                StagedCheckpointVerificationFailure,
                "unknown Muon-local optimizer slot 9",
            ):
                stabilize.momentum_norm_by_group("unused")
        finally:
            if original is None:
                delattr(timeshare, "load_checkpoint")
            else:
                timeshare.load_checkpoint = original

    def test_materialize_path_does_not_remap_local_state_back_to_global_ids(self) -> None:
        tree = ast.parse(stabilize_source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "materialize_optimizer_grown_bundle"
        )
        source = ast.get_source_segment(stabilize_source, function)
        self.assertIsNotNone(source)
        self.assertNotIn("remapped_muon_state", source)
        self.assertNotIn("seed_param_names.index", source)
        self.assertIn(
            "transplant_muon_ff_momentum(\n        seed_m, seed_o,",
            source,
        )
        # The adjacent write is intentionally local-to-local and must remain so.
        self.assertIn("local_idx = muon_local_names.index(name)", source)
        self.assertIn("grown_muon_state[local_idx]", source)

    def test_momentum_group_receipt_maps_local_slots_back_to_global_partition(self) -> None:
        model_state: OrderedDict[str, torch.Tensor] = OrderedDict()
        # Global ids 0..44 are AdamW-routed; ids 45..139 are Muon-routed.
        for index in range(45):
            model_state[f"prefix_norm_{index}.weight"] = torch.ones(1)
        for index in range(95):
            model_state[f"warm_muon_{index}.weight"] = _tensor()
        # Global ids 140..184 are also Muon-routed, but form the reset group.
        for index in range(45):
            model_state[f"reset_muon_{index}.weight"] = _tensor()

        optimizer_state = {
            "muon": {
                "state": {
                    local_id: {"momentum_buffer": torch.ones(1)}
                    for local_id in range(140)
                }
            },
            "adamw": {
                "state": {
                    local_id: {"exp_avg": torch.ones(1)}
                    for local_id in range(45)
                }
            },
        }

        original = (
            timeshare.load_checkpoint
            if hasattr(timeshare, "load_checkpoint")
            else None
        )
        timeshare.load_checkpoint = lambda _path: (
            model_state,
            optimizer_state,
            {},
            {"step": 1},
        )
        try:
            result = stabilize.momentum_norm_by_group("unused")
        finally:
            if original is None:
                delattr(timeshare, "load_checkpoint")
            else:
                timeshare.load_checkpoint = original

        self.assertEqual(result["transplanted_group_n_tensors"], 95)
        self.assertEqual(result["reset_group_n_tensors"], 45)

    def test_real_checkpoint_absence_is_reported_as_skip_not_pass(self) -> None:
        helper = _load_functions(
            ROOT / "scripts" / "test_580_optimizer_id_helper.py",
            {"test_ac2_zero_missing_against_real_seed_checkpoint"},
            {
                "_get_seed_opt_state": lambda: None,
                "SEED_CKPT_RELATIVE": os.path.join("missing", "checkpoint"),
                "unittest": unittest,
            },
        )
        with self.assertRaises(unittest.SkipTest):
            helper.test_ac2_zero_missing_against_real_seed_checkpoint()

    def test_forensic_emitter_describes_muon_local_resolution(self) -> None:
        source = (ROOT / "scripts" / "p513_p3_forensic.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "param_id = list(model_state.keys()).index(gate_key)",
            source,
        )
        self.assertIn("muon_name_to_id", source)


if __name__ == "__main__":
    unittest.main()

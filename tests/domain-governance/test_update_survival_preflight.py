# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import math
import unittest

import torch

# issue2015 exact-local-import:src/ember/governance/scripts/preflight/update_survival.py
import importlib.util as _ember_ab945664fa2baab1_importlib
import sys as _ember_ab945664fa2baab1_sys
from pathlib import Path as _ember_ab945664fa2baab1_Path
_ember_ab945664fa2baab1_path = _ember_ab945664fa2baab1_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'preflight', 'update_survival.py')
if not _ember_ab945664fa2baab1_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/preflight/update_survival.py')
_ember_ab945664fa2baab1_aliases = ('_ember_issue2015_ab945664fa2baab1', 'scripts.preflight.update_survival', 'src.ember.governance.scripts.preflight.update_survival', 'update_survival')
_ember_ab945664fa2baab1_existing = []
for _ember_ab945664fa2baab1_alias in _ember_ab945664fa2baab1_aliases:
    _ember_ab945664fa2baab1_candidate = _ember_ab945664fa2baab1_sys.modules.get(_ember_ab945664fa2baab1_alias)
    if _ember_ab945664fa2baab1_candidate is not None and all(_ember_ab945664fa2baab1_candidate is not item for item in _ember_ab945664fa2baab1_existing):
        _ember_ab945664fa2baab1_existing.append(_ember_ab945664fa2baab1_candidate)
if len(_ember_ab945664fa2baab1_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/preflight/update_survival.py')
if _ember_ab945664fa2baab1_existing:
    _ember_ab945664fa2baab1_module = _ember_ab945664fa2baab1_existing[0]
    _ember_ab945664fa2baab1_observed = getattr(_ember_ab945664fa2baab1_module, '__file__', None)
    if _ember_ab945664fa2baab1_observed is None or _ember_ab945664fa2baab1_Path(_ember_ab945664fa2baab1_observed).resolve() != _ember_ab945664fa2baab1_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/preflight/update_survival.py')
else:
    _ember_ab945664fa2baab1_spec = _ember_ab945664fa2baab1_importlib.spec_from_file_location('_ember_issue2015_ab945664fa2baab1', _ember_ab945664fa2baab1_path)
    if _ember_ab945664fa2baab1_spec is None or _ember_ab945664fa2baab1_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/preflight/update_survival.py')
    _ember_ab945664fa2baab1_module = _ember_ab945664fa2baab1_importlib.module_from_spec(_ember_ab945664fa2baab1_spec)
    for _ember_ab945664fa2baab1_alias in _ember_ab945664fa2baab1_aliases:
        _ember_ab945664fa2baab1_prior = _ember_ab945664fa2baab1_sys.modules.get(_ember_ab945664fa2baab1_alias)
        if _ember_ab945664fa2baab1_prior is not None and _ember_ab945664fa2baab1_prior is not _ember_ab945664fa2baab1_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/preflight/update_survival.py')
        _ember_ab945664fa2baab1_sys.modules[_ember_ab945664fa2baab1_alias] = _ember_ab945664fa2baab1_module
    try:
        _ember_ab945664fa2baab1_spec.loader.exec_module(_ember_ab945664fa2baab1_module)
    except BaseException:
        for _ember_ab945664fa2baab1_alias in _ember_ab945664fa2baab1_aliases:
            if _ember_ab945664fa2baab1_sys.modules.get(_ember_ab945664fa2baab1_alias) is _ember_ab945664fa2baab1_module:
                _ember_ab945664fa2baab1_sys.modules.pop(_ember_ab945664fa2baab1_alias, None)
        raise
for _ember_ab945664fa2baab1_alias in _ember_ab945664fa2baab1_aliases:
    _ember_ab945664fa2baab1_prior = _ember_ab945664fa2baab1_sys.modules.get(_ember_ab945664fa2baab1_alias)
    if _ember_ab945664fa2baab1_prior is not None and _ember_ab945664fa2baab1_prior is not _ember_ab945664fa2baab1_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/preflight/update_survival.py')
    _ember_ab945664fa2baab1_sys.modules[_ember_ab945664fa2baab1_alias] = _ember_ab945664fa2baab1_module
OptimizerSpec = getattr(_ember_ab945664fa2baab1_module, 'OptimizerSpec')
TensorProbe = getattr(_ember_ab945664fa2baab1_module, 'TensorProbe')
run_update_survival_preflight = getattr(_ember_ab945664fa2baab1_module, 'run_update_survival_preflight')
# issue2015 exact-local-import-end:src/ember/governance/scripts/preflight/update_survival.py


def _sgd_spec() -> OptimizerSpec:
    return OptimizerSpec(
        family="sgd",
        kwargs={
            "lr": 1.0,
            "momentum": 0.0,
            "dampening": 0.0,
            "weight_decay": 0.0,
            "nesterov": False,
            "maximize": False,
            "foreach": False,
        },
    )


def _adamw_decay_spec() -> OptimizerSpec:
    return OptimizerSpec(
        family="adamw",
        kwargs={
            "lr": 0.01,
            "betas": (0.9, 0.999),
            "eps": 1.0e-8,
            "weight_decay": 1.0,
            "amsgrad": False,
            "maximize": False,
            "foreach": False,
            "capturable": False,
            "differentiable": False,
            "fused": False,
        },
    )


class UpdateSurvivalPreflightTests(unittest.TestCase):
    def test_weight_decay_total_delta_cannot_mint_signal_survival(self) -> None:
        probe = TensorProbe(
            name="weight",
            tensor_class="weight",
            initial=torch.ones(32, dtype=torch.bfloat16),
            gradient=torch.full((32,), 1.0e-12, dtype=torch.float32),
            required_survival=True,
        )
        receipt = run_update_survival_preflight(
            probes=[probe],
            optimizer_spec=_adamw_decay_spec(),
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.01},
            gradient_source={"kind": "synthetic", "source_id": "decay-confound-v1"},
        )

        metrics = receipt["steps"][0]["tensor_classes"]["weight"]
        self.assertEqual(receipt["verdict"], "PREFLIGHT_FAIL")
        self.assertEqual(metrics["total_changed_fraction"], 1.0)
        self.assertEqual(metrics["causal_changed_fraction"], 0.0)
        self.assertGreater(metrics["decay_rms"], 0.0)
        self.assertGreater(metrics["fp32_causal_rms"], 0.0)

    def test_cpu_dead_zone_curve_falls_to_zero(self) -> None:
        fractions: list[float] = []
        for scale in (1.0e-2, 1.0e-4, 1.0e-7):
            probe = TensorProbe(
                name=f"weight-{scale}",
                tensor_class="weight",
                initial=torch.linspace(0.5, 1.5, 256, dtype=torch.float32).to(
                    torch.bfloat16
                ),
                gradient=torch.full((256,), scale, dtype=torch.float32),
                required_survival=True,
            )
            receipt = run_update_survival_preflight(
                probes=[probe],
                optimizer_spec=_sgd_spec(),
                treatment_dtype=torch.bfloat16,
                step_counts=(1,),
                class_survival_floors={"weight": 0.0},
                gradient_source={
                    "kind": "synthetic",
                    "source_id": f"dead-zone-{scale}",
                },
            )
            fractions.append(
                receipt["steps"][0]["tensor_classes"]["weight"][
                    "causal_changed_fraction"
                ]
            )

        self.assertGreater(fractions[0], fractions[1])
        self.assertGreaterEqual(fractions[1], fractions[2])
        self.assertEqual(fractions[-1], 0.0)

    def test_bitnet_15_of_24_freeze_is_preflight_fail(self) -> None:
        probes = []
        for index in range(24):
            is_weight = index < 15
            probes.append(
                TensorProbe(
                    name=f"{'weight' if is_weight else 'norm-scale'}.{index}",
                    tensor_class="weight" if is_weight else "norm_scale",
                    initial=torch.ones(8, dtype=torch.bfloat16),
                    gradient=torch.full(
                        (8,),
                        1.0e-2 if is_weight else 1.0e-4,
                        dtype=torch.float32,
                    ),
                    required_survival=not is_weight,
                )
            )
        receipt = run_update_survival_preflight(
            probes=probes,
            optimizer_spec=_sgd_spec(),
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.9, "norm_scale": 0.01},
            gradient_source={"kind": "synthetic", "source_id": "bitnet-15-of-24"},
        )

        step = receipt["steps"][0]
        self.assertEqual(receipt["verdict"], "PREFLIGHT_FAIL")
        self.assertEqual(step["changed_tensor_count"], 15)
        self.assertEqual(step["tensor_count"], 24)
        self.assertEqual(
            step["tensor_classes"]["norm_scale"]["causal_changed_fraction"],
            0.0,
        )
        self.assertEqual(len(step["frozen_required_tensors"]), 9)

    def test_fp32_master_same_fixture_passes(self) -> None:
        probes = [
            TensorProbe(
                name=f"{'weight' if index < 15 else 'norm-scale'}.{index}",
                tensor_class="weight" if index < 15 else "norm_scale",
                initial=torch.ones(8, dtype=torch.bfloat16),
                gradient=torch.full(
                    (8,),
                    1.0e-2 if index < 15 else 1.0e-4,
                    dtype=torch.float32,
                ),
                required_survival=index >= 15,
            )
            for index in range(24)
        ]
        receipt = run_update_survival_preflight(
            probes=probes,
            optimizer_spec=_sgd_spec(),
            treatment_dtype=torch.float32,
            step_counts=(1, 3),
            class_survival_floors={"weight": 0.9, "norm_scale": 0.9},
            gradient_source={"kind": "synthetic", "source_id": "bitnet-fp32-master"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_PASS")
        for step in receipt["steps"]:
            self.assertEqual(step["changed_tensor_count"], 24)
            self.assertEqual(step["frozen_required_tensors"], [])

    def test_adafactor_implicit_dtype_default_is_invalid_reference(self) -> None:
        probe = TensorProbe(
            name="gate_proj.weight",
            tensor_class="weight",
            initial=torch.ones((4, 4), dtype=torch.bfloat16),
            gradient=torch.full((4, 4), 1.0e-2, dtype=torch.float32),
            required_survival=True,
        )
        implicit = OptimizerSpec(
            family="adafactor",
            kwargs={
                "lr": 0.01,
                "beta2_decay": -0.8,
                "eps": (None, 0.001),
                "d": 1.0,
                "weight_decay": 0.0,
                "foreach": False,
                "maximize": False,
            },
        )
        invalid = run_update_survival_preflight(
            probes=[probe],
            optimizer_spec=implicit,
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "adafactor-eps-none"},
        )
        self.assertEqual(invalid["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(
            invalid["invalid_code"],
            "PREFLIGHT_INVALID_REFERENCE",
        )

        explicit = OptimizerSpec(
            family="adafactor",
            kwargs={**implicit.kwargs, "eps": (0.001, 0.001)},
        )
        cleared = run_update_survival_preflight(
            probes=[probe],
            optimizer_spec=explicit,
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={
                "kind": "captured",
                "source_id": "adafactor-eps-explicit",
            },
        )
        self.assertNotEqual(cleared["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(cleared["reference_identity"]["status"], "CLEAR")

    def test_receipt_is_finite_and_closed_at_top_level(self) -> None:
        receipt = run_update_survival_preflight(
            probes=[
                TensorProbe(
                    name="weight",
                    tensor_class="weight",
                    initial=torch.ones(4, dtype=torch.float32),
                    gradient=torch.ones(4, dtype=torch.float32),
                    required_survival=True,
                )
            ],
            optimizer_spec=_sgd_spec(),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 1.0},
            gradient_source={"kind": "synthetic", "source_id": "finite-receipt"},
        )
        self.assertEqual(
            set(receipt),
            {
                "schema",
                "verdict",
                "invalid_code",
                "optimizer",
                "treatment_dtype",
                "gradient_source",
                "gradient_source_sha256",
                "reference_identity",
                "class_survival_floors",
                "steps",
                "receipt_sha256",
            },
        )
        self.assertTrue(
            all(
                math.isfinite(float(metric))
                for step in receipt["steps"]
                for values in step["tensor_classes"].values()
                for key, metric in values.items()
                if key.endswith(("_rms", "_fraction"))
            )
        )


if __name__ == "__main__":
    unittest.main()

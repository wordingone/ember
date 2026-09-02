# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

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


def _adamw_spec(*, lr: float = 0.01) -> OptimizerSpec:
    return OptimizerSpec(
        family="adamw",
        kwargs={
            "lr": lr,
            "betas": (0.9, 0.999),
            "eps": 1.0e-8,
            "weight_decay": 0.0,
            "amsgrad": False,
            "maximize": False,
            "foreach": False,
            "capturable": False,
            "differentiable": False,
            "fused": False,
        },
    )


def _probe() -> TensorProbe:
    return TensorProbe(
        name="weight",
        tensor_class="weight",
        initial=torch.ones(8, dtype=torch.float32),
        gradient=torch.full((8,), 0.1, dtype=torch.float32),
        required_survival=True,
    )


class UpdateSurvivalValidationTests(unittest.TestCase):
    def test_nonfinite_optimizer_input_returns_invalid_receipt(self) -> None:
        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(lr=float("nan")),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "synthetic", "source_id": "nan-lr"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_malformed_gradient_source_returns_invalid_receipt(self) -> None:
        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_state_hyperparameters_cannot_override_declared_optimizer(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.float32))
        source = torch.optim.AdamW(
            [parameter],
            lr=0.02,
            betas=(0.9, 0.999),
            eps=1.0e-8,
            weight_decay=0.0,
            amsgrad=False,
            maximize=False,
            foreach=False,
            capturable=False,
            differentiable=False,
            fused=False,
        )
        parameter.grad = torch.full_like(parameter, 0.1)
        source.step()

        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(lr=0.01),
            optimizer_state_dict=source.state_dict(),
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "state-lr-drift"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")

    def test_pre_step_optimizer_state_mapping_is_receipted(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(8, dtype=torch.float32))
        source = torch.optim.AdamW(
            [parameter],
            **dict(_adamw_spec().kwargs),
        )
        parameter.grad = torch.full_like(parameter, 0.1)
        source.step()

        receipt = run_update_survival_preflight(
            probes=[_probe()],
            optimizer_spec=_adamw_spec(),
            optimizer_state_dict=source.state_dict(),
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "state-map"},
        )

        identity = receipt["steps"][0]["pre_step_optimizer_state_identity"]
        self.assertEqual(identity["status"], "CLEAR")
        self.assertGreater(identity["tensor_state_count"], 0)
        self.assertRegex(identity["mapping_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

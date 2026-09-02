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
LiveTensorBinding = getattr(_ember_ab945664fa2baab1_module, 'LiveTensorBinding')
run_live_optimizer_update_survival_preflight = getattr(_ember_ab945664fa2baab1_module, 'run_live_optimizer_update_survival_preflight')
# issue2015 exact-local-import-end:src/ember/governance/scripts/preflight/update_survival.py


class _ForeignOptimizer(torch.optim.Optimizer):
    def __init__(self, params) -> None:
        super().__init__(params, {"lr": 1.0})

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            for parameter in group["params"]:
                if parameter.grad is not None:
                    parameter.add_(parameter.grad, alpha=-group["lr"])


def _binding(
    name: str,
    parameter: torch.nn.Parameter,
    *,
    tensor_class: str,
) -> LiveTensorBinding:
    return LiveTensorBinding(
        name=name,
        tensor_class=tensor_class,
        parameter=parameter,
        required_survival=True,
    )


class UpdateSurvivalLiveOptimizerTests(unittest.TestCase):
    def test_live_optimizer_preserves_realized_split_groups(self) -> None:
        fast = torch.nn.Parameter(torch.ones(16, dtype=torch.bfloat16))
        slow = torch.nn.Parameter(torch.ones(16, dtype=torch.bfloat16))
        fast.grad = torch.full_like(fast, 1.0e-2)
        slow.grad = torch.full_like(slow, 1.0e-2)
        optimizer = torch.optim.SGD(
            [
                {"params": [fast], "lr": 1.0},
                {"params": [slow], "lr": 0.5},
            ],
            momentum=0.0,
            dampening=0.0,
            weight_decay=0.0,
            nesterov=False,
            maximize=False,
            foreach=False,
            differentiable=False,
            fused=False,
        )

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[
                _binding("fast.weight", fast, tensor_class="fast"),
                _binding("slow.weight", slow, tensor_class="slow"),
            ],
            optimizer=optimizer,
            treatment_dtype=torch.bfloat16,
            step_counts=(1,),
            class_survival_floors={"fast": 0.0, "slow": 0.0},
            gradient_source={"kind": "captured", "source_id": "split-groups"},
        )

        self.assertNotEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["optimizer"]["family"], "sgd")
        self.assertEqual(
            [
                group["parameter_names"]
                for group in receipt["optimizer"]["param_groups"]
            ],
            [["fast.weight"], ["slow.weight"]],
        )
        self.assertEqual(
            [group["options"]["lr"] for group in receipt["optimizer"]["param_groups"]],
            [1.0, 0.5],
        )
        self.assertGreater(
            receipt["steps"][0]["tensor_classes"]["fast"]["causal_rms"],
            receipt["steps"][0]["tensor_classes"]["slow"]["causal_rms"],
        )

    def test_live_optimizer_rejects_incomplete_parameter_coverage(self) -> None:
        included = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        omitted = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        included.grad = torch.ones_like(included)
        omitted.grad = torch.ones_like(omitted)
        optimizer = torch.optim.SGD([included, omitted], lr=1.0)

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("included", included, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "incomplete-map"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")

    def test_live_optimizer_requires_captured_non_none_gradients(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        optimizer = torch.optim.AdamW([parameter], lr=0.01)

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("weight", parameter, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "missing-grad"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_INPUT")

    def test_unrecognized_optimizer_class_fails_closed(self) -> None:
        parameter = torch.nn.Parameter(torch.ones(4, dtype=torch.float32))
        parameter.grad = torch.ones_like(parameter)
        optimizer = _ForeignOptimizer([parameter])

        receipt = run_live_optimizer_update_survival_preflight(
            bindings=[_binding("weight", parameter, tensor_class="weight")],
            optimizer=optimizer,
            treatment_dtype=torch.float32,
            step_counts=(1,),
            class_survival_floors={"weight": 0.0},
            gradient_source={"kind": "captured", "source_id": "foreign"},
        )

        self.assertEqual(receipt["verdict"], "PREFLIGHT_INVALID")
        self.assertEqual(receipt["invalid_code"], "PREFLIGHT_INVALID_REFERENCE")


if __name__ == "__main__":
    unittest.main()

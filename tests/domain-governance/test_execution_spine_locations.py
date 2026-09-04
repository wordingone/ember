from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEGACY_MODEL_DIR = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
SPINE = (
    ("src/ember/model/model.py", "src.ember.model.model", "UnifiedDecoder"),
    ("src/ember/training/pretrain.py", "src.ember.training.pretrain", "run_pretraining_segment"),
    ("src/ember/evaluation/cbase_heldout_eval.py", "src.ember.evaluation.cbase_heldout_eval", "evaluate_teacher_forced"),
    ("src/ember/runtime/infer.py", "src.ember.runtime.infer", "greedy_generate"),
)


def test_active_execution_spine_has_one_importable_canonical_location() -> None:
    for relative, module_name, public_entrypoint in SPINE:
        canonical = ROOT / relative
        assert canonical.is_file(), f"missing canonical execution-spine module: {relative}"
        module = importlib.import_module(module_name)
        assert Path(module.__file__).resolve() == canonical.resolve()
        assert hasattr(module, public_entrypoint), (
            f"{module_name} does not expose {public_entrypoint}"
        )


def test_canonical_runtime_import_ignores_transient_legacy_model_alias() -> None:
    tracked = ("model", "src.ember.runtime.infer")
    prior = {name: sys.modules.get(name) for name in tracked}
    sys.path.insert(0, str(LEGACY_MODEL_DIR))
    try:
        for name in tracked:
            sys.modules.pop(name, None)
        legacy = importlib.import_module("model")
        assert Path(legacy.__file__).resolve() == (LEGACY_MODEL_DIR / "model.py").resolve()
        runtime = importlib.import_module("src.ember.runtime.infer")
        assert runtime.RestartDecoderConfig.__module__ == "src.ember.model.model"
    finally:
        sys.path.remove(str(LEGACY_MODEL_DIR))
        for name, module in prior.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

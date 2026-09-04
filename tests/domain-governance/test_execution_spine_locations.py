from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
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
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

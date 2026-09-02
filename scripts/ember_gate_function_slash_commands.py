# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# disposition: ADAPTER
# issue1949 old_path: scripts/ember_gate_function_slash_commands.py
# issue1949 new_path: src/ember/governance/scripts/ember_gate_function_slash_commands.py
from __future__ import annotations
import importlib.util as _issue1949_importlib
import sys as _issue1949_sys
from pathlib import Path as _issue1949_Path
_issue1949_root = next(parent for parent in _issue1949_Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
_issue1949_target = _issue1949_root.joinpath('src', 'ember', 'governance', 'scripts', 'ember_gate_function_slash_commands.py')
if not _issue1949_target.is_file():
    raise ImportError("ISSUE1949_ADAPTER_TARGET_MISSING:src/ember/governance/scripts/ember_gate_function_slash_commands.py")
_issue1949_name = "_ember_issue1949_50a62e35a6e0e856"
_issue1949_spec = _issue1949_importlib.spec_from_file_location(_issue1949_name, _issue1949_target)
if _issue1949_spec is None or _issue1949_spec.loader is None:
    raise ImportError("ISSUE1949_ADAPTER_SPEC_INVALID:src/ember/governance/scripts/ember_gate_function_slash_commands.py")
_issue1949_module = _issue1949_importlib.module_from_spec(_issue1949_spec)
_issue1949_sys.modules[_issue1949_name] = _issue1949_module
_issue1949_spec.loader.exec_module(_issue1949_module)
globals().update({name: value for name, value in vars(_issue1949_module).items() if name not in {"__name__", "__loader__", "__package__", "__spec__"}})

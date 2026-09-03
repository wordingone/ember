# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compatibility bridge while EMBER-02B moves the restart tool tree."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_CANONICAL_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ember"
    / "infrastructure"
    / "tools"
    / "corpus_connectors"
    / "receipt.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "ember_canonical_connector_receipt", _CANONICAL_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("canonical connector receipt authority cannot be loaded")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

for _NAME in dir(_MODULE):
    if not _NAME.startswith("__"):
        globals()[_NAME] = getattr(_MODULE, _NAME)

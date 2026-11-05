# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Make the sibling ``hour_test_support`` module importable under every pytest import mode.

Each test here starts with ``import hour_test_support``. Under pytest's default ``prepend``
mode that works because the test's own directory is put on ``sys.path``; the nightly runs
with ``--import-mode=importlib``, which does not, so all eight files failed at collection
with ``ModuleNotFoundError: No module named 'hour_test_support'``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

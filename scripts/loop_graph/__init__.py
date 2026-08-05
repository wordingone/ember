# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Loop/graph engineering substrate for Ember issue #1309.

Engine-agnostic: this package stores graphs and receipts as plain JSON /
JSONL and never assumes a specific driving engine (Claude Code, codex, or
a future Ember-native mind). See docs/charter/loop-graph-engine-contract.md.
"""

from __future__ import annotations

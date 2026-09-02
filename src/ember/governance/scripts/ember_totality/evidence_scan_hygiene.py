#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed exclusions for artifacts that may never serve as probe evidence.

Totality board renders summarize other evidence and repeat condition reasons
verbatim. They are outputs of the probe graph, so consuming them as inputs
creates circular verdicts.
"""

import json
import os


BOARD_RECEIPT_TYPE = "ember_totality_board"
BOARD_TICKET = "EMBER-TOTALITY-BOARD"
BOARD_OUTPUT_DIRNAME = "receipts-totality"


def is_board_render_output(path):
    """Return True only for a canonical totality-board output."""
    normalized = os.path.normpath(os.fspath(path))
    if BOARD_OUTPUT_DIRNAME in normalized.replace("\\", "/").split("/"):
        return True
    if not normalized.lower().endswith(".json"):
        return False
    try:
        with open(normalized, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, UnicodeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("receipt_type") == BOARD_RECEIPT_TYPE
        and payload.get("ticket") == BOARD_TICKET
    )

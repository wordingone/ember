#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest entrypoint for ember_resident_training_candidate."""
from __future__ import annotations

import ember_resident_training_candidate as candidate


def main() -> int:
    return candidate.selftest()


if __name__ == "__main__":
    raise SystemExit(main())

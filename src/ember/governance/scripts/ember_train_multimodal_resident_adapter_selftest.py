# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Selftest entrypoint for ember_train_multimodal_resident_adapter."""
from __future__ import annotations

import ember_train_multimodal_resident_adapter as adapter


def main() -> int:
    return adapter.selftest()


if __name__ == "__main__":
    raise SystemExit(main())

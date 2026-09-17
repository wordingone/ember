#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# claim_boundary: timing successor only; no learning or trainer installation credit
"""Entry point for the separately versioned FP8 speed probe."""
from pathlib import Path
import sys

SCRIPTS=Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
from fp8_pair_v2.runner import main

if __name__=='__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# claim_boundary: bounded shared-pair precision evidence; no model admission
"""#1945 isolated FP8 shared up/gate probe. Must use owned_process.py."""
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from fp8_pair_v1.probe import main

if __name__=='__main__':
    raise SystemExit(main())

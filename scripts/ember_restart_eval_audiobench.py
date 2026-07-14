#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Retired unsafe AudioBench summary producer; use the bound scorer instead."""
import sys
def main():
 print('summary-only AudioBench scoring is retired; use ember_restart_eval_audiobench_bound.py with canonical predictions',file=sys.stderr)
 return 2
if __name__=='__main__':raise SystemExit(main())

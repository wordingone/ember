#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# wait for phase 1 (H38 H39 H43 SLEEP H40-42) to finish, then upload+HF-verify the 38 older children one at a time (lead 81919)
until grep -q "ALL DONE" $EMBER_LANE_ROOT/logs/ckpt-backup.log 2>/dev/null; do sleep 60; done
cd $EMBER_LANE_ROOT && python scripts/ckpt_backup.py $(cat logs/ckpt-old-names.txt) > logs/ckpt-backup-old.log 2>&1

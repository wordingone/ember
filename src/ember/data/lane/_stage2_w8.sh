#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
cd $EMBER_LANE_ROOT
RESTORE_WORKERS=8 python scripts/ckpt_restore.py run --chain H39 --only all >> logs/ckpt-restore2.log 2>&1
echo "STAGE2-EXIT $?" >> logs/ckpt-restore2.log

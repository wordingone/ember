#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
cd $EMBER_LANE_ROOT
while tasklist //FI "PID eq 33536" 2>/dev/null | grep -q 33536; do sleep 20; done
python scripts/ckpt_restore.py run --chain H39 --only all >> logs/ckpt-restore2.log 2>> logs/ckpt-restore2.err
echo STAGE2-EXIT $? >> logs/ckpt-restore2.log

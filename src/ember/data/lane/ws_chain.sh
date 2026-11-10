#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
cd /b/M/data-staging || exit 1
export HELDOUT_EXTRA="$EMBER_LANE_ROOT/heldout-index/wiki-heldout-2M.npy,$EMBER_LANE_ROOT/arxiv/heldout-pdf-sent-hashes.npy"
W=wikisource-20220501
python scripts/wikisource_prep.py $W/enwikisource-20220501-pages-articles.xml.bz2 $W/ws-prep.jsonl.zst > logs/ws-prep.log 2>&1 &&
python scripts/scrub.py $W/ws-prep.jsonl.zst $W/ws-scrub.jsonl.zst > logs/ws-scrub.log 2>&1 &&
python scripts/dedup.py $W/ws-scrub.jsonl.zst $W/ws-final.jsonl.zst > logs/ws-dedup.log 2>&1 && echo "wikisource chain done $(date +%T)" >> logs/ws-chain.log

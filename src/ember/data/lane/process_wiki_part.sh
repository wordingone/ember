#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# process_wiki_part.sh PARTNAME : extract -> scrub (full index + frozen wiki 2M heldout + arXiv heldout PDFs) -> dedup. Output wikipedia-20220501/work/<tag>-final.jsonl.zst
cd /b/M/data-staging || exit 1
N="$1"; TAG=$(echo "$N" | sed -E 's/.*multistream([0-9]+)\.xml-p([0-9]+)p([0-9]+)\.bz2/m\1-p\2p\3/')
W=wikipedia-20220501/work; mkdir -p $W; [ -f $W/$TAG.done ] && exit 0
export HELDOUT_EXTRA="$EMBER_LANE_ROOT/heldout-index/wiki-heldout-2M.npy"
[ -f arxiv/heldout-pdf-sent-hashes.npy ] && export HELDOUT_EXTRA="$HELDOUT_EXTRA,$EMBER_LANE_ROOT/arxiv/heldout-pdf-sent-hashes.npy"
python scripts/wiki_pilot.py wikipedia-20220501/parts/$N $W/$TAG-full.jsonl.zst > logs/wp-$TAG-extract.log 2>&1 &&
python scripts/scrub.py $W/$TAG-full.jsonl.zst $W/$TAG-scrubbed.jsonl.zst > logs/wp-$TAG-scrub.log 2>&1 &&
python scripts/dedup.py $W/$TAG-scrubbed.jsonl.zst $W/$TAG-final.jsonl.zst > logs/wp-$TAG-dedup.log 2>&1 &&
touch $W/$TAG.done && echo "$TAG done $(date +%T)" >> logs/wiki-process.log

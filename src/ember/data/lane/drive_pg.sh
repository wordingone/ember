#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# drive_pg.sh : PG shards 0..29 -> prep -> scrub (full index + wiki 2M heldout + arXiv heldout PDFs) -> dedup ; gate on arXiv heldout hashes
cd /b/M/data-staging || exit 1
while [ ! -f arxiv/heldout-pdf-sent-hashes.npy ]; do sleep 30; done
export HELDOUT_EXTRA="$EMBER_LANE_ROOT/heldout-index/wiki-heldout-2M.npy,$EMBER_LANE_ROOT/arxiv/heldout-pdf-sent-hashes.npy"
W=pg/work; mkdir -p $W
for i in $(seq 0 29); do
  n=$(printf "%05d" $i); [ -f $W/$n.done ] && continue
  python scripts/pg_prep.py pg/${n}_pg.jsonl.gz $W/prep-$n.jsonl.zst > logs/pg-$n-prep.log 2>&1 &&
  python scripts/scrub.py $W/prep-$n.jsonl.zst $W/scrubbed-$n.jsonl.zst > logs/pg-$n-scrub.log 2>&1 &&
  python scripts/dedup.py $W/scrubbed-$n.jsonl.zst $W/final-$n.jsonl.zst > logs/pg-$n-dedup.log 2>&1 &&
  touch $W/$n.done && echo "pg $n done $(date +%T)" >> logs/pg-process.log
done
echo "ALL PG PROCESSED $(date +%T)" >> logs/pg-process.log

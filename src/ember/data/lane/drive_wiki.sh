#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# drive_wiki.sh : process each verified Wikipedia part as it lands, sequentially (gate: arXiv heldout hashes exist)
cd /b/M/data-staging || exit 1
while [ ! -f arxiv/heldout-pdf-sent-hashes.npy ]; do sleep 30; done
while true; do
  left=0
  while IFS=$'\t' read -r N SZ SHA; do
    TAG=$(echo "$N" | sed -E 's/.*multistream([0-9]+)\.xml-p([0-9]+)p([0-9]+)\.bz2/m\1-p\2p\3/')
    [ -f wikipedia-20220501/work/$TAG.done ] && continue
    left=$((left+1))
    if [ -f wikipedia-20220501/parts/$N.ok ]; then ./scripts/process_wiki_part.sh "$N"; fi
  done < wikipedia-20220501/todo.tsv
  [ "$left" = 0 ] && break
  sleep 60
done
echo "ALL WIKI PARTS PROCESSED $(date +%T)" >> logs/wiki-process.log

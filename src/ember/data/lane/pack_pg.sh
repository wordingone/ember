#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# pack_pg.sh NN [NN ...] : pack processed PG shards (as one dataset named pg-<first>-<last>) with per-doc provenance + source manifest
cd /b/M/data-staging || exit 1
FIRST=$1; LAST=${@: -1}; NAME="pg-$FIRST-$LAST"; INS=(); PAIRS=()
for n in "$@"; do INS+=("pg/work/final-$n.jsonl.zst"); PAIRS+=("pg/work/final-$n.jsonl.zst=pg/${n}_pg.jsonl.gz"); done
python scripts/prov_const.py packed/$NAME.prov.jsonl "2026-11-06" "Public Domain (US) - Project Gutenberg; common-pile/project_gutenberg@01dc90a5002f8977c7fb03a372c14bca29c65cf1" "${PAIRS[@]}" &&
python scripts/pack.py packed $NAME "${INS[@]}" > logs/pack-$NAME.log 2>&1 &&
python scripts/source_manifest.py packed/$NAME packed/$NAME.prov.jsonl "huggingface.co/datasets/common-pile/project_gutenberg@01dc90a5002f8977c7fb03a372c14bca29c65cf1 (v0/documents shard; LFS sha256 verified)" "Public Domain (US)" "2026-11-06" "2022-10-31" text &&
tail -c 420 logs/pack-$NAME.log

#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
cd /b/M/data-staging || exit 1
NAME=wikipedia-20220501-p41243p151573
python scripts/prov_const.py packed/$NAME.prov.jsonl "2026-11-06" "CC BY-SA 3.0 + GFDL (Wikipedia text)" "wikipedia-20220501/v-train2.jsonl.zst=wikipedia-20220501/verified-p41243p151573.bz2" &&
python scripts/pack.py packed $NAME wikipedia-20220501/v-train2.jsonl.zst > logs/pack-$NAME.log 2>&1 &&
python scripts/source_manifest.py packed/$NAME packed/$NAME.prov.jsonl "archive.org/details/enwiki-20220501 enwiki-20220501-pages-articles-multistream2.xml-p41243p151573.bz2 (sha1 8d256c02, verified; ns0 non-redirect, frozen 2M heldout carved out)" "CC BY-SA 3.0 + GFDL" "2026-11-06" "2022-05-01" text &&
tail -c 300 logs/pack-$NAME.log

#!/bin/bash
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# pack_wiki_group.sh NAME TAG1 TAG2 ... : pack processed enwiki-20220501 parts (work/<tag>-final.jsonl.zst) as one dataset; raw = parts/<file>
cd /b/M/data-staging || exit 1
NAME="$1"; shift; INS=(); PAIRS=()
for T in "$@"; do
  F=$(awk -F'\t' -v t="$T" '{n=$1; sub(/.*multistream/,"m",n); sub(/\.xml-/,"-",n); sub(/\.bz2$/,"",n); if (n==t) print $1}' wikipedia-20220501/todo.tsv | head -1)
  INS+=("wikipedia-20220501/work/$T-final.jsonl.zst"); PAIRS+=("wikipedia-20220501/work/$T-final.jsonl.zst=wikipedia-20220501/parts/$F")
done
python scripts/prov_const.py packed/$NAME.prov.jsonl "2026-11-06" "CC BY-SA 3.0 + GFDL (Wikipedia text)" "${PAIRS[@]}" &&
python scripts/pack.py packed $NAME "${INS[@]}" > logs/pack-$NAME.log 2>&1 &&
python scripts/source_manifest.py packed/$NAME packed/$NAME.prov.jsonl "archive.org/details/enwiki-20220501 pages-articles-multistream parts $* (sha1-verified; ns0 non-redirect; frozen 2M heldout scrubbed)" "CC BY-SA 3.0 + GFDL" "2026-11-06" "2022-05-01" text &&
tail -c 300 logs/pack-$NAME.log

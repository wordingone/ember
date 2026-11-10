# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ONE command (lead 81924): python <lane-root>/scripts/census_now.py  -> a fresh HF-only census and exactly four answer lines (text / images / audio / other).
HF repos are the authority (3 dataset repos, listings run concurrently, immutable manifests and parquet footers cached under census/json-cache keyed by path+size),
byte-identical overlap is zero-checked, the H19 exclusion is applied, heldout and superseded packs are not counted. Warm run: well under a minute. Cold run (first MLS audio_duration read): a few minutes.
Flags: --cached prints the lines from census/census-latest.json without touching HF (seconds)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, json, time
pass
import hf_inventory as H
OUT = (LANE_ROOT + "/census/census-latest.json")
def main():
    if "--cached" not in sys.argv:
        sys.argv = [sys.argv[0], "--quiet", "--out", OUT]; H.main()
    r = json.load(open(OUT, encoding="utf-8")); T = r["totals"]; U = r["unique"]
    tr = T.get("train_ready/text", {}); ri = T.get("raw/image", {}); ra = T.get("raw/audio", {}); sup = T.get("superseded/text", {}); held = T.get("heldout/text", {})
    packs = r["repos"]["train"].get("packs", []); pm = [p for p in packs if p["name"].startswith("pubmed")]
    ov = sum(v["overlap_items"] for v in U.values())
    G = 2 ** 30
    print(f"TEXT   {tr.get('tokens', 0)/1e9:.2f}B tokens train-ready, {tr.get('docs', 0):,} docs in the train repo (H19 exclusion applied: -{tr.get('h19_excluded_tokens', 0)/1e6:.0f}M tok); not counted: heldout {held.get('bytes', 0)/G:.1f} GiB, superseded packs {sup.get('tokens', 0)/1e9:.2f}B tok; pubmed pack {'IN (' + format(sum(p['tokens'] for p in pm), ',') + ' tok)' if pm else 'NOT in it'}")
    print(f"IMAGES {ri.get('images', 0):,} raw ({ri.get('bytes', 0)/G:.1f} GiB), 0 train-ready/packed (cc-by parquet + PD12M tars + commons-pd; PD12M is model-captioned, see census notes)")
    print(f"AUDIO  {ra.get('hours', 0) + ra.get('hours_est', 0):,.0f} h raw ({ra.get('hours', 0):,.0f} h MLS from {ra.get('segments', 0):,} segments + {ra.get('hours_est', 0):,.0f} h LibriVox mp3 estimated at 64 kbps; {ra.get('bytes', 0)/G:.1f} GiB), LibriSpeech {ra.get('hours_official', 0)} h is eval-only; 0 train-ready")
    print(f"OTHER  video {T.get('raw/video', {}).get('videos', 0)}; code/other outside the text packs 0; byte-identical overlap across repos {ov} items; census {r['ts']} ({r.get('elapsed_s', '?')} s)")
if __name__ == "__main__": main()

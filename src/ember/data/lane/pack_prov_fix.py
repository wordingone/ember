# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Finish a text-lane pack whose prov/source_manifest/domain.json step did not complete (caselaw-00000-00002: source_manifest crashed on a missing prov, 2026-11-10).
Mirrors the tail of text_lane.maybe_pack for the finals named in the pack's receipt.json 'inputs'; touches nothing else (no pack.py, no state.json write: a live lane holds state in memory).
Usage: python pack_prov_fix.py <lane> <pack-name>"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, io, json, time
LANE, NAME = sys.argv[1], sys.argv[2]
sys.argv = ["text_lane.py", LANE]
pass
import text_lane as T
import zstandard
BASE = T.ROOT; B = T.B; SPEC = T.SPEC
rec = json.load(open(f"{BASE}/packed/{NAME}/receipt.json"))
fin = B.state["finals"]; by_path = {v["path"].replace("\\", "/"): v for v in fin.values()}
prov = f"{BASE}/packed/{NAME}.prov.jsonl"
rows = 0
with open(prov, "w", encoding="utf-8") as pf:
    for ip in rec["inputs"]:
        v = by_path[ip.replace("\\", "/")]
        with open(v["path"], "rb") as f:
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
                r = json.loads(line)
                pf.write(json.dumps(dict(doc_id=r["id"], raw_sha256=v["raw_sha256"], raw_file=v["raw_file"], fetched_ts=time.strftime("%Y-%m-%d"), license_url=r.get("license"))) + "\n"); rows += 1
print("prov rows", rows, "pack docs", rec["docs"], flush=True)
T.run([sys.executable, BASE + "/scripts/source_manifest.py", f"{BASE}/packed/{NAME}", prov, f"huggingface.co/datasets/{SPEC['repo']} (see raw_file per row; " + ("public rev-pinned source, no raw re-host)" if SPEC.get("rawup") is False else f"raw copy in ember-raw-private {SPEC['rawdir']}/)"), "per-doc licence (see rows)", time.strftime("%Y-%m-%d"), T.WALL, "text"], f"{BASE}/logs/srcman-{NAME}.log")
json.dump(dict(domain=SPEC.get("domain", "mixed"), wall=T.WALL, source_repo=SPEC["repo"], date_method="per-doc date where present; else source-snapshot/pre-1929 (see prep fn)", uspto_cap=SPEC.get("uspto_cap", "n/a")), open(f"{BASE}/packed/{NAME}/domain.json", "w"))
print("DONE", NAME, sorted(os.listdir(f"{BASE}/packed/{NAME}")), flush=True)

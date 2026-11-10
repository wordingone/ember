# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""LibriVox-vs-MLS dedupe key sets (prep). MLS rows carry speaker_id + chapter_id (LibriSpeech lineage: chapter_id = LibriVox section id); the LibriVox pilot rows carry project id (section_id 'lv<proj>-s<n>'),
archive.org item, PG ebook, readers. This resolves each pilot (project, section_number) -> LibriVox section id via the audiotracks API (tiny JSON, cached) and writes lvpilot/lv-keys.json:
{section_ids, projects, archive_items, pg_ebooks, readers}. Use: lv_overlap_mls(chapter_id) membership, or reader-name match as a secondary signal. Resumable: cache lvpilot/audiotracks-cache.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, os, re, subprocess, time
R = (LANE_ROOT + "/lvpilot/"); C = R + "audiotracks-cache.json"
rows = [json.loads(l) for l in open(R + "pairs.jsonl")]
cache = json.load(open(C)) if os.path.exists(C) else {}
projs = sorted({int(re.match(r"lv(\d+)-s(\d+)", r["section_id"]).group(1)) for r in rows})
for p in projs:
    if str(p) in cache: continue
    for att in range(3):
        o = subprocess.run(["curl", "-s", "--max-time", "30", f"https://librivox.org/api/feed/audiotracks?project_id={p}&format=json"], capture_output=True, text=True).stdout
        try: cache[str(p)] = {s["section_number"]: s["id"] for s in json.loads(o)["sections"]}; break
        except Exception: time.sleep(3)
    json.dump(cache, open(C, "w"))
sec = set(); miss = 0
for r in rows:
    m = re.match(r"lv(\d+)-s(\d+)", r["section_id"]); i = cache.get(m.group(1), {}).get(m.group(2))
    if i: sec.add(i)
    else: miss += 1
keys = dict(section_ids=sorted(sec, key=int), projects=projs, archive_items=sorted({m.group(1) for r in rows if (m := re.search(r"^.*archive\.org/(.*)$", r["origin"], re.S))}),
            pg_ebooks=sorted({r["pg_ebook"] for r in rows if r.get("pg_ebook")}, key=int), readers=sorted({n for r in rows for n in r["readers"]}), unresolved_rows=miss)
json.dump(keys, open(R + "lv-keys.json", "w"), indent=1)
print({k: (len(v) if isinstance(v, list) else v) for k, v in keys.items()})

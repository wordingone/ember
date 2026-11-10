# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Download licence-kept COCO images (coco-keep.jsonl) from images.cocodataset.org, resumable, 6 threads. Writes coco/images/<file_name> and coco/fetched.jsonl (file_name, bytes, sha256). Usage: coco_fetch.py BASE"""
import sys, os, json, hashlib, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
BASE = sys.argv[1]; IMG2 = os.environ.get("COCO_IMG2", "A:/ember-stage/coco-images"); os.makedirs(BASE + "/images", exist_ok=True); os.makedirs(IMG2, exist_ok=True)
rows = [json.loads(l) for l in open(BASE + "/coco-keep.jsonl", encoding="utf-8")]
fp = BASE + "/fetched.jsonl"; done = {json.loads(l)["file_name"] for l in open(fp, encoding="utf-8")} if os.path.exists(fp) else set()
todo = [r for r in rows if r["file_name"] not in done and not os.path.exists(BASE + "/images/" + r["file_name"])]; fo = open(fp, "a", encoding="utf-8"); bad = 0
def get(r):
    p = IMG2 + "/" + r["file_name"]   # B: is floor-limited (lead 81393): new downloads go to A:
    for t in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(r["coco_url"], headers={"User-Agent": "ember-data-pilot/1.0 (research dataset; read-only)"}), timeout=60).read()
            if len(b) < 1000: raise ValueError("short")
            open(p, "wb").write(b); return dict(file_name=r["file_name"], bytes=len(b), sha256=hashlib.sha256(b).hexdigest())
        except Exception: time.sleep(3 * (t + 1))
    return None
n = 0
with ThreadPoolExecutor(3) as ex:   # lane cap 8 cores total (lead 81497); tick.py weights this job at 3
    for res in ex.map(get, todo):
        if res: fo.write(json.dumps(res) + "\n"); n += 1
        else: bad += 1
        if (n + bad) % 2000 == 0: fo.flush(); print(n, bad, flush=True)
fo.flush(); print("DONE", n, "failed", bad, "of", len(todo))
if bad == 0: open(BASE + "/FETCH.done", "w").write(str(len(rows)))

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-level join (lead 81826): H19 article maps file3-6 (page id + revision id 'ver') vs data wikipedia pack docs-index (page id), per pack.
Same-revision test: the pack is the 2022-05-01 dump (latest revision <= T of each page); the H19 snapshot is later. If H19 ver <= R_T (rev id at T = max ts seen in the pack objects) nobody edited the page between T and the H19 snapshot,
so H19 holds the SAME revision text. If ver > R_T the page was edited later: same article, different revision (near-duplicate, not identical). 1 core, BelowNormal, VeryLow IO."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, io, glob, time, urllib.request, urllib.parse
import psutil, zstandard as z
p = psutil.Process(); p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
try: p.ionice(psutil.IOPRIO_VERYLOW)
except Exception: pass
try: p.cpu_affinity([17])
except Exception: pass
MAPS = {"file3": "A:/ember-staging/h19-percatalog-20261004/file3-article-map-v1.jsonl", "file4": "A:/ember-staging/h19-percatalog-20261004/file4-article-map-v1.jsonl",
        "file5": "A:/ember-staging/h19-percatalog-20261004/file5-article-map-v1.jsonl", "file6": "A:/ember-staging/h19-percatalog-files6-10-v2-20261004T190306Z/file6-article-map-v1.jsonl"}
OBJ = {"file3": "1983e863", "file4": "a6ac037d", "file5": "3bc93f29", "file6": "0d544e19"}
h19 = {}   # page id -> (file, ver)
dup = 0
for fk, path in MAPS.items():
    for l in open(path, encoding="utf-8"):
        d = json.loads(l); i = str(d["id"])
        if i in h19: dup += 1
        h19[i] = (fk, int(d["ver"]))
print("h19 articles", len(h19), "dup ids across maps", dup, flush=True)
packs = []
for n in sorted(os.listdir((LANE_ROOT + "/packed"))):
    if not n.startswith("wikipedia-20220501-") or n.endswith(".jsonl") or n.endswith("-r1"): continue
    packs.append(n + "-r1" if os.path.isdir(f"{LANE_ROOT}/packed/{n}-r1") else n)
print("packs", packs, flush=True)
def maxts(pack):
    m = ""; objs = sorted(glob.glob(f"{LANE_ROOT}/packed/{pack}/objects/*.jsonl.zst"))
    for f in objs:
        for l in io.TextIOWrapper(z.ZstdDecompressor().stream_reader(open(f, "rb")), encoding="utf-8"):
            t = l.split('"ts": "', 1)[1][:20] if '"ts": "' in l else ""
            if t > m: m = t
    return m
def api_ts(ids):    # one batched call (<=50 revids); returns timestamp of the first id that exists, throttled + 429 backoff
    for att in range(8):
        try:
            u = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "prop": "revisions", "revids": "|".join(str(x) for x in ids), "rvprop": "timestamp|ids", "format": "json"})
            r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "ember-data-lane/1 (research; contact via repo owner)"}), timeout=30))
            time.sleep(1.5)
            got = {}
            for pg in r["query"]["pages"].values():
                for rv in pg.get("revisions", []): got[rv["revid"]] = rv["timestamp"]
            for x in ids:
                if x in got: return got[x]
            return None
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(20 * (att + 1))
    raise RuntimeError("API 429 persists")
def rev_at(T):    # largest rev id with timestamp <= T (revids are monotone in time)
    lo, hi = 1_040_000_000, 1_110_000_000
    while hi - lo > 1:
        mid = (lo + hi) // 2
        t = api_ts(list(range(mid, mid + 50)))
        if t is None: hi = mid; continue
        if t <= T: lo = mid
        else: hi = mid
    return lo
# T = global max ts over a spread sample of all packs' objects (every object of every pack is cheap enough but sample 4 objects/pack for speed, then full scan if time allows)
res = {"method": __doc__, "h19_articles": len(h19), "packs": {}}
T = ""
for pk in packs:
    objs = sorted(glob.glob(f"{LANE_ROOT}/packed/{pk}/objects/*.jsonl.zst"))
    mt = ""
    for f in objs[:: max(1, len(objs) // 4)][:6]:
        for l in io.TextIOWrapper(z.ZstdDecompressor().stream_reader(open(f, "rb")), encoding="utf-8"):
            t = l.split('"ts": "', 1)[1][:20] if '"ts": "' in l else ""
            if t > mt: mt = t
    res["packs"][pk] = {"max_ts_sampled": mt}; T = max(T, mt); print(pk, "max ts (sampled)", mt, flush=True)
RT = rev_at(T); res["T"] = T; res["R_T"] = RT; print("T", T, "R_T", RT, flush=True)
tot = dict(arts=0, toks=0, same_arts=0, same_toks=0, diff_arts=0, diff_toks=0)
for pk in packs:
    n_arts = 0; n_tok = 0; o = dict(arts=0, toks=0, same_arts=0, same_toks=0, diff_arts=0, diff_toks=0, by_file={})
    for l in io.TextIOWrapper(z.ZstdDecompressor().stream_reader(open(f"{LANE_ROOT}/packed/{pk}/docs-index.jsonl.zst", "rb")), encoding="utf-8"):
        if not l.strip(): continue
        d = json.loads(l); tk = d["token_end"] - d["token_start"]; n_arts += 1; n_tok += tk
        h = h19.get(str(d["id"]))
        if not h: continue
        fk, ver = h; o["arts"] += 1; o["toks"] += tk; b = o["by_file"].setdefault(fk, dict(arts=0, toks=0, same_arts=0, same_toks=0))
        b["arts"] += 1; b["toks"] += tk
        if ver <= RT: o["same_arts"] += 1; o["same_toks"] += tk; b["same_arts"] += 1; b["same_toks"] += tk
        else: o["diff_arts"] += 1; o["diff_toks"] += tk
    o["pack_articles"] = n_arts; o["pack_tokens"] = n_tok; res["packs"][pk].update(o)
    for k in tot: tot[k] += o[k]
    print(pk, {k: o[k] for k in ("pack_articles", "pack_tokens", "arts", "toks", "same_arts", "same_toks", "diff_arts", "diff_toks")}, flush=True)
res["total"] = tot; json.dump(res, open((LANE_ROOT + "/logs/h19-overlap.json"), "w"), indent=1); print("TOTAL", tot, flush=True)

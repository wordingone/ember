# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Widen the Commons candidate pull (lead 81399): members of community-curated categories (Quality images, Featured pictures) via generator=categorymembers.
Same candidate schema as commons_pilot.py, appended to OUT/cands.jsonl (deduped by title). Resumable: OUT/cat-state.json (per-category gcmcontinue). Usage: commons_cat.py OUT [TOTAL_NEW=30000]
Only candidate collection (read-only API, 1 req/2 s); all admission filters (licence, wall, bot, human description as-of the wall) happen in commons_pilot2.py."""
import sys, os, re, json, time, html, urllib.request, urllib.parse
OUT = sys.argv[1]; TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
API = "https://commons.wikimedia.org/w/api.php"; UA = "ember-data-pilot/1.0 (research dataset pilot; read-only)"
CATS = ["Category:Quality images", "Category:Featured pictures on Wikimedia Commons"]
TAG = re.compile(r"<[^>]+>"); WS = re.compile(r"\s+")
def clean(h): return WS.sub(" ", html.unescape(TAG.sub(" ", h or ""))).strip()
def api(**kw):
    time.sleep(2.0); kw.update(format="json", formatversion="2")
    for t in range(5):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode(kw), headers={"User-Agent": UA}), timeout=60).read())
        except Exception: time.sleep(5 * (t + 1))
    return None
cp = OUT + "/cands.jsonl"; seen = {json.loads(l)["title"] for l in open(cp, encoding="utf-8")} if os.path.exists(cp) else set()
sp = OUT + "/cat-state.json"; state = json.load(open(sp)) if os.path.exists(sp) else {}
new = 0; fo = open(cp, "a", encoding="utf-8")
for cat in CATS:
    st = state.setdefault(cat, {"cont": None, "done": False})
    while not st["done"] and new < TOTAL:
        kw = dict(action="query", generator="categorymembers", gcmtitle=cat, gcmtype="file", gcmlimit="50", prop="imageinfo|revisions", iiprop="timestamp|user|url|size|mime|extmetadata", iiurlwidth="512", rvprop="timestamp|user|comment")
        if st["cont"]: kw["gcmcontinue"] = st["cont"]
        d = api(**kw)
        if not d or "query" not in d:
            if d is not None and "continue" not in d: st["done"] = True
            break
        for p in d["query"]["pages"]:
            if p["title"] in seen or not p.get("imageinfo") or not p.get("revisions"): continue
            ii = p["imageinfo"][0]; rv = p["revisions"][0]; em = ii.get("extmetadata", {})
            c = dict(title=p["title"], upload_ts=ii["timestamp"], uploader=ii.get("user"), mime=ii.get("mime"), thumb=ii.get("thumburl"), w=ii.get("width"), h=ii.get("height"),
                     desc=clean(em.get("ImageDescription", {}).get("value")), lic=em.get("LicenseShortName", {}).get("value"), lic_url=em.get("LicenseUrl", {}).get("value"),
                     artist=clean(em.get("Artist", {}).get("value")), credit=clean(em.get("Credit", {}).get("value")), rev_ts=rv["timestamp"], rev_user=rv.get("user"), rev_comment=rv.get("comment"), via=cat)
            seen.add(p["title"]); fo.write(json.dumps(c, ensure_ascii=False) + "\n"); new += 1
        fo.flush(); st["cont"] = (d.get("continue") or {}).get("gcmcontinue"); json.dump(state, open(sp, "w"))
        if not st["cont"]: st["done"] = True; json.dump(state, open(sp, "w"))
        if new % 500 < 50: print("new cands", new, cat, flush=True)
if all(state.get(c, {}).get("done") for c in CATS) or new >= TOTAL: open(OUT + "/CAT.done", "w").write(str(new))
print("DONE new", new)

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Wikimedia Commons pilot (lead 81169/81222): ~1,000 human-described images, uploaded 2015..now, description last edited by a non-bot. NO DATE WALL (owner 2026-11-11, lead 83389): upload and last-edit timestamps are recorded as content_date_max, never filtered.
Usage: commons_pilot.py OUTDIR [TARGET=1000] [CANDIDATES=6000]
Read-only public API, 1 request/2 s, 512 px server-made thumbnails (deterministic resize, no ML). Resumable: OUTDIR/cands.jsonl, OUTDIR/thumbs/, OUTDIR/manifest.jsonl.
Filters (deterministic): licence in allow-list (PD*, CC0, CC BY, CC BY-SA, GFDL excluded), description >= 15 words after tag strip and not a filename echo,
last editor not in group 'bot' and name has no 'bot', mime jpeg/png, upload ts sampled over [2015-01-01, now]."""
import sys, os, re, json, time, random, html, hashlib, urllib.request, urllib.parse
OUT = sys.argv[1]; TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 1000; NC = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
API = "https://commons.wikimedia.org/w/api.php"
UA = "ember-data-pilot/1.0 (research dataset pilot; read-only; contact: project mail)"
os.makedirs(OUT + "/thumbs", exist_ok=True)
def get(url, binary=False):
    for t in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60); b = r.read()
            return b if binary else json.loads(b)
        except Exception as e:
            time.sleep(5 * (t + 1))
    return None
def api(**kw):
    time.sleep(2.0); kw.update(format="json", formatversion="2")
    return get(API + "?" + urllib.parse.urlencode(kw))
TAG = re.compile(r"<[^>]+>"); WS = re.compile(r"\s+")
LIC_OK = re.compile(r"^(public domain|pd[- ]|cc0|cc[- ]by(-sa)?[- ]\d|cc by(-sa)? \d|cc-zero)", re.I)
def clean(h): return WS.sub(" ", html.unescape(TAG.sub(" ", h or ""))).strip()
cp = OUT + "/cands.jsonl"; cands = [json.loads(l) for l in open(cp, encoding="utf-8")] if os.path.exists(cp) else []
seen = {c["title"] for c in cands}; rng = random.Random(20261106)
t0 = time.mktime((2015, 1, 1, 0, 0, 0, 0, 0, 0)); t1 = time.time()
with open(cp, "a", encoding="utf-8") as fo:
    while len(cands) < NC:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rng.uniform(t0, t1)))
        d = api(action="query", generator="allimages", gaisort="timestamp", gaistart=ts, gaidir="ascending", gailimit="50", prop="imageinfo|revisions",
                iiprop="timestamp|user|url|size|mime|extmetadata", iiurlwidth="512", rvprop="timestamp|user|comment")
        if not d or "query" not in d: continue
        for p in d["query"]["pages"]:
            if p["title"] in seen or not p.get("imageinfo") or not p.get("revisions"): continue
            ii = p["imageinfo"][0]; rv = p["revisions"][0]; em = ii.get("extmetadata", {})
            c = dict(title=p["title"], upload_ts=ii["timestamp"], uploader=ii.get("user"), mime=ii.get("mime"), thumb=ii.get("thumburl"), w=ii.get("width"), h=ii.get("height"),
                     desc=clean(em.get("ImageDescription", {}).get("value")), lic=em.get("LicenseShortName", {}).get("value"), lic_url=em.get("LicenseUrl", {}).get("value"),
                     artist=clean(em.get("Artist", {}).get("value")), credit=clean(em.get("Credit", {}).get("value")), rev_ts=rv["timestamp"], rev_user=rv.get("user"), rev_comment=rv.get("comment"))
            seen.add(p["title"]); cands.append(c); fo.write(json.dumps(c, ensure_ascii=False) + "\n")
        fo.flush(); print("cands", len(cands), flush=True)
# bot groups for last-rev users
users = sorted({c["rev_user"] for c in cands if c["rev_user"]}); bots = set(); ucp = OUT + "/botusers.json"
if os.path.exists(ucp): bots = set(json.load(open(ucp)))
else:
    for i in range(0, len(users), 50):
        d = api(action="query", list="users", ususers="|".join(users[i:i + 50]), usprop="groups")
        for u in (d or {}).get("query", {}).get("users", []):
            if "bot" in (u.get("groups") or []): bots.add(u["name"])
    json.dump(sorted(bots), open(ucp, "w"))
stat = dict(cands=len(cands), lic=0, desc=0, bot=0, mime=0, upload=0, kept=0)
kept = []
for c in cands:
    if not (c["mime"] in ("image/jpeg", "image/png") and c["thumb"]): stat["mime"] += 1; continue
    if not (c["lic"] and LIC_OK.search(c["lic"])): stat["lic"] += 1; continue
    if c["rev_user"] in bots or "bot" in (c["rev_user"] or "").lower() or "bot" in (c["uploader"] or "").lower(): stat["bot"] += 1; continue
    nm = re.sub(r"^File:|\.[a-z]+$", "", c["title"], flags=re.I).replace("_", " ").lower()
    if len(c["desc"].split()) < 15 or c["desc"].lower().strip() == nm: stat["desc"] += 1; continue
    kept.append(c)
kept = kept[:TARGET]; stat["kept"] = len(kept)
mp = OUT + "/manifest.jsonl"; n = 0; fail = 0
with open(mp, "w", encoding="utf-8") as fm:
    for c in kept:
        fn = OUT + "/thumbs/" + hashlib.sha1(c["title"].encode()).hexdigest()[:16] + (".jpg" if c["mime"] == "image/jpeg" else ".png")
        if not os.path.exists(fn):
            time.sleep(1.0); b = get(c["thumb"], binary=True)
            if not b: fail += 1; continue
            open(fn, "wb").write(b)
        fm.write(json.dumps(dict(path=fn.replace(chr(92), "/"), caption=c["desc"], licence=c["lic"], licence_url=c["lic_url"], author=c["artist"], credit=c["credit"],
                                 origin="https://commons.wikimedia.org/wiki/" + urllib.parse.quote(c["title"].replace(" ", "_")), fetch_date=time.strftime("%Y-%m-%d"),
                                 upload_ts=c["upload_ts"], last_edit_ts=c["rev_ts"], content_date_max=max(c["upload_ts"], c["rev_ts"])[:10]), ensure_ascii=False) + "\n"); n += 1
stat["thumb_fail"] = fail; stat["manifest_rows"] = n
json.dump(stat, open(OUT + "/pilot-stats.json", "w")); print(json.dumps(stat))

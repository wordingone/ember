# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Commons pilot v2: caption = the 'description' field of the page revision AS OF the wall (2022-10-31), not the current text (80% of pages were edited after the wall, so
'last edit <= wall' keeps only 0.3%). Reuses commons-pilot/cands.jsonl. Usage: commons_pilot2.py OUTDIR [TARGET=1000]
Rules (deterministic): latest file version uploaded <= wall; jpeg/png; licence allow-list (current licence, 'licence-now' caveat recorded); uploader name has no 'bot'; the as-of-wall revision's editor
not in group bot and no 'bot' in name; description from {{Information}} parsed by fixed regexes, English only (en template or plain ASCII-dominant), >= 15 words, not a filename echo."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, re, json, time, html, hashlib, urllib.parse
pass
OUT = sys.argv[1]; TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
WALL = "2022-10-31T23:59:59Z"; API = "https://commons.wikimedia.org/w/api.php"; UA = "ember-data-pilot/1.0 (research dataset pilot; read-only)"
import urllib.request
def get(url, binary=False):
    for t in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read(); return b if binary else json.loads(b)
        except Exception: time.sleep(5 * (t + 1))
    return None
def api(**kw):
    time.sleep(2.0); kw.update(format="json", formatversion="2"); return get(API + "?" + urllib.parse.urlencode(kw))
LIC_OK = re.compile(r"^(public domain|pd[- ]|cc0|cc[- ]by(-sa)?[- ]\d|cc by(-sa)? \d|cc-zero)", re.I)
INFO = re.compile(r"\|\s*description\s*=\s*(.*?)(?=\n\s*\|\s*(?:date|source|author|permission|other[ _]versions|other[ _]fields|id|accession|object|credit line|references?)\s*=|\n\}\})", re.S | re.I)
LANG = re.compile(r"\{\{\s*([a-z]{2,3}(?:-[a-z]+)?)\s*(?:\|\s*(?:1\s*=)?\s*)(.*?)\}\}", re.S | re.I)
def parse_desc(wt):
    m = INFO.search(wt or "")
    if not m: return None
    d = m.group(1).strip()
    langs = LANG.findall(d)
    if langs:
        en = [t for l, t in langs if l.lower() == "en"]
        if not en: return None
        d = " ".join(en)
    for _ in range(4): d = re.sub(r"\{\{[^{}]*\}\}", " ", d)
    d = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", " ", d, flags=re.I); d = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", d); d = re.sub(r"\[\[([^\]]*)\]\]", r"\1", d)
    d = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", d); d = re.sub(r"<ref.*?</ref>|<[^>]+>|'{2,}", " ", d, flags=re.S)
    d = re.sub(r"\s+", " ", html.unescape(d)).strip()
    if not d or sum(c.isascii() and (c.isalpha() or c == " ") for c in d) / len(d) < 0.8: return None
    return d
cands = [json.loads(l) for l in open(OUT + "/cands.jsonl", encoding="utf-8")]
stat = dict(cands=len(cands), pre_drop=0, no_rev=0, bot=0, no_desc=0, short=0, kept=0, thumb_fail=0)
bots = set(json.load(open(OUT + "/botusers.json"))) if os.path.exists(OUT + "/botusers.json") else set()
rp = OUT + "/asof.jsonl"; seen = {json.loads(l)["title"]: json.loads(l) for l in open(rp, encoding="utf-8")} if os.path.exists(rp) else {}
fo = open(rp, "a", encoding="utf-8"); rows = []
def botuser(u):
    return (not u) or u in bots or "bot" in u.lower()
for c in cands:
    if len(rows) >= TARGET: break
    if len((c.get("desc") or "").split()) < 15: stat["pre_drop"] += 1; continue   # prefilter on current description length (cheap) before the as-of-wall lookup
    if not (c["mime"] in ("image/jpeg", "image/png") and c["thumb"] and c["lic"] and LIC_OK.search(c["lic"]) and c["upload_ts"] <= WALL and not botuser(c["uploader"] or "x")):
        stat["pre_drop"] += 1; continue
    r = seen.get(c["title"])
    if r is None:
        d = api(action="query", titles=c["title"], prop="revisions", rvprop="content|timestamp|user", rvslots="main", rvstart=WALL, rvdir="older", rvlimit="1")
        try: rv = d["query"]["pages"][0]["revisions"][0]; r = dict(title=c["title"], ts=rv["timestamp"], user=rv.get("user"), wt=rv["slots"]["main"]["content"])
        except Exception: r = dict(title=c["title"], ts=None, user=None, wt=None)
        fo.write(json.dumps(r, ensure_ascii=False) + "\n"); fo.flush(); seen[c["title"]] = r
    if not r["ts"]: stat["no_rev"] += 1; continue
    if botuser(r["user"]): stat["bot"] += 1; continue
    desc = parse_desc(r["wt"])
    if not desc: stat["no_desc"] += 1; continue
    nm = re.sub(r"^File:|\.[a-z]+$", "", c["title"], flags=re.I).replace("_", " ").lower()
    if len(desc.split()) < 15 or desc.lower() == nm: stat["short"] += 1; continue
    fn = OUT + "/thumbs/" + hashlib.sha1(c["title"].encode()).hexdigest()[:16] + (".jpg" if c["mime"] == "image/jpeg" else ".png")
    if not os.path.exists(fn):
        time.sleep(1.0); b = get(c["thumb"], binary=True)
        if not b: stat["thumb_fail"] += 1; continue
        open(fn, "wb").write(b)
    rows.append(dict(path=fn.replace(chr(92), "/"), caption=desc, licence=c["lic"], licence_url=c["lic_url"], licence_note="licence-now (current page); item text is the as-of-2022-10-31 revision", author=c["artist"], credit=c["credit"],
                     origin="https://commons.wikimedia.org/wiki/" + urllib.parse.quote(c["title"].replace(" ", "_")), fetch_date=time.strftime("%Y-%m-%d"), upload_ts=c["upload_ts"], desc_revision_ts=r["ts"], desc_revision_user_is_bot=False,
                     content_date_max=max(c["upload_ts"], r["ts"])[:10]))
    if len(rows) % 50 == 0: print(len(rows), json.dumps(stat), flush=True)
    if len(rows) % 500 == 0 and rows: json.dump(stat, open(OUT + "/pilot2-stats.json", "w"))
with open(OUT + "/manifest.jsonl", "w", encoding="utf-8") as f:
    for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
open(OUT + "/V2.done", "w").write(str(len(rows)))
stat["kept"] = len(rows); json.dump(stat, open(OUT + "/pilot2-stats.json", "w")); print("DONE", json.dumps(stat))

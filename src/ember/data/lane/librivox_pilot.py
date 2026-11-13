# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""LibriVox pilot (lead 81169/81222): ~1,000 sections, chapter-level audio<->Project-Gutenberg text pairs, all human, no model timestamps.
Usage: librivox_pilot.py OUTDIR [N_PROJECTS=70] [SECTIONS_PER_PROJECT=15] [TARGET_SECTIONS=1000]
Stages (resumable; every stage skips finished work): 1) PG id index of shards 0..6, 2) (removed: no date wall since 2026-11-11, lead 83389; the archive.org publicdate is recorded as content_date_max), 3) pick projects (English, PG-linked,
PG text present, spread over the id range = years), 4) per project: audiotracks API, archive.org item metadata (publicdate recorded as content_date_max, per-file sha1), mp3 download + sha1 verify,
5) pair section <-> PG text span by heading rule (number/roman/title), accept if words per audio-second in [1.5, 4.0]. Drop reasons are counted.
Outputs: pairs.jsonl (manifest for pack_media audio: path, transcript_ref, ...), text/<section>.txt, pilot-stats.json."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, re, io, json, gzip, time, subprocess, hashlib, random, urllib.parse
OUT = sys.argv[1]; NP = int(sys.argv[2]) if len(sys.argv) > 2 else 70; SPP = int(sys.argv[3]) if len(sys.argv) > 3 else 15; TARGET = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
UA = "ember-data-pilot/1.0 (research dataset pilot; read-only)"; from lane_config import LANE_ROOT as ROOT
for d in ("audio", "text", "pgtext"): os.makedirs(f"{OUT}/{d}", exist_ok=True)
def curl_json(url):
    for t in range(4):
        r = subprocess.run(["curl", "-sSL", "-A", UA, "--max-time", "120", url], capture_output=True)
        try: return json.loads(r.stdout.decode("utf-8"))
        except Exception: time.sleep(4 * (t + 1))
    return None
def sha1f(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()
# 1) PG ids in shards 0..6 (+ texts of chosen ones later)
ip = OUT + "/pgids.json"
if os.path.exists(ip): pgids = json.load(open(ip))
else:
    pgids = {}
    for s in range(7):
        with gzip.open(f"{ROOT}/pg/{s:05d}_pg.jsonl.gz", "rt", encoding="utf-8") as f:
            for l in f: pgids[json.loads(l)["id"]] = s
    json.dump(pgids, open(ip, "w"))
print("pg ids", len(pgids), flush=True)
# 2) (no post-wall catalog exclusion any more: owner 2026-11-11, lead 83389)
# 3) pick projects
cat = [json.loads(l) for l in open(f"{ROOT}/scoping/lv_all.jsonl", encoding="utf-8")]
def gid(u):
    m = re.search(r"(?:etext|ebooks)/(\d+)", u or ""); return m.group(1) if m else None
cand = [c for c in cat if c["language"] == "English" and gid(c["url_text_source"]) in pgids and 8 <= int(c["num_sections"] or 0) <= 80 and int(c["totaltimesecs"] or 0) < 6 * 3600]
cand.sort(key=lambda c: int(c["id"])); rng = random.Random(20261106)
step = max(1, len(cand) // NP); picks = [cand[i] for i in range(rng.randrange(step), len(cand), step)][:NP]
print("candidates", len(cand), "picked", len(picks), flush=True)
need = {gid(c["url_text_source"]) for c in picks}
for s in sorted({pgids[i] for i in need}):
    if all(os.path.exists(f"{OUT}/pgtext/{i}.txt") for i in need if pgids[i] == s): continue
    with gzip.open(f"{ROOT}/pg/{s:05d}_pg.jsonl.gz", "rt", encoding="utf-8") as f:
        for l in f:
            d = json.loads(l)
            if d["id"] in need and not os.path.exists(f"{OUT}/pgtext/{d['id']}.txt"): open(f"{OUT}/pgtext/{d['id']}.txt", "w", encoding="utf-8").write(d["text"])
ROM = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
def roman(s):
    s = s.lower()
    if not s or any(ch not in ROM for ch in s): return None
    t = 0
    for i, ch in enumerate(s): t += -ROM[ch] if i + 1 < len(s) and ROM[ch] < ROM[s[i + 1]] else ROM[ch]
    return t
HEAD = re.compile(r"^[ \t]*((?:chapter|letter|part|book|section|canto|act|scene|story|tale)\s+[0-9ivxlc]+\b[^\n]{0,70})$", re.I | re.M)
BARE = re.compile(r"^[ 	]*([0-9]{1,3}|[IVXLC]{1,7})\.?[ 	]*$", re.M)
def heads(txt):
    H = [(m.start(), m.group(1)) for m in HEAD.finditer(txt)]
    cand = []
    for m in BARE.finditer(txt):
        w = m.group(1); n = int(w) if w.isdigit() else roman(w)
        if n: cand.append((m.start(), n, "Chapter " + w))
    # keep the longest strictly consecutive run n, n+1, ... (rejects stray numerals)
    best = []; run = []
    for c in cand:
        if run and c[1] == run[-1][1] + 1: run.append(c)
        else:
            if len(run) > len(best): best = run
            run = [c] if c[1] == 1 else []
    if len(run) > len(best): best = run
    if len(best) >= 3: H += [(a, h) for a, n, h in best]
    return sorted(H)
def key(s):
    m = re.search(r"\b(chapter|letter|part|book|section|canto|act|scene|story|tale)\s+([0-9]+|[ivxlc]+)\b", s, re.I)
    if not m: return None
    w = m.group(2); n = int(w) if w.isdigit() else roman(w)
    return (m.group(1).lower(), n) if n else None
LINE = re.compile(r"^[ \t]*(\S[^\n]{2,98})[ \t]*$", re.M)
LEAD = re.compile(r"^(chapter|part|section|book|canto|letter|act|scene)\s+([0-9]+|[ivxlc]+)\b[ \t.:\-]*", re.I)
def tnorm(x):
    x = LEAD.sub("", x.strip()); return re.sub(r"[^a-z0-9 ]", "", x.lower()).strip()
def title_positions(pgt, secs):
    lines = [(m.start(), tnorm(m.group(1))) for m in LINE.finditer(pgt)]
    out = {}
    for q in secs:
        t = tnorm(q["title"])
        if len(t) < 4 or t in ("chapter", "introduction", "conclusion", "end", "the end"): continue
        pos = [p0 for p0, n0 in lines if n0 == t]
        if pos: out[str(q["section_number"])] = pos[-1]
    return out
stats = dict(projects=0, sections_seen=0, dl=0, dl_bytes=0, sha1_bad=0, paired=0, no_heading=0, rate_out=0, no_pg=0, api_fail=0)
pairs = []; pp = OUT + "/pairs.jsonl"
done_ids = {json.loads(l)["section_id"] for l in open(pp, encoding="utf-8")} if os.path.exists(pp) else set()
fo = open(pp, "a", encoding="utf-8")
for c in picks:
    if stats["paired"] + len(done_ids) >= TARGET or stats["dl_bytes"] > 45e9: break   # 50 GB per-source cap (lead 81232)
    pid = c["id"]; g = gid(c["url_text_source"]); stats["projects"] += 1
    pgt = open(f"{OUT}/pgtext/{g}.txt", encoding="utf-8").read(); H = heads(pgt)
    tr = curl_json(f"https://librivox.org/api/feed/audiotracks?project_id={pid}&format=json")
    secs = (tr or {}).get("sections") or []
    if not secs: stats["api_fail"] += 1; continue
    # archive.org item
    item = re.search(r"archive\.org/(?:download|details)/([^/\"]+)", json.dumps(secs[0].get("listen_url", "")) + (secs[0].get("url_iarchive", "") or ""))
    item = item.group(1) if item else None
    if not item: stats["api_fail"] += 1; continue
    meta = curl_json(f"https://archive.org/metadata/{item}"); time.sleep(1)
    if not meta or "files" not in meta: stats["api_fail"] += 1; continue
    pubdate = (meta.get("metadata", {}).get("publicdate") or "")[:10]
    sha = {f["name"]: f.get("sha1") for f in meta["files"]}
    ex = curl_json(f"https://librivox.org/api/feed/audiobooks?id={pid}&format=json&extended=1"); rd = {}
    for b0 in (ex or {}).get("books", []):
        for q in b0.get("sections", []): rd[str(q.get("section_number"))] = [r.get("display_name") for r in q.get("readers", [])]
    keyed = {}; tpos = title_positions(pgt, secs); bounds = sorted({p0 for p0, _ in H} | set(tpos.values()))
    for i, (pos, h) in enumerate(H):
        k = key(h)
        if k and k not in keyed: keyed[k] = i
    proj_rows = []
    for s in secs[:SPP]:
        stats["sections_seen"] += 1; sid = f"lv{pid}-s{s['section_number']}"
        if sid in done_ids: continue
        url = s["listen_url"]; fn = url.rsplit("/", 1)[-1]; ap = f"{OUT}/audio/{sid}.mp3"
        k = key(s["title"]); i = keyed.get(k) if k else None
        secsn = int(s.get("playtime") or 0); txt = None; why = None
        if i is None and str(s["section_number"]) in tpos:
            a = tpos[str(s["section_number"])]; nb = [x for x in bounds if x > a]; b = nb[0] if nb else len(pgt); txt = pgt[a:b].strip(); words = len(txt.split()); hd = s["title"]
            if secsn <= 0 or not (1.5 <= words / secsn <= 4.0): why = "rate_out"; txt = None
        elif i is None: why = "no_heading"
        else:
            a = H[i][0]; b = H[i + 1][0] if i + 1 < len(H) else len(pgt); txt = pgt[a:b].strip(); words = len(txt.split()); hd = H[i][1]
            if secsn <= 0 or not (1.5 <= words / secsn <= 4.0): why = "rate_out"; txt = None
        stats[why or "paired_n"] = stats.get(why or "paired_n", 0) + 1
        if not os.path.exists(ap):
            subprocess.run(["curl", "-sSL", "--retry", "4", "-A", UA, "-o", ap, url]); stats["dl"] += 1
        if sha.get(fn) and sha1f(ap) != sha[fn]:
            stats["sha1_bad"] += 1; os.replace(ap, ap + ".bad"); continue
        stats["dl_bytes"] += os.path.getsize(ap)
        if txt is not None:
            open(f"{OUT}/text/{sid}.txt", "w", encoding="utf-8").write(txt)
        row = dict(path=ap.replace(chr(92), "/"), section_id=sid, transcript_ref=(f"text/{sid}.txt" if txt is not None else None), pair_status=("paired" if txt is not None else "audio_only:" + why),
                   transcript_sha256=(hashlib.sha256(txt.encode()).hexdigest() if txt is not None else None), pg_ebook=g, pg_heading=(hd if txt is not None else None), words=(len(txt.split()) if txt is not None else None), playtime_s=secsn,
                   words_per_s=(round(len(txt.split()) / secsn, 2) if txt is not None and secsn else None),
                   licence="LibriVox: public-domain dedication by volunteer readers (wording UNVERIFIED -> PRIVATE twin); text PD(US) Project Gutenberg", origin=f"https://librivox.org/ project {pid}; archive.org/{item}",
                   archive_sha1=sha.get(fn), readers=rd.get(str(s["section_number"]), []), fetch_date=time.strftime("%Y-%m-%d"), content_date_max=(pubdate or None))
        fo.write(json.dumps(row, ensure_ascii=False) + "\n"); fo.flush(); stats["paired"] += 1
    try:   # rolling raw budget (lead 81397): upload this project's mp3 to the private raw repo, verify, delete local
        sys.path.insert(0, ROOT + "/scripts"); import raw_roll
        res = raw_roll.roll([(r_['path'], f"audio/librivox/{pid}/{os.path.basename(r_['path'])}") for r_ in proj_rows], message=f"librivox project {pid}"); stats["rolled"] = stats.get("rolled", 0) + sum(1 for x in res if x['ok'])
    except Exception as e: print('roll failed', type(e).__name__, str(e)[:150], flush=True)
    print(pid, c["title"][:30], json.dumps(stats), flush=True)
    json.dump(stats, open(OUT + "/pilot-stats.json", "w"))
json.dump(stats, open(OUT + "/pilot-stats.json", "w")); open(OUT + "/ALL.done", "w").write("1"); print("DONE", json.dumps(stats))

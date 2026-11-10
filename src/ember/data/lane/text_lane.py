# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bulk TEXT lanes (lead 81651/81661): LoC-PD-Books (CC0), peS2o and PubMed (common-pile, per-doc licence). One raw file at a time:
download -> upload raw to <raw-repo> text/<lane>/ (verify LFS sha) -> prep (date wall, licence, quality, zero-overlap gate) -> scrub vs heldout -> dedup
-> keep final-*.jsonl.zst -> delete raw -> every ~1B tokens pack into packed/<lane>-<first>-<last>/ (+prov, source manifest) for the intake tick -> training C1/C2 -> train upload.
Usage: python scripts/text_lane.py loc|pes2o|pubmed        (resumable; state in bulk/<lane>/state.json)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import sys, os, io, re, json, gzip, time, glob, subprocess, hashlib
LANE = sys.argv[1]; from lane_config import LANE_ROOT as ROOT
sys.argv = ["bulk_lane.py", LANE]
pass
import bulk_lane as B
import zstandard
WALL = "2022-10-31"; PACK_TOK_TARGET = 1.0e9
HELDOUT_EXTRA = (LANE_ROOT + "/heldout-index/wiki-heldout-2M.npy," + LANE_ROOT + "/arxiv/heldout-pdf-sent-hashes.npy")
ENV = dict(os.environ, HELDOUT_EXTRA=HELDOUT_EXTRA, PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="")
W = f"{ROOT}/textwork/{LANE}"; os.makedirs(W, exist_ok=True)
BADLIC = re.compile(r"noncommercial|non-commercial|no\s*deriv|noderiv|-nc|-nd|\bnc\b|\bnd\b|ccbync|ccbynd", re.I)
def norm_date(s):
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else (s or "")[:10]
def words_ok(t, minw=120, alpha=0.6):
    if len(t.split()) < minw: return False
    a = sum(c.isalpha() or c.isspace() for c in t[:20000]); return a / max(1, len(t[:20000])) >= alpha

def rows_loc(path):
    import pyarrow.parquet as pq
    with open(path, "rb") as fh:
        pf = pq.ParquetFile(fh)
        for b in pf.iter_batches(batch_size=64):
            for r in b.to_pylist(): yield r
def prep_loc(r, st):
    t = (r.get("text") or "").replace("\r\n", "\n").strip()
    if not words_ok(t): st["quality"] += 1; return None
    return dict(id=f"loc-{r['lccn']}-{r['filename']}", title=r.get("title"), issued=str(r.get("year")), text=t, origin="human-written (OCR of LoC-declared public-domain books)", license="CC0-1.0 / US public domain (LoC-declared)", src="storytracer/LoC-PD-Books", url=f"https://www.loc.gov/item/{r['lccn']}/")
def rows_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for l in f: yield json.loads(l)
def prep_pes2o(r, st):
    if norm_date(r.get("created")) > WALL: st["post_wall"] += 1; return None
    m = str(r.get("metadata")); lic = re.search(r"'oa_license': '([^']*)'", m); lic = lic.group(1) if lic else "unspecified-in-row (common-pile open-licence filter)"
    if BADLIC.search(lic): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="pes2o-" + str(r["id"]), title=None, issued=norm_date(r.get("created")), text=t, origin="human-written (S2ORC open-access papers)", license=lic, src="common-pile/peS2o", url=None)
def prep_pubmed(r, st):
    if norm_date(r.get("created")) > WALL: st["post_wall"] += 1; return None
    m = str(r.get("metadata")); lic = re.search(r"'license': '([^']*)'", m); lic = lic.group(1) if lic else ""
    if not lic or BADLIC.search(lic): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="pubmed-" + str(r["id"]), title=None, issued=norm_date(r.get("created")), text=t, origin="human-written (PMC open-access papers)", license=lic, src="common-pile/pubmed", url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/{r['id']}/")

# ---- common-pile wall-safe fill (lead 81977): per-doc date where the source carries one; by-source only when the collection snapshot predates the wall or is pre-1929 by construction
def _lic_ok(m, st):
    lic = re.search(r"['\"]license['\"]\s*:\s*['\"]([^'\"]*)['\"]", str(m)); lic = lic.group(1) if lic else ""
    if not lic or BADLIC.search(lic): st["bad_licence"] += 1; return None
    return lic
def prep_caselaw(r, st):    # CAP: no per-doc date in rows; collection (static.case.law) covers cases through 2020 => snapshot predates the wall (method: source-snapshot)
    lic = _lic_ok(r.get("metadata"), st)
    if not lic: return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="caselaw-" + str(r["id"]), title=None, issued=None, text=t, origin="human-written (US court opinions, Caselaw Access Project)", license=lic, src="common-pile/caselaw_access_project_filtered", url="https://static.case.law/", date_method="source-snapshot: CAP coverage ends 2020 (<= 2022-10-31); no per-doc date")
def prep_usgpo(r, st):      # per-doc publication date
    d = norm_date(r.get("date"))
    if not d or d > WALL: st["post_wall"] += 1; return None
    lic = _lic_ok(r.get("metadata"), st)
    if not lic: return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="usgpo-" + str(r["id"]), title=r.get("title"), issued=d, text=t, origin="human-written (US Government Publishing Office documents)", license=lic, src="common-pile/usgpo_filtered", url=None, date_method="per-doc date field")
def prep_hansard(r, st):    # sitting date is the tail of the id (e.g. lordswrans2016-06-15); fall back to metadata year only when <= 2021
    m = re.search(r"(\d{4}-\d{2}-\d{2})$", str(r.get("id"))); d = m.group(1) if m else None
    if d is None:
        y = re.search(r"['\"]year['\"]\s*:\s*['\"]?(\d{4})", str(r.get("metadata"))); d = f"{y.group(1)}-01-01" if y and int(y.group(1)) <= 2021 else None
    if not d or d > WALL: st["post_wall"] += 1; return None
    lic = _lic_ok(r.get("metadata"), st)
    if not lic: return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="hansard-" + str(r["id"]), title=None, issued=d, text=t, origin="human-written (UK Parliament Hansard)", license=lic, src="common-pile/uk_hansard_filtered", url=None, date_method="sitting date from id / year<=2021")
def prep_pre1929(r, st):    # pre-1929 by construction (HathiTrust public-domain pre-1929 set)
    t = (r.get("text") or "").strip()
    if not words_ok(t, 120, 0.5): st["quality"] += 1; return None
    return dict(id="pre1929-" + str(r["id"]), title=None, issued="<1929", text=t, origin="human-written (OCR of public-domain books published before 1929)", license="Public Domain (pre-1929, US)", src="common-pile/pre_1929_books_filtered", url=None, date_method="pre-1929 by construction")

# ---- Tier-1 (lead 81977 follow-up; per-doc `created` verified by range reads 2026-11-09, data/state/datewall-tier1-20261109.md)
BADLIC2 = re.compile(r"non[\s_-]?commercial|no[\s_-]?deriv|noderiv", re.I)
PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "unlicense", "cc0-1.0", "zlib", "0bsd", "bsl-1.0", "cc-by-4.0", "python-2.0", "mit-0", "bsd-3-clause-clear"}
def _created_ok(r, st):
    d = norm_date(r.get("created"))
    if not d or d > WALL: st["post_wall"] += 1; return None
    return d
def prep_stackv2_edu(r, st):
    d = _created_ok(r, st)
    if not d: return None
    ls = [str(x).lower() for x in ((r.get("metadata") or {}).get("detected_licenses") or [])]
    if not ls or any(x not in PERMISSIVE for x in ls): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if len(t) < 200 or len(t) > 400000: st["quality"] += 1; return None
    return dict(id="stackv2edu-" + str(r["id"]), title=(r.get("metadata") or {}).get("filename"), issued=d, text=t, origin="human-written (permissively licensed code/docs, Stack-Edu v2 via Common Pile)", license=",".join(ls), src="common-pile/stackv2_edu_filtered", url=None, date_method="per-doc created (blob committer date)")
def prep_github_archive(r, st):
    d = _created_ok(r, st)
    if not d: return None
    m = r.get("metadata") or {}
    if str(m.get("license_type")) != "permissive" or BADLIC2.search(str(m.get("license"))): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if len(t.split()) < 60: st["quality"] += 1; return None
    return dict(id="gharchive-" + str(r["id"]), title=None, issued=d, text=t, origin="human-written (GitHub issues/PRs of permissively licensed repos)", license=str(m.get("license")), src="common-pile/github_archive_filtered", url=m.get("url"), date_method="per-doc created")
def prep_arxiv_papers(r, st):
    d = _created_ok(r, st)
    if not d: return None
    lic = str((r.get("metadata") or {}).get("license") or "")
    if not lic or BADLIC.search(lic) or BADLIC2.search(lic): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 200, 0.4): st["quality"] += 1; return None
    return dict(id="arxiv-" + re.sub(r"v\d+$", "", str(r["id"])), title=None, issued=d, text=t, origin="human-written (arXiv papers, per-paper permissive licence)", license=lic, src="common-pile/arxiv_papers_filtered", url=(r.get("metadata") or {}).get("url"), date_method="per-doc created (submission date)")
def prep_uspto(r, st):
    d = _created_ok(r, st)
    if not d: return None
    m = r.get("metadata") or {}; pd = norm_date(m.get("publication_date"))
    if pd and pd > WALL: st["post_wall"] += 1; return None
    lic = str(m.get("license") or "")
    if not lic or BADLIC.search(lic) or BADLIC2.search(lic): st["bad_licence"] += 1; return None
    t = (r.get("text") or "").strip()
    if not words_ok(t, 150, 0.5): st["quality"] += 1; return None
    return dict(id="uspto-" + str(r["id"]), title=None, issued=d, text=t, origin="human-written (US patents, USPTO via Google Patents Public Data)", license=lic, src="common-pile/uspto_filtered", url=None, date_method="per-doc created+publication_date")
SPEC = {
 "loc": dict(repo="storytracer/LoC-PD-Books", pref="data/", suffix=".parquet", rows=rows_loc, prep=prep_loc, rawdir="sources/loc-pd-books"),
 "pes2o": dict(repo="common-pile/peS2o", pref="v0/documents", suffix=".json.gz", rows=rows_json, prep=prep_pes2o, rawdir="text/pes2o"),
 "pubmed": dict(repo="common-pile/pubmed", pref="data", suffix=".jsonl.gz", rows=rows_json, prep=prep_pubmed, rawdir="text/pubmed"),
 "caselaw": dict(repo="common-pile/caselaw_access_project_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_caselaw, rawdir="text/caselaw", rawup=False, domain="legal"),
 "usgpo": dict(repo="common-pile/usgpo_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_usgpo, rawdir="text/usgpo", rawup=False, domain="government"),
 "hansard": dict(repo="common-pile/uk_hansard_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_hansard, rawdir="text/hansard", rawup=False, domain="parliamentary"),
 "stackv2_edu": dict(repo="common-pile/stackv2_edu_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_stackv2_edu, rawdir="text/stackv2_edu", rawup=False, domain="code"),
 "github_archive": dict(repo="common-pile/github_archive_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_github_archive, rawdir="text/github_archive", rawup=False, domain="code-discussion"),
 "arxiv_papers": dict(repo="common-pile/arxiv_papers_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_arxiv_papers, rawdir="text/arxiv_papers", rawup=False, domain="science"),
 "uspto": dict(repo="common-pile/uspto_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_uspto, rawdir="text/uspto", rawup=False, domain="patents", uspto_cap=0.10),
 "pre1929": dict(repo="common-pile/pre_1929_books_filtered", pref="", suffix=".json.gz", rows=rows_json, prep=prep_pre1929, rawdir="text/pre1929", rawup=False, domain="books"),
}[LANE]

def run(cmd, log):
    B.reserve_plan.harm_wait(f"text_lane {LANE} {os.path.basename(cmd[1]) if len(cmd) > 1 else cmd}", B.log)   # lead 82070: harm-only (link priority / disk floor)
    with open(log, "w") as lf: r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=ENV)
    if r.returncode: raise RuntimeError(f"{cmd[1]} failed rc={r.returncode}; see {log}")

_dyn = {"t": 0, "v": 1.0}
def dyn_cap_mbps():
    """lead 81868: while this lane is the only one downloading, 5 MB/s; back to TEXT_DL_MBPS (1.0) whenever a push is in flight (uplink ACKs) or another lane is downloading. Re-evaluated every 5 s."""
    if time.time() - _dyn["t"] < 5: return _dyn["v"]
    low = float(os.environ.get("TEXT_DL_MBPS", "1.0")); v = low
    try:
        import psutil
        push = B.upq_bytes() > 0
        for pr in psutil.process_iter(["cmdline"]):
            c = " ".join(pr.info.get("cmdline") or [])
            if "upload_file(" in c or " upload wordingone/" in c or "hf.exe upload" in c: push = True; break
        other = False
        for ln in os.listdir(ROOT + "/bulk"):
            dl = f"{ROOT}/bulk/{ln}/dl"
            if ln != LANE and os.path.isdir(dl):
                for dp, _, fs in os.walk(dl):
                    if any(time.time() - os.path.getmtime(os.path.join(dp, f)) < 60 for f in fs): other = True; break
            if other: break
        v = low if (push or other) else float(os.environ.get("TEXT_DL_MBPS_ALONE", "5.0"))
    except Exception: pass
    try:
        import net_cap; sh = net_cap.share_mbps()      # M-NET-2 (lead 82238): global cap sum 2.5 MB/s while uploads are queued and the uplink is starved
        if sh is not None: v = min(v, sh)
    except Exception: pass
    _dyn.update(t=time.time(), v=v); return v
def throttled_get(repo, path, rev, d, size):
    """Rate-capped Range-resumable download (TEXT_DL_MBPS, default 1.0): on a shared Wi-Fi link an uncapped 5 MB/s download starves the uplink ACKs (lead 81761)."""
    import requests
    cap = float(os.environ.get("TEXT_DL_MBPS", "1.0")) * 2**20; loc = os.path.join(d, *path.split("/")); os.makedirs(os.path.dirname(loc), exist_ok=True)
    have = os.path.getsize(loc) if os.path.exists(loc) else 0
    while have < size:
        t0 = time.time(); got = 0
        with requests.get(f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{path}", stream=True, timeout=(30, 90), headers={"Range": f"bytes={have}-", "User-Agent": "ember-text-lane/1.0"}) as r:
            if r.status_code == 416: break
            r.raise_for_status()
            with open(loc, "ab") as f:
                for c in r.iter_content(1 << 20):
                    f.write(c); got += len(c); have += len(c)
                    try: import net_cap; net_cap.touch(); net_cap.account(len(c))
                    except Exception: pass
                    nc = dyn_cap_mbps() * 2**20
                    if nc != cap: cap = nc; t0 = time.time(); got = 0     # cap changed (push started/ended): restart the rate window so there is no catch-up burst or long stall
                    lag = got / cap - (time.time() - t0)
                    if lag > 0: time.sleep(lag)
    if os.path.getsize(loc) != size: raise RuntimeError(f"{path}: size {os.path.getsize(loc)} != {size}")
    return loc

def one(path, size, idx):
    d = f"{B.STG}/dl"; os.makedirs(d, exist_ok=True)
    B.upload_first(); B.wait_space(3 * size, item_bytes=size)
    rev = B.api.dataset_info(SPEC["repo"]).sha
    loc = B.retry(lambda: throttled_get(SPEC["repo"], path, rev, d, size), what=path)
    rawsha = B.sha256f(loc)
    st = dict(docs_in=0, post_wall=0, bad_licence=0, quality=0, gate_dup=0, kept=0)
    n = f"{idx:05d}"; prepf = f"{W}/prep-{n}.jsonl.zst"; cctx = zstandard.ZstdCompressor(level=6); batch = []
    import overlap_gate as G
    def flush(w):
        nonlocal batch
        if not batch: return
        dups = {k for k, why, src in G.check_docs([(G.ns_key(LANE, r["id"]), r["text"]) for r in batch], LANE)}   # the index stores ns_key ids (arXiv ids are normalised there), so look up the same key
        for r in batch:
            if G.ns_key(LANE, r["id"]) in dups: st["gate_dup"] += 1; G.log_refusal(LANE, path, r["id"], "doc-level duplicate of an indexed document"); continue
            w.write((json.dumps(r, ensure_ascii=False) + "\n").encode()); st["kept"] += 1
        batch = []
    with open(prepf, "wb") as fo, cctx.stream_writer(fo) as w:
        for r in SPEC["rows"](loc):
            st["docs_in"] += 1; rec = SPEC["prep"](r, st)
            if rec: batch.append(rec)
            if len(batch) >= 2000: flush(w)
        flush(w)
    if SPEC.get("rawup") is False:
        sz_raw = 0; os.remove(loc)     # raw stays at its public, rev-pinned source (recorded in prov raw_file/rev); saves the uplink
    else:
      sz_raw = B.push(loc, f"{SPEC['rawdir']}/{os.path.basename(path)}", dict(source=f"huggingface.co/datasets/{SPEC['repo']}@{rev} {path}", licence="see per-doc licence in rows; CC0/PD/CC-BY family", modality="text", units={"docs_in": st["docs_in"]}), keep=False)
    scr = f"{W}/scrubbed-{n}.jsonl.zst"; fin = f"{W}/final-{n}.jsonl.zst"
    run([sys.executable, ROOT + "/scripts/scrub.py", prepf, scr], f"{ROOT}/logs/{LANE}-{n}-scrub.log")
    run([sys.executable, ROOT + "/scripts/dedup.py", scr, fin], f"{ROOT}/logs/{LANE}-{n}-dedup.log")
    for p in (prepf, scr): os.remove(p)
    fs = os.path.getsize(fin)
    B.state.setdefault("finals", {})[n] = dict(path=fin, raw_sha256=rawsha, raw_file=os.path.basename(path), rev=rev, stats=st, bytes=fs, packed=False)
    log = json.dumps(dict(file=path, **st)); B.log("prepared", log); return sz_raw

def maybe_pack(force=False):
    fin = B.state.get("finals", {}); todo = sorted(k for k, v in fin.items() if not v["packed"])
    # approx tokens = utf8 text bytes / 4 ; final files are zstd-compressed (~3x) so use kept docs * avg unknown -> use compressed bytes * 3 / 4
    est = sum(fin[k]["bytes"] * 3 / 4 for k in todo)
    if not todo or (est < PACK_TOK_TARGET and not force): return
    name = f"{LANE}-{todo[0]}-{todo[-1]}"
    prov = f"{ROOT}/packed/{name}.prov.jsonl"; os.makedirs(f"{ROOT}/packed", exist_ok=True)
    with open(prov, "w", encoding="utf-8") as pf:
        for k in todo:
            v = fin[k]
            with open(v["path"], "rb") as f:
                for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8"):
                    r = json.loads(line); pf.write(json.dumps(dict(doc_id=r["id"], raw_sha256=v["raw_sha256"], raw_file=v["raw_file"], fetched_ts=time.strftime("%Y-%m-%d"), license_url=r.get("license"))) + "\n")
    run([sys.executable, ROOT + "/scripts/pack.py", ROOT + "/packed", name] + [fin[k]["path"] for k in todo], f"{ROOT}/logs/pack-{name}.log")
    run([sys.executable, ROOT + "/scripts/source_manifest.py", f"{ROOT}/packed/{name}", prov, f"huggingface.co/datasets/{SPEC['repo']} (see raw_file per row; " + ("public rev-pinned source, no raw re-host)" if SPEC.get("rawup") is False else f"raw copy in {HF_RAW_REPO} {SPEC['rawdir']}/)"), "per-doc licence (see rows)", time.strftime("%Y-%m-%d"), WALL, "text"], f"{ROOT}/logs/srcman-{name}.log")
    json.dump(dict(domain=SPEC.get("domain", "mixed"), wall=WALL, source_repo=SPEC["repo"], date_method="per-doc date where present; else source-snapshot/pre-1929 (see prep fn)", uspto_cap=SPEC.get("uspto_cap", "n/a")), open(f"{ROOT}/packed/{name}/domain.json", "w"))   # lead 81977: domain tag per pack so training can weight the mix
    for k in todo: fin[k]["packed"] = name
    import overlap_gate as G; G.build_docs([name])   # later shards must not duplicate this pack
    B.save(); B.log("PACKED", name, f"{len(todo)} finals")

if __name__ == "__main__":
    files = sorted((t.path, t.size) for t in B.api.list_repo_tree(SPEC["repo"], repo_type="dataset", path_in_repo=SPEC["pref"].rstrip("/")) if hasattr(t, "size") and t.path.endswith(SPEC["suffix"]))
    B.log(f"{LANE}: {len(files)} raw files"); lim = B.LIMIT
    for i, (p, s) in enumerate(files):
        if p in B.state["done"]: continue
        if lim and i >= lim: break
        try:
            r = one(p, s, i); B.state["done"][p] = {"bytes": r, "ts": time.time()}; B.save(); maybe_pack()
            age = time.time() - B.prog["started"]; B.log(f"done {p}; lane {B.prog['bytes_uploaded']/2**30:.1f} GiB raw up, {B.prog['bytes_uploaded']/2**30/max(age/86400,1e-6):.1f} GiB/day")
        except SystemExit as e: B.log(str(e)); os._exit(2)
        except Exception as e: B.log(f"FAILED {p}: {type(e).__name__} {str(e)[:300]}")
    maybe_pack(force=True)
    B.log("LANE DONE", LANE)
    if not B.LIMIT: open(f"{B.STG}/ALL.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

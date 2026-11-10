# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""One-command inventory of the three HF dataset repos (lead 81645). Reads ONLY from HF (file tree + LFS sha256 + manifests); local staging does not count.
Usage: python scripts/hf_inventory.py [--out census/census-latest.json] [--quiet]
Per repo / per modality (text tokens+docs, image count, audio hours, video) / raw vs train-ready, plus unique-content counts next to totals.
Unique key = LFS sha256 of the file (byte-identical content across ALL repos). Doc-level overlap is the zero-overlap gate's job (scripts/overlap_gate.py).
Checkpoints, software bundles and run receipts are NOT data: counted separately under 'excluded'."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, LANE_ROOT
import sys, os, json, time, collections, argparse
from huggingface_hub import HfApi, hf_hub_download

REPOS = {"public": "wordingone/ember-corpus", "raw": ("wordingone/" + HF_RAW_REPO), "train": ("wordingone/" + HF_TRAIN_REPO)}
IMG = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp")
AUD = (".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a")
VID = (".mp4", ".mkv", ".webm", ".avi", ".mov")
MP3_BPS = 64000                       # LibriVox standard CBR; hours from bytes are an ESTIMATE until a duration manifest is on HF
LIBRISPEECH_HOURS = {"dev-clean": 5.4, "dev-other": 5.3, "test-clean": 5.4, "test-other": 5.1}   # official corpus durations (openslr 12)

api = HfApi()
SIZES = {}                                   # (repo, path) -> size, filled by tree(); keys the manifest cache so a changed manifest is re-read
CACHE = (LANE_ROOT + "/census/json-cache"); os.makedirs(CACHE, exist_ok=True)

def tree(repo):
    out = []
    for t in api.list_repo_tree(repo, repo_type="dataset", recursive=True, expand=True):
        if not hasattr(t, "size"): continue
        sha = None
        lfs = getattr(t, "lfs", None)
        if lfs is not None: sha = lfs.sha256 if hasattr(lfs, "sha256") else lfs.get("sha256")
        out.append((t.path, t.size, sha)); SIZES[(repo, t.path)] = t.size
    return out

def get_json(repo, path, jsonl=False):
    import hashlib
    ck = CACHE + "/" + hashlib.sha1(f"{repo}|{path}|{SIZES.get((repo, path))}".encode()).hexdigest()    # manifests are write-once on HF (uploads never overwrite); size in the key catches an appended jsonl
    if SIZES.get((repo, path)) is not None and os.path.exists(ck): p = ck
    else:
        p = hf_hub_download(repo, path, repo_type="dataset")
        if SIZES.get((repo, path)) is not None:
            import shutil; shutil.copyfile(p, ck + ".tmp"); os.replace(ck + ".tmp", ck)
    txt = open(p, encoding="utf-8-sig", errors="replace").read()
    if jsonl: return [json.loads(l) for l in txt.splitlines() if l.strip()]
    return json.loads(txt)

def media_counts(repo, media, files):
    import hashlib, concurrent.futures as cf
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem
    fs = HfFileSystem(); out = collections.defaultdict(lambda: {"rows": 0, "hours": 0.0})
    def one(it):
        _, path, size, tag = it
        ck = CACHE + "/media-" + hashlib.sha1(f"{repo}|{path}|{size}".encode()).hexdigest()
        if os.path.exists(ck): return tag, json.load(open(ck))
        if path.endswith(".parquet"):
            f = pq.ParquetFile(fs.open(f"datasets/{repo}/{path}", "rb")); v = {"rows": f.metadata.num_rows, "hours": 0.0}
            if tag == "mls-eng": v["hours"] = sum(x for x in f.read(columns=["audio_duration"]).column(0).to_pylist() if x) / 3600
        else: v = {"rows": 0, "hours": 0.0}
        json.dump(v, open(ck + ".tmp", "w")); os.replace(ck + ".tmp", ck); return tag, v
    with cf.ThreadPoolExecutor(int(os.environ.get("CENSUS_THREADS","8"))) as ex:
        for tag, v in ex.map(one, media): out[tag]["rows"] += v["rows"]; out[tag]["hours"] += v["hours"]
    if repo.endswith("ember-corpus"):         # PD12M: one manifest line per image
        mans = [(p, sz) for p, sz, _ in files if p.startswith("sources/pd12m/") and p.endswith(".manifest.jsonl")]
        def lines(a):
            p, sz = a; ck = CACHE + "/media-" + hashlib.sha1(f"{repo}|{p}|{sz}".encode()).hexdigest()
            if os.path.exists(ck): return json.load(open(ck))["rows"]
            n = sum(1 for l in open(hf_hub_download(repo, p, repo_type="dataset"), encoding="utf-8") if l.strip()); json.dump({"rows": n}, open(ck + ".tmp", "w")); os.replace(ck + ".tmp", ck); return n
        if mans:
            with cf.ThreadPoolExecutor(int(os.environ.get("CENSUS_THREADS","8"))) as ex: out["pd12m"]["rows"] += sum(ex.map(lines, mans))
    return out

def classify(key, path):
    """-> (stage, modality, tag). stage in raw|train_ready|excluded|heldout. tag = free text."""
    p = path
    if key == "public":
        if p.startswith("checkpoints/"): return "excluded", "checkpoint", "checkpoints"
        if p.startswith(("avir-cli/", "ember-corpus-v1-lane-285/", "catalog/", "staging/")) or p in ("README.md", "LICENSE", ".gitattributes"): return "excluded", "software/docs/catalog", p.split("/")[0]
        if p.startswith("tokens/"):
            return ("train_ready", "text", "tokens-shard") if p.endswith(".bin") else ("excluded", "ledger", "tokens-ledger")
        if p.startswith(("objects/heldout/", "acquisition/heldout/")): return "heldout", "text", "heldout (NOT training)"
        if p.startswith(("objects/", "acquisition/")): return "raw", "text", p.split("/")[0]
        if p.startswith("sources/librispeech-seed/"): return ("raw", "audio", "librispeech") if p.endswith(".tar.gz") else ("excluded", "manifest", "manifest")
        if p.startswith("sources/wikimedia-commons-pd/"): return ("raw", "image", "commons-pd") if p.lower().endswith(IMG) else ("excluded", "manifest", "manifest")
        if p.startswith("sources/pd12m/") and p.endswith(".tar"): return "raw", "image", "pd12m"      # fix 2026-11-09: was bucketed as raw text
        if p.startswith("sources/"): return ("excluded", "manifest", "manifest") if p.endswith(("manifest.jsonl", ".md", ".json")) else ("raw", "text", p.split("/")[1])
        return "excluded", "other", p.split("/")[0]
    if key == "raw":
        if p.startswith("image/") and p.endswith(".parquet"): return "raw", "image", "commoncatalog-cc-by"      # fix 2026-11-09: was 'excluded other'
        if p.startswith("audio/mls-eng/") and p.endswith(".parquet"): return "raw", "audio", "mls-eng"
        if p.startswith("audio/"): return "raw", "audio", "librivox"
        if p.startswith("text/"):
            return ("excluded", "manifest", "manifest") if p.endswith((".json", ".jsonl", ".tsv", ".txt", ".md")) else ("raw", "text", p.split("/")[1])
        return "excluded", "other", p
    if key == "train":
        if p.startswith("text/") and "/shards/" in p: return "train_ready", "text", "shard"
        if p.startswith("text/") and "/objects/" in p: return "train_ready", "text", "pack-object (source text of the shards)"
        return "excluded", "manifest", "manifest"
    return "excluded", "other", p

def uniq_stats(rows):
    """rows = [(content_sha, size, repo)]. Unique = distinct content sha across all repos; overlap = items - unique (must be 0)."""
    uniq = {}
    for s, sz, rp in rows: uniq.setdefault(s, sz)
    return {"items": len(rows), "unique_items": len(uniq), "overlap_items": len(rows) - len(uniq), "total_bytes": sum(sz for _, sz, _ in rows), "unique_bytes": sum(uniq.values()),
            "overlap_bytes": sum(sz for _, sz, _ in rows) - sum(uniq.values()), "granularity": "file-level LFS sha256, across all 3 repos (byte-identical); doc/image/audio-level index = overlap_gate.py",
            "nolfs_items": sum(1 for s, _, _ in rows if s.startswith("nolfs:"))}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=(LANE_ROOT + "/census/census-latest.json")); ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "HF only (tree + LFS sha256 + manifests); local staging not counted", "repos": {}, "totals": {}, "unique": {}, "notes": []}
    keyed = collections.defaultdict(list)     # (stage, modality) -> [(sha, size, repo)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex: TREES = dict(zip(REPOS, ex.map(tree, REPOS.values())))      # the three listings run concurrently
    for key, repo in REPOS.items():
        files = TREES[key]
        excl = {}     # pack -> article_exclusion row
        sup = {}      # original hf prefix -> declaration row (supersession*.jsonl in the train repo, lead 81767)
        if key == "train":
            import re
            for p_, _, _ in files:
                if re.fullmatch(r"supersession(-\d+)?\.jsonl", p_):
                    for row in get_json(repo, p_, jsonl=True):
                        if row.get("kind") == "article_exclusion": excl[row["pack"]] = row      # lead 81829: H19-overlap articles, subtracted from the unique count
                        else: sup[row["original_hf_prefix"]] = row
        sup_pref = tuple(sup)
        info = api.dataset_info(repo, expand=["usedStorage", "private"])
        r = {"repo": repo, "private": bool(info.private), "used_storage_bytes": info.used_storage, "files": len(files),
             "tree_bytes": sum(s for _, s, _ in files), "stages": {}, "excluded": collections.Counter(), "excluded_bytes": collections.Counter()}
        st = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
        media = []
        for path, size, sha in files:
            stage, mod, tag = classify(key, path)
            if sup_pref and path.startswith(sup_pref) and stage == "train_ready":
                c = st["superseded"][mod]; c["files"] += 1; c["bytes"] += size; continue      # declared pair: counted on the superseded line, not as overlap
            if stage == "excluded":
                r["excluded"][tag] += 1; r["excluded_bytes"][tag] += size; continue
            c = st[stage][mod]; c["files"] += 1; c["bytes"] += size
            if mod == "image" and not path.endswith((".parquet", ".tar")): c["images"] += 1
            if mod == "audio":
                if path.endswith(".mp3"): c["hours_est"] += size * 8 / MP3_BPS / 3600
            if stage == "raw" and path.endswith((".parquet", ".tar")) and mod in ("image", "audio"): media.append((repo, path, size, tag))
            if mod == "video": c["videos"] += 1
            keyed[(stage, mod)].append((sha or f"nolfs:{key}:{path}:{size}", size, key))
        if media or key == "public":     # exact image / audio counts from HF itself: parquet footers (rows), MLS audio_duration column, PD12M manifest lines; cached by (path, size)
            m = media_counts(repo, media, files)
            for kind, v in m.items():
                if kind == "mls-eng": c = st["raw"]["audio"]; c["segments"] += v["rows"]; c["hours"] += v["hours"]
                else: c = st["raw"]["image"]; c["images"] += v["rows"]
        # exact text counts for train-ready (manifests on HF)
        if key == "train":
            docs = toks = shards = 0; packs = []
            have_intake = {p.rsplit("/", 1)[0] for p, _, _ in files if p.endswith("/intake.json")}
            sdocs = stoks = sshards = 0; spacks = []
            edocs = etoks = 0; epacks = []
            for path, size, sha in files:
                if sup_pref and path.startswith(sup_pref) and path.endswith("/intake.json"):
                    d = get_json(repo, path); sdocs += d["docs"]; stoks += d["content_tokens"]; sshards += d["shards"]; spacks.append(d["name"]); continue
                if sup_pref and path.startswith(sup_pref): continue
                if path.startswith("text/") and path.endswith("/intake.json"):
                    d = get_json(repo, path); docs += d["docs"]; toks += d["content_tokens"]; shards += d["shards"]; packs.append((d["name"], d["docs"], d["content_tokens"], d["shards"]))
                    if d["name"] in excl: edocs += excl[d["name"]]["articles"]; etoks += excl[d["name"]]["tokens"]; epacks.append(d["name"])
                elif path.startswith("text/") and path.endswith("/receipt.json") and path.rsplit("/", 1)[0] not in have_intake:   # packs uploaded without intake.json (arXiv): use the receipt
                    d = get_json(repo, path); docs += d["docs"]; toks += d["content_tokens"]; shards += d["shards"]; packs.append((d["name"], d["docs"], d["content_tokens"], d["shards"]))
            c = st["train_ready"]["text"]; c["docs"] = docs - edocs; c["tokens"] = toks - etoks; c["shards_in_manifests"] = shards
            if excl: c["tokens_before_h19_exclusion"] = toks; c["docs_before_h19_exclusion"] = docs; c["h19_excluded_docs"] = edocs; c["h19_excluded_tokens"] = etoks; r["h19_excluded_packs"] = sorted(epacks)
            r["packs"] = [dict(name=n, docs=dd, tokens=tt, shards=ss) for n, dd, tt, ss in sorted(packs)]
            if sup:
                c = st["superseded"]["text"]; c["docs"] = sdocs; c["tokens"] = stoks; c["shards_in_manifests"] = sshards; c["packs"] = len(spacks)
                r["superseded_packs"] = sorted(spacks)
        if key == "public":
            led = [p for p, _, _ in files if p.endswith("shard-ledger-s4194304.jsonl")]
            toks = shards = 0
            for lp in led:
                for row in get_json(repo, lp, jsonl=True): toks += row["n_tokens"]; shards += 1
            c = st["train_ready"]["text"]; c["tokens"] = toks; c["shards_in_manifests"] = shards
            c = st["raw"]["audio"]
            c["hours_official"] = sum(h for k, h in LIBRISPEECH_HOURS.items() if any(p.endswith(f"librispeech-seed/{k}.tar.gz") for p, _, _ in files))
        if key == "raw":
            ab = [p for p, _, _ in files if p.endswith("batch-report.json")]
            if ab:
                br = get_json(repo, ab[0]); st["raw"]["text"]["arxiv_papers"] = br.get("final", {}).get("docs", 0)
        r["stages"] = {s: {m: dict(v) for m, v in mods.items()} for s, mods in st.items()}
        r["excluded"] = dict(r["excluded"]); r["excluded_bytes"] = dict(r["excluded_bytes"])
        res["repos"][key] = r
    # totals per stage/modality and uniqueness (byte-identical LFS content across all three repos)
    for (stage, mod), rows in sorted(keyed.items()):
        res["unique"][f"{stage}/{mod}"] = uniq_stats(rows)
    for stage in ("raw", "train_ready", "heldout", "superseded"):
        for mod in ("text", "image", "audio", "video"):
            tot = collections.Counter()
            for r in res["repos"].values():
                for k, v in r["stages"].get(stage, {}).get(mod, {}).items(): tot[k] += v
            if tot: res["totals"][f"{stage}/{mod}"] = dict(tot)
    res["totals"].setdefault("raw/video", {"videos": 0}); res["totals"].setdefault("train_ready/video", {"videos": 0})
    res["notes"] = ["audio hours for mp3 are bytes*8/64kbps estimates (LibriVox CBR) until a duration manifest is uploaded; LibriSpeech hours are the official corpus durations",
                    "raw and train_ready stages are reported separately and are not unique against each other by design (train_ready is derived from raw)",
                    "unique/overlap here is byte-identical file content; same-document-different-bytes overlap (e.g. PG text in two repos) is measured by the zero-overlap gate",
                    "heldout material is listed under its own stage and is not training data"]
    res["elapsed_s"] = round(time.time() - t0, 1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"; json.dump(res, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, a.out)
    if not a.quiet:
        for k, r in res["repos"].items(): print(f"{k:6s} {r['repo']:34s} used {r['used_storage_bytes']/2**30:7.1f} GiB  tree {r['tree_bytes']/2**30:7.1f} GiB  files {r['files']}  excluded " + ", ".join(f"{t}={b/2**30:.1f}GiB" for t, b in r["excluded_bytes"].items() if b > 2**28))
        for k, v in res["totals"].items(): print(f"  {k:20s}", {x: (round(y, 2) if isinstance(y, float) else y) for x, y in v.items()})
        for k, v in res["unique"].items(): print(f"  unique {k:18s} items {v['items']} unique {v['unique_items']} overlap {v['overlap_items']} ({v['overlap_bytes']/2**30:.2f} GiB)")
    print(f"WROTE {a.out} in {res['elapsed_s']}s")

if __name__ == "__main__":
    main()

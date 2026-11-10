# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bulk HF -> private raw repo lanes with the rolling cycle: download -> transform -> sha256 -> upload -> verify LFS sha256 -> delete local (lead 81651).
Usage: python scripts/bulk_lane.py <lane>      lanes: mls | ccby | pd12m
Resumable: bulk/<lane>/state.json holds finished items; a receipt row per item goes to logs/bulk-<lane>-receipts.jsonl.
Rules enforced here: dest is the PRIVATE raw repo only; never overwrites (remote file present => size must match, else STOP);
B: free floor 301 GiB (waits, never goes under); no model-derived fields uploaded (ccby blip2_caption and pd12m caption are DROPPED and recorded);
zero-overlap gate (overlap_gate.check_hashes) refuses byte-identical duplicates of anything already in the three repos' index when the index exists.
CPU: I/O bound; thread counts per lane below; the tick spawn pins CPUs 16-23 and BelowNormal."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, json, time, hashlib, shutil, threading, traceback, io, tarfile, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from huggingface_hub import HfApi
import net_cap as _nc      # M-NET-2 (lead 82238): every lane download goes through the shared, cap-aware downloader (unthrottled while the cap is off)
def hf_hub_download(repo, path, repo_type="dataset", revision=None, local_dir=".", **kw): return _nc.download(repo, path, rev=revision, local_dir=local_dir, repo_type=repo_type)

from lane_config import LANE_ROOT as ROOT; FLOOR_GIB = None   # single source: reserve_plan.floor_gib() (lead 82070); no literal here
LANE = sys.argv[1]; LIMIT = int(os.environ.get('LANE_LIMIT', '0'))   # smoke test: process only this many items
PUBLIC_LANES = {"pd12m", "loc"}
RAW = "wordingone/ember-corpus" if LANE in PUBLIC_LANES else ("wordingone/" + HF_RAW_REPO)
PRIV_CAP_BYTES = 1e12; PRIV_STOP = 0.85   # Pro private quota ~1 TB shared by raw+train; at 85% stop and let the tick mail lead
STG = f"{ROOT}/bulk/{LANE}"; os.makedirs(STG, exist_ok=True)
STATE = f"{STG}/state.json"; PROG = f"{STG}/progress.json"; RCPT = f"{ROOT}/logs/bulk-{LANE}-receipts.jsonl"
api = HfApi(); lock = threading.Lock()
state = json.load(open(STATE)) if os.path.exists(STATE) else {"done": {}}
prog = json.load(open(PROG)) if os.path.exists(PROG) else {"lane": LANE, "started": time.time(), "bytes_uploaded": 0, "items": 0, "units": {}, "events": []}
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def save():
    with lock:
        json.dump(state, open(STATE + ".tmp", "w")); os.replace(STATE + ".tmp", STATE)
        json.dump(prog, open(PROG + ".tmp", "w")); os.replace(PROG + ".tmp", PROG)
def b_free_gib(): return shutil.disk_usage("B:/").free / 2**30
pass; import reserve_plan
LEASE = ROOT + "/loops/floor-borrow.json"
def lease_for(lane):
    """lead 81866: ONE lane may stage down to a 295 GiB floor until H44's window closes (lease 'until'); items <= max_item_gib. Expiry restores 301 automatically (time-based, no manual step)."""
    try:
        L = json.load(open(LEASE))
        if L["lane"] == lane and time.time() < L["until_epoch"]: return L
    except Exception: pass
    return None
def wait_space(need_bytes, item_bytes=None):
    while True:
        L = lease_for(LANE)
        if L and item_bytes is not None and item_bytes <= L["max_item_gib"] * 2**30:
            if b_free_gib() - (item_bytes * 1.5) / 2**30 >= max(L["floor"], reserve_plan.floor_gib()): return        # borrower: raw item + ~0.5x prep working set stays >= 295
            log(f"waiting for space (lease floor {L['floor']}): B free {b_free_gib():.1f} GiB, item {item_bytes/2**30:.1f} GiB x1.5")
        elif b_free_gib() - need_bytes / 2**30 >= reserve_plan.floor_gib() + 1: return      # reserve planner (lead 81875): the next chain's declared need is reserved first
        else: log(f"waiting for space: B free {b_free_gib():.1f} GiB, need {need_bytes/2**30:.1f} + floor {reserve_plan.floor_gib():.0f} ({reserve_plan.describe()})")
        time.sleep(120)
def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""): h.update(b)
    return h.hexdigest()
def retry(fn, tries=5, what=""):
    for i in range(tries):
        try: return fn()
        except Exception as e:
            log(f"retry {i+1}/{tries} {what}: {type(e).__name__} {str(e)[:150]}"); time.sleep(min(60, 5 * 2 ** i))
    raise RuntimeError(f"gave up: {what}")
try:
    sys.path.insert(0, ROOT + "/scripts"); import overlap_gate
except Exception: overlap_gate = None
def remote_info(rp):
    r = api.get_paths_info(RAW, [rp], repo_type="dataset", expand=True)
    return r[0] if r else None
_q = {"t": 0, "used": 0}
def private_used():
    if time.time() - _q["t"] > 300:
        _q["used"] = sum(api.dataset_info(r, expand=["usedStorage"]).used_storage for r in (("wordingone/" + HF_RAW_REPO), ("wordingone/" + HF_TRAIN_REPO))); _q["t"] = time.time()
    return _q["used"]
def quota_guard(add):
    """lead 81851: shared hard guard (hf_cap.py): hold (wait + mail lead) instead of pushing past 900 GB total private; never exits, never deletes."""
    if RAW.endswith("-private"):
        import hf_cap
        while not hf_cap.check(add, f"lane {LANE}", RAW): time.sleep(300)
UPQ_PATH = ROOT + "/upq"; UPQ_MAX_GIB = float(os.environ.get("UPQ_MAX_GIB", "4")); _uq = {"n": 0}
def upq_bytes():
    tot = 0
    try:
        for e in os.scandir(UPQ_PATH):
            if e.name.endswith(".dat"): tot += e.stat().st_size
    except OSError: pass
    return tot
def upload_first():
    """Wi-Fi half-duplex contention (measured: up 2.05 MB/s when down ~1 MB/s, up 0.06 MB/s when down ~3 MB/s): do not START a download while the shared uploader has queued data.
    Skips the wait if the uploader looks dead (no heartbeat for 3 min) so a lane can never deadlock."""
    import psutil
    def _pack_upload_running():      # tick-started `hf upload` pack pushes (train-ready packs) are uploads too: they get the Wi-Fi first
        for pr in psutil.process_iter(["cmdline"]):
            c = pr.info.get("cmdline") or []
            if len(c) >= 2 and os.path.basename(c[0]).lower().startswith("hf") and c[1] == "upload": return True
        return False
    n = 0
    while upq_bytes() > 0 or _pack_upload_running():
        try: alive = time.time() - os.path.getmtime(UPQ_PATH + "/heartbeat") < 180
        except OSError: alive = False
        if (upq_bytes() > 0 and not alive) or n > 270: return    # never hold a lane more than 45 min per download
        if n % 12 == 0: log(f"upload_first: {upq_bytes()/2**20:.0f} MiB queued / pack upload running; holding the next download so the uplink gets the Wi-Fi")
        n += 1; time.sleep(10)
def _enqueue(local, rp, meta, keep, size, sha):
    """hand a verified-ready shard to the shared uploader: move it (same volume) into upq/ with a job file; bounded by queue GiB and by B: headroom, never by count."""
    os.makedirs(UPQ_PATH, exist_ok=True)
    while upq_bytes() > 0 and upq_bytes() + size > UPQ_MAX_GIB * 2**30:
        log(f"upq full ({upq_bytes()/2**30:.1f} GiB queued); waiting for the uploader"); time.sleep(60)
    _uq["n"] += 1; uid = f"{time.strftime('%Y%m%d%H%M%S')}-{LANE}-{os.getpid()}-{_uq['n']:05d}"
    dat = f"{UPQ_PATH}/{uid}.dat"
    if keep: shutil.copy2(local, dat)
    else: os.replace(local, dat)
    job = dict(lane=LANE, repo=RAW, rp=rp, size=size, sha=sha, meta=meta, rcpt=RCPT, queued=time.time())
    json.dump(job, open(f"{UPQ_PATH}/{uid}.job.tmp", "w")); os.replace(f"{UPQ_PATH}/{uid}.job.tmp", f"{UPQ_PATH}/{uid}.job.json")
    with lock:
        prog["bytes_uploaded"] += size; prog["items"] += 1     # = handed to the uploader; true uploaded bytes are in upq/stats.json
        for k, v in meta.get("units", {}).items(): prog["units"][k] = prog["units"].get(k, 0) + v
        prog["events"].append([time.time(), size]); prog["events"] = prog["events"][-5000:]
    return size
def push(local, rp, meta, keep=False):
    """upload one file, verify LFS sha256 + size against local, record receipt, delete local. Returns bytes."""
    size = os.path.getsize(local); quota_guard(size); sha = sha256f(local)
    if RAW == "wordingone/ember-corpus":   # lead 81676: secret-scan gate on EVERY public upload (value-free refusal log: logs/secret-refusals.jsonl)
        import secret_scan
        if not secret_scan.gate(local, LANE, rp): raise RuntimeError(f"SECRET GATE REFUSED {rp}: credential-shaped spans found (counts in logs/secret-refusals.jsonl); local kept, not uploaded")
    if overlap_gate is not None:
        dup = overlap_gate.check_hashes([sha])
        if dup: log("REFUSED duplicate content", rp, dup); overlap_gate.log_refusal(LANE, rp, sha, dup); (None if keep else os.remove(local)); return 0
    ri = remote_info(rp)
    if ri is None and os.environ.get("UPQ", "1") == "1": return _enqueue(local, rp, meta, keep, size, sha)   # decoupled upload (lead 81769): the shared upload_worker.py does the push
    if ri is not None:
        if ri.size != size: raise SystemExit(f"STOP: remote {rp} exists with different size {ri.size} != {size}")
    else:
        # heartbeat while the upload is in flight: a healthy slow upload writes nothing to disk, so the tick watchdog (_stalled) used to kill it after 40 min (lead 81763).
        # Touched every 60 s until the file could not plausibly finish even at 50 KB/s (+10 min), so a truly wedged upload is still caught.
        _hb = f"{ROOT}/bulk/{LANE}/upload.heartbeat"; _stop = threading.Event(); _dl = time.time() + size / 50000 + 600
        def _beat():
            while not _stop.is_set() and time.time() < _dl:
                try: open(_hb, "a").close(); os.utime(_hb, None)
                except OSError: pass
                _stop.wait(60)
        threading.Thread(target=_beat, daemon=True).start()
        import upload_refuse; upload_refuse.check(local)      # lead 82100
        try: retry(lambda: hf_push.upload_file(api, path_or_fileobj=local, path_in_repo=rp, repo_id=RAW, repo_type="dataset", commit_message=f"{LANE}: {os.path.basename(rp)} (data bulk lane, lead 81651)"), what=rp)
        finally: _stop.set()
        ri = remote_info(rp)
    rsha = (ri.lfs.sha256 if hasattr(ri.lfs, "sha256") else ri.lfs["sha256"]) if ri is not None and ri.lfs is not None else None
    how = "LFS sha256 == local"
    if rsha is None and ri is not None and ri.lfs is None and ri.blob_id:   # small non-LFS file: verify the git blob sha1 (hash of 'blob <size>\0'+bytes)
        h = hashlib.sha1(b"blob %d\0" % size)
        with open(local, "rb") as _f:
            for _c in iter(lambda: _f.read(1 << 20), b""): h.update(_c)
        if h.hexdigest() == ri.blob_id: rsha = sha; how = "git blob sha1 == local (non-LFS small file)"
    if rsha != sha or ri.size != size: raise RuntimeError(f"VERIFY FAILED {rp}: local {sha} remote {rsha}; local kept")
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), lane=LANE, hf_path=rp, bytes=size, sha256=sha, hf_repo=RAW, verified=how, **meta)
    with lock:
        with open(RCPT, "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\n")
        prog["bytes_uploaded"] += size; prog["items"] += 1
        for k, v in meta.get("units", {}).items(): prog["units"][k] = prog["units"].get(k, 0) + v
        prog["events"].append([time.time(), size]); prog["events"] = prog["events"][-5000:]
    if not keep: os.remove(local)
    return size

def run_pool(items, fn, workers):
    todo = [i for i in items if i[0] not in state["done"]]
    if LIMIT: todo = todo[:LIMIT]
    log(f"{LANE}: {len(items)} items, {len(items)-len(todo)} done, {len(todo)} to do, {workers} workers")
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, *i): i for i in todo}
        for fu in as_completed(futs):
            i = futs[fu]
            try:
                r = fu.result(); state["done"][i[0]] = {"bytes": r, "ts": time.time()}; save()
                age = time.time() - prog["started"]; log(f"done {i[0]} ({r/2**20:.0f} MiB); lane total {prog['bytes_uploaded']/2**30:.1f} GiB, {prog['bytes_uploaded']/2**30/max(age/86400,1e-6):.1f} GiB/day")
            except SystemExit as e: log(str(e)); os._exit(2)
            except Exception as e: log(f"FAILED {i[0]}: {type(e).__name__} {str(e)[:300]}")

# ---------------- lane: MLS English (CC-BY-4.0; LibriVox recordings) -- raw parquet mirrored as-is ----------------
def lane_mls():
    SRC = "parler-tts/mls_eng"; rev = api.dataset_info(SRC).sha
    files = sorted(t.path for t in api.list_repo_tree(SRC, repo_type="dataset", path_in_repo="data") if hasattr(t, "size") and t.path.endswith(".parquet"))
    import pyarrow.parquet as pq
    def one(path):
        d = f"{STG}/dl"; os.makedirs(d, exist_ok=True)
        sz = 600 * 2**20   # files are ~0.25-0.6 GiB
        upload_first(); wait_space(2 * sz)
        loc = retry(lambda: hf_hub_download(SRC, path, repo_type="dataset", revision=rev, local_dir=d), what=path)
        hours = 0.0; keys = set(); books = set()
        with open(loc, "rb") as fh:                      # explicit handle so Windows lets us delete the file afterwards
            pf = pq.ParquetFile(fh); rows = pf.metadata.num_rows
            for b in pf.iter_batches(batch_size=2048, columns=["audio_duration", "original_path", "book_id"]):
                dd = b.to_pydict(); hours += sum(dd["audio_duration"]) / 3600; keys.update(dd["original_path"]); books.update(dd["book_id"])
        meta = dict(source=f"huggingface.co/datasets/{SRC}@{rev}", licence="CC-BY-4.0", modality="audio", units={"audio_hours": hours, "segments": rows}, mp3_sources=len(keys), book_ids=len(books))
        with lock, open(f"{ROOT}/logs/bulk-mls-keys.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps(dict(file=path, original_paths=sorted(keys), book_ids=sorted(books))) + "\n")
        return push(loc, f"audio/mls-eng/{path}", meta)
    run_pool([(p,) for p in files], one, 2)   # weight 2 (lead 81661)

# ---------------- lane: CommonCatalog CC-BY images only (Flickr CC-BY); blip2_caption dropped ----------------
def lane_ccby():
    import pyarrow.parquet as pq
    SRC = "common-canvas/commoncatalog-cc-by"; rev = api.dataset_info(SRC).sha
    tree = [t for t in api.list_repo_tree(SRC, repo_type="dataset", recursive=True) if hasattr(t, "size") and t.path.endswith(".parquet")]
    pref = {"least_dim_range=512-768": 0, "least_dim_range=768-1024": 1, "least_dim_range=256-512": 2}
    sel = [t for t in tree if any(k in t.path for k in pref)]
    sel.sort(key=lambda t: (next(v for k, v in pref.items() if k in t.path), t.path))
    log(f"ccby: {len(sel)} parquet files selected = {sum(t.size for t in sel)/2**30:.0f} GiB (mid-res buckets only)")
    CUT = "2022-10-31"
    def one(path, size):
        d = f"{STG}/dl"; os.makedirs(d, exist_ok=True)
        upload_first(); wait_space(2 * size + 2**28)
        loc = retry(lambda: hf_hub_download(SRC, path, repo_type="dataset", revision=rev, local_dir=d), what=path)
        tag = hashlib.md5(path.encode()).hexdigest()[:10]; w = None; n_in = n_out = 0; parts = []; LIM = 400 * 2**20   # output split into <=~400 MB part files so one push is never a 1-2 GB all-or-nothing upload (lead 81769)
        with open(loc, "rb") as fh:
            pf = pq.ParquetFile(fh); cols = [c for c in pf.schema_arrow.names if c != "blip2_caption"]
            for b in pf.iter_batches(batch_size=32, columns=cols):
                n_in += b.num_rows
                keep = [i for i, (st, dt) in enumerate(zip(b.column("status").to_pylist(), b.column("datetaken").to_pylist())) if st == "success" and (dt is None or dt.strftime("%Y-%m-%d") <= CUT)]
                if not keep: continue
                b = b.take(keep)
                if w is None: parts.append([f"{STG}/out-{tag}-p{len(parts):02d}.parquet", 0]); w = pq.ParquetWriter(parts[-1][0], b.schema, compression="zstd")
                w.write_batch(b); n_out += b.num_rows; parts[-1][1] += b.num_rows
                if os.path.getsize(parts[-1][0]) > LIM: w.close(); w = None
        if w: w.close()
        os.remove(loc)
        if n_out == 0: return 0
        tot = 0
        for pi, (fp, nrows) in enumerate(parts):
            rp = f"image/commoncatalog-cc-by/{path}" if len(parts) == 1 else f"image/commoncatalog-cc-by/{path[:-8]}.p{pi:02d}.parquet"
            meta = dict(source=f"huggingface.co/datasets/{SRC}@{rev} {path}", licence="CC-BY (Flickr per-image licensename/licenseurl kept in rows; dataset card cc-by-4.0)", modality="image", units={"images": nrows}, rows_in=n_in, rows_out=n_out, part=f"{pi+1}/{len(parts)}",
                        dropped_fields=["blip2_caption (external-model caption, lead 81651/GOAL 14)"], filters=f"status==success; datetaken<={CUT}")
            tot += push(fp, rp, meta)
        return tot
    run_pool([(t.path, t.size) for t in sel], one, 1)   # 1 worker: PD12M gets the bandwidth (lead 81661)

# ---------------- lane: PD12M images from the public S3 bucket; caption (Florence-2 synthetic) dropped ----------------
def lane_pd12m():
    import pyarrow.parquet as pq
    SRC = "Spawning/PD12M"; rev = api.dataset_info(SRC).sha
    metas = sorted(t.path for t in api.list_repo_tree(SRC, repo_type="dataset", path_in_repo="metadata") if hasattr(t, "size") and t.path.endswith(".parquet"))
    log(f"pd12m: {len(metas)} metadata files")
    OLD_CHUNK = 1000; CHUNK = 200   # images per tar shard: 200 (~0.2-0.8 GiB) so a stalled push costs minutes, not an hour (lead 81769). Old 1000-image shards keep their keys; new shards start after the last old one.
    def fetch(url, md5):
        for i in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ember-data-lane/1.0"}), timeout=60) as r: data = r.read()
                _nc.pace(len(data))      # M-NET-2 (lead 82238): aggregate cap across the 8 fetch threads while the cap is on
                if md5 and hashlib.md5(data).hexdigest() != md5: return None, "md5 mismatch"
                return data, None
            except Exception as e: err = f"{type(e).__name__}"; time.sleep(1 + i)
        return None, err
    def shard(mpath, ci, rows):
        key = f"{mpath}@{CHUNK}#{ci}"
        if key in state["done"]: return 0
        upload_first(); wait_space(CHUNK * 4 * 2**20)
        tarp = f"{STG}/pd12m-{os.path.basename(mpath)[:-8]}-c{CHUNK}-{ci:05d}.tar"; man = []; bad = 0
        mp = tarp[:-4] + ".manifest.jsonl"; rman = f"sources/pd12m/{os.path.basename(mp)}"; ri0 = remote_info(rman)
        if ri0 is not None and os.path.exists(tarp):   # an earlier run finished this tar and pushed its manifest but failed verify: reuse the finished tar, no refetch
            loc_m = retry(lambda: hf_hub_download(RAW, rman, repo_type="dataset", local_dir=f"{STG}/mrecover"), what=rman)
            nm = sum(1 for _ in open(loc_m, encoding="utf-8"))
            with tarfile.open(tarp) as _t: nt = len(_t.getnames())
            if nm == nt:
                meta = dict(source=f"huggingface.co/datasets/{SRC}@{rev} {mpath} (images from s3 pd12m)", licence="CDLA-Permissive-2.0 / public domain & CC0 per row", modality="image", units={"images": nm}, dropped_fields=["caption (Florence-2 synthetic recaption; external-model output, lead 81651)"], recovered_tar=True)
                b2 = push(tarp, f"sources/pd12m/{os.path.basename(tarp)}", meta); state["done"][key] = {"bytes": b2, "ts": time.time()}; save(); os.remove(loc_m); return b2
            log(f"recover mismatch {nm} manifest rows vs {nt} tar members; refetching chunk")
        with tarfile.open(tarp, "w") as tf, ThreadPoolExecutor(int(os.environ.get("PD12M_THREADS","8"))) as ex:
            futs = {ex.submit(fetch, r["url"], r.get("hash")): r for r in rows}
            for fu in as_completed(futs):
                r = futs[fu]; data, err = fu.result()
                if data is None: bad += 1; continue
                ext = (r.get("mime_type") or "image/jpeg").split("/")[-1].replace("jpeg", "jpg")
                ti = tarfile.TarInfo(f"{r['id']}.{ext}"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
                man.append(dict(id=r["id"], url=r["url"], width=r.get("width"), height=r.get("height"), mime=r.get("mime_type"), md5=r.get("hash"), sha256=hashlib.sha256(data).hexdigest(), license=r.get("license"), source=r.get("source")))
        mp = tarp[:-4] + ".manifest.jsonl"
        with open(mp, "w", encoding="utf-8") as f:
            for m in man: f.write(json.dumps(m) + "\n")
        meta = dict(source=f"huggingface.co/datasets/{SRC}@{rev} {mpath} (images from s3 pd12m)", licence="CDLA-Permissive-2.0 / public domain & CC0 per row", modality="image", units={"images": len(man)}, fetch_failed=bad,
                    dropped_fields=["caption (Florence-2 synthetic recaption; external-model output, lead 81651)"])
        b1 = push(mp, f"sources/pd12m/{os.path.basename(mp)}", dict(meta, units={}))
        b2 = push(tarp, f"sources/pd12m/{os.path.basename(tarp)}", meta)
        state["done"][key] = {"bytes": b1 + b2, "ts": time.time()}; save(); return b1 + b2
    for mp in (metas if not LIMIT else metas[:1]):
        loc = retry(lambda: hf_hub_download(SRC, mp, repo_type="dataset", revision=rev, local_dir=f"{STG}/meta"), what=mp)
        t = pq.read_table(loc, columns=["id", "url", "width", "height", "mime_type", "hash", "license", "source"]).to_pylist()
        olds = [int(k.rsplit("#", 1)[1]) for k in state["done"] if k.startswith(mp + "#") and "@" not in k]; start = (max(olds) + 1) * OLD_CHUNK if olds else 0   # rows already covered by old 1000-image shards
        for ci in range(start, len(t) if not LIMIT else min(len(t), start + CHUNK), CHUNK):
            try:
                n = shard(mp, ci // CHUNK, t[ci:ci + CHUNK]); age = time.time() - prog["started"]
                if n: log(f"pd12m {mp} chunk {ci//CHUNK}: {n/2**20:.0f} MiB; lane total {prog['bytes_uploaded']/2**30:.1f} GiB, {prog['bytes_uploaded']/2**30/max(age/86400,1e-6):.1f} GiB/day, images {prog['units'].get('images',0):.0f}")
            except SystemExit as e: log(str(e)); os._exit(2)
            except Exception as e: log(f"FAILED chunk {mp}@{CHUNK}#{ci//CHUNK}: {type(e).__name__} {str(e)[:300]}")

if __name__ == "__main__":
    {"mls": lane_mls, "ccby": lane_ccby, "pd12m": lane_pd12m}[LANE]()  # text lanes (loc, pes2o, pubmed) live in text_lane.py and import this module
    log("LANE DONE", LANE)
    if not LIMIT: open(f"{STG}/ALL.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

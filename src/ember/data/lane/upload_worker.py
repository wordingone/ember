# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ONE shared upload worker for every bulk lane (lead 81769): lanes drop finished shards into <lane-root>/upq/ (bulk_lane.push enqueues), this process uploads them oldest-first, verifies
the remote LFS sha256 + size, appends the lane's receipt row, deletes the staged file. Lanes keep downloading while it uploads. Resumable: jobs live on disk; a restart picks up where it stopped.
Never overwrites: if the remote path exists with a different size the job goes to upq/failed/ (file kept) and is counted in stats. Writes upq/stats.json (queue depth, true uploaded bytes, events)
and upq/heartbeat (touched every 30 s while alive and while an upload is in flight) so the tick can see it is healthy even during a multi-hour push."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, glob, threading, traceback
pass; import hf_cap
class CapHold(Exception): pass
from huggingface_hub import HfApi
from lane_config import LANE_ROOT as ROOT; Q = os.environ.get("UPQ_DIR", ROOT + "/upq"); FAILED = Q + "/failed"; os.makedirs(FAILED, exist_ok=True)
api = HfApi(); STATS = Q + "/stats.json"; HB = Q + "/heartbeat"
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
stats = json.load(open(STATS)) if os.path.exists(STATS) else {"uploaded_bytes": 0, "uploaded_files": 0, "events": [], "by_lane": {}, "failed_files": 0}
def beat():
    while True:
        try: open(HB, "a").close(); os.utime(HB, None); save_stats()
        except Exception: pass
        time.sleep(30)
threading.Thread(target=beat, daemon=True).start()
import subprocess, psutil
STALL_S = 240   # a push whose process shows no I/O progress for this long (half-closed socket, CloseWait) is killed and retried; completed LFS parts are not re-sent
def upload_with_watchdog(dat, rp, repo, msg, size):
    import upload_refuse; upload_refuse.check(dat)      # lead 82100: pre-redaction originals never upload
    code = "import sys; from huggingface_hub import HfApi; HfApi().upload_file(path_or_fileobj=sys.argv[1], path_in_repo=sys.argv[2], repo_id=sys.argv[3], repo_type='dataset', commit_message=sys.argv[4])"
    while os.path.exists((LANE_ROOT + "/loops/RESTORE-PRIORITY.flag")):      # training 82037 / lead 82035: restore owns the saturated link; hold every push
        log("push HELD: RESTORE-PRIORITY.flag"); time.sleep(120)
    import reserve_plan; reserve_plan.harm_wait("upload_worker push", log, kinds=("link",))   # lead 82070: harm-only (link priority); a push FREES disk, so no disk-floor wait here
    pr = subprocess.Popen([sys.executable, "-c", code, dat, rp, repo, msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ps = psutil.Process(pr.pid); last = None; last_t = time.time()
    cw_t = None
    while pr.poll() is None:
        try:
            io = ps.io_counters(); cur = io.read_bytes   # progress = bytes read from the staged file; write/other trickle (log, keep-alive) must not reset the stall timer
            try: cur += sum(c.io_counters().read_bytes for c in ps.children(recursive=True))
            except Exception: pass
        except Exception: cur = None
        try: cw = any(c.status == "CLOSE_WAIT" for c in ps.net_connections())
        except Exception: cw = False
        cw_t = (cw_t or time.time()) if cw else None
        if cw_t and time.time() - cw_t > 120:      # lead 81847: a push socket in CLOSE_WAIT for >2 min is a dead connection; kill and retry (completed LFS parts are not re-sent)
            log(f"CLOSE_WAIT socket >120 s: killing the push and retrying ({rp})"); pr.kill(); pr.wait(); raise RuntimeError("push socket CLOSE_WAIT; killed for retry")
        if cur != last: last = cur; last_t = time.time()
        elif time.time() - last_t > STALL_S:
            log(f"stalled {STALL_S}s with no I/O progress: killing the push and retrying ({rp})"); pr.kill(); pr.wait(); raise RuntimeError("push stalled; killed for retry")
        time.sleep(5)
    if pr.returncode != 0: raise RuntimeError(f"push exited rc={pr.returncode}")
def queue():
    return sorted(glob.glob(Q + "/*.job.json"))
def save_stats():
    q = queue(); qb = 0
    for j in q:
        try: qb += json.load(open(j))["size"]
        except Exception: pass
    stats["queue_files"] = len(q); stats["queue_bytes"] = qb; stats["ts"] = time.time(); stats["events"] = stats["events"][-3000:]
    _t = STATS + f".{threading.get_ident()}.tmp"; json.dump(stats, open(_t, "w")); os.replace(_t, STATS)
def remote(repo, rp):
    r = api.get_paths_info(repo, [rp], repo_type="dataset", expand=True)
    return r[0] if r else None
def do(jp):
    job = json.load(open(jp)); dat = jp[:-len(".job.json")] + ".dat"; repo, rp, size, sha = job["repo"], job["rp"], job["size"], job["sha"]
    if not os.path.exists(dat): log("missing data file for", os.path.basename(jp), "-> failed/"); os.replace(jp, FAILED + "/" + os.path.basename(jp)); stats["failed_files"] += 1; return
    ri = remote(repo, rp)
    if ri is not None and ri.size != size:
        log(f"STOP-FILE: remote {rp} exists with size {ri.size} != {size}; not overwriting -> failed/")
        os.replace(jp, FAILED + "/" + os.path.basename(jp)); os.replace(dat, FAILED + "/" + os.path.basename(dat)); stats["failed_files"] += 1; return
    if ri is None:
        if repo.endswith("-private") and not hf_cap.check(size, "upload_worker", rp): raise CapHold(rp)      # lead 81851: hard guard, hold (job stays queued)
        t0 = time.time()
        upload_with_watchdog(dat, rp, repo, f"{job['lane']}: {os.path.basename(rp)} (data bulk lane via shared uploader, lead 81769)", size)
        ri = remote(repo, rp); log(f"uploaded {rp} {size/2**20:.0f} MiB in {time.time()-t0:.0f}s ({size/2**20/max(time.time()-t0,1e-6):.2f} MB/s)")
    rsha = ri.lfs.sha256 if ri is not None and ri.lfs is not None and hasattr(ri.lfs, "sha256") else (ri.lfs["sha256"] if ri is not None and ri.lfs is not None else None)
    how = "LFS sha256 == local"
    if rsha is None and ri is not None and ri.lfs is None and ri.blob_id:        # small non-LFS file: git blob sha1
        import hashlib
        h = hashlib.sha1(b"blob %d\0" % size)
        with open(dat, "rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
        if h.hexdigest() == ri.blob_id: rsha = sha; how = "git blob sha1 == local (non-LFS small file)"
    if rsha != sha or ri.size != size: raise RuntimeError(f"VERIFY FAILED {rp}: local {sha} remote {rsha}")
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), lane=job["lane"], hf_path=rp, bytes=size, sha256=sha, hf_repo=repo, verified=how, via="upq", **job["meta"])
    with open(job["rcpt"], "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\n")
    os.remove(dat); os.remove(jp)
    stats["uploaded_bytes"] += size; stats["uploaded_files"] += 1; stats["events"].append([time.time(), size, job["lane"]])
    bl = stats["by_lane"].setdefault(job["lane"], {"bytes": 0, "files": 0}); bl["bytes"] += size; bl["files"] += 1
log("upload_worker up; queue", len(queue()))
fails = {}
while True:
    q = queue()
    if not q: save_stats(); time.sleep(20); continue
    jp = q[0]
    try:
        do(jp); fails.pop(jp, None)
    except SystemExit: raise
    except CapHold as e: log(f"PRIVATE CAP HOLD: {e}; job stays queued, retry in 300 s"); save_stats(); time.sleep(300); continue
    except Exception as e:
        fails[jp] = fails.get(jp, 0) + 1; log(f"FAILED {os.path.basename(jp)} try {fails[jp]}: {type(e).__name__} {str(e)[:200]}")
        if fails[jp] >= 6:
            dat = jp[:-len(".job.json")] + ".dat"; os.replace(jp, FAILED + "/" + os.path.basename(jp))
            if os.path.exists(dat): os.replace(dat, FAILED + "/" + os.path.basename(dat))
            stats["failed_files"] += 1; fails.pop(jp, None)
        else: time.sleep(min(120, 10 * 2 ** fails[jp]))
    save_stats()

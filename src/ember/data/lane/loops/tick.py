# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic loop ticks for the data data lane (lead 81222). Zero model tokens: this script decides, the cron prompt only relays its ONE output line.
Usage: tick.py fetch|prep|intake|upload|census
Appends a receipt row to loops/receipts.jsonl: {ts, loop, status: idle|worked|blocked, note}. A loop blocked 3 ticks in a row prints ESCALATE (mail lead then).
Directive words in the printed line for the cron prompt: NEW_PACKED <name> -> mail training the intake pointer; ESCALATE -> mail lead.
Rules this script enforces: CPU-only work, <=3 PG workers; lane total <=8 logical cores (LANE_WEIGHT table in spawn(), lead 81497), BelowNormal priority, OMP/MKL=1, no new job while total CPU >85%; PRIVATE-repo uploads go automatically for any packed set that passed the rules + training's C1/C2 intake and is listed in loops/approved-uploads.json (lead 81232); PUBLIC repos always need lead's ruling; never overwrites an HF file."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import HF_TRAIN_REPO, LANE_ROOT, M_ROOT, SEAT_LEAD, SEAT_TRAIN
import sys, os, json, time, glob, subprocess, hashlib, shutil
from lane_config import LANE_ROOT as ROOT; L = ROOT + "/loops"; os.makedirs(L, exist_ok=True)
LOOP = sys.argv[1]
# (quiet-window presence guard removed, lead 82070 / run-unaffected rule: ticks wait only on measured harm - RESTORE-PRIORITY.flag, disk floor - see reserve_plan.harm)
# Hardware isolation (lead 81608, operator: no more HOLDs): lane work is pinned to CCD1 (logical CPUs 16-31, mask 0xFFFF0000) and sees no GPU.
# Pinning THIS process makes every child (bash -> python) inherit the mask; CUDA_VISIBLE_DEVICES="" is set below and in spawn().
os.environ["CUDA_VISIBLE_DEVICES"] = ""
LANE_AFFINITY = 0x00FF0000   # lead 81625: narrowed to logical CPUs 16-23 (8 cores), BelowNormal
try:
    import ctypes
    _k = ctypes.windll.kernel32; _k.GetCurrentProcess.restype = ctypes.c_void_p
    _k.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    _k.SetProcessAffinityMask(_k.GetCurrentProcess(), LANE_AFFINITY)
except Exception as _e: print(f"[{LOOP}] WARNING: affinity pin failed: {_e}")
BASH = "C:/Program Files/Git/bin/bash.exe"   # NOT plain "bash" (resolves to WSL from python)
DETACH = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
STATE = L + "/state.json"
st = json.load(open(STATE)) if os.path.exists(STATE) else {}
# Drift gate (#2454, lead 82490) - FIRST, before the scratch sweep or any work: the lane runs only code that is byte-identical to the reviewed tree copy (or drift acknowledged with a ruling, see lane_drift.py).
# Fail closed: if the check cannot run, the tick refuses. A refused tick records a blocked row (3 in a row print ESCALATE) and starts nothing - it does not go through done(), which would start lane jobs.
DRIFT_NOTE = ""
try:
    sys.path.insert(0, ROOT + "/scripts"); import lane_drift; _dok, DRIFT_NOTE = lane_drift.gate(LOOP)
except BaseException as _e: _dok, DRIFT_NOTE = False, f"drift gate error {type(_e).__name__}: {str(_e)[:160]}"
if not _dok:
    _bl = st.get(LOOP, {}).get("blocked", 0) + 1; st[LOOP] = {"blocked": _bl, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}; json.dump(st, open(STATE, "w"))
    with open(L + "/receipts.jsonl", "a", encoding="utf-8") as _f: _f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), loop=LOOP, status="blocked", note="DRIFT-REFUSED " + DRIFT_NOTE)) + chr(10))
    print(f"[{LOOP}] blocked: DRIFT-REFUSED {DRIFT_NOTE}" + (" ESCALATE (blocked 3 ticks)" if _bl >= 3 else "")); sys.exit(0)
try:      # lead 82361: a killed writer's owner-stamped scratch is swept every tick (receipt row first; unstamped dirs are never touched)
    sys.path.insert(0, ROOT + "/scripts"); import scratch_dir; scratch_dir.sweep()
except Exception as _e: print(f"[{LOOP}] scratch sweep failed: {_e}")

MEDIA_DIRS = [ROOT + "/media-packed", "A:/ember-stage/media-packed"]
def gate_ok(gate_path, intake_path):
    """training's c1c2 verdict must be PASS *and* be for the CURRENT pack: when the verdict carries inputs.candidate_sha256 (ledger sha) it must equal intake.json ledger_sha256 (a repacked/redacted pack with the same name needs a fresh verdict; pes2o pushed on a stale PASS 2026-11-09)."""
    try:
        v = json.load(open(gate_path, encoding="utf-8")); it = json.load(open(intake_path, encoding="utf-8"))
    except Exception:
        return False
    if v.get("verdict") != "PASS":
        return False
    c = (v.get("inputs") or {}).get("candidate_sha256"); l = it.get("ledger_sha256") or it.get("index_sha256")      # text packs bind to the ledger sha, media sets to the index sha
    return bool(c) and bool(l) and c == l      # fail closed (lead 82448 / review row tick.py): a PASS missing either hash, or an intake with no binding key, approves nothing


def mglob(tail): return sorted(x for d in MEDIA_DIRS for x in glob.glob(d + "/" + tail))

def sh(cmd, timeout=600):
    r = subprocess.run([BASH, "-c", cmd], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return r.stdout.strip()

_cmd = None
def cmdlines():
    global _cmd
    if _cmd is None:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
        _cmd = [x for x in out.splitlines() if x.strip()]
    return _cmd
def alive(pat): return sum(1 for c in cmdlines() if pat in c and "tick.py" not in c)
def scan_listing():
    """One process listing -> [(pid, cmdline)]. Raises when the listing fails, is empty or parses to nothing: a lookup that saw no process at all (a live host always has some) is a failed lookup,
    never 'no scan running' (lead 82933 / PR 2467 review D3). The upload tick builds it ONCE per tick and every pack reads it."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if out.returncode != 0: raise RuntimeError("process lookup rc=%d" % out.returncode)
    rows = []
    for ln in out.stdout.splitlines():
        pid, _, c = ln.partition("\t")
        if pid.strip().isdigit(): rows.append((int(pid), c))
    if not rows: raise RuntimeError("process listing empty or unparsable")
    return rows
def scan_pids(name, rows=None):
    """PIDs of live `th_pack_scan.py <name> ` processes (pack_scan_status, lead 82613 item 3). `rows` is the tick's shared listing (scan_listing()); without it one listing is made. Raises on a failed lookup: the caller reads that as unknown, never as running."""
    if rows is None: rows = scan_listing()
    return [pid for pid, c in rows if ("th_pack_scan.py " + name + " ") in c and "tick.py" not in c]
# ---- CPU cap (lead 81497, operator): the lane may use at most LANE_CORES logical cores in total; BelowNormal priority; no new job while total CPU > CPU_MAX %. ----
LANE_CORES = 8; CPU_MAX = 85
BELOW_NORMAL = 0x00004000
LANE_WEIGHT = [("coco_fetch.py", 3), ("se_drive.py", 2), ("librivox_pilot.py", 2), ("commons_pilot2.py", 2), ("commons_cat.py", 1), ("commons_finish.py", 1), ("imgtext_manifest.py", 1),
               ("pack_media.py", 3), ("pack_pg.sh", 2), ("pack_wiki_group.sh", 2), ("drive_wiki.sh", 2), ("pg_worker.sh", 1), ("fetch_part.sh", 1), ("pack.py", 2), ("th_pack_scan.py", 2), ("hf upload", 0),("run_loops.py", 0),("hf_inventory.py", 0), ("audit_secrets.py", 0), ("remedy_move.py", 0), ("redact_r1.py", 0), ("repack_r1", 0), ("bulk_lane.py mls", 2), ("bulk_lane.py ccby", 1), ("bulk_lane.py pd12m", 1), ("text_lane.py", 0), ("ccby_pack.py", 1), ("mls_pack.py", 1), ("upload_worker.py", 0), ("net_arbiter.py", 0)]   # inventory = HF API calls only, ~0 CPU
DEFERRED = []; ADDED = 0
def _weight_of(cmd):
    for k, w in LANE_WEIGHT:
        if k in cmd: return w
    return 1
def lane_load():
    """Sum of weights of live lane jobs (python/bash/hf command lines under data-staging; counts each distinct script once-per-process)."""
    tot = 0
    for c in cmdlines():
        lc = c.lower()
        if "tick.py" in c: continue
        # count only real worker processes (python.exe / hf / in-tick appended "python ..."), NOT bash -c wrappers or the powershell process listing (those carry the same script names -> 24 cores counted for ~5 jobs)
        if not (lc.startswith('"c:\\program files\\python') or lc.startswith("python ") or lc.startswith("hf upload") or lc.startswith('"c:\\program files\\python310\\scripts\\hf')): continue
        if any(k in c for k, _ in LANE_WEIGHT): tot += _weight_of(c)
    return tot
def total_cpu():
    """Average busy % of the LANE's own logical CPUs 16-23 (CCD1), not the whole machine: other cores belong to the training chain (lead 81608/81625: no holds, own cores only)."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | Where-Object { $_.Name -match '^(1[6-9]|2[0-3])$' } | Measure-Object -Property PercentProcessorTime -Average).Average"], capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception: return 0.0
def spawn(cmd, log):
    """Start a lane job unless the 8-core lane cap or the 85% total-CPU gate says no. Returns True if started, False if deferred (caller must not report 'started')."""
    global ADDED
    if os.path.exists(ROOT + "/loops/RESTORE-PRIORITY.flag") and any(k in cmd for k in ("bulk_lane.py", "text_lane.py", "ccby_pack", "mls_pack", "coco_fetch", "se_drive", "librivox", "drive_wiki", "fetch_part", "pg_worker")):      # lead 81958: the checkpoint restore owns the downlink until the flag is removed
        DEFERRED.append(f"{cmd.split()[1] if len(cmd.split()) > 1 else cmd[:30]} (RESTORE-PRIORITY.flag: checkpoint restore has the downlink)"); return False
    w = _weight_of(cmd); load = lane_load() + ADDED; cpu = total_cpu()   # ADDED: jobs spawned earlier in THIS tick are not in the cached process snapshot
    if (load + w > LANE_CORES or cpu > CPU_MAX) and "upload_worker.py" not in cmd and "net_arbiter.py" not in cmd and "run_loops.py" not in cmd and "th_pack_scan.py" not in cmd and not cmd.startswith("hf upload") and "hf_inventory.py" not in cmd:   # the shared uploader is network-bound and must never be deferred by the CPU gate (lead 81769)
        DEFERRED.append(f"{cmd.split()[1] if len(cmd.split()) > 1 else cmd[:30]} (lane {load}+{w}>{LANE_CORES} cores or CPU {cpu:.0f}%>{CPU_MAX}%)"); return False
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", LANE_MAX_WORKERS=str(LANE_CORES), CUDA_VISIBLE_DEVICES="")
    pr = subprocess.Popen([BASH, "-c", f"cd {ROOT}; {cmd} > {log} 2>&1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=DETACH | BELOW_NORMAL, env=env)
    with open(L + "/spawn-pids.jsonl", "a", encoding="utf-8") as sf: sf.write(json.dumps(dict(pid=pr.pid, ts=time.time(), cmd=cmd, log=log)) + "\n")   # lead 81558: kill_lane.ps1 stops ONLY pids recorded here (verified), never by name
    ADDED += w
    cmdlines().append("python " + cmd)   # make later alive()/alive_py() checks in THIS tick see the job (fetch() and backlog_state() both start coco_fetch/se_drive/librivox -> duplicate instances otherwise)
    return True


# ---- backlog (lead 81395): an idle tick is legal only when the backlog is empty AND the budget is exhausted; the row names which. ----
def _n(path):
    try: return sum(1 for _ in open(path, encoding="utf-8"))
    except Exception: return 0
def alive_py(pat): return sum(1 for c in cmdlines() if pat in c and 'tick.py' not in c and ('python.exe' in c.lower()[:60] or c.lower().startswith('python')))
def A_free(): return shutil.disk_usage("A:/").free / 2**30
def B_free(): return shutil.disk_usage("B:/").free / 2**30
def _lease():
    try:
        L = json.load(open(ROOT + "/loops/floor-borrow.json"))
        return L if time.time() < L["until_epoch"] else None
    except Exception: return None
def _bulk_prog(lane):
    """'12.3 GiB up, 40.1 GiB/day' from bulk/<lane>/progress.json (rolling 24 h window)."""
    try:
        pj = json.load(open(f"{ROOT}/bulk/{lane}/progress.json")); now = time.time(); age = max(now - pj["started"], 60)
        win = min(age, 86400); recent = sum(b for t, b in pj["events"] if now - t <= win)
        u = pj.get("units", {}); us = ", ".join(f"{k}={v:,.0f}" for k, v in u.items())
        return f"{pj['bytes_uploaded']/2**30:.1f} GiB up, {recent/2**30/(win/86400):.1f} GiB/day, {us}"
    except Exception: return "no progress yet"
PK = "python scripts/pack_media.py image A:/ember-stage/media-packed"
def _net_cap_prog():
    try:
        st = json.load(open(ROOT + "/loops/net-cap.json", encoding="utf-8"))
        return f"net cap {'ON ' + str(st.get('cap_mbps')) + ' MB/s' if st.get('on') else 'off'} (up {st.get('uplink_mbps')} / down {st.get('downlink_mbps')} MB/s, queue {st.get('queue_files')})"
    except Exception: return "net cap n/a"

def _upq_prog():
    """shared uploader state for the tick line: queue depth, true uploaded GiB, MB/s over the last hour, failures (upq/stats.json written by upload_worker.py)"""
    try:
        st = json.load(open(ROOT + "/upq/stats.json")); h = sum(b for t, b, *_ in st["events"] if time.time() - t < 3600)
        return f"shared uploader: queue {st.get('queue_files',0)} files {st.get('queue_bytes',0)/2**30:.2f} GiB, uploaded {st['uploaded_bytes']/2**30:.1f} GiB total, {h/3600/2**20:.2f} MB/s last hour, failed {st.get('failed_files',0)}"
    except Exception: return "shared uploader (no stats yet)"
BACKLOG = [   # ordered; start=None means another tick manages it; needs = file that must exist first
 dict(id="tick-runner", done=None, alive="run_loops.py", start="python scripts/loops/run_loops.py"),   # lead 82344: detached singleton runner for the mechanical ticks (upload/fetch/census); the judgment ticks stay session crons; restarted here if it died
 dict(id="net-arbiter", done=None, alive="net_arbiter.py", start="python scripts/net_arbiter.py", prog=lambda: _net_cap_prog()),   # M-NET-2 (lead 82238): caps the SUM of lane downloads to 2.5 MB/s while uploads are queued and the uplink is starved
 dict(id="upload-worker", done=None, alive="upload_worker.py", start="python scripts/upload_worker.py", prog=_upq_prog),   # ONE shared uploader for all bulk lanes (lead 81769); must be up before the lanes enqueue
 dict(id="remedy-move", done=ROOT + "/logs/remedy-move-final.json", alive="remedy_move.py", start="python scripts/pinned_run.py scripts/remedy_move.py", prog=lambda: "move flagged public heldout archives to private, one delete commit (lead 81698)"),
 dict(id="redact-r1", done=ROOT + "/redact-r1/ALL.done", alive="redact_r1.py", start="python scripts/pinned_run.py scripts/redact_r1.py", prog=lambda: "wikipedia redaction pass r1 (lead 81713)"),
 dict(id="repack-r1", done=ROOT + "/redact-r1/REPACK.done", alive="repack_r1", start="python scripts/pinned_run.py scripts/repack_r1_all.py", prog=lambda: "wikipedia -r1 repack, smallest pack first (training 81727)"),
 dict(id="audit-secrets-train", done=ROOT + ("/audit/secret-audit-" + HF_TRAIN_REPO + ".done"), alive=("audit_secrets.py wordingone/" + HF_TRAIN_REPO), start=("python scripts/audit_secrets.py wordingone/" + HF_TRAIN_REPO), prog=lambda: ("secret audit of " + HF_TRAIN_REPO + " (lead 81693)")),
 dict(id="audit-secrets", needs=ROOT + "/loops/AUDIT-RUN.flag", done=ROOT + "/audit/secret-audit.done", alive="audit_secrets.py", start="python scripts/audit_secrets.py", prog=lambda: "secret audit of ember-corpus (lead 81676)"),
 dict(id="bulk-mls", done=ROOT + "/bulk/mls/ALL.done", alive="bulk_lane.py mls", start="python scripts/bulk_lane.py mls", prog=lambda: _bulk_prog("mls")),   # lead 81651 fill order: audio MLS-English bulk (3 workers)
 dict(id="bulk-pd12m", done=ROOT + "/bulk/pd12m/ALL.done", alive="bulk_lane.py pd12m", start="python scripts/bulk_lane.py pd12m", prog=lambda: _bulk_prog("pd12m")),   # images PD12M (1 proc, 12 I/O threads)
 dict(id="bulk-ccby", done=ROOT + "/bulk/ccby/ALL.done", alive="bulk_lane.py ccby", start="python scripts/bulk_lane.py ccby", prog=lambda: _bulk_prog("ccby")),   # images commoncatalog-cc-by, blip2 dropped (2 workers)
 dict(id="image-ccby-pack", done=ROOT + "/staging/ccby-pack/ALL.done", alive="ccby_pack.py", start="python scripts/ccby_pack.py", prog=lambda: "commoncatalog-cc-by stream-through pack (human Flickr text only; queue item 7)", min_a=0),
 dict(id="text-pre1929", done=ROOT + "/bulk/pre1929/ALL.done", alive="text_lane.py pre1929", start="python scripts/text_lane.py pre1929", prog=lambda: _bulk_prog("pre1929")),   # common-pile wall-safe fill (lead 81977), priority order: pre1929, caselaw, hansard, usgpo
 dict(id="text-caselaw", done=ROOT + "/bulk/caselaw/ALL.done", alive="text_lane.py caselaw", start="python scripts/text_lane.py caselaw", prog=lambda: _bulk_prog("caselaw")),   # common-pile wall-safe fill (lead 81977), priority order: pre1929, caselaw, hansard, usgpo
 dict(id="text-hansard", done=ROOT + "/bulk/hansard/ALL.done", alive="text_lane.py hansard", start="python scripts/text_lane.py hansard", prog=lambda: _bulk_prog("hansard")),   # common-pile wall-safe fill (lead 81977), priority order: pre1929, caselaw, hansard, usgpo
 dict(id="text-usgpo", done=ROOT + "/bulk/usgpo/ALL.done", alive="text_lane.py usgpo", start="python scripts/text_lane.py usgpo", prog=lambda: _bulk_prog("usgpo")),   # common-pile wall-safe fill (lead 81977), priority order: pre1929, caselaw, hansard, usgpo
 dict(id="text-stackv2_edu", done=ROOT + "/bulk/stackv2_edu/ALL.done", alive="text_lane.py stackv2_edu", start="python scripts/text_lane.py stackv2_edu", prog=lambda: _bulk_prog("stackv2_edu")),   # common-pile wall-safe fill (lead 81977), Tier-1 (wall per-doc created); uspto last, <=10% of any mixture
 dict(id="text-arxiv_papers", done=ROOT + "/bulk/arxiv_papers/ALL.done", alive="text_lane.py arxiv_papers", start="python scripts/text_lane.py arxiv_papers", prog=lambda: _bulk_prog("arxiv_papers")),   # common-pile wall-safe fill (lead 81977), Tier-1 (wall per-doc created); uspto last, <=10% of any mixture
 dict(id="text-github_archive", done=ROOT + "/bulk/github_archive/ALL.done", alive="text_lane.py github_archive", start="python scripts/text_lane.py github_archive", prog=lambda: _bulk_prog("github_archive")),   # common-pile wall-safe fill (lead 81977), Tier-1 (wall per-doc created); uspto last, <=10% of any mixture
 dict(id="text-uspto", done=ROOT + "/bulk/uspto/ALL.done", alive="text_lane.py uspto", start="python scripts/text_lane.py uspto", prog=lambda: _bulk_prog("uspto")),   # common-pile wall-safe fill (lead 81977), Tier-1 (wall per-doc created); uspto last, <=10% of any mixture
 dict(id="docs-nh-fill", done=ROOT + "/logs/fill-nh.done", alive="fill_nh.py --hf", start="python scripts/fill_nh.py --hf", prog=lambda: "docs.sqlite NULL nh rows filled from HF objects"),   # #1581 dedupe-index completeness; script refuses while RESTORE-PRIORITY.flag
 dict(id="audio-mls-pack", done=ROOT + "/staging/mls-pack/ALL.done", alive="mls_pack.py", start="python scripts/mls_pack.py", prog=lambda: "MLS-English train 500 h speaker-balanced subset, stream-through pack (lead 81981; after the Comma text fill)", min_a=0),
 dict(id="text-loc", done=ROOT + "/bulk/loc/ALL.done", alive="text_lane.py loc", start="python scripts/text_lane.py loc", prog=lambda: _bulk_prog("loc")),   # LoC-PD-Books (CC0) first (lead 81661)
 dict(id="text-pes2o", done=ROOT + "/bulk/pes2o/ALL.done", alive="text_lane.py pes2o", start="python scripts/text_lane.py pes2o", prog=lambda: _bulk_prog("pes2o")),
 dict(id="text-pubmed", done=ROOT + "/bulk/pubmed/ALL.done", alive="text_lane.py pubmed", start="python scripts/text_lane.py pubmed", prog=lambda: _bulk_prog("pubmed")),
 dict(id="textcaps-manifest", done=ROOT + "/textcaps/manifest.jsonl", alive="imgtext_manifest.py textcaps", start="python scripts/imgtext_manifest.py textcaps textcaps textcaps/manifest.jsonl"),
 dict(id="textcaps-pack", needs=ROOT + "/textcaps/manifest.jsonl", done="A:/ember-stage/media-packed/textcaps-train-v1/receipt.json", alive="textcaps-train-v1", start=PK + " textcaps-train-v1 textcaps/manifest.jsonl loops/meta/textcaps-train-v1.json", min_a=8),
 dict(id="coco-manifest", needs=ROOT + "/coco/FETCH.done", done=ROOT + "/coco/manifest.jsonl", alive="imgtext_manifest.py coco", start="python scripts/imgtext_manifest.py coco coco coco/manifest.jsonl"),
 dict(id="coco-pack", needs=ROOT + "/coco/manifest.jsonl", done="A:/ember-stage/media-packed/coco-captions-2014-v1/receipt.json", alive="coco-captions-2014-v1", start=PK + " coco-captions-2014-v1 coco/manifest.jsonl loops/meta/coco-captions-2014-v1.json", min_a=11),
 dict(id="commons-pack", needs=ROOT + "/commons-pilot/manifest.jsonl", done="A:/ember-stage/media-packed/commons-human-v1/receipt.json", alive="commons-human-v1", start=PK + " commons-human-v1 commons-pilot/manifest.jsonl loops/meta/commons-human-v1.json", min_a=2),
 dict(id="teacher-licences", done=ROOT + "/audit/teacher-candidates.done", alive="__none__", start=None, prog=lambda: "draft table audit/teacher-candidates.md; LICENSE files unread"),
 dict(id="wiki-process", done=None, alive="wiki_pilot.py", start=None, prog=lambda: f"{len(glob.glob(ROOT+'/wikipedia-20220501/work/*.done'))}/48 parts", donef=lambda: len(glob.glob(ROOT + "/wikipedia-20220501/work/*.done")) >= 48),
 dict(id="se-drive", done=ROOT + "/se-20221005/work/ALL.done", alive="se_drive.py", start="python scripts/se_drive.py", prog=lambda: f"{len(glob.glob(ROOT+'/se-20221005/work/*.done'))+len(glob.glob('A:/ember-stage/se-20221005/work/*.done'))}/360 sites"),
]
# RETIRED lanes (lead 81651, 2026-11-08): per-file coco-fetch / Commons (cands, v2, delta, pack-v2) / LibriVox lv-scale removed from the backlog; bulk HF lanes replace them (see bulk_lanes in this file).
MANUAL = ["c1c2 follow-ups with training"]
def _stalled(lane, mins=120):   # was 40: a slow healthy upload of a 1-3 GB shard writes nothing for >40 min (lead 81763); new lanes also write bulk/<lane>/upload.heartbeat
    try:
        d = f"{ROOT}/bulk/{lane}"; ts = [os.path.getmtime(f"{ROOT}/logs/backlog-bulk-{lane}.log")]
        for e in os.scandir(d): ts.append(e.stat().st_mtime)
        for sub in ("dl/data", "dl"):
            if os.path.isdir(f"{d}/{sub}"): ts += [e.stat().st_mtime for e in os.scandir(f"{d}/{sub}")]
        return time.time() - max(ts) > mins * 60
    except Exception: return False

def backlog_state(start_missing=True):
    live, pend, started, held = [], [], [], []
    for it in BACKLOG:
        isdone = it["donef"]() if it.get("donef") else (it["done"] and os.path.exists(it["done"]))
        if isdone: continue
        pend.append(it["id"]); pg = ""
        try: pg = it["prog"]() if it.get("prog") else ""
        except Exception: pass
        if (alive(it["alive"]) if it["alive"] == "wiki_pilot.py" else alive_py(it["alive"])):
            if start_missing and it["id"].startswith("bulk-") and _stalled(it["id"][5:]):   # class fix: a wedged HF download (no log, file or progress write for 40 min) is stopped via kill_lane and restarted next tick
                subprocess.run(["powershell", "-NoProfile", "-File", ROOT + "/scripts/kill_lane.ps1", "-Reason", f"watchdog: {it['id']} wedged >40 min with no write", "-Only", it["alive"]], capture_output=True, timeout=120)
                pg += " WATCHDOG-KILLED(wedged)"
            live.append(it["id"] + (f" {pg}" if pg else "")); continue
        if it.get("needs") and not os.path.exists(it["needs"]): continue
        if not it.get("start"): continue
        lease = _lease(); sys.path.insert(0, ROOT + "/scripts"); import reserve_plan; fl = max(lease["floor"], reserve_plan.floor_gib()) if lease and it["id"] == "text-" + lease["lane"] else reserve_plan.floor_gib()   # lead 81866 borrow: ONE lane, 295 floor, until H44 closes
        if it["id"] not in ("upload-worker", "net-arbiter", "tick-runner") and (B_free() < fl or A_free() < (0 if lease and it["id"] == "text-" + lease["lane"] else it.get("min_a", 12))): held.append(it["id"]); continue   # the lease lane (text_lane) stages only on B:, never writes A:
        if start_missing and spawn(it["start"], ROOT + f"/logs/backlog-{it['id']}.log"): started.append(it["id"]); live.append(it["id"] + " (started)")
    return live, pend, started, held

def refresh_listing():
    """lead 83208: loops/trainable-listing.json is rewritten by every intake and upload tick (after the scans it reads), so a read of it is never older than one tick. A failed refresh keeps the old file, says so in the
    receipt line and never fails the tick. Returns the text appended to the receipt note.
    lead 83284: the never-trained columns need the ledgers of the hours already trained: loops/trained-ledgers.json {"ledgers": [path, ...]} (h42 and h49 seeded) is passed as --trained, and the run time of
    the refresh is in the receipt note (it shares the core budget of the tick). No list file = the columns stay empty AND the note says so."""
    t0 = time.time(); led = []; nt = ""
    try:
        led = [x for x in json.load(open(ROOT + "/loops/trained-ledgers.json", encoding="utf-8")).get("ledgers", []) if isinstance(x, str) and x.strip()]
    except Exception as _e: nt = f"; never-trained NOT computed (no readable loops/trained-ledgers.json: {type(_e).__name__})"
    args = [sys.executable, ROOT + "/scripts/trainable_listing.py"]
    for x in led: args += ["--trained", x]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=180, cwd=ROOT)
        took = " in %.0f s" % (time.time() - t0)
        if r.returncode != 0: return f" | trainable_listing refresh FAILED rc={r.returncode}{took} (old file kept)"
        j = json.load(open(ROOT + "/loops/trainable-listing.json", encoding="utf-8"))
        if led and j.get("trained_errors"): nt = "; TRAINED LEDGER NOT READ: " + ", ".join(os.path.basename(str(x.get("trained", ""))) for x in j["trained_errors"])
        elif led: nt = "; never-trained from %d ledger(s)" % len(j.get("trained_sets", []))
        return " | listing refreshed " + time.strftime("%H:%M") + took + nt + ": " + ", ".join("%s %d packs %d tok" % (k, v.get("packs", 0), v.get("tokens", 0)) + (" (never-trained min %d)" % v["never_trained_min"] if led and "never_trained_min" in v else "") for k, v in sorted(j.get("totals", {}).items()) if isinstance(v, dict))
    except Exception as _e: return f" | trainable_listing refresh FAILED {type(_e).__name__} in {time.time() - t0:.0f} s (old file kept)"

def done(status, note):
    if DRIFT_NOTE: note += ' | ' + DRIFT_NOTE      # an acknowledged drift is always visible in the receipt
    try:
        try:
            sys.path.insert(0, ROOT + '/scripts'); import stall_alarm; _sa = stall_alarm.run()   # lead 81807: no-progress alarm; mails lead itself
            if not _sa.startswith('ok'): note += ' | ' + _sa
        except Exception as _e: note += f' | stall_alarm error {type(_e).__name__}'
        try:   # lead 82534: a gate edit must list the long-lived drivers that still run the old code (restart each at a step boundary)
            import stale_drivers; _sd = stale_drivers.line(show=3)
            if not _sd.startswith('stale_drivers 0'): note += ' | ' + _sd
        except Exception as _e: note += f' | stale_drivers error {type(_e).__name__}'
        live, pend, started, held = backlog_state(start_missing=(LOOP in ("fetch", "prep", "upload")))
        tail = f" | live: {', '.join(live) or 'none'}; backlog {len(pend)}" + (f"; held by budget: {', '.join(held)}" if held else "") + f"; B free {B_free():.1f} GiB, A free {A_free():.1f} GiB"
        if started: note += "; started " + ", ".join(started)
        if DEFERRED: note += "; DEFERRED by CPU cap: " + ", ".join(DEFERRED)
        note += tail
        if status == "idle" and (pend or MANUAL):
            status = "worked"
            if pend and not live:
                note += " ALARM idle-with-backlog" + (" (budget exhausted)" if held else " (nothing startable: needs ACTION_NEEDED " + "; ".join(MANUAL) + ")")
    except Exception as e: note += f" [backlog check failed: {type(e).__name__}]"
    try: sys.path.insert(0, ROOT + "/scripts"); import sources_ledger; sources_ledger.write()      # D1 (lead 82134): keep loops/sources-ledger.jsonl fresh every tick; never fails the tick
    except BaseException as e: note += f" [sources-ledger failed: {type(e).__name__}]"
    blocked = st.get(LOOP, {}).get("blocked", 0) + 1 if status == "blocked" else 0
    st[LOOP] = {"blocked": blocked, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    json.dump(st, open(STATE, "w"))
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), loop=LOOP, status=status, note=note)
    with open(L + "/receipts.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\n")
    try:      # lead 83155: ESCALATE only on a change; the same known item twice is one escalation, the repeat goes to loops/escalate-repeats.jsonl
        sys.path.insert(0, L); import escalate_dedup
        _pn, _sfx = escalate_dedup.apply(note, blocked, L + "/escalate-seen-" + LOOP + ".json", L + "/escalate-repeats.jsonl")
    except Exception: _pn, _sfx = note, blocked >= 3      # the dedup can never hide an escalation: on any failure the old line prints
    print(f"[{LOOP}] {status}: {_pn}" + (" ESCALATE (blocked 3 ticks)" if _sfx else ""))
    sys.exit(0)

def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()

def fetch():
    acts = []; blocked = []
    # Wikipedia parts
    W = ROOT + "/wikipedia-20220501"; todo = [l.split("\t") for l in open(W + "/todo.tsv", encoding="utf-8").read().splitlines() if l.strip()]
    miss = [t for t in todo if not os.path.exists(f"{W}/parts/{t[0]}.ok")]
    if miss and not alive("fetch_part.sh"):
        if spawn(f"bash -c \"awk -F'\\t' '{{print \\$1,\\$2,\\$3}}' wikipedia-20220501/todo.tsv | xargs -P 3 -L 1 wikipedia-20220501/fetch_part.sh\"", ROOT + "/logs/fetch-wiki-restart.log"): acts.append(f"restarted wiki fetch ({len(miss)} parts missing)")
    # Wikisource
    ws = ROOT + "/wikisource-20220501/enwikisource-20220501-pages-articles.xml.bz2"; okf = ws + ".ok"
    if not os.path.exists(okf) and not os.path.exists(ROOT + "/logs/manifests-20261108/wikisource-manifest.jsonl"):   # tombstone: wikisource raw was deleted on purpose (lead 81781); never auto-refetch, refetch only if we use it
        try:
            import urllib.request
            meta = json.load(urllib.request.urlopen("https://archive.org/metadata/enwikisource-20220501", timeout=60))
            f = [x for x in meta["files"] if x["name"].endswith("pages-articles.xml.bz2")][0]
            size = int(f["size"]); sz = os.path.getsize(ws) if os.path.exists(ws) else 0
            if sz < size and not alive("enwikisource-20220501"):
                if spawn(f"curl -sSL -C - --retry 5 --retry-delay 10 -o {ws} https://archive.org/download/enwikisource-20220501/{f['name']}", ROOT + "/logs/fetch-wikisource.log"): acts.append("resumed wikisource")
            elif sz == size:
                if sha256f_sha1(ws) == f["sha1"]: open(okf, "w").write(f["sha1"]); acts.append("wikisource sha1 verified")
                else: blocked.append("wikisource sha1 mismatch (moved .bad)"); shutil.move(ws, ws + ".bad")
        except Exception as e: blocked.append("wikisource check failed: " + type(e).__name__)
    # Stack Exchange 2022-10-05 sites
    BFREE = shutil.disk_usage("B:/").free / 2**30   # GiB. lead 81393: keep B free >= 300 GiB during the H39 window; big downloaders only launch with 340+ GiB free
    sys.path.insert(0, ROOT + "/scripts"); import reserve_plan; BIG_OK = BFREE >= reserve_plan.floor_gib() and shutil.disk_usage('A:/').free / 2**30 >= 12   # rolling-budget rule (lead 81397): downloaders upload+verify+delete raw as they go; hard stop only at the floors
    if BIG_OK and not os.path.exists(ROOT + "/se-20221005/work/ALL.done") and not alive("se_drive.py"):
        if spawn("python scripts/se_drive.py", ROOT + "/logs/se-drive.out"): acts.append("started SE driver")
    # RETIRED (lead 81651, 2026-11-08): per-file LibriVox scale-up and COCO image fetch no longer restart; bulk HF lanes (MLS, PD12M, commoncatalog) replace them.
    if not BIG_OK: acts.append(f"floor guard: B free {BFREE:.1f} GiB / A low: SE/LibriVox held")
    # PG workers
    P = ROOT + "/pg/work"; free = [i for i in range(1, 30) if not os.path.exists(f"{P}/{i:05d}.done") and not os.path.exists(f"{P}/{i:05d}.lock")]
    nw = alive("pg_worker.sh")
    if free and nw < 3:
        ns = sum(1 for _ in range(3 - nw) if spawn("bash scripts/pg_worker.sh", ROOT + "/logs/pg-worker-restart.log"))
        if ns: acts.append(f"started {ns} PG worker(s); {len(free)} shards unclaimed")
    if blocked: done("blocked", "; ".join(blocked))
    wdone = len(glob.glob(W + "/parts/*.ok")); pgd = len(glob.glob(P + "/*.done"))
    done("worked" if acts else "idle", ("; ".join(acts) + "; " if acts else "nothing to restart; ") + f"wiki parts {wdone}/{len(todo)}, PG shards done {pgd}/30")

def sha256f_sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()

def prep():
    acts = []
    W = ROOT + "/wikipedia-20220501"
    todo = [l.split("\t")[0] for l in open(W + "/todo.tsv", encoding="utf-8").read().splitlines() if l.strip()]
    pend = [n for n in todo if os.path.exists(f"{W}/parts/{n}.ok")]
    if pend and not alive("drive_wiki.sh") and os.path.exists(W + "/work") and len(glob.glob(W + "/work/*.done")) < len(todo):
        if spawn("./scripts/drive_wiki.sh", ROOT + "/logs/drive-wiki.log"): acts.append("started wiki part processor")
    # PG packing: consecutive finished shards after the last packed one, in groups of up to 5 (or the tail)
    packed = glob.glob(ROOT + "/packed/pg-*-*"); last = -1
    for p in packed:
        b = os.path.basename(p).split("-")
        if len(b) == 3 and b[1].isdigit() and b[2].isdigit() and os.path.isdir(p) and os.path.exists(p + "/source-manifest.jsonl"): last = max(last, int(b[2]))
    busy = alive("pack_pg.sh") or alive("pack.py")
    run = []; i = last + 1
    while i < 30 and os.path.exists(f"{ROOT}/pg/work/{i:05d}.done") and len(run) < 5: run.append(f"{i:05d}"); i += 1
    if run and not busy and (len(run) >= 3 or i >= 30):
        if spawn("bash scripts/pack_pg.sh " + " ".join(run), ROOT + f"/logs/pack-pg-{run[0]}-{run[-1]}.log"): acts.append(f"packing PG shards {run[0]}..{run[-1]}")
    elif run and not busy: acts.append(f"PG shards {run[0]}..{run[-1]} done, waiting for a group of 3")
    # Wikipedia parts: pack processed parts in groups of >=4 (or the tail), tracked in loops/wiki-packed.json
    wp = L + "/wiki-packed.json"; packed_tags = json.load(open(wp)) if os.path.exists(wp) else {"tags": [], "groups": 0}
    import re as _re
    tags_in_order = []
    for l in open(W + "/todo.tsv", encoding="utf-8").read().splitlines():
        if l.strip():
            n0 = l.split("	")[0]; m0 = _re.search(r"multistream(\d+)\.xml-p(\d+)p(\d+)\.bz2", n0)
            if m0: tags_in_order.append(f"m{m0.group(1)}-p{m0.group(2)}p{m0.group(3)}")
    ready = [t for t in tags_in_order if t not in packed_tags["tags"] and os.path.exists(f"{W}/work/{t}.done")]
    left = [t for t in tags_in_order if t not in packed_tags["tags"]]
    if ready and not busy and not alive("pack_wiki_group.sh") and (len(ready) >= 4 or len(ready) == len(left)):
        grp = ready[:6]; nm = f"wikipedia-20220501-g{packed_tags['groups']:02d}"
        if spawn("bash scripts/pack_wiki_group.sh " + nm + " " + " ".join(grp), ROOT + f"/logs/pack-{nm}.out"):
            packed_tags["tags"] += grp; packed_tags["groups"] += 1; json.dump(packed_tags, open(wp, "w")); acts.append(f"packing Wikipedia {nm} ({len(grp)} parts)")
    done("worked" if any(a.startswith(("started", "packing")) for a in acts) else "idle", "; ".join(acts) or "nothing landed to prep")

def intake():
    new = []; gate_pending = []; gate_refused = []; _gspawn = False
    for p in sorted(glob.glob(ROOT + "/packed/*/")):
        p = p.rstrip("/\\"); name = os.path.basename(p)
        rp = p + "/receipt.json"; sm = p + "/source-manifest.jsonl"
        if not (os.path.exists(rp) and os.path.exists(sm)) or os.path.exists(p + "/intake.json"): continue
        try:      # #2449 item 2 / lead 83284: no intake.json (= not announced, not uploadable) until the degenerate scan and the held-out overlap hold a PASS row on the CURRENT ledger sha
            sys.path.insert(0, ROOT + "/scripts"); import pack_gates; _gs, _gd = pack_gates.status(name, p)
        except Exception as _e: _gs, _gd = "pending", "pack_gates error " + type(_e).__name__
        if _gs != "pass":
            if _gs == "refused": gate_refused.append(name + " (" + _gd + ")")
            else:
                gate_pending.append(name + " (" + _gd + ")")
                if not _gspawn and not alive("pack_gates.py run"): _gspawn = spawn(f"python scripts/pack_gates.py run {name}", ROOT + f"/logs/pack-gates-{name}.log")      # one pack at a time (CPU only)
            continue
        r = json.load(open(rp)); rows = [json.loads(l) for l in open(sm, encoding="utf-8")]
        if any("content_date_max" not in x or "modality" not in x for x in rows): continue
        form = dict(name=name, dataset_id=r["dataset_id"], docs=r["docs"], content_tokens=r["content_tokens"], shards=r["shards"], objects=len(r["objects"]),
                    tokenizer_sha256=r["tokenizer_sha256"], docs_index_sha256=sha256f(p + "/docs-index.jsonl.zst"), ledger_sha256=sha256f(p + "/ledger.jsonl"),
                    source_manifest_sha256=sha256f(sm), content_date_max=max(x["content_date_max"] for x in rows), modality=rows[0]["modality"], path=p, written=time.strftime("%Y-%m-%dT%H:%M:%S"))
        json.dump(form, open(p + "/intake.json", "w"), indent=1); new.append(name)
    for p in sorted(mglob("*/")):
        p = p.rstrip("/\\")
        if os.path.exists(p + "/receipt.json") and not os.path.exists(p + "/intake.json"):
            r = json.load(open(p + "/receipt.json")); json.dump(dict(name=os.path.basename(p), path=p, modality=r["mode"], mode=r["mode"], objects_kept=r["objects_kept"], units_total=r["units_total"], index_sha256=r["index_sha256"], shards=r["shards"]), open(p + "/intake.json", "w"), indent=1); new.append(os.path.basename(p))
    try:
        sys.path.insert(0, ROOT + "/scripts"); import pack_gate; _pg = pack_gate.sweep(); _pgs = " | " + pack_gate.summary(_pg)      # lead 82278: packed = all artifacts present, else in progress or an orphan (moved, receipted)
    except Exception as _e: _pgs = f" | pack_gate error {type(_e).__name__}: {_e}"
    if gate_pending: _pgs += " | GATES_PENDING (not announced, not uploadable): " + "; ".join(gate_pending)
    if gate_refused: _pgs += " | GATE_REFUSED (no intake, never uploaded; rebuild, ESCALATE): " + "; ".join(gate_refused)
    try:   # skill-probe contamination scan (lead 82428): every local text pack is scanned once against the frozen test split; a hit is PROBE_HIT <pack> in this line -> mail lead
        _packs = [os.path.basename(os.path.dirname(x)) for x in glob.glob(ROOT + "/packed/*/objects") if glob.glob(x + "/*.jsonl.zst")]
        if any(not os.path.exists(ROOT + f"/logs/probe-scan-{n}.json") for n in _packs) and not alive("probe_scan_all.py"): spawn("python scripts/probe_scan_all.py", ROOT + "/logs/probe-scan-all.out")
        _hits = []
        for _p in glob.glob(ROOT + "/logs/probe-scan-*.json"):
            try:
                if json.load(open(_p)).get("prompt_hits", 0) > 0: _hits.append(os.path.basename(_p)[11:-5])
            except Exception: pass
        _pgs += f" | probe_scan {len(glob.glob(ROOT + '/logs/probe-scan-*.json'))}/{len(_packs)} packs" + (" PROBE_HIT " + ",".join(sorted(_hits)) if _hits else ", 0 hits")
    except Exception as _e: _pgs += f" | probe_scan error {type(_e).__name__}: {_e}"
    done("worked" if new else "idle", (("NEW_PACKED " + " NEW_PACKED ".join(new)) if new else "no new packed datasets") + _pgs + refresh_listing())

def upload():
    ap = L + "/approved-uploads.json"
    items = json.load(open(ap)) if os.path.exists(ap) else []
    # lead 81232: a packed text set that passed the rules + training's C1/C2 gate (verdict PASS) goes to the PRIVATE train repo automatically
    have = {i["name"] for i in items}
    for ip in sorted(glob.glob(ROOT + "/packed/*/intake.json")):
        nm = os.path.basename(os.path.dirname(ip)); ent = "train-" + nm
        if ent in have or nm == "arxiv-pdf-prewall": continue   # arXiv was uploaded earlier under text/arxiv-pdf (entries arxiv-pdf-prewall-train/raw)
        gates = sorted(glob.glob(f"{M_ROOT}/avir/{SEAT_TRAIN}/state/c1c2-{nm}-*.json"))
        if gates and gate_ok(gates[-1], ip):
            items.append(dict(name=ent, repo=("wordingone/" + HF_TRAIN_REPO), path="text/" + nm, local=os.path.dirname(ip).replace(chr(92), "/"), approved_by="lead 81232 + training c1c2 PASS " + os.path.basename(gates[-1])))
    # media sets (image/audio): same standing rule (lead 81232/81393): rules + training C1/C2 PASS -> private train repo, path <modality>/<name>
    for ip in sorted(mglob("*/intake.json")):
        nm = os.path.basename(os.path.dirname(ip)); ent = "train-" + nm; mod = json.load(open(ip, encoding="utf-8")).get("modality", "image")
        if ent in have or nm == "lv-pilot-v1": continue   # lv-pilot-v1 is a format sample, never registered
        gates = sorted(glob.glob(f"{M_ROOT}/avir/{SEAT_TRAIN}/state/c1c2-{nm}-*.json"))
        if gates and gate_ok(gates[-1], ip):
            items.append(dict(name=ent, repo=("wordingone/" + HF_TRAIN_REPO), path=mod.split("-")[0] + "/" + nm, local=os.path.dirname(ip).replace(chr(92), "/"), approved_by="standing rule (lead 81232/81393): rules + training c1c2 PASS " + os.path.basename(gates[-1])))
    if os.path.exists(ROOT + "/loops/RESTORE-PRIORITY.flag"): done("held", "uploads HELD while RESTORE-PRIORITY.flag exists (training 82037 / lead 82035: the uplink is saturated; restore first)")
    sys.path.insert(0, ROOT + "/scripts"); import upload_refuse      # lead 82100: pre-redaction originals never upload
    _ref = [i for i in items if upload_refuse.refused(i["local"])]; items = [i for i in items if i not in _ref]
    if _ref: bad_ref = "; ".join(i["name"] for i in _ref)
    todo = [i for i in items if not i.get("verified")]
    if not todo: done("idle", "no batch pending: nothing newly C1/C2-PASSed (standing rule: private uploads auto-start on rules + training C1/C2 PASS)")
    acts = []; bad = []; skipped = []
    _lst = {}      # PR 2467 review note 8: ONE process listing per tick (built on first use, result or failure cached), not one per pack
    def _pids(n):
        if "v" not in _lst:
            try: _lst["v"] = ("ok", scan_listing())
            except Exception as _e: _lst["v"] = ("err", _e)
        if _lst["v"][0] == "err": raise _lst["v"][1]
        return scan_pids(n, _lst["v"][1])
    try: from huggingface_hub import HfApi
    except Exception as e: done("blocked", "huggingface_hub import failed")
    api = HfApi()
    def _other_push_alive(me):      # owner load cut (lead 83126): ONE hf upload at a time on this desktop; the pack pushes of the tick are resumable, so a waiting item loses nothing
        try:
            import psutil
            for _p in psutil.process_iter(["cmdline"]):
                _c = " ".join(_p.info["cmdline"] or [])
                if "hf.exe upload" in _c and me not in _c: return True
        except Exception: return False
        return False
    for it in todo:
        if it.get("hold"): acts.append(f"{it['name']}: HELD ({str(it['hold'])[:80]})"); continue      # per-item hold written by the lane (a rebuilt pack replaces it); never pushed while set
        _lp = it["local"].replace(chr(92), "/").rstrip("/")
        _rootn = ROOT.replace(chr(92), "/").rstrip("/")      # both sides normalised (#2478 review): a backslash EMBER_LANE_ROOT must not skip the gate
        if _lp.lower().startswith(_rootn.lower() + "/packed/"):      # #2449 item 2: gate on LOCATION, not on a ledger being present: the upload gate refuses a text pack without a current degenerate+held-out PASS (media packs live under media-packed/ and have their own gates)
            try: sys.path.insert(0, ROOT + "/scripts"); import pack_gates; _gs, _gd = pack_gates.status(os.path.basename(_lp), _lp)
            except Exception as _e: _gs, _gd = "pending", "pack_gates error " + type(_e).__name__
            if _gs != "pass":
                if _gs == "refused": bad.append(f"{it['name']}: NOT PUSHED, pack gate {_gd} (ESCALATE)")
                else:
                    acts.append(f"{it['name']}: NOT PUSHED, pack gates pending ({_gd})")
                    if os.path.exists(_lp + "/ledger.jsonl") and not alive("pack_gates.py run"): spawn(f"python scripts/pack_gates.py run {os.path.basename(_lp)}", ROOT + f"/logs/pack-gates-{os.path.basename(_lp)}.log")      # no ledger = nothing to run yet: pending
                continue
        if alive(f"hf upload {it['repo']} {it['local']} {it['path']}") or alive(f"hf.exe upload {it['repo']} {it['local']} {it['path']}"): acts.append(f"{it['name']}: upload in progress"); continue
        if _other_push_alive(it["local"]): acts.append(f"{it['name']}: waits (one upload at a time, lead 83126)"); continue
        try: tree = {t.path: t for t in api.list_repo_tree(it["repo"], repo_type="dataset", path_in_repo=it["path"], recursive=True) if hasattr(t, "size")}
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e): tree = {}
            else: bad.append(f"{it['name']}: HF listing failed {type(e).__name__}"); continue
        loc = [os.path.join(dp, f) for dp, _, fs in os.walk(it["local"]) for f in fs]
        miss = []; shabad = []
        for f in loc:
            rel = it["path"].rstrip("/") + "/" + os.path.relpath(f, it["local"]).replace(chr(92), "/")
            if any(rel.endswith(x) for x in it.get("ignore_paths", [])): continue
            t = tree.get(rel)
            if t is None: miss.append(rel); continue
            if getattr(t, "lfs", None) and t.lfs.sha256 != sha256f(f): shabad.append(rel)
            elif not getattr(t, "lfs", None) and t.size != os.path.getsize(f): shabad.append(rel)
        shabad = [x for x in shabad if not x.endswith("source-manifest.jsonl")] if it.get("manifest_reemit_ok") else shabad   # lead 81232: manifest re-emits with unchanged docs-index/ledger shas may replace the HF copy by hand; tick never overwrites
        if shabad: bad.append(f"{it['name']}: {len(shabad)} file(s) differ from the HF copy (never overwritten without lead approval): {shabad[:2]}")
        elif miss:
            sys.path.insert(0, ROOT + "/scripts"); import th_pack_scan      # operator / lead 81934: TruffleHog pre-upload gate on EVERY repo, fail-closed; push only on a clean scan of the CURRENT file set (path + byte size signature, not content)
            import pack_scan_status as _pss      # lead 82613 item 3: one function names the scan state; 'unknown' is never printed as 'running'
            _st, _sd = _pss.pack_scan_status(it["name"], it["local"], ROOT + "/logs/th-scan", th_pack_scan.signature, _pids)
            _tries = int(it.get("scan_tries", 0) or 0)
            _dec = _pss.push_decision(_st, bool(it.get("scan_pass") or it.get("started")), _tries, _pss.LOOKUP_FAILED in _sd)      # was-PASS = scan_pass OR started (items pushed before scan_pass existed carry only `started`)
            # lead 82933 class fix: the decision comes BEFORE the cap check and the push, and ANYTHING other than "push" never pushes (PR 2467 review note 1).
            if _dec != "push":
                if _st in ("clean", "refused_hits"): it.pop("scan_tries", None); it.pop("scan_escalated", None)      # a definitive verdict resets the bounded-retry state
                if _dec == "rescan":
                    try: _alive = _pids(it["name"])      # alive-guard: never spawn while a scan of this pack runs; a failed lookup spawns nothing
                    except Exception: _alive = None
                    if _alive is None or _alive: skipped.append(_pss.status_line(it["name"], "unknown", _pss.LOOKUP_FAILED if _alive is None else "scan process alive"))
                    elif spawn(f"python scripts/th_pack_scan.py {it['name']} {it['local']}", ROOT + f"/logs/th-scan-{it['name']}.log"):
                        it["scan_tries"] = _tries + 1; acts.append(f"{it['name']}: TruffleHog pre-upload scan started (try {it['scan_tries']}/{_pss.MAX_SCAN_TRIES}; state {_st})")
                    else: skipped.append(_pss.status_line(it["name"], _st, _sd) + " (scan start deferred)")
                elif _dec == "escalate":
                    bad.append(_pss.status_line(it["name"], _st, _sd) + (" (was PASS earlier: ESCALATE)" if _st == "refused_hits" else " (%d scans started without a verdict: ESCALATE)" % _tries))
                    if _st != "refused_hits" and not it.get("scan_escalated"):
                        try:
                            sys.path.insert(0, ROOT + "/scripts"); import mb_send
                            mb_send.send(SEAT_LEAD, f"SCAN STUCK: {it['name']}", f"{it['name']}: {_st} after {_tries} TruffleHog scans started ({_sd}); nothing uploaded. Needs a look at logs/th-scan-{it['name']}.log.")
                            it["scan_escalated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        except Exception as _e: bad.append(f"{it['name']}: scan-stuck mail failed {type(_e).__name__}")
                else: skipped.append(_pss.status_line(it["name"], _st, _sd))      # wait / skip
                continue
            sys.path.insert(0, ROOT + "/scripts"); import defender_guard as _dg      # lead 83073 interim: a clean verdict counts only with no Defender detection on scan scratch in its window (TruffleHog rc 0 on a vanished part); cannot check = no push
            _gok, _gwhy = _dg.check(ROOT + "/logs/th-scan/" + it["name"] + ".json")
            if not _gok: bad.append(f"{it['name']}: NOT PUSHED, {_gwhy}"); continue
            it.pop("scan_tries", None); it.pop("scan_escalated", None)
            it["scan_pass"] = time.strftime("%Y-%m-%dT%H:%M:%S")      # a clean verdict for the current file set was seen for this item
            mb = sum(os.path.getsize(f) for f in loc if (it["path"].rstrip("/") + "/" + os.path.relpath(f, it["local"]).replace(chr(92), "/")) in miss)
            sys.path.insert(0, ROOT + "/scripts"); import hf_cap
            if it["repo"].endswith("-private") and not hf_cap.check(mb, f"pack push {it['name']}", f"{len(miss)} files"): bad.append(f"{it['name']}: PRIVATE CAP HOLD (push {mb/1e9:.1f} GB not started; lead mailed)"); continue   # lead 81851 hard guard
            if not it.get("started") or it.get("restarts", 0) < 5:   # class fix: a pack push that died/was stopped (wedged socket restart) is relaunched; hf upload is resumable and never overwrites; capped at 5 relaunches
                if it.get("started"): it["restarts"] = it.get("restarts", 0) + 1
                if spawn(f"hf upload {it['repo']} {it['local']} {it['path']} --repo-type dataset", ROOT + f"/logs/hf-upload-{it['name']}.log"): it["started"] = True; acts.append(f"{it['name']}: upload {'re' if it.get('restarts') else ''}started ({len(miss)} missing)")
            else: bad.append(f"{it['name']}: still missing {len(miss)} after {it.get('restarts', 0)} relaunches")
        else:
            it["verified"] = time.strftime("%Y-%m-%dT%H:%M:%S"); acts.append(f"{it['name']}: VERIFIED {len(loc)} files vs HF")
            if it["repo"] == ("wordingone/" + HF_TRAIN_REPO) and it["path"].startswith("text/"):      # lead 82379(4)/82381: a set is dropped locally the moment its upload is server-verified, then lead is mailed
                try:
                    sys.path.insert(0, ROOT + "/scripts"); import drop_uploaded
                    _r, _m = drop_uploaded.run(it["local"], it["repo"], it["path"], go=True); acts.append("DROPPED " + _m); it["dropped"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    try:      # Hub binding (queue item, caselaw-00003-00004 lost PASS 11-11 03:18..05:44): the Hub-listing signature of the pack just dropped is written by code, never by hand
                        import hub_binding as _hb; _hbr = _hb.refresh_one(it["path"].split("/")[1])
                        acts.append("hub binding " + (("refreshed" + ("" if _hbr.get("row_sig_eq_hub") else " (scan row signature differs from the Hub listing: the listing will say NOT RUN)")) if _hbr["ok"] else "NOT refreshed: " + _hbr["why"]))
                        if not _hbr["ok"]: bad.append(f"{it['name']}: hub binding not refreshed ({_hbr['why']})")
                    except Exception as _e: bad.append(f"{it['name']}: hub binding refresh failed {type(_e).__name__}")
                    import mb_send; mb_send.send(SEAT_LEAD, f"SET UPLOADED + DROPPED: {it['name']} ({_r['dropped_bytes']/2**30:.2f} GiB freed)", _m + ("; kept: " + "; ".join(f"{os.path.basename(p)} ({w})" for p, w in _r['kept'][:5]) if _r["kept"] else ""))
                except Exception as e: bad.append(f"{it['name']}: verified but drop failed {type(e).__name__} {str(e)[:120]}")
    json.dump(items, open(ap, "w"), indent=1)
    _sk = (" | skipped by scan state (no push attempted, no mail): " + "; ".join(skipped)) if skipped else ""
    _rl = refresh_listing()
    if bad and not acts: done("blocked", "; ".join(bad) + _sk + _rl)
    done("worked" if (acts or bad) else "idle", ("; ".join(acts + bad) or "nothing to push") + _sk + _rl)

def census():
    tot = dict(text_content_tokens=0, datasets=[]);
    for p in sorted(glob.glob(ROOT + "/packed/*/receipt.json")):
        r = json.load(open(p)); tot["text_content_tokens"] += r["content_tokens"]; tot["datasets"].append([r["name"], r["content_tokens"]])
    tot["media"] = [[json.load(open(p))["name"], json.load(open(p))["units_total"]] for p in sorted(mglob("*/receipt.json"))]
    tot["pg_done"] = len(glob.glob(ROOT + "/pg/work/*.done")); tot["wiki_parts_ok"] = len(glob.glob(ROOT + "/wikipedia-20220501/parts/*.ok"))
    tot["wiki_parts_processed"] = len(glob.glob(ROOT + "/wikipedia-20220501/work/*.done"))
    tot["b_free_gb"] = round(shutil.disk_usage("B:/").free / 1e9)
    cp = L + "/census-local-latest.json"; prev = json.load(open(cp)) if os.path.exists(cp) else {}
    json.dump(dict(tot, ts=time.strftime("%Y-%m-%dT%H:%M:%S")), open(cp, "w"), indent=1)
    d = tot["text_content_tokens"] - prev.get("text_content_tokens", 0)
    # lead 81645: HF inventory (the data authority) on every census tick -> census/census-latest.json; runs detached under the lane cap
    inv = ""
    if alive_py("hf_inventory.py") == 0: spawn("python scripts/hf_inventory.py --quiet", "logs/hf-inventory.log")
    try:
        hj = json.load(open(ROOT + "/census/census-latest.json")); tt = hj["totals"]
        inv = " | HF[" + hj["ts"] + "] train-ready text " + f"{tt['train_ready/text']['tokens']/1e9:.2f}B tok, raw text {tt['raw/text']['bytes']/2**30:.0f} GiB, images {tt.get('raw/image',{}).get('images',0)}, audio {tt.get('raw/audio',{}).get('hours_est',0):.0f} h est, video 0, overlap items " + str(sum(v['overlap_items'] for v in hj['unique'].values()))
        sp = tt.get('superseded/text')
        if sp: inv += f" (undeclared; declared supersession pairs excluded) | superseded (kept for provenance, lead 81767) {sp.get('packs',0)} packs {sp.get('tokens',0)/1e9:.2f}B tok"
    except Exception as e: inv = f" | HF inventory not yet readable ({e})"
    # lead 81661: private used / 1 TB on every census line; per-lane GiB/day; at 85% -> ESCALATE
    try:
        hj = json.load(open(ROOT + "/census/census-latest.json")); pu = hj["repos"]["raw"]["used_storage_bytes"] + hj["repos"]["train"]["used_storage_bytes"]
        inv += f" | private used {pu/1e9:.0f}/1000 GB ({pu/1e10:.1f}%)" + (" ESCALATE quota>=85%" if pu >= 0.85e12 else "")
        # lead 81773: the one number that counts = HF usedStorage growth over the last ~2 h, GB/day per repo (history appended once per new HF inventory ts)
        try:
            hp = ROOT + "/census/used-history.jsonl"; hist = [json.loads(l) for l in open(hp)] if os.path.exists(hp) else []
            cur = dict(ts=hj["ts"], raw=hj["repos"]["raw"]["used_storage_bytes"], train=hj["repos"]["train"]["used_storage_bytes"], public=hj["repos"]["public"]["used_storage_bytes"], private_total=pu)
            if not hist or hist[-1]["ts"] != cur["ts"]:
                open(hp, "a").write(json.dumps(cur) + chr(10)); hist.append(cur)
            import calendar
            tsec = lambda z: calendar.timegm(time.strptime(z, "%Y-%m-%dT%H:%M:%SZ"))
            base = next((h for h in reversed(hist[:-1]) if tsec(cur["ts"]) - tsec(h["ts"]) >= 7000), hist[0] if len(hist) > 1 else None)
            if base and base["ts"] != cur["ts"]:
                dt = (tsec(cur["ts"]) - tsec(base["ts"])) / 86400
                g = lambda k: ((cur[k] - base[k]) / 1e9 / dt) if k in base else None
                pt = (cur["private_total"] - base["private_total"]) / 1e9 / dt
                parts = [f"private {pt:.0f}"] + [f"{k} {g(k):.0f}" for k in ("raw", "train", "public") if g(k) is not None]
                inv += f" | HF landed GB/day over {dt*24:.1f} h: " + ", ".join(parts)
        except Exception as e: inv += f" | HF growth n/a ({type(e).__name__})"
    except Exception: pass
    if os.path.exists(L + "/QUOTA-85.flag"): inv += " ESCALATE quota flag: " + open(L + "/QUOTA-85.flag").read().strip()
    # lead 81663: link-wide down/up MB/s (mean since previous census tick, from Wi-Fi adapter counters) + per-lane stored MB/s (progress events, last 60 min)
    try:
        o = subprocess.run(["powershell", "-NoProfile", "-Command", "$s=Get-NetAdapterStatistics -Name 'Wi-Fi'; \"$($s.ReceivedBytes) $($s.SentBytes)\""], capture_output=True, text=True, timeout=30).stdout.split()
        rx, tx, now = int(o[0]), int(o[1]), time.time(); npth = L + "/net-last.json"; pn = json.load(open(npth)) if os.path.exists(npth) else None
        json.dump(dict(rx=rx, tx=tx, t=now), open(npth, "w"))
        if pn and rx >= pn["rx"] and now - pn["t"] > 30: inv += f" | link down {(rx-pn['rx'])/(now-pn['t'])/1e6:.2f} MB/s, up {(tx-pn['tx'])/(now-pn['t'])/1e6:.2f} MB/s (mean over {(now-pn['t'])/60:.0f} min)"
    except Exception: pass
    def _stored_mbps(ln):
        try:
            ev = json.load(open(f"{ROOT}/bulk/{ln}/progress.json")).get("events", []); w = [b for t, b in ev if t > time.time() - 3600]
            return f"{ln} stored {sum(w)/3600/1e6:.2f} MB/s ({sum(w)/2**30*24:.1f} GiB/day at that rate)"
        except Exception: return None
    inv += " | stored/60min: " + "; ".join(x for x in (_stored_mbps(ln) for ln in ("mls", "ccby", "pd12m", "pre1929", "caselaw", "hansard", "usgpo", "loc", "pes2o", "pubmed") if os.path.exists(f"{ROOT}/bulk/{ln}/progress.json")) if x)
    inv += " | lanes: " + "; ".join(f"{ln} {_bulk_prog(ln)}" for ln in ("mls", "ccby", "pd12m", "pre1929", "caselaw", "hansard", "usgpo", "loc", "pes2o", "pubmed") if os.path.exists(f"{ROOT}/bulk/{ln}/progress.json"))
    done("worked" if d else "idle", f"packed text {tot['text_content_tokens']/1e6:.1f}M tok (delta {d/1e6:+.1f}M), media sets {len(tot['media'])}, PG done {tot['pg_done']}/30, wiki parts {tot['wiki_parts_ok']} fetched/{tot['wiki_parts_processed']} processed, B: free {tot['b_free_gb']} GB{inv}")

{"fetch": fetch, "prep": prep, "intake": intake, "upload": upload, "census": census}[LOOP]()

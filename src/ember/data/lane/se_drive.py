# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stack Exchange 2022-10-05 driver (resumable, sequential, CPU-light): for each site .7z (smallest first; stackoverflow.com-Posts last; PostHistory/Votes/Comments/Badges/Users skipped)
download (curl -C -) -> sha1 verify vs archive.org metadata -> se_prep -> scrub (full index + wiki2M + arXiv heldout hashes) -> dedup. Marker se-20221005/work/<site>.done.
The .7z archives stay in se-20221005/ until the raw upload step deletes them. Usage: se_drive.py [MAX_SITES]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys, os, json, subprocess, hashlib, time, urllib.request
import shutil
pass; import raw_roll
from lane_config import LANE_ROOT as ROOT; OLD = ROOT + "/se-20221005"; D = "A:/ember-stage/se-20221005"; W = D + "/work"; os.makedirs(W, exist_ok=True)   # B: is floor-limited (lead 81393/81397): new work on A:, markers in both
MAXS = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
meta = json.load(urllib.request.urlopen("https://archive.org/metadata/stackexchange_20221005", timeout=120))
fs = [f for f in meta["files"] if f["name"].endswith(".7z") and not any(k in f["name"] for k in ("-PostHistory", "-Votes", "-Comments", "-Badges", "-Users", "-PostLinks", "-Tags"))]
fs.sort(key=lambda f: (f["name"] == "stackoverflow.com-Posts.7z", int(f["size"])))
env = dict(os.environ, HELDOUT_EXTRA=f"{ROOT}/heldout-index/wiki-heldout-2M.npy,{ROOT}/arxiv/heldout-pdf-sent-hashes.npy")
def sha1f(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()
def log(*a):
    with open(ROOT + "/logs/se-drive.log", "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(map(str, a)) + "\n")
for f in fs:
    zo = f"{OLD}/{f['name']}"; sn = f["name"][:-3]
    if os.path.exists(zo) and os.path.exists(f"{OLD}/work/{sn}.done"):
        try: raw_roll.roll([(zo, "text/stackexchange-20221005/" + f["name"])], message="stackexchange 20221005 catch-up " + sn); log(sn, "catch-up raw rolled")
        except Exception as e: log(sn, "catch-up roll failed", type(e).__name__, str(e)[:120])
n = 0
for f in fs:
    site = f["name"][:-3]; zp = f"{D}/{f['name']}"
    if os.path.exists(f"{W}/{site}.done") or os.path.exists(f"{OLD}/work/{site}.done"): continue
    if n >= MAXS: break
    n += 1; size = int(f["size"])
    if shutil.disk_usage("A:/").free < size * 2 + 10 * 2**30: log(site, "A: budget (need size*2+10GiB); stopping until space frees"); break
    for t in range(3):
        if not os.path.exists(zp) or os.path.getsize(zp) != size:
            subprocess.run(["curl", "-sSL", "-C", "-", "--retry", "5", "--retry-delay", "10", "-o", zp, f"https://archive.org/download/stackexchange_20221005/{f['name']}"])
        if os.path.exists(zp) and os.path.getsize(zp) == size and sha1f(zp) == f["sha1"]: break
        log(site, "BAD download try", t); os.replace(zp, zp + f".bad{t}") if os.path.exists(zp) else None
    else:
        log(site, "FAILED download"); continue
    steps = [["python", f"{ROOT}/scripts/se_prep.py", zp, f"{W}/{site}-prep.jsonl.zst"], ["python", f"{ROOT}/scripts/scrub.py", f"{W}/{site}-prep.jsonl.zst", f"{W}/{site}-scrub.jsonl.zst"],
             ["python", f"{ROOT}/scripts/dedup.py", f"{W}/{site}-scrub.jsonl.zst", f"{W}/{site}-final.jsonl.zst"]]
    ok = True
    for s in steps:
        r = subprocess.run(s, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log(site, os.path.basename(s[1]), r.returncode, (r.stdout or "").strip()[-300:], (r.stderr or "").strip()[-200:])
        if r.returncode != 0: ok = False; break
    if ok:
        open(f"{W}/{site}.done", "w").write(f["sha1"])
        for k in ("prep", "scrub"):
            p = f"{W}/{site}-{k}.jsonl.zst"
            if os.path.exists(p): os.remove(p)
        log(site, "DONE")
        try:
            res = raw_roll.roll([(zp, "text/stackexchange-20221005/" + f["name"])], message="stackexchange 20221005 " + site); log(site, "raw rolled", res and res[0].get("ok"))
        except Exception as e: log(site, "raw roll failed", type(e).__name__, str(e)[:150])
if all(os.path.exists(f"{W}/{f['name'][:-3]}.done") or os.path.exists(f"{OLD}/work/{f['name'][:-3]}.done") for f in fs): open(f"{OLD}/work/ALL.done", "w").write(str(len(fs)))
log("driver finished", n, "sites this run")

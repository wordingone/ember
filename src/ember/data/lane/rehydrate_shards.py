# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rehydrate the packed token shards that clear_uploaded_shards.py evicted but an admitted-not-yet-trained intake still needs (lead 82108). Plan: logs/rehydrate-plan-20261109.json (path, hf, size, sha256).
Waits (reserve_plan.harm_wait, link only) while RESTORE-PRIORITY.flag exists, then downloads each shard from wordingone/<train-repo> to a tmp file, requires sha256 == plan, os.replace into packed/<pack>/shards/. Skips files already present with the right size+sha. Stops (does not fill B:) when free would drop under reserve_plan.floor_gib()+1.
2 workers, BelowNormal. Log: logs/rehydrate-shards.log. Usage: python scripts/rehydrate_shards.py [--wait]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, hashlib, shutil
pass
import reserve_plan
from lane_config import LANE_ROOT as ROOT; REPO = ("wordingone/" + HF_TRAIN_REPO); PLAN = ROOT + "/logs/rehydrate-plan-20261109.json"; LOG = ROOT + "/logs/rehydrate-shards.log"
def log(*a):
    with open(LOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(map(str, a)) + "\n")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""): h.update(c)
    return h.hexdigest()
def one(x):
    import net_cap as _nc
    hf_hub_download = lambda repo, path, repo_type='dataset', local_dir='.': _nc.download(repo, path, local_dir=local_dir, repo_type=repo_type)
    p = x["path"]
    if os.path.exists(p) and os.path.getsize(p) == x["size"] and sha(p) == x["sha256"]: return "present"
    if shutil.disk_usage("B:/").free / 2**30 - x["size"] / 2**30 < reserve_plan.floor_gib() + 1: return "floor"
    tmpd = ROOT + "/scratch/rehydrate-tmp"; os.makedirs(tmpd, exist_ok=True)
    key = x["hf"].split(":", 1)[1]
    got = hf_hub_download(REPO, key, repo_type="dataset", local_dir=tmpd)
    if sha(got) != x["sha256"]: os.remove(got); return "SHA-MISMATCH"
    os.makedirs(os.path.dirname(p), exist_ok=True); os.replace(got, p); return "restored"
def main():
    try: os.nice(10)
    except Exception: pass
    plan = json.load(open(PLAN)); log("plan", len(plan), "shards", round(sum(x["size"] for x in plan) / 2**30, 2), "GiB")
    reserve_plan.harm_wait("rehydrate_shards", log, cap_s=10 ** 9, kinds=("link",), poll_s=30)
    from concurrent.futures import ThreadPoolExecutor
    cnt = {}
    def run(x):
        try: r = one(x)
        except Exception as e: r = "error:" + str(e)[:80]
        cnt[r.split(":")[0]] = cnt.get(r.split(":")[0], 0) + 1
        if r not in ("restored", "present"): log(r, x["path"])
        if sum(cnt.values()) % 100 == 0: log("progress", cnt)
        return r
    with ThreadPoolExecutor(2) as ex: list(ex.map(run, plan))
    log("DONE", cnt); print("DONE", cnt)
if __name__ == "__main__": main()

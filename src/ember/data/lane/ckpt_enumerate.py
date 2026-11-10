# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Enumerate trained-child dirs with weights under ember-live-receipts (read-only) -> logs/ckpt-old.json (pre-Nov hour/probe children + Nov hour child 9db1d785) and logs/ckpt-probes.json (Nov probe children).
Excludes the 7 children handled by ckpt_children.CH. id8 = sha256(checkpoint-manifest.json)[:8]."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, glob, hashlib, json, time, sys
pass; from ckpt_children import CH
have = {v[0] for v in CH.values()}; BS = chr(92); old = []; probes = []; seen = set()
for d in sorted(glob.glob((M_ROOT + "/ember-live-receipts/*/measurement-*/trained-child"))):
    d = d.replace(BS, "/"); m = d + "/checkpoint-manifest.json"
    if not os.path.exists(m) or not (os.path.isdir(d + "/objects") and os.listdir(d + "/objects")): continue
    i8 = hashlib.sha256(open(m, "rb").read()).hexdigest()[:8]
    if i8 in have or i8 in seen: continue
    seen.add(i8); sz = nl1 = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            s = os.stat(os.path.join(dp, f)); sz += s.st_size; nl1 += s.st_size if s.st_nlink == 1 else 0
    hour = d.split("/")[-3]; kind = "probe" if "-probe-" in hour else "hour"; stamp = hour.rsplit("-", 1)[-1]
    row = dict(name=f"O-{kind}-{stamp}", id8=i8, dir=d, bytes=sz, nlink1_bytes=nl1, mtime=time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(m))))
    (probes if kind == "probe" and stamp >= "20261101" else old).append(row)
for d in sorted(glob.glob((M_ROOT + "/ember-live-receipts/cia-probe-*/measurement-*/.checkpoint-quarantine/candidate-trained-child-*"))):   # lead ruling 82451: a failed probe write leaves its candidate child here
    d = d.replace(BS, "/"); stamp = d.split("/")[-4].rsplit("-", 1)[-1]
    if not os.path.isdir(d) or stamp < "20261101": continue
    sz = nl1 = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            s = os.stat(os.path.join(dp, f)); sz += s.st_size; nl1 += s.st_size if s.st_nlink == 1 else 0
    if sz: probes.append(dict(name=f"O-probe-{stamp}-quarantine", id8=hashlib.sha256(d.encode()).hexdigest()[:8], dir=d, bytes=sz, nlink1_bytes=nl1, mtime=time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(d)))))
json.dump(old, open((LANE_ROOT + "/logs/ckpt-old.json"), "w"), indent=1); json.dump(probes, open((LANE_ROOT + "/logs/ckpt-probes.json"), "w"), indent=1)
print("older (upload+verify, delete after training window):", len(old), round(sum(r["bytes"] for r in old) / 2**30, 1), "GiB, nlink1", round(sum(r["nlink1_bytes"] for r in old) / 2**30, 1))
print("Nov probes (delete w/o upload after training confirms):", len(probes), round(sum(r["bytes"] for r in probes) / 2**30, 1), "GiB, nlink1", round(sum(r["nlink1_bytes"] for r in probes) / 2**30, 1))

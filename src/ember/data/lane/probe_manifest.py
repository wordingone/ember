# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only manifest of the terminal-probe payload reclaim class (lead ruling 82451, branch (c) of ckpt_lineage_delete.py only).
Usage: python scripts/probe_manifest.py [out.json]
For every entry of logs/ckpt-probes.json (written by ckpt_enumerate.py, incl. quarantine dirs) it asks probe_terminal_guard.probe_eligibility and, for each ELIGIBLE probe, lists
path, bytes (unique inodes, files >= 1 MiB whose every hard-link name is inside the selected set: the same rule as ckpt_lineage_delete.py), consumer hours, their terminal receipts and
the clause that passed. Refused probes are listed with the stable refusal code. Never removes, writes (except the output json) or calls the network."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_terminal_guard as PG, evict_ckpt_list as EK
OUT = sys.argv[1] if len(sys.argv) > 1 else (LANE_ROOT + "/logs/probe-manifest.json")
BIG = 1 << 20
probes = json.load(open((LANE_ROOT + "/logs/ckpt-probes.json")))
elig, refused = [], []
for r in probes:
    g = PG.probe_eligibility(r["dir"], kept=EK.kept)
    (elig if g["ok"] else refused).append((r, g))
cand = []
for r, g in elig:
    for dp, _, fs in os.walk(r["dir"]):
        for f in fs:
            p = os.path.join(dp, f); st = os.stat(p); cand.append((r["name"], p, st.st_size, (st.st_dev, st.st_ino), st.st_nlink))
inset = collections.Counter(c[3] for c in cand)
per = collections.defaultdict(lambda: dict(files=0, bytes=0, shared_outside_files=0, shared_outside_bytes=0, small_files=0))
seen = set()
for name, p, sz, ino, nl in cand:
    d = per[name]
    if sz < BIG: d["small_files"] += 1; continue
    if inset[ino] != nl: d["shared_outside_files"] += 1; d["shared_outside_bytes"] += sz; continue
    d["files"] += 1
    if ino not in seen: seen.add(ino); d["bytes"] += sz
rows = []
for r, g in elig:
    d = per[r["name"]]
    rows.append(dict(name=r["name"], path=r["dir"].replace("\\", "/"), bytes=d["bytes"], files=d["files"], shared_outside_files=d["shared_outside_files"], shared_outside_bytes=d["shared_outside_bytes"], small_files=d["small_files"],
                     consumer_hours=[dd.replace("\\", "/") for k, dd in g["consumers"] if k == "hour"], stale_refs=[dd.replace("\\", "/") for k, dd in g["consumers"] if k == "ref"],
                     terminal_receipts=[t.replace("\\", "/") for t in (g["terminal_receipt"] or [])], clause=g["clause"]))
out = dict(generated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), eligible=rows, refused=[dict(name=r["name"], path=r["dir"].replace("\\", "/"), bytes=r["bytes"], reason=g["reason"], consumer_hours=[dd.replace("\\", "/") for k, dd in g["consumers"] if k == "hour"]) for r, g in refused],
           eligible_bytes=sum(x["bytes"] for x in rows), refused_bytes=sum(r["bytes"] for r, _ in refused))
json.dump(out, open(OUT, "w"), indent=1)
for x in rows:
    print("ELIGIBLE %-34s %7.2f GiB files %-4d %s | hours %s | terminal %s" % (x["name"], x["bytes"] / 2**30, x["files"], x["clause"].split(":")[0], [os.path.basename(h).rsplit("-", 1)[-1] for h in x["consumer_hours"]], [os.path.basename(os.path.dirname(t)) and os.path.basename(t) for t in x["terminal_receipts"]]))
for r, g in refused:
    print("REFUSED  %-34s %7.2f GiB %s" % (r["name"], r["bytes"] / 2**30, g["reason"]))
print("eligible %.2f GiB in %d probes | refused %.2f GiB in %d probes | out %s" % (out["eligible_bytes"] / 2**30, len(rows), out["refused_bytes"] / 2**30, len(refused), OUT))

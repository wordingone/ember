# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""H39 ancestor closure (lead 81958): walk lineage.parent_checkpoint upward from a bound child, and list which files of each ancestor our delete manifests removed.
Usage: python ckpt_chain.py [CHILD=H39]  -> prints the chain and writes logs/h39-chain.json {chain:[{dir,parent_manifest_sha8,deleted:[rows]}]}"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import json, sys, os, collections
pass
import ckpt_children as C

BS = chr(92)


def norm(p):
    return p.replace(BS, "/")


def deleted_rows():
    rows = []
    for f in ("ckpt-lineage-delete-manifest.jsonl", "ckpt-delete-manifest.jsonl"):
        p = (LANE_ROOT + "/logs/manifests-20261108/") + f
        if os.path.exists(p):
            rows += [json.loads(l) for l in open(p) if l.strip()]
    seen = {}
    for r in rows:
        seen[norm(r["path"])] = r
    return [r for p, r in seen.items() if not os.path.exists(p)]


def child_dir(path):
    path = norm(path)
    i = path.find("/trained-child")
    return path[: i + len("/trained-child")] if i >= 0 else os.path.dirname(path)


def chain(start_dir):
    d = norm(start_dir); out = []; seen = set()
    while d and d not in seen:
        seen.add(d); mp = d + "/checkpoint-manifest.json"
        if not os.path.exists(mp):
            out.append(dict(dir=d, parent=None, note="MANIFEST MISSING")); break
        m = json.load(open(mp)); lin = m.get("lineage") or {}
        out.append(dict(dir=d, parent=(lin.get("parent_manifest_sha256") or "")[:8] or None, note=""))
        pc = lin.get("parent_checkpoint")
        d = norm(pc) if pc else None
    return out


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "H39"
    dels = collections.defaultdict(list)
    for r in deleted_rows():
        dels[child_dir(r["path"])].append(r)
    ch = chain(C.CH[name][1]); tot = 0; n = 0
    for c in ch:
        c["deleted"] = dels.get(c["dir"], []); b = sum(r["size"] for r in c["deleted"]); tot += b; n += len(c["deleted"])
        print(os.path.basename(os.path.dirname(c["dir"]))[-34:], "parent", c["parent"], "deleted", len(c["deleted"]), "files", round(b / 2 ** 30, 2), "GiB", c["note"])
    print("chain length", len(ch), "| files to restore", n, "| GiB", round(tot / 2 ** 30, 2))
    json.dump(ch, open((LANE_ROOT + "/logs/%s-chain.json") % name.lower(), "w"), indent=1)

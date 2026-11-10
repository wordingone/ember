# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Delete the local pg-*/objects files whose private copy is on HF (lead 81864; training 81861: shards/ stay). #2454: per file, in the remove call, the server entry is read back NOW (size AND LFS sha256), the local sha256 is recomputed NOW
and the receipt row is fsynced BEFORE the os.remove (verified_remove.remove_verified); a file without a verifying server copy stays and is reported, the others still go (each file carries its own proof). Nothing runs on import:
`python _pg_obj_del.py` is a DRY RUN that verifies and deletes nothing, `--go` deletes. Plan manifest: logs/manifests-20261108/pg-objects-manifest.jsonl, receipts: logs/manifests-20261108/pg-objects-receipts.jsonl."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verified_remove as VR
REPO = ("wordingone/" + HF_TRAIN_REPO); PACKED = (LANE_ROOT + "/packed"); MD = (LANE_ROOT + "/logs/manifests-20261108")
READER = None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    go = "--go" in argv; reader = READER or VR.hub_reader()
    os.makedirs(MD, exist_ok=True); M = MD + "/pg-objects-manifest.jsonl"; RC = MD + "/pg-objects-receipts.jsonl"
    plan = []
    for d in sorted(glob.glob(PACKED + "/pg-*/")):
        pack = os.path.basename(d.rstrip("/\\")); od = d + "objects"
        for dp, _, fs in os.walk(od):
            for f in fs:
                p = os.path.join(dp, f); rel = os.path.relpath(p, d).replace(chr(92), "/")
                plan.append(dict(path=p.replace(chr(92), "/"), size=os.path.getsize(p), hf_repo=REPO, hf_path=f"text/{pack}/{rel}", authority="lead 81864 (training 81861: shards/ stay)", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    if go and plan:
        with open(M, "a", encoding="utf-8") as mf:
            mf.write("".join(json.dumps(r) + chr(10) for r in plan)); mf.flush(); os.fsync(mf.fileno())
    ok_n = ok_b = 0; kept = []
    for r in plan:
        res = VR.remove_verified(r["path"], r["hf_repo"], r["hf_path"], roots=[PACKED], receipt=RC, authority=r["authority"], reader=reader, dry=not go)
        if res["ok"]: ok_n += 1; ok_b += res["bytes"]
        else: kept.append((r["path"], res["why"]))
    print(("" if go else "DRY ") + "VERIFIED", ok_n, "files", round(ok_b / 2**30, 2), "GiB;", "kept", len(kept), kept[:5])
    return 0 if not kept else 7


if __name__ == "__main__":
    sys.exit(main())

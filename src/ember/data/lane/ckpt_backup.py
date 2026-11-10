# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Checkpoint backup to the private model repo wordingone/ember-checkpoints (lead 81916, operator yes 2026-11-09). One child at a time, resumable:
local verify (manifest sha prefix == child id; objects/<sha>.pt name == sha256 of content; optimizer + replay sha256 == manifest) -> hf_cap.check -> `hf upload` (never overwrites) -> HF verify every file (LFS sha256 / size)
-> mail lead (GiB, verify, B free) -> for REFUTED children only: manifest first, then os.remove of weights/optimizer files (st_nlink == 1, >= 1 MiB); small receipts/manifests stay -> mail freed GiB.
Usage: python scripts/ckpt_backup.py H38 H39 H43 SLEEP H40 H41 H42"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT, SEAT_LEAD
import os, sys, json, hashlib, time, subprocess, shutil
pass
import psutil, hf_cap, mb_send
from ckpt_children import CH
MAN = (LANE_ROOT + '/logs/manifests-20261108/ckpt-delete-manifest.jsonl')
_send = mb_send.send
from huggingface_hub import HfApi


def _setup():
    """Process-level side effects, run by main() only (importing this module must change nothing)."""
    mb_send.send = lambda to, subj, body, *a, **k: (None if os.environ.get('CKPT_BATCH') and 'FAILED' not in subj else _send(to, subj, body, *a, **k))   # lead 81942: one mail per batch (the caller sends the table); failures still mail at once
    try: p = psutil.Process(); p.cpu_affinity(list(range(16, 24))); p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception: pass
REPO = os.environ.get("CKPT_REPO", ("wordingone/" + HF_RAW_REPO)); RT = os.environ.get("CKPT_REPO_TYPE", "dataset"); api = HfApi()   # the token is scoped to the 3 dataset repos (no repo.create): checkpoints go under <raw-repo>/checkpoints/ until a model repo can be created; LOG = "<lane-root>/logs/ckpt-backup.log"; MAN = "<lane-root>/logs/manifests-20261108/ckpt-delete-manifest.jsonl"
def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(map(str, a)); print(s, flush=True)
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()
def bfree(): return shutil.disk_usage("B:/").free / 2**30
RCPT = os.path.dirname(MAN) + "/ckpt-delete-receipts.jsonl"


def delete_refuted(name, id8, d, files, sh, dest, reader=None, remove=os.remove, receipt=None, man=None):
    """Local delete of a REFUTED child's weight/optimizer files after the HF upload (#2454). The upload-time comparison above is a report; THIS is the proof: per file, in the remove call, the server entry is read back
    NOW (size AND LFS sha256; a missing entry, no LFS sha256 or an unreadable server keeps the file), the local sha256 is recomputed NOW, the receipt row (both hashes) is fsynced before the os.remove, and the file must sit inside
    the child dir with st_nlink == 1. Plan rows (path, size, HF path) go to the manifest first, fsynced. Returns (freed_bytes, kept[(path, why)], rows_planned)."""
    import verified_remove as VR
    receipt = receipt or RCPT; man = man or MAN; reader = reader or VR.hub_reader(RT)
    rows = [dict(child=name, id8=id8, path=files[rel][0], size=files[rel][1], hf_repo=REPO, hf_path=f"{dest}/{rel}", kind="server-verify", sha256_in="receipt row (verified_remove), same call as the server read-back",
                 authority="lead 81916 (refuted child, HF-verified)", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            for rel in sorted(files) if files[rel][1] >= (1 << 20)]
    os.makedirs(os.path.dirname(man), exist_ok=True)
    with open(man, "a", encoding="utf-8") as mf:
        mf.write("".join(json.dumps(r) + chr(10) for r in rows)); mf.flush(); os.fsync(mf.fileno())
    freed, kept = 0, []
    for r in rows:
        res = VR.remove_verified(r["path"], r["hf_repo"], r["hf_path"], roots=[d], receipt=receipt, authority=r["authority"], reader=reader, remove=remove, extra=dict(child=name, id8=id8))
        if res["ok"]: freed += res["bytes"]
        else: kept.append((r["path"], res["why"]))
    return freed, kept, len(rows)


def main(names):
    _setup()
    for name in names:
        id8, d, refuted = CH[name]; t0 = time.time(); files = {}
        mp = d + "/checkpoint-manifest.json"; msha = sha(mp)
        if msha[:8] != id8: raise SystemExit(f"{name}: manifest sha {msha[:8]} != child id {id8}")
        m = json.load(open(mp)); bad = []
        for dp, _, fs in os.walk(d):
            for f in fs:
                p = os.path.join(dp, f).replace(chr(92), "/"); rel = os.path.relpath(p, d).replace(chr(92), "/"); files[rel] = (p, os.path.getsize(p))
        sh = {}
        for rel, (p, sz) in files.items():
            if sz >= (1 << 20) or rel.endswith(".json"): sh[rel] = sha(p)
            else: sh[rel] = sha(p)
            if rel.startswith("objects/") and sh[rel] != os.path.basename(rel).split(".")[0]: bad.append(("object name != sha", rel))
        if sh.get("optimizer-state.pt") not in (None, m["optimizer"]["sha256"]): bad.append(("optimizer sha", sh["optimizer-state.pt"]))
        if sh.get("replay-state.pt") not in (None, m["replay"]["sha256"]): bad.append(("replay sha", sh["replay-state.pt"]))
        if bad: raise SystemExit(f"{name}: LOCAL VERIFY FAILED {bad[:3]}")
        tot = sum(s for _, s in files.values()); log(name, id8, len(files), "files", round(tot / 2**30, 2), "GiB local-verified vs manifest in", round(time.time() - t0), "s")
        while not hf_cap.check(tot, f"ckpt {name}", REPO): time.sleep(300)
        dest = f"checkpoints/{id8}-{name}"
        for att in range(1, 6):
            import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push; hf_push.check_path(d)   # lead 82104: one funnel
            r = subprocess.run(["hf", "upload", REPO, d, dest, "--repo-type", RT, "--commit-message", f"{name} child {id8} (lead 81916)"], capture_output=True, text=True)
            log(name, "hf upload attempt", att, "rc", r.returncode, (r.stderr or "")[-200:].replace("\n", " "))
            if r.returncode == 0: break
            time.sleep(30)
        tree = {t.path: t for t in api.list_repo_tree(REPO, repo_type=RT, path_in_repo=dest, recursive=True) if hasattr(t, "size")}
        miss = []
        for rel, (p, sz) in files.items():
            t = tree.get(f"{dest}/{rel}")
            if t is None or t.size != sz or (getattr(t, "lfs", None) and t.lfs.sha256 != sh[rel]): miss.append(rel)
        if miss: log(name, "HF VERIFY FAILED", miss[:5]); mb_send.send(SEAT_LEAD, f"ckpt backup {name}: HF VERIFY FAILED {len(miss)} files", f"{name} {id8}: {miss[:5]}. Nothing deleted."); continue
        log(name, "HF-verified", len(files), "files", round(tot / 2**30, 2), "GiB at", dest)
        freed = 0; note = "kept local (not refuted)"
        PASS = (LANE_ROOT + "/logs/ckpt-roundtrip.PASS")     # lead 81923: no local delete until a real HF round-trip download matched the local sha256
        if refuted and os.path.exists((LANE_ROOT + "/loops/CKPT-DELETE-FREEZE.flag")): note = "kept local: CKPT-DELETE-FREEZE.flag (lead 81956)"
        elif refuted and not os.path.exists(PASS): note = "kept local: round-trip gate (lead 81923) not passed yet"
        elif refuted and (__import__("evict_ckpt_list").kept(d)): note = "kept local: KEEP marker (lead 82363: H41 child cb516ed9 / H44 child e73486d2 score better than the selected head)"
        elif refuted:
            import ckpt_bound                                          # lead 81958: never delete a dir in the ancestor closure of a bound child (or the newest trained child)
            try: ckpt_bound.assert_deletable(d)
            except ckpt_bound.Bound as e:
                log(name, str(e)); mb_send.send(SEAT_LEAD, f"ckpt backup {name}: delete REFUSED (ancestor of a bound child)", str(e)); continue
            freed, kept, nrows = delete_refuted(name, id8, d, files, sh, dest)
            note = f"deleted {nrows - len(kept)} of {nrows} weight/optimizer files (each re-verified against the server NOW, receipt before each remove); {len(kept)} kept unverified: {kept[:3]}; small receipts/manifest kept local"
        log(name, note, "freed GiB", round(freed / 2**30, 2), "B free", round(bfree(), 2))
        mb_send.send(SEAT_LEAD, f"ckpt backup {name} {id8}: {tot/2**30:.2f} GiB uploaded, HF-verified {len(files)} files; freed {freed/2**30:.2f} GiB; B free {bfree():.1f} GiB",
            f"Repo {REPO} (private model) path {dest}/. Local verify before push: manifest sha prefix == child id, objects/<sha>.pt names == content sha256, optimizer + replay sha256 == manifest. HF verify after push: every file LFS sha256/size == local ({len(files)}/{len(files)}). {note}. Freed {freed/2**30:.2f} GiB. B free {bfree():.1f} GiB.")
    log("ALL DONE")


if __name__ == "__main__":
    main(sys.argv[1:])

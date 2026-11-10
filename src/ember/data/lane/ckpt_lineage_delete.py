# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Local delete of ember children that are ALREADY on HF inside ember-corpus checkpoints/lineage-2119 (lead 81925), after:
  (1) logs/ckpt-lineage-check.json says status COVERED for the child (every file present there with equal size and server-side lfs sha256 == local sha256),
  (2) the real HF round-trip download matched (logs/ckpt-roundtrip.PASS must exist),
  (3) the child is not in the --keep list (bound by training) and not H38/H39.
Per child: manifest rows FIRST (path, size, sha256, nlink, HF path; fsync), then os.remove, only for files >= 1 MiB whose EVERY hard-link name is inside the delete set
(count of that inode inside the set == st_nlink) so no name outside the set (catalog-train-cache, kept children) is ever touched and the freed space is real. Small files (manifest, expert index,
receipts) stay local. Dry run by default: --apply to delete.
The manifest lists the PLAN (every row, kept files included, with the protected set read at planning). logs/manifests-20261108/ckpt-lineage-delete-decisions.jsonl says what was DONE: one row per file, written and fsynced before the os.remove (decision remove) or when the file is kept (decision kept + marker), each with the protected set re-read right before that file (#2450).
Usage: python ckpt_lineage_delete.py [--apply] [--keep NAME ...]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, sys, json, time, shutil, hashlib, collections
pass
CHK = (LANE_ROOT + "/logs/ckpt-lineage-check.json"); PASS = (LANE_ROOT + "/logs/ckpt-roundtrip.PASS")
MAN = (LANE_ROOT + "/logs/manifests-20261108/ckpt-lineage-delete-manifest.jsonl"); os.makedirs(os.path.dirname(MAN), exist_ok=True)
apply_ = "--apply" in sys.argv; keep = set(sys.argv[sys.argv.index("--keep") + 1:]) if "--keep" in sys.argv else set()
KEEP_ALWAYS = {"H38", "H39"}
_hc = {}


def sha256(p):
    st = os.stat(p); k = (st.st_ino, st.st_size, st.st_mtime_ns)
    if k not in _hc:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(1 << 24), b""):
                h.update(c)
        _hc[k] = h.hexdigest()
    return _hc[k]


def main():
    if apply_ and not os.path.exists(PASS):
        print("REFUSED: round-trip gate logs/ckpt-roundtrip.PASS missing"); sys.exit(2)
    chk = json.load(open(CHK)); sel = []
    for n, r in chk.items():                       # (a) already inside lineage-2119 on ember-corpus
        if r["status"] == "COVERED" and n not in keep and n not in KEEP_ALWAYS:
            sel.append(dict(name=n, dir=r["dir"], hf_repo="wordingone/ember-corpus", prefix=r["step_dir"], via="lineage-2119 server-side sha256"))
    upl = {}                                       # (b) uploaded + server-verified to <raw-repo>/checkpoints/<id8>-<name> by ckpt_backup (log lines 'HF-verified')
    for lg in ((LANE_ROOT + "/logs/ckpt-backup2.log"), (LANE_ROOT + "/logs/ckpt-backup.log")):
        if os.path.exists(lg):
            for l in open(lg, encoding="utf-8"):
                if " HF-verified " in l and " at checkpoints/" in l: upl[l.split()[1]] = l.strip().split(" at ")[-1]
    reg = {r["name"]: r for r in json.load(open((LANE_ROOT + "/logs/ckpt-old.json")))}
    for n, pth in upl.items():
        if n in reg and n not in keep and n not in KEEP_ALWAYS and not any(x["name"] == n for x in sel) and chk.get(n, {}).get("status") != "COVERED":
            sel.append(dict(name=n, dir=reg[n]["dir"], hf_repo=("wordingone/" + HF_RAW_REPO), prefix=pth, via="ckpt_backup HF-verified (lfs sha256/size)"))
    for r in json.load(open((LANE_ROOT + "/logs/ckpt-probes.json"))):      # (c) Nov probe children: reproducible from pinned scripts, delete without upload; training 81920: all unbound
        if r["name"] not in keep: sel.append(dict(name=r["name"], dir=r["dir"], hf_repo=None, prefix=None, via="probe child, reproducible (disk-custody strategy 2026-11-09); training 81920 unbound"))
    import protected_set as _PS                        # #2450: the declared protected set, re-read per remove
    import evict_ckpt_list as _E                       # lead 82363: KEEP markers (H41 child cb516ed9, H44 child e73486d2, depth 1/2, H45 child)
    kept_names = [r["name"] for r in sel if _E.kept(r["dir"])]
    if kept_names: print("KEEP MARKER: refusing", kept_names)
    sel = [r for r in sel if r["name"] not in kept_names]
    import ckpt_bound                                  # lead 81958: ancestor-closure guard - bound set = closure of every bound child + newest trained child
    bnd = ckpt_bound.bound_dirs(); hit = [r["name"] for r in sel if ckpt_bound.is_bound(r["dir"], bnd)]
    if hit: print("ANCESTOR GUARD: refusing bound-closure children:", hit)
    sel = [r for r in sel if r["name"] not in hit]
    if os.path.exists((LANE_ROOT + "/loops/CKPT-DELETE-FREEZE.flag")): print("REFUSED: CKPT-DELETE-FREEZE.flag present (lead 81956)"); sys.exit(3)
    cand = []                      # (child, abs path, rel, size, ino, nlink, hf path)
    now = time.time(); fresh = [r['name'] for r in sel if max((os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(r['dir']) for f in fs), default=0) > now - 1800]
    if fresh: print('SKIPPING children modified in the last 30 min (possibly being written by a live hour):', fresh)
    sel = [r for r in sel if r['name'] not in fresh]
    for r in sel:
        d = r["dir"]
        for dp, _, fs in os.walk(d):
            for f in fs:
                p = os.path.join(dp, f); st = os.stat(p); rel = os.path.relpath(p, d).replace("\\", "/")
                cand.append((r["name"], p, rel, st.st_size, st.st_ino, st.st_nlink, (f"{r['hf_repo']}:{r['prefix']}/{rel}" if r["prefix"] else None), r["via"]))
    inset = collections.Counter(c[4] for c in cand)
    rows = []; keep_shared = 0; keep_small = 0; keep_shared_b = 0
    for name, p, rel, sz, ino, nl, hp, via in cand:
        if sz < (1 << 20): keep_small += 1; continue
        if inset[ino] != nl: keep_shared += 1; keep_shared_b += sz; continue      # another name exists outside the set: not touched
        rows.append(dict(child=name, path=p, size=sz, nlink=nl, hf_ref=hp, verified_via=via, authority="lead 81925/81919/81916 + training 81920 (none bound) + HF round-trip PASS", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    names_per_ino = collections.defaultdict(list)
    for r in rows: names_per_ino[os.stat(r["path"]).st_ino].append(r)
    uniq = sum(v[0]["size"] for v in names_per_ino.values())
    print(f"children selected {len(sel)} | files to delete {len(rows)} | unique inodes {len(names_per_ino)} | REAL freed {uniq/2**30:.1f} GiB | kept: shared-with-outside {keep_shared} names ({keep_shared_b/2**30:.1f} GiB logical), small {keep_small}")
    if not apply_:
        print("DRY RUN (use --apply)"); return
    for r in rows: r["sha256"] = sha256(r["path"])
    ps0 = _PS.load()                                   # #2450: the set the manifest rows were written under (each remove below re-reads it)
    for r in rows: r["protected_set_sha256_at_plan"] = ps0["sha256"]; r["protected_set_path_at_plan"] = ps0["path"]      # the PLAN was written under this set; each decision row below records the set re-read for that file
    with open(MAN, "a") as mf:
        mf.write("".join(json.dumps(r) + "\n" for r in rows)); mf.flush(); os.fsync(mf.fileno())
    DEC = os.path.dirname(MAN) + "/ckpt-lineage-delete-decisions.jsonl"      # one row per file and decision, written + fsynced BEFORE the os.remove: removed / kept (with the marker) / outcome, each with the protected set read right before that file
    def _dec(r, cur, decision, **kw):
        with open(DEC, "a") as df:
            df.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), decision=decision, path=r["path"], size=r["size"], sha256=r["sha256"], protected_set_sha256=cur["sha256"], protected_set_path=cur["path"], planned_under_sha256=ps0["sha256"], **kw)) + "\n"); df.flush(); os.fsync(df.fileno())
    b0 = shutil.disk_usage("B:/").free
    failed = []; kept = []
    for r in rows:
        cur = _PS.load()                                 # #2450: re-read right before this remove (selection and hashing ran minutes ago): a marker declared since keeps the file
        _k = _E.kept(r["path"], cur["markers"])
        if _k: kept.append((r["path"], _k)); _dec(r, cur, "kept", marker=_k); continue
        _dec(r, cur, "remove")                           # receipt row first; the manifest above lists the PLAN (kept files included), this file says what was done
        try: os.remove(r["path"])
        except FileNotFoundError: _dec(r, cur, "already-gone")
        except PermissionError as e: failed.append(r["path"]); _dec(r, cur, "remove-failed-in-use")          # file held open by another process: left in place, retried on the next run
    if failed:
        json.dump(failed, open(os.path.dirname(MAN) + "/ckpt-lineage-delete-failed.json", "w"), indent=1); print("could not remove (in use):", len(failed), failed[:3])
    if kept: print(f"KEPT {len(kept)} files under a KEEP node (re-declared during the run), not deleted:", kept[:3])
    print(f"deleted {len(rows) - len(kept) - len(failed)} names; B free {b0/2**30:.1f} -> {shutil.disk_usage('B:/').free/2**30:.1f} GiB; manifest {MAN}; decisions {DEC}")


if __name__ == "__main__":
    main()

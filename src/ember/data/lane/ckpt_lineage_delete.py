# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Local delete of ember children that are ALREADY on HF inside ember-corpus checkpoints/lineage-2119 (lead 81925), after:
  (1) logs/ckpt-lineage-check.json says status COVERED for the child (every file present there with equal size and server-side lfs sha256 == local sha256),
  (2) the real HF round-trip download matched (logs/ckpt-roundtrip.PASS must exist),
  (3) the child is not in the --keep list (bound by training) and not H38/H39.
Only files >= 1 MiB whose EVERY hard-link name is inside the delete set (count of that inode inside the set == st_nlink) are removed, so no name outside the set (catalog-train-cache, kept children)
is ever touched and the freed space is real. Small files (manifest, expert index, receipts) stay local. Dry run by default: --apply to delete.
Deletes go through verified_remove.py (#2454), two named paths, and the status json / HF-verified log lines only SELECT candidates, they prove nothing at delete time:
  branches (a)/(b) (a server copy exists): per file, in the remove call itself, the server entry is read back NOW (size AND LFS sha256; a missing entry, an entry without an LFS sha256 or an unreadable
    server keeps the file), the local sha256 is recomputed NOW, and the receipt row (both hashes) is fsynced BEFORE the os.remove. Plan rows (path, size, nlink, HF path) are written first too.
  branch (c) (probe children, no copy anywhere, reproducible): needs --ruling ID (a mail id) AND --expect-dirs FILE.json (the ruled dir list is the pin; --apply refuses without it); the manifest (path, size, sha256, mtime_ns, inode, ruling) for ALL files is fsynced before the first remove and each remove re-checks
    that the file is still the one in the manifest. This path is "ruled, no copy" and is never labelled verified.
Receipts: logs/manifests-20261108/ckpt-lineage-delete-receipts.jsonl. Every path must be inside its child dir with no link or junction on the way.
  File-level plan (#2459 round 2): the dry run prints PLAN-SHA256, the sha256 of the sorted lines path|bytes|sha256 of EVERY selected no-copy file, and lists the rows in logs/manifests-20261108/ckpt-lineage-delete-plan-<sha12>.jsonl; --apply requires --plan-sha256 with that value and refuses (exit 4, nothing hashed further, no manifest row, nothing removed)
    when the files found now are another set, naming a file added to a ruled dir after the dry run. Nothing is removed that was not listed. An inode with several names inside the set is removed name by name with a per-inode nlink countdown (nlink, then nlink-1, ...); a name added meanwhile still refuses.
Usage: python ckpt_lineage_delete.py [--apply] [--only-probes] [--expect-dirs FILE.json] [--ruling ID] [--plan-sha256 SHA] [--keep NAME ...]   (--only-probes: branch (c), the guarded terminal probes, only; --expect-dirs: refuse, exit 4, unless the selected child dirs equal that list; --ruling: required by --apply when any no-copy child is selected, else exit 5; --plan-sha256: required with it, exit 5 without, exit 4 on another file set; put --expect-dirs/--ruling/--plan-sha256 BEFORE --keep; lead rulings 82451/82461)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT
import os, sys, json, time, shutil, hashlib, collections
pass
import verified_remove as VR
CHK = (LANE_ROOT + "/logs/ckpt-lineage-check.json"); PASS = (LANE_ROOT + "/logs/ckpt-roundtrip.PASS")
MAN = (LANE_ROOT + "/logs/manifests-20261108/ckpt-lineage-delete-manifest.jsonl"); os.makedirs(os.path.dirname(MAN), exist_ok=True)
RCPT = os.path.dirname(MAN) + "/ckpt-lineage-delete-receipts.jsonl"
BK_LOGS = ((LANE_ROOT + "/logs/ckpt-backup2.log"), (LANE_ROOT + "/logs/ckpt-backup.log")); OLD = (LANE_ROOT + "/logs/ckpt-old.json"); PROBES = (LANE_ROOT + "/logs/ckpt-probes.json")
FREEZE = (LANE_ROOT + "/loops/CKPT-DELETE-FREEZE.flag")        # module constants so the red test can point them at a tmp tree
READER = None          # tests inject a fake server reader; production asks the Hub NOW for every file
apply_ = "--apply" in sys.argv; keep = set(sys.argv[sys.argv.index("--keep") + 1:]) if "--keep" in sys.argv else set()
EXPECT = sys.argv[sys.argv.index("--expect-dirs") + 1] if "--expect-dirs" in sys.argv else None      # json list of the child dirs the lead ruled on (82461); put it BEFORE --keep
RULING = sys.argv[sys.argv.index("--ruling") + 1] if "--ruling" in sys.argv else None      # required for the no-copy branch (c); put it BEFORE --keep
PLAN_SHA = sys.argv[sys.argv.index("--plan-sha256") + 1] if "--plan-sha256" in sys.argv else None     # round 2 F-C: file-level pin of the no-copy path; put it BEFORE --keep
ONLY_PROBES = "--only-probes" in sys.argv       # lead ruling 82451: branch (c) only; the upload branches (a)/(b) select nothing (put this flag BEFORE --keep)
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


DEC = os.path.dirname(MAN) + "/ckpt-lineage-delete-decisions.jsonl"      # issue 2481: one row per file saying what this run DECIDED, fsynced BEFORE the removal is attempted (the manifest is the plan, the receipts are the outcome)


def _dec(r, cur, decision, marker=None, reason=None, outcome_of=None):
    """Append and fsync the decision row for file r under the protected set `cur` re-read for THIS file. decision = "remove" (admitted for removal now) or "kept" (with the marker that kept it, or, when the removal call refused the file after its `remove` row, with `reason` = the refusal text and `outcome_of` = "remove"; lead 83411)."""
    row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), child=r["child"], path=r["path"], size=r["size"], decision=decision, marker=marker, protected_set_sha256=cur["sha256"], protected_set_path=cur["path"],
               planned_under_sha256=r.get("protected_set_sha256_at_plan"), reason=reason, outcome_of=outcome_of)
    with open(DEC, "a", encoding="utf-8") as df:
        df.write(json.dumps(row) + chr(10)); df.flush(); os.fsync(df.fileno())


def main():
    if apply_ and not os.path.exists(PASS):
        print("REFUSED: round-trip gate logs/ckpt-roundtrip.PASS missing"); sys.exit(2)
    chk = json.load(open(CHK)); sel = []
    for n, r in ({} if ONLY_PROBES else chk).items():                       # (a) already inside lineage-2119 on ember-corpus
        if r["status"] == "COVERED" and n not in keep and n not in KEEP_ALWAYS:
            sel.append(dict(name=n, dir=r["dir"], hf_repo="wordingone/ember-corpus", prefix=r["step_dir"], via="lineage-2119 server-side sha256"))
    upl = {}                                       # (b) uploaded + server-verified to <raw-repo>/checkpoints/<id8>-<name> by ckpt_backup (log lines 'HF-verified')
    for lg in (() if ONLY_PROBES else BK_LOGS):
        if os.path.exists(lg):
            for l in open(lg, encoding="utf-8"):
                if " HF-verified " in l and " at checkpoints/" in l: upl[l.split()[1]] = l.strip().split(" at ")[-1]
    reg = {r["name"]: r for r in json.load(open(OLD))}
    for n, pth in upl.items():
        if n in reg and n not in keep and n not in KEEP_ALWAYS and not any(x["name"] == n for x in sel) and chk.get(n, {}).get("status") != "COVERED":
            sel.append(dict(name=n, dir=reg[n]["dir"], hf_repo=("wordingone/" + HF_RAW_REPO), prefix=pth, via="ckpt_backup HF-verified (lfs sha256/size)"))
    import probe_terminal_guard as PG, evict_ckpt_list as _EK                  # lead ruling 82451: branch (c) takes a probe only when its guard says so
    for r in json.load(open(PROBES)):      # (c) Nov probe children: reproducible from pinned scripts, delete without upload; training 81920: all unbound
        if r["name"] in keep: continue
        g = PG.probe_eligibility(r["dir"], kept=_EK.kept)
        if not g["ok"]: print("PROBE REFUSED", r["name"], g["reason"], [d for _, d in g["consumers"]]); continue
        sel.append(dict(name=r["name"], dir=r["dir"], hf_repo=None, prefix=None, via="probe child, reproducible (disk-custody strategy 2026-11-09); training 81920 unbound; " + g["clause"],
                        probe_consumers=[d for _, d in g["consumers"]], probe_terminal=g["terminal_receipt"], probe_clause=g["clause"]))
    import protected_set as _PS                        # #2450: the declared protected set, re-read per remove
    import evict_ckpt_list as _E                       # lead 82363: KEEP markers (H41 child cb516ed9, H44 child e73486d2, depth 1/2, H45 child)
    kept_names = [r["name"] for r in sel if _E.kept(r["dir"])]
    if kept_names: print("KEEP MARKER: refusing", kept_names)
    sel = [r for r in sel if r["name"] not in kept_names]
    import ckpt_bound                                  # lead 81958: ancestor-closure guard - bound set = closure of every bound child + newest trained child
    bnd = ckpt_bound.bound_dirs(); hit = [r["name"] for r in sel if ckpt_bound.is_bound(r["dir"], bnd)]
    if hit: print("ANCESTOR GUARD: refusing bound-closure children:", hit)
    sel = [r for r in sel if r["name"] not in hit]
    if os.path.exists(FREEZE): print("REFUSED: CKPT-DELETE-FREEZE.flag present (lead 81956)"); sys.exit(3)
    cand = []                      # (child, abs path, rel, size, ino, nlink, hf path)
    now = time.time(); fresh = [r['name'] for r in sel if max((os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(r['dir']) for f in fs), default=0) > now - 1800]
    if fresh: print('SKIPPING children modified in the last 30 min (possibly being written by a live hour):', fresh)
    sel = [r for r in sel if r['name'] not in fresh]
    for r in sel: print("SELECTED", r["name"], r["dir"].replace("\\", "/"))
    if EXPECT:                                         # lead ruling 82461: the selected set must equal the ruled manifest, else nothing below runs (no hashing, no manifest rows, no remove)
        _exp = set(json.load(open(EXPECT))); _got = {r["dir"].replace("\\", "/") for r in sel}
        if _exp != _got: print("REFUSED: selected set != expected manifest; extra", sorted(_got - _exp), "missing", sorted(_exp - _got)); sys.exit(4)
    for r in sel:
        d = r["dir"]
        for dp, _, fs in os.walk(d):
            for f in fs:
                p = os.path.join(dp, f); st = os.stat(p); rel = os.path.relpath(p, d).replace("\\", "/")
                cand.append((r["name"], p, rel, st.st_size, st.st_ino, st.st_nlink, (f"{r['hf_repo']}:{r['prefix']}/{rel}" if r["prefix"] else None), r["via"]))
    inset = collections.Counter(c[4] for c in cand)
    probe_info = {r["name"]: {k: r[k] for k in ("probe_consumers", "probe_terminal", "probe_clause")} for r in sel if "probe_clause" in r}   # manifest: consumer hour, its terminal receipt, the clause that passed (82451)
    _pb = ("expect-dirs sha256 " + hashlib.sha256(open(EXPECT, "rb").read()).hexdigest()) if EXPECT else None      # the pin of branch (c): the ruled dir list (#2459 F1)
    rows = []; keep_shared = 0; keep_small = 0; keep_shared_b = 0
    for name, p, rel, sz, ino, nl, hp, via in cand:
        if sz < (1 << 20): keep_small += 1; continue
        if inset[ino] != nl: keep_shared += 1; keep_shared_b += sz; continue      # another name exists outside the set: not touched
        _st = os.stat(p); _repo, _, _hpath = (hp or "").partition(":")
        rows.append(dict(child=name, path=p, size=sz, nlink=nl, hf_ref=hp, hf_repo=(_repo or None), hf_path=(_hpath or None), mtime_ns=_st.st_mtime_ns, ino=_st.st_ino, kind=("server-verify" if hp else "ruled-no-copy"), ruling=(None if hp else RULING), pinned_by=(None if hp else _pb),
                         verified_via=via, authority="lead 81925/81919/81916 + training 81920 (none bound) + HF round-trip PASS", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **probe_info.get(name, {})))
    names_per_ino = collections.defaultdict(list)
    for r in rows: names_per_ino[os.stat(r["path"]).st_ino].append(r)
    uniq = sum(v[0]["size"] for v in names_per_ino.values())
    print(f"children selected {len(sel)} | files to delete {len(rows)} | unique inodes {len(names_per_ino)} | REAL freed {uniq/2**30:.1f} GiB | kept: shared-with-outside {keep_shared} names ({keep_shared_b/2**30:.1f} GiB logical), small {keep_small}")
    nocopy = sorted({r["child"] for r in rows if not r["hf_ref"]})
    plan = None                                        # round 2 F-C: the no-copy path is pinned at FILE level: sha256 over the sorted lines path|bytes|sha256 of every selected no-copy file
    nc_rows = [r for r in rows if not r["hf_ref"]]
    if nc_rows:
        for r in nc_rows: r["sha256"] = sha256(r["path"])
        plan_lines = sorted("%s|%d|%s" % (r["path"].replace(chr(92), "/"), r["size"], r["sha256"]) for r in nc_rows)
        plan = hashlib.sha256("\n".join(plan_lines).encode("utf-8")).hexdigest()
        plan_file = os.path.dirname(MAN) + "/ckpt-lineage-delete-plan-" + plan[:12] + ".jsonl"
        if not os.path.exists(plan_file):
            with open(plan_file, "w", encoding="utf-8") as pf:
                pf.write("".join(json.dumps(dict(path=r["path"].replace(chr(92), "/"), bytes=r["size"], sha256=r["sha256"])) + chr(10) for r in sorted(nc_rows, key=lambda x: x["path"]))); pf.flush(); os.fsync(pf.fileno())
        print(f"PLAN-SHA256 {plan} over {len(nc_rows)} no-copy files ({sum(r['size'] for r in nc_rows)/2**30:.2f} GiB); the lead rules on this value; rows listed in {plan_file}")
    if not apply_:
        print("DRY RUN (use --apply)" + (f" | {len(nocopy)} no-copy children need --ruling ID, --expect-dirs and --plan-sha256" if nocopy and not RULING else "")); return
    if nocopy and not VR.ruling_ok(RULING):
        print("REFUSED: children with no server copy (branch c) need --ruling ID, a mail id such as 'lead 82451'", nocopy[:5]); sys.exit(5)
    if nocopy and not EXPECT:
        print("REFUSED: children with no server copy (branch c) need --expect-dirs FILE.json (the ruled dir list is the pin of the no-copy path; NO_PIN)", nocopy[:5]); sys.exit(5)
    if nocopy and not PLAN_SHA:
        print("REFUSED: children with no server copy (branch c) need --plan-sha256 (the file-level plan the dry run printed; NO_FILE_PIN)", nocopy[:5]); sys.exit(5)
    if plan and PLAN_SHA.strip().lower() != plan:       # a file added to (or changed in) a ruled dir after the dry run: nothing is hashed further, no manifest row, no remove
        pf0 = os.path.dirname(MAN) + "/ckpt-lineage-delete-plan-" + PLAN_SHA.strip().lower()[:12] + ".jsonl"; extra = missing = changed = []
        if os.path.exists(pf0):
            old_rows = {x["path"]: x for x in (json.loads(l) for l in open(pf0, encoding="utf-8") if l.strip())}; now_rows = {r["path"].replace(chr(92), "/"): r for r in nc_rows}
            extra = sorted(set(now_rows) - set(old_rows)); missing = sorted(set(old_rows) - set(now_rows)); changed = sorted(p for p in set(now_rows) & set(old_rows) if (now_rows[p]["size"], now_rows[p]["sha256"]) != (old_rows[p]["bytes"], old_rows[p]["sha256"]))
        print(f"REFUSED: the no-copy file set found now (plan {plan[:16]}) is not the ruled plan ({PLAN_SHA[:16]}); not in the plan: {extra[:5]}; missing: {missing[:3]}; changed: {changed[:3]}; nothing removed"); sys.exit(4)
    for r in nc_rows: r["pinned_by"] = (r["pinned_by"] or "") + " ; plan sha256 " + plan      # the manifest and receipt rows carry both pins
    reader = READER or VR.hub_reader()
    child_dir = {r["name"]: r["dir"] for r in sel}
    _plan_sha = _PS.load()["sha256"]                    # issue 2481: the protected set the plan is written under; every manifest row and every decision row names it
    for r in rows:
        r["protected_set_sha256_at_plan"] = _plan_sha
        if not r["hf_ref"]: r["sha256"] = sha256(r["path"])             # no-copy rows: hashed once, manifest fsynced before the first remove; server rows: hashed inside the remove call, receipt before each remove
        else: r["sha256"] = None; r["hashed_in"] = "receipt row (verified_remove), same call as the server read-back"
    with open(MAN, "a") as mf:
        mf.write("".join(json.dumps(r) + chr(10) for r in rows)); mf.flush(); os.fsync(mf.fileno())
    b0 = shutil.disk_usage("B:/").free
    failed, kept, n_ok = [], [], 0
    nl_left = {}                                       # round 2 F-A: per-inode countdown. Every name of an inode is in the set (inset[ino] == nlink), so the k-th name removed must see nlink - (names of that inode already removed)
    for r in rows:
        cur = _PS.load()      # #2450: the declared protected set re-read right before this remove (selection and hashing ran minutes ago); a marker declared since refuses the file, and the receipt records the set that admitted it
        _k = _E.kept(r["path"], cur["markers"])
        if _k: _dec(r, cur, "kept", _k); kept.append((r["path"], "under a KEEP node (re-declared during the run): " + _k)); continue
        r["protected_set_sha256"] = cur["sha256"]; r["protected_set_path"] = cur["path"]
        _dec(r, cur, "remove")                              # issue 2481: the decision row is on disk BEFORE the removal below is attempted
        roots = [child_dir[r["child"]]]
        req = nl_left.setdefault(r["ino"], r["nlink"])      # planned nlink minus the names already removed; a name added after the plan still refuses (#2459 F5)
        if r["hf_ref"]:
            res = VR.remove_verified(r["path"], r["hf_repo"], r["hf_path"], roots=roots, receipt=RCPT, authority=r["authority"], reader=reader, require_nlink=req, extra=dict(child=r["child"], via=r["verified_via"], protected_set_sha256=cur["sha256"], protected_set_path=cur["path"]))   # nlink as planned: a name added after the plan refuses (#2459 F5)
        else:
            res = VR.remove_ruled(r, roots=roots, receipt=RCPT, require_nlink=req)
        if not res["ok"]: _dec(r, cur, "kept", reason=res["why"], outcome_of="remove")      # follow-up to 2481 (lead 83411): a file refused INSIDE remove_verified/remove_ruled keeps its `remove` row, so a second row says it was kept and why
        if res["ok"]: n_ok += 1; nl_left[r["ino"]] = req - 1
        elif res["why"].startswith("remove failed: PermissionError"): failed.append(r["path"])          # file held open by another process: left in place, retried on the next run
        else: kept.append((r["path"], res["why"]))
    if failed:
        json.dump(failed, open(os.path.dirname(MAN) + "/ckpt-lineage-delete-failed.json", "w"), indent=1); print("could not remove (in use):", len(failed), failed[:3])
    if kept:
        print(f"KEPT {len(kept)} files that did not verify (not deleted):"); [print("  kept", p, why) for p, why in kept[:8]]
    print(f"deleted {n_ok} names; B free {b0/2**30:.1f} -> {shutil.disk_usage('B:/').free/2**30:.1f} GiB; manifest {MAN}; receipts {RCPT}")
    if kept: sys.exit(7)

if __name__ == "__main__":
    main()

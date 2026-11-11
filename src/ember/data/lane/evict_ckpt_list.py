# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Evict the checkpoint object files NAMED in training's list (lead 82130 ruling YES; training 82141). Verify-before-delete, one receipt row per file, os.remove only.
List: <m-root>/avir/<training>/state/evict-list-final-20261109.tsv (sha256 pinned below; columns depth, size, path; '#' footer). Walk receipt: <m-root>/avir/<training>/state/h44-walk-20261109.json (rc 0).
Per file, ALL must hold or the file is SKIPPED (and listed for lead; never deleted on a mismatch):
  - the path is in the list, is a regular file under an objects/ dir, is not under a KEEP node (walk depth 1 d4a908e3, depth 2 8ed2307c, the H45 child);
  - local size == list size and local sha256 (recomputed now) == the file's content-addressed name objects/<sha>.pt;
  - HF custody in wordingone/<raw-repo>: a file whose LFS sha256 == that sha and size == local, re-read from the server (get_paths_info) immediately before the delete.
Receipt (appended BEFORE each os.remove): logs/evict-ckpt-20261109.jsonl {ts, path, size, sha256, hf_path, verified, walk_receipt, list_sha256}.
Usage: python scripts/evict_ckpt_list.py [--dry] [--workers N]      Red: python scripts/tests/evict_ckpt_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT, M_ROOT, SEAT_TRAIN
import os, sys, json, time, hashlib, threading
LIST = (M_ROOT + "/avir/" + SEAT_TRAIN + "/state/evict-list-final-20261109.tsv"); LIST_SHA = "90a747e8e5e52950a9737699b561af6a81e46cd10e8bbc056a49071a73a666a4"
WALK = (M_ROOT + "/avir/" + SEAT_TRAIN + "/state/h44-walk-20261109.json"); REPO = ("wordingone/" + HF_RAW_REPO); RC = (LANE_ROOT + "/logs/evict-ckpt-20261109.jsonl")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protected_set as _PS
KEEP_MARKERS = _PS.markers()      # issue 2450: the declared protected set (loops/protected-set.json), not a literal here; an unreadable/invalid file raises ProtectedSetError at import = nothing is removed. This is an IMPORT-TIME SNAPSHOT for short-lived readers (reserve_manifest); every deleter asks kept(), which re-reads the file on each call


class EvictRefused(RuntimeError):
    pass


def kept(path, markers=None):
    """The KEEP marker that covers `path` (a file or a directory), else None. The deleters (this one, ckpt_backup, ckpt_lineage_delete) ask this one function (lead 82363).
    markers=None reads the declared protected set now (on every call: a long-lived caller never keeps a stale, smaller set); a caller that already loaded the set passes its markers so the check and the receipt use the same read."""
    p = path.replace("\\", "/")
    p = p if p.endswith("/") else p + "/"
    return next((k for k in (_PS.markers() if markers is None else markers) if k in p), None)


def load_list(path=LIST, want_sha=LIST_SHA):
    raw = open(path, "rb").read()
    if want_sha and hashlib.sha256(raw).hexdigest() != want_sha: raise EvictRefused("list sha256 != the one training mailed (82141): refusing")
    rows = []
    for l in raw.decode("utf-8").splitlines():
        if not l.strip() or l.startswith("#"): continue
        d, sz, p = l.split("\t", 2); rows.append((int(d), int(sz), p.replace("\\", "/")))
    return rows


def refuse_reason(path, keep=None):
    """Static guards, checked for every row before any I/O. Returns a reason string or None."""
    p = path.replace("\\", "/")
    keep = _PS.markers() if keep is None else keep
    if any(k in p for k in keep): return "under a KEEP node (depth 1 / depth 2 / H45 child)"
    if not ("/trained-child/objects/" in p or "/zero-parent/objects/" in p) or not p.endswith(".pt"): return "not a trained-child / zero-parent objects/*.pt file"      # walk depth 36 is the chain's zero-parent root node (in training's list, 36 files)
    return None


def child_of(path):
    """The <measurement>/trained-child directory that holds `path`, or None."""
    p = path.replace("\\", "/"); i = p.find("/trained-child")
    return p[:i + len("/trained-child")] if i > 0 else None


def child_gaps(child_dir, removing, hf_has):
    """lead 82370 rule: a child of a SCORED hour (its measurement dir holds hour-result.json) must stay restorable after a removal. Every item of its checkpoint manifest (core, each expert object, optimizer-state.pt,
    replay-state.pt) must be a local file in the child dir that is NOT being removed, or have a server-verified copy (hf_has(sha256, bytes) -> bool). Returns the items that would be on neither B: nor HF
    (empty list = fine, also when the dir is not a scored child). The optimizer and replay state of a child that is a parent candidate are often the only copies: they are never removable without an HF copy."""
    child_dir = child_dir.replace("\\", "/"); meas = os.path.dirname(child_dir)
    mp = child_dir + "/checkpoint-manifest.json"
    if not (os.path.isfile(meas + "/hour-result.json") and os.path.isfile(mp)): return []
    import glob
    m = json.load(open(mp, encoding="utf-8")); rm = {p.replace("\\", "/") for p in removing}
    items = [("core", f"{child_dir}/objects/{m['core']['sha256']}.pt", m["core"]["sha256"], m["core"]["bytes"]),
             ("optimizer-state.pt", child_dir + "/optimizer-state.pt", m["optimizer"]["sha256"], m["optimizer"]["bytes"]), ("replay-state.pt", child_dir + "/replay-state.pt", m["replay"]["sha256"], m["replay"]["bytes"])]
    for ep in glob.glob(child_dir + "/expert-index-*.json"):
        for e in json.load(open(ep, encoding="utf-8"))["experts"]: items.append((f"expert{e['expert_id']}", f"{child_dir}/objects/{e['sha256']}.pt", e["sha256"], e["bytes"]))
    return [(lab, sha, by) for lab, own, sha, by in items if not (os.path.isfile(own) and own not in rm) and not hf_has(sha, by)]


def guard_children(paths, hf_has):
    """{child_dir: gaps} for every child touched by `paths` whose removal would leave a gap (see child_gaps)."""
    by = {}
    for p in paths:
        c = child_of(p)
        if c: by.setdefault(c, []).append(p)
    return {c: g for c, ps in by.items() if (g := child_gaps(c, ps, hf_has))}


def _norm(p): return os.path.normcase(os.path.abspath(p.replace("\\", "/")))


def all_links(p):
    """Every name (absolute, normalized) of the inode behind p. nlink == 1 -> just p; else `fsutil hardlink list` (drive-relative names, so the drive of p is prepended)."""
    if os.stat(p).st_nlink == 1: return {_norm(p)}
    import subprocess
    out = subprocess.run(["fsutil", "hardlink", "list", p], capture_output=True, text=True).stdout.splitlines()
    drv = os.path.splitdrive(os.path.abspath(p))[0]
    names = {_norm(drv + l.strip()) for l in out if l.strip()}
    if not names: raise EvictRefused(f"could not enumerate the links of {p}: refusing (fail closed)")
    return names


def link_plan(paths):
    """lead 82147: expected PHYSICAL bytes = sum of sizes over unique inodes whose EVERY link is in the list. Returns (phys_expected_bytes, partial) where partial = [(path, [names outside the list])]."""
    inl = {_norm(p) for p in paths}; seen = {}; partial = []; phys = 0
    for p in paths:
        st = os.stat(p); key = (st.st_dev, st.st_ino)
        if key in seen: continue
        names = all_links(p); outside = sorted(n for n in names if n not in inl); seen[key] = 1
        if outside: partial.append((p, outside))
        else: phys += st.st_size
    return phys, partial


def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()


def main():
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import HfApi
    dry = "--dry" in sys.argv; nw = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    allow_partial = "--allow-partial-links" in sys.argv
    rows = load_list(); walk = json.load(open(WALK)); print("list rows", len(rows), "GiB", round(sum(r[1] for r in rows) / 2**30, 2), flush=True)
    live = [r[2] for r in rows if os.path.isfile(r[2]) and not refuse_reason(r[2])]
    exp, partial = link_plan(live)
    print(f"EXPECTED physical freed (unique inodes whose every link is in the list): {exp/2**30:.2f} GiB over {len(live)} present names; links outside the list: {len(partial)} inodes", flush=True)
    for pth, outs in partial[:20]: print("  PARTIAL-LINK", pth, "-> other names:", outs[:3], flush=True)
    if partial and not allow_partial: raise EvictRefused(f"{len(partial)} inodes have links outside the list: refusing (pass --allow-partial-links to remove just the listed names, which frees nothing for them)")
    api = HfApi(); idx = {}
    for e in api.list_repo_tree(REPO, path_in_repo="checkpoints", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs:
            sh = e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256
            idx.setdefault(sh, (e.path, e.size))
    print("HF checkpoint LFS files indexed (unique sha):", len(idx), flush=True)
    gaps = guard_children(live, lambda s, b: (idx.get(s) or (None, -1))[1] == b)      # lead 82370: no child of a scored hour may become unrestorable
    for c, g in gaps.items(): print("CHILD-GAP (all its rows skipped):", c, g[:3], flush=True)
    lock = threading.Lock(); st = dict(deleted=0, bytes=0, phys=0, shared=0, skipped=[]); os.makedirs(os.path.dirname(RC), exist_ok=True)

    def skip(p, why):
        with lock: st["skipped"].append((p, why))

    def one(r):
        d, sz, p = r
        why = refuse_reason(p)
        if why: return skip(p, why)
        if child_of(p) in gaps: return skip(p, f"child would not stay restorable: {len(gaps[child_of(p)])} manifest items on neither B: nor HF (lead 82370)")
        if not os.path.isfile(p) or os.path.islink(p): return skip(p, "not a regular file (missing or link)")
        if os.path.getsize(p) != sz: return skip(p, f"local size {os.path.getsize(p)} != list {sz}")
        name = os.path.basename(p)[:-3]; s = sha_of(p)
        if s != name: return skip(p, "local sha256 != content-addressed name")
        hit = idx.get(s)
        if not hit or hit[1] != sz: return skip(p, "no HF custody with equal sha256+size")
        srv = api.get_paths_info(REPO, [hit[0]], expand=True, repo_type="dataset")       # re-read from the server immediately before the delete
        lf = srv[0].lfs if srv else None; ssha = (lf["sha256"] if isinstance(lf, dict) else getattr(lf, "sha256", None)) if lf else None
        if not srv or ssha != s or srv[0].size != sz: return skip(p, "server re-read mismatch")
        if dry:
            with lock: st["deleted"] += 1; st["bytes"] += sz
            return
        stt = os.stat(p); nlink = stt.st_nlink; phys = sz if nlink == 1 else 0      # lead 82144: bytes are only freed when the LAST name of an inode goes
        with lock:
            cur = _PS.load()      # re-read immediately before the remove (the hash above can take minutes): a re-declaration in that window is honoured and recorded
            k = kept(p, cur["markers"])
            if k: st["skipped"].append((p, "under a KEEP node (re-declared during the run): " + k)); return
            with open(RC, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(st_nlink=nlink, physical_bytes_freed=phys, inode=f"{stt.st_dev}:{stt.st_ino}", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=p, size=sz, sha256=s, hf_path=f"{REPO}:{hit[0]}", verified="local sha256 recomputed == name == server LFS sha256, size equal, server re-read just before delete",
                                        walk_receipt=WALK, list_sha256=LIST_SHA, authority="lead 82130 / training 82141", protected_set_sha256=cur["sha256"], protected_set_path=cur["path"])) + "\n")
            os.remove(p)
            st["deleted"] += 1; st["bytes"] += sz; st["phys"] += phys; st["shared"] += (nlink > 1)

    import shutil; free0 = shutil.disk_usage("B:/").free
    with ThreadPoolExecutor(nw) as ex: list(ex.map(one, rows))
    freed = shutil.disk_usage("B:/").free - free0
    print(("DRY " if dry else "") + f"names removed {st['deleted']} (logical {st['bytes']/2**30:.2f} GiB; of which nlink>1: {st['shared']}); PHYSICAL freed by receipts {st['phys']/2**30:.2f} GiB; MEASURED B: free change {freed/2**30:+.2f} GiB (other writers included); skipped {len(st['skipped'])}; B free {shutil.disk_usage('B:/').free/2**30:.1f} GiB", flush=True)
    for p, why in st["skipped"][:50]: print("SKIP", why, p, flush=True)
    json.dump(dict(skipped=st["skipped"], deleted=st["deleted"], bytes=st["bytes"], physical_bytes=st["phys"], measured_free_delta=freed, dry=dry), open(os.path.join(os.path.dirname(RC), "evict-ckpt-20261109.summary.json"), "w"), indent=1)      # next to the receipt (a sandboxed run, issue 2450 N3, must not overwrite the real summary)


if __name__ == "__main__":
    main()

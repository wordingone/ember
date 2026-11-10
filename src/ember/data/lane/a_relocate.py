# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""A: custody relocation (lead 82016, hardened per lead 82070): MOVE a top-level dir A:/<name> to <m-root>/a-relocated/<name>, leaving a directory JUNCTION at the old path so every recorded path keeps resolving.
Safe by construction:
 (1) refuse if the dir is in the checkpoint bound closure, or ANY process holds an open handle on a file under it (psutil open_files; re-checked right before the delete);
 (2) pass 1 copies each file hashing the SOURCE bytes as they are read (manifest row: rel path,size,mtime_ns,sha256 -> logs/manifests-20261109/a-relocate-<name>.jsonl, written BEFORE any delete);
 (3) pass 2 re-reads every DEST file and requires sha256 == manifest;
 (4) pass 3 re-reads every SOURCE file AFTER the full copy and requires size, mtime_ns and sha256 == the manifest values taken at copy time, and the source file SET (re-walk) == the walked set (a file appended/modified/added after its copy is a refusal);
 (5) only then rmtree the source (python, never shell rm) and `mklink /J`. Any mismatch/exception -> source untouched, dest left for inspection. Resumable: files already at dest with the right size+sha are skipped.
B: floor = reserve_plan.floor_gib() (the single source). Usage: python a_relocate.py NAME [--dry]"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, hashlib, shutil, time, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
pass
SRC_ROOT = "A:/"; DST_BASE = (M_ROOT + "/a-relocated/"); MAN = (LANE_ROOT + "/logs/manifests-20261109/")
BS = chr(92)
_TEST_HOOK_AFTER_COPY = None      # red-test only: called after pass 1 (simulates a writer appending to the source mid-relocation)


def sha_copy(s, d):
    """Copy s -> d hashing the source bytes as read. Returns (sha256, size, mtime_ns) of the source taken around the read."""
    h = hashlib.sha256(); os.makedirs(os.path.dirname(d), exist_ok=True); tmp = d + ".part"
    st0 = os.stat(s)
    with open(s, "rb") as fi, open(tmp, "wb") as fo:
        for c in iter(lambda: fi.read(1 << 24), b""):
            h.update(c); fo.write(c)
    os.replace(tmp, d); shutil.copystat(s, d)
    return h.hexdigest(), st0.st_size, st0.st_mtime_ns


def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest()


def walk(src):
    out = []
    for r, _, fs in os.walk(src):
        for f in fs:
            p = os.path.join(r, f); out.append((p.replace(BS, "/"), os.path.getsize(p)))
    return out


def open_writers(src):
    """[(pid, path)] for every process holding an open handle on a file under src (any mode: Windows open_files() does not report write mode, so any holder is refused)."""
    import psutil
    pref = src.replace(BS, "/").rstrip("/").lower() + "/"; hits = []
    for p in psutil.process_iter(["pid"]):
        try:
            for f in p.open_files():
                if f.path.replace(BS, "/").lower().startswith(pref): hits.append((p.pid, f.path))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
    return hits


def relocate(src, dst, mp, files=None, check_bound=True, check_floor=True, make_junction=True, check_writers=True):
    """Returns 0 on success, nonzero rc on refusal/failure (source is untouched on any nonzero rc)."""
    name = os.path.basename(src)
    if check_bound:
        import ckpt_bound as B
        if any(b.upper().startswith(src.upper()) for b in B.bound_dirs()):
            print("REFUSED: bound set touches", src); return 2
    if check_writers:
        w = open_writers(src)
        if w:
            print("REFUSED: open handle(s) under", src, w[:5]); return 4
    files = files or walk(src); tot = sum(s for _, s in files)
    print(f"{name}: {len(files)} files {tot/2**30:.2f} GiB -> {dst}", flush=True)
    if check_floor:
        import reserve_plan
        fl = reserve_plan.floor_gib(); left = shutil.disk_usage("B:/").free - tot
        if left < fl * 2 ** 30:
            print(f"REFUSED: move would leave B: at {left/2**30:.0f} GiB free (< {fl:.0f} GiB reserve_plan.floor_gib())"); return 3
    os.makedirs(os.path.dirname(mp), exist_ok=True); rows = {}
    if os.path.exists(mp):
        for l in open(mp):
            r = json.loads(l); rows[r["rel"]] = r
    lock = threading.Lock(); done = [0]; t0 = time.time()

    def one(fs):
        p, size = fs; rel = p[len(src) + 1:]; d = dst + "/" + rel
        r = rows.get(rel)
        if r and "mtime_ns" in r and os.path.exists(d) and os.path.getsize(d) == size and r["size"] == size and os.stat(p).st_mtime_ns == r["mtime_ns"]:
            return
        sha, sz, mt = sha_copy(p, d)
        row = dict(rel=rel, size=sz, mtime_ns=mt, sha256=sha)
        with lock:
            with open(mp, "a") as f:
                f.write(json.dumps(row) + "\n")
            rows[rel] = row; done[0] += 1
            if done[0] % 50 == 0: print(time.strftime("%H:%M:%S"), "copied", done[0], f"{(time.time()-t0)/60:.1f} min", flush=True)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, files))
    if _TEST_HOOK_AFTER_COPY: _TEST_HOOK_AFTER_COPY()
    bad = []

    def ver(fs):
        p, size = fs; rel = p[len(src) + 1:]; d = dst + "/" + rel; r = rows[rel]
        try:
            if not os.path.exists(d) or os.path.getsize(d) != r["size"] or sha_of(d) != r["sha256"]:
                bad.append(("dest", rel)); return
            st = os.stat(p)      # pass 3: the SOURCE as it is now must equal what was copied
            if st.st_size != r["size"] or st.st_mtime_ns != r["mtime_ns"] or sha_of(p) != r["sha256"]:
                bad.append(("source-changed", rel))
        except OSError:
            bad.append(("error", rel))
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(ver, files))
    now = {p for p, _ in walk(src)}; was = {p for p, _ in files}
    if now != was:
        bad += [("source-set-changed", p[len(src) + 1:]) for p in sorted(now ^ was)]
    if bad or any(p[len(src) + 1:] not in rows for p, _ in files):
        print("VERIFY FAILED; source untouched:", bad[:5], len(bad), len(rows), len(files)); return 1
    if check_writers:
        w = open_writers(src)
        if w:
            print("REFUSED at delete: open handle(s) under", src, w[:5], "; source untouched"); return 4
    print("VERIFIED", len(files), "files sha256-equal at dest and unchanged at source; removing source", flush=True)
    shutil.rmtree(src)
    if make_junction:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", src.replace("/", BS), dst.replace("/", BS)], capture_output=True, text=True)
        print(r.stdout.strip(), r.stderr.strip(), flush=True)
    print("RELOCATE DONE", name, flush=True)
    return 0


def main():
    name = sys.argv[1]; dry = "--dry" in sys.argv
    src = name.replace(BS, "/").rstrip("/") if ":" in name else SRC_ROOT + name      # NAME = dir under A:/, or a full path (e.g. a model-cache directory on the system drive)
    name = os.path.basename(src) if ":" in sys.argv[1] else name; dst = DST_BASE + (src[0] + "-" + name if ":" in sys.argv[1] else name)
    if os.path.islink(src) or (os.path.isdir(src) and os.path.realpath(src).replace(BS, "/").upper().startswith("B:")):
        print("already a junction/redirect:", src); return
    if dry:
        import reserve_plan
        files = walk(src); tot = sum(s for _, s in files)
        print(f"DRY {name}: {len(files)} files {tot/2**30:.2f} GiB; floor {reserve_plan.floor_gib():.0f} GiB; open handles: {open_writers(src)[:5]}"); return
    sys.exit(relocate(src, dst, MAN + "a-relocate-" + name + ".jsonl"))


if __name__ == "__main__":
    main()

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute an ACKED B-reserve manifest (lead 82254/82258). Usage: python scripts/reserve_evict.py <manifest.tsv> --manifest-sha256 <sha> --ack <lead-mail-id> [--dry] [--workers N]
Refuses without the pinned manifest sha256 and an --ack id. Per file, ALL must hold or it is SKIPPED (never deleted on a mismatch):
  - row status CANDIDATE; path under <m-root>/ember-live-receipts, a regular file (not a link), not under any KEEP path (H47 hour, H46 head trained-child, H45 child, depth 1/2 nodes, selected-continuation-head.json);
  - local size == manifest size; local sha256 (recomputed now) == manifest sha256;
  - HF custody: file in the row's repo:path whose server LFS sha256 == sha and size equal, re-read from the server immediately before the delete.
Receipt row (appended BEFORE os.remove): logs/reserve-evict-receipts.jsonl. os.remove only. Physical bytes: unique inodes whose every link is a candidate (lead 82147).
Red: python scripts/tests/reserve_evict_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, LANE_ROOT, M_ROOT
import os, sys, json, time, hashlib, threading
pass
import evict_ckpt_list as E
RC = (LANE_ROOT + "/logs/reserve-evict-receipts.jsonl"); BASE = (M_ROOT + "/ember-live-receipts/")
import protected_set as PS
KEEP = PS.reserve_markers()      # issue 2450: the declared protected set (loops/protected-set.json: shared markers + reserve_markers); refuse_reason re-reads it per file
RESERVE_FILE = os.environ.get("RESERVE_FILE", (LANE_ROOT + "/loops/reserve.json"))
class Refused(RuntimeError): pass
def reserve_decl(path=None):
    """The reserve declaration this run serves (loops/reserve.json), with its sha256, for the run receipt (issue 2450)."""
    p = path or RESERVE_FILE
    try:
        raw = open(p, "rb").read(); return dict(file=p, sha256=hashlib.sha256(raw).hexdigest(), declaration=json.loads(raw.decode("utf-8")))
    except Exception as e:
        return dict(file=p, missing=True, error=type(e).__name__)
def refuse_reason(path):
    p = path.replace("\\", "/")
    if not p.startswith(BASE): return ("outside " + M_ROOT + "/ember-live-receipts")
    if any(k in p for k in PS.reserve_markers()): return "under a KEEP path"      # fail closed: ProtectedSetError propagates and nothing is removed
    if not p.endswith(".pt"): return "not a .pt file"
    return None
def sha_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(16 << 20), b""): h.update(c)
    return h.hexdigest()
def load(man, want_sha):
    raw = open(man, "rb").read()
    if hashlib.sha256(raw).hexdigest() != want_sha: raise Refused("manifest sha256 != pinned value: refusing")
    rows = [l.split("\t") for l in raw.decode().splitlines()[1:] if l.strip()]
    return [dict(gib=float(r[1]), sha=r[2], hf=r[3], path=r[4].replace("\\", "/")) for r in rows if r[0] == "CANDIDATE"]
def main():
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import HfApi
    a = sys.argv
    if "--manifest-sha256" not in a or "--ack" not in a: raise Refused("--manifest-sha256 and --ack <lead mail id> are required")
    man = a[1]; rows = load(man, a[a.index("--manifest-sha256") + 1]); ack = a[a.index("--ack") + 1]; dry = "--dry" in a
    nw = int(a[a.index("--workers") + 1]) if "--workers" in a else 4
    api = HfApi(); lock = threading.Lock(); st = dict(n=0, phys=0, skipped=[]); os.makedirs(os.path.dirname(RC), exist_ok=True)
    import shutil; free0 = shutil.disk_usage("B:/").free; st["series"] = []; PSD = PS.load(); rdecl = reserve_decl()      # PS.load raises = fail closed before any I/O
    hidx = {}
    for e in api.list_repo_tree(("wordingone/" + HF_RAW_REPO), path_in_repo="checkpoints", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs: hidx.setdefault(e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256, e.size)
    gaps = E.guard_children([r["path"] for r in rows if not refuse_reason(r["path"]) and os.path.isfile(r["path"])], lambda s, b: hidx.get(s) == b)      # lead 82370: no child of a scored hour may become unrestorable
    for c, g in gaps.items(): print("CHILD-GAP (all its rows skipped):", c, g[:3], flush=True)
    def skip(p, why):
        with lock: st["skipped"].append((p, why))
    def one(r):
        p = r["path"]; why = refuse_reason(p)
        if why: return skip(p, why)
        if E.child_of(p) in gaps: return skip(p, f"child would not stay restorable: {len(gaps[E.child_of(p)])} manifest items on neither B: nor HF (lead 82370)")
        if not os.path.isfile(p) or os.path.islink(p): return skip(p, "not a regular file (missing or link)")
        stt = os.stat(p)
        if stt.st_nlink != 1: return skip(p, f"st_nlink {stt.st_nlink} != 1: not listed as a sole name")
        s = sha_of(p)
        if s != r["sha"]: return skip(p, "local sha256 != manifest sha256")
        repo, hp = r["hf"].split(":", 1)
        srv = api.get_paths_info(repo, [hp], expand=True, repo_type="dataset")
        lf = srv[0].lfs if srv else None; ssha = (lf["sha256"] if isinstance(lf, dict) else getattr(lf, "sha256", None)) if lf else None
        if not srv or ssha != s or srv[0].size != stt.st_size: return skip(p, "server re-read mismatch")
        if dry:
            with lock: st["n"] += 1; st["phys"] += stt.st_size
            return
        with lock:
            open(RC, "a", encoding="utf-8").write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=p, size=stt.st_size, sha256=s, hf=r["hf"], physical_bytes_freed=stt.st_size,
                verified="local sha256 recomputed == manifest == server LFS sha256, size equal, server re-read just before delete", manifest=man, ack=f"lead mail {ack}", protected_set_sha256=PSD["sha256"])) + "\n")
        os.remove(p)
        with lock: st["n"] += 1; st["phys"] += stt.st_size; st["series"].append(dict(path=p, bytes=stt.st_size, free_after_bytes=shutil.disk_usage("B:/").free))      # measured after EACH eviction (other writers included)
    with ThreadPoolExecutor(nw) as ex: list(ex.map(one, rows))
    d = shutil.disk_usage("B:/").free - free0
    print(("DRY " if dry else "") + f"removed {st['n']} of {len(rows)}; PHYSICAL by receipts {st['phys']/2**30:.2f} GiB; MEASURED B: free change {d/2**30:+.2f} GiB (other writers included); skipped {len(st['skipped'])}; B free {shutil.disk_usage('B:/').free/2**30:.1f} GiB", flush=True)
    for p, w in st["skipped"][:50]: print("SKIP", w, p, flush=True)
    if not dry:   # ONE run receipt: the reserve declaration served, the protected set used, free space before / after each eviction / at the end (issue 2450)
        open(RC, "a", encoding="utf-8").write(json.dumps(dict(kind="run", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), manifest=man, ack=f"lead mail {ack}", reserve_declaration=rdecl,
            protected_set=dict(path=PSD["path"], sha256=PSD["sha256"], declared_by=PSD["declared_by"], declared_at=PSD["declared_at"]), removed=st["n"], skipped=len(st["skipped"]),
            physical_bytes_by_receipts=st["phys"], free_before_bytes=free0, free_after_bytes=shutil.disk_usage("B:/").free, measured_delta_bytes=d, free_after_each=st["series"])) + "\n")
    json.dump(dict(skipped=st["skipped"], removed=st["n"], physical=st["phys"], dry=dry), open((LANE_ROOT + "/logs/reserve-evict.summary.json"), "w"), indent=1)
if __name__ == "__main__": main()

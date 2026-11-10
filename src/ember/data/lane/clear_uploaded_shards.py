# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Clear local packed token shards / objects that are already on the PRIVATE train repo and server-verified (lead 82094; verify-before-delete, data stays on HF).
CLASS GUARD (lead 82108, after H45's builder died on an evicted NEW shard): a SHARD is evictable ONLY if (a) its name is in the ledger of an hour in the SELECTED head's ancestry (derived from selected-continuation-head.json; refuted H40-H44 children are NOT in it; fail CLOSED when the head/chain/ledger is unreadable) or (b) its pack is DROPPED from admission (an -r1/-r2 twin exists, or supersession-3/4 names it) so no hour will ever read it. Any shard of an admitted-but-not-yet-consumed intake is REFUSED. Objects (objects/*.zst) are not hour inputs and keep the old rule.
For each candidate: HF path text/<pack>/(shards|objects)/<file> in wordingone/ember-train-private; deleted ONLY if the repo has that path, server size == local size and server LFS sha256 == the locally recomputed sha256. docs-index/ledger/intake/receipt/source-manifest/prov files are never touched.
Deletion is os.remove inside <lane-root>/packed only, receipt row appended to logs/clear-uploaded-20261109.jsonl BEFORE each remove.
Usage: python scripts/clear_uploaded_shards.py [--dry] [--min-free-gib N] [--only PACK ...]
Red: python scripts/tests/clear_shards_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, time, hashlib, shutil, threading
from lane_config import LANE_ROOT as ROOT; REPO = "wordingone/ember-train-private"; RC = ROOT + "/logs/clear-uploaded-20261109.jsonl"
HEAD_FILE = os.environ.get("HEAD_FILE", (M_ROOT + "/ember-live-receipts/selected-continuation-head.json"))   # lead 82113: consumed = ancestry of the selected head, derived, not hand-seeded
SUP = [ROOT + "/audit/supersession-3.jsonl", ROOT + "/audit/supersession-4.jsonl"]


class GuardError(RuntimeError):
    pass


def lineage_ledgers(head_path=None):
    """Shard-ledger paths of every hour in the SELECTED head's ancestry (lead 82113): selected-continuation-head.json -> hour-result.json ->
    lineage.parent_checkpoint -> that measurement dir's hour-result.json -> ... Refuted children (H40-H44) are not in the head's ancestry, so they never count.
    Fails CLOSED: unreadable head, missing hour-result, missing ledger path or a broken/cyclic chain raises GuardError."""
    head_path = head_path or HEAD_FILE
    try: head = json.load(open(head_path, encoding="utf-8")); hp = head["hour_result_path"]
    except Exception as e: raise GuardError(f"selected head unreadable at {head_path}: {e} (fail closed)")
    ledgers, seen, n = [], set(), 0
    while hp:
        key = os.path.normcase(os.path.abspath(hp))
        if key in seen: break                        # the chain bottoms out on a self-parented seed hour
        seen.add(key)
        try: r = json.load(open(hp, encoding="utf-8"))
        except Exception as e: raise GuardError(f"hour-result unreadable at {hp}: {e} (fail closed)")
        lp = (r.get("input_binding") or {}).get("shard_ledger_path")
        if not lp: raise GuardError(f"hour-result {hp} names no shard_ledger_path (fail closed)")
        if lp not in ledgers: ledgers.append(lp)
        par = (r.get("lineage") or {}).get("parent_checkpoint")
        if not par: break
        hp = os.path.join(os.path.dirname(str(par).rstrip(r"\/")), "hour-result.json")
        if not os.path.exists(hp) and os.path.normcase(os.path.abspath(hp)) not in seen:
            raise GuardError(f"ancestor hour-result missing: {hp} (fail closed)")
        n += 1
        if n > 500: raise GuardError("ancestry deeper than 500 hours (fail closed)")
    if not ledgers: raise GuardError("selected head yields no ledgers (fail closed)")
    return ledgers


def consumed_names(head_path=None):
    """Shard names (v1-NNNNN-sha12.bin) referenced by the ledgers of the selected head's ancestry. Fails closed."""
    names = set()
    for lp in lineage_ledgers(head_path):
        if not os.path.exists(lp): raise GuardError(f"consumed ledger missing: {lp} (fail closed)")
        for l in open(lp, encoding="utf-8"):
            if l.strip():
                nm = json.loads(l).get("name")
                if nm: names.add(nm)
    return names


def dropped_packs(packed_root=None, sup_files=None):
    """Packs no hour will read: has an -r1/-r2 twin, named by supersession-3/4 (same rule as training's h45_intakes)."""
    packed_root = packed_root or ROOT + "/packed"; d = set()
    names = {n for n in os.listdir(packed_root) if os.path.isdir(f"{packed_root}/{n}")}
    for n in names:
        if (n + "-r1") in names or (n + "-r2") in names: d.add(n)
    for sf in (sup_files if sup_files is not None else SUP):
        if os.path.exists(sf):
            for l in open(sf, encoding="utf-8"):
                if l.strip():
                    r = json.loads(l); p = r.get("original_pack") or r.get("pack")
                    if p: d.add(p)
    return d


def evictable(pack, sub, fname, consumed, dropped):
    """(ok, reason). The class guard; every deletion goes through this."""
    if sub == "objects": return True, "object (not an hour input)"
    if fname in consumed: return True, "consumed by a trained hour"
    if pack in dropped: return True, "pack dropped from admission"
    return False, "admitted and not yet consumed by a governed hour"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest()


def main():
    from concurrent.futures import ThreadPoolExecutor
    from huggingface_hub import HfApi
    dry = "--dry" in sys.argv; only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else []
    target = float(sys.argv[sys.argv.index("--min-free-gib") + 1]) if "--min-free-gib" in sys.argv else None
    consumed = consumed_names(); dropped = dropped_packs(); print(f"consumed shard names: {len(consumed)}; dropped packs: {len(dropped)}", flush=True)
    api = HfApi(); hf = {}
    for e in api.list_repo_tree(REPO, path_in_repo="text", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs: hf[e.path] = (e.size, e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256)
    print("HF files indexed:", len(hf), flush=True)
    freed = [0]; kept = {"not_on_hf": 0, "mismatch": 0, "admitted_unconsumed": 0}; deleted = [0]; lock = threading.Lock(); stop = [False]; work = []
    for pack in sorted(os.listdir(ROOT + "/packed")):
        if only and pack not in only: continue
        for sub in ("shards", "objects"):
            d = f"{ROOT}/packed/{pack}/{sub}"
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)): work.append((pack, sub, f, f"{d}/{f}"))
    print("local candidate files:", len(work), flush=True)

    def one(w):
        pack, sub, f, p = w
        if stop[0]: return
        ok, why = evictable(pack, sub, f, consumed, dropped)
        if not ok:
            with lock: kept["admitted_unconsumed"] += 1
            return
        key = f"text/{pack}/{sub}/{f}"; srv = hf.get(key)
        if not srv:
            with lock: kept["not_on_hf"] += 1
            return
        size = os.path.getsize(p)
        if size != srv[0]:
            with lock: kept["mismatch"] += 1
            return
        s = sha(p)
        if s != srv[1]:
            with lock: kept["mismatch"] += 1
            print("MISMATCH kept:", key, flush=True); return
        if dry:
            with lock: freed[0] += size; deleted[0] += 1
            return
        with lock:
            with open(RC, "a") as rc: rc.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), path=p.replace("\\", "/"), hf=f"{REPO}:{key}", size=size, sha256=s, verified="server LFS sha256+size == local", why=why)) + "\n")
        os.remove(p)
        with lock:
            freed[0] += size; deleted[0] += 1
            if target and shutil.disk_usage("B:/").free / 2**30 >= target: stop[0] = True
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, work))
    print(("DRY " if dry else "") + f"deleted {deleted[0]} files {freed[0]/2**30:.2f} GiB; kept not_on_hf={kept['not_on_hf']} mismatch={kept['mismatch']} admitted_unconsumed={kept['admitted_unconsumed']}; B free now {shutil.disk_usage('B:/').free/2**30:.1f} GiB", flush=True)


if __name__ == "__main__":
    main()

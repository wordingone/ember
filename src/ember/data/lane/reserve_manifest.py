# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only eviction MANIFEST for B: free space (lead 82254). Deletes nothing.
Candidates: *.pt objects under <m-root>/ember-live-receipts that are NOT in a protected tree and whose sha256 (content-addressed file name, recomputed locally) has a server-side LFS copy of equal size in wordingone/ember-raw-private (read back from HF now, not from our ledger).
Protected trees: selected head + its ancestry (hour-result lineage.parent_checkpoint chain), the newest N hour dirs by mtime (default 2) and their probes, the H45 child, depth 1/2 KEEP nodes of evict_ckpt_list, anything in --pin files (paths listed one per line, e.g. training's H48 derive).
Physical GiB counts unique inodes whose EVERY link is a candidate (lead 82147).
Usage: python scripts/reserve_manifest.py [--newest N] [--pin file]   -> logs/reserve-manifest-<ts>.tsv/.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, time, hashlib
pass
import evict_ckpt_list as E
BASE = (M_ROOT + "/ember-live-receipts"); REPO = E.REPO
SEL = BASE + "/selected-continuation-head.json"
def norm(p): return p.replace("\\", "/")
def ancestry():
    out = []; hr = json.load(open(SEL))["hour_result_path"]
    while hr and os.path.exists(hr):
        d = os.path.dirname(norm(hr)); out.append(d); r = json.load(open(hr)); par = (r.get("lineage") or {}).get("parent_checkpoint")
        if not par: break
        par = norm(par)
        i = par.find("/trained-child"); base = par[:i] if i > 0 else par
        hr = base + "/hour-result.json"
    return out
_SC = (LANE_ROOT + "/logs/sha-cache.json")
def sha_cached(p, sz):
    c = json.load(open(_SC)) if os.path.exists(_SC) else {}
    st = os.stat(p); k = f"{p}|{sz}|{int(st.st_mtime)}"
    if k not in c:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(16 << 20), b""): h.update(b)
        c[k] = h.hexdigest(); json.dump(c, open(_SC, "w"))
    return c[k]
def main():
    n = int(sys.argv[sys.argv.index("--newest") + 1]) if "--newest" in sys.argv else 2
    pins = []
    for i, a in enumerate(sys.argv):
        if a == "--pin": pins += [norm(l.strip()) for l in open(sys.argv[i + 1]) if l.strip()]
    anc = ancestry()
    hours = sorted([d for d in os.listdir(BASE) if d.startswith("cia-hour-") or d.startswith("cia-probe-")], key=lambda d: os.path.getmtime(f"{BASE}/{d}"), reverse=True)
    newest = [f"{BASE}/{d}" for d in hours[:n * 2]]      # hour + probe per slot
    depth = int(sys.argv[sys.argv.index("--anc-depth") + 1]) if "--anc-depth" in sys.argv else 2      # lead 82254: selected head + its parent; the older keeps are E.KEEP_MARKERS (H39 chain depth 1/2, H45 child)
    protect = [norm(x) for x in anc[:depth]] + newest + list(E.KEEP_MARKERS) + pins
    def prot(p):
        p = norm(p)
        return next((k for k in protect if (k in p) or p.startswith(k.rstrip("/") + "/")), None)
    cands = []; t0 = time.time()
    for dp, dn, fn in os.walk(BASE):
        for f in fn:
            if not f.endswith(".pt"): continue
            p = norm(os.path.join(dp, f))
            try: st = os.stat(p)
            except OSError: continue
            if st.st_size < (50 << 20): continue
            cands.append((p, st.st_size, st.st_nlink, (st.st_dev, st.st_ino)))
    print("scanned .pt >=50MB:", len(cands), "in", round(time.time() - t0), "s", flush=True)
    from huggingface_hub import HfApi
    api = HfApi(); idx = {}
    for e in api.list_repo_tree(REPO, path_in_repo="checkpoints", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs:
            sh = e.lfs["sha256"] if isinstance(e.lfs, dict) else e.lfs.sha256; idx.setdefault(sh, (e.path, e.size))
    print("HF LFS shas:", len(idx), flush=True)
    rows = []; inode_seen = {}
    for p, sz, nl, key in cands:
        why = prot(p)
        name = os.path.basename(p)[:-3]
        if len(name) != 64 or any(c not in "0123456789abcdef" for c in name): name = sha_cached(p, sz)      # non-content-addressed file (optimizer-state.pt): sha256 recomputed locally
        if why: rows.append(dict(path=p, gib=sz / 2**30, status="PROTECTED", why=why[-70:])); continue
        hit = idx.get(name)       # pre-filter by content-addressed NAME; sha recomputed below only for the chosen set
        if not hit or hit[1] != sz: rows.append(dict(path=p, gib=sz / 2**30, status="NO-HF-COPY", why="name sha not in raw-private LFS index with equal size")); continue
        rows.append(dict(path=p, gib=sz / 2**30, nlink=nl, inode=f"{key[0]}:{key[1]}", status="CANDIDATE", hf=f"{REPO}:{hit[0]}", sha256=name, size=sz))
    cand = [r for r in rows if r["status"] == "CANDIDATE"]
    # physical: unique inodes; links outside candidates -> partial
    byino = {}
    for r in cand: byino.setdefault(r["inode"], []).append(r)
    phys = 0; partial = 0
    for ino, rs in byino.items():
        if rs[0]["nlink"] > 1 and len(rs) < rs[0]["nlink"]: partial += 1; [x.update(note="inode has links outside the candidate set: frees nothing alone") for x in rs]
        else: phys += rs[0]["size"]
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()); base = f"{LANE_ROOT}/logs/reserve-manifest-{ts}"
    with open(base + ".tsv", "w") as f:
        f.write("status\tgib\tsha256\thf\tpath\n")
        for r in sorted(rows, key=lambda r: (r["status"], r["path"])): f.write(f"{r['status']}\t{r['gib']:.3f}\t{r.get('sha256','')}\t{r.get('hf','')}\t{r['path']}\n")
    summ = dict(ts=ts, ancestry=anc, newest_protected=newest, pins=pins, n_candidates=len(cand), cand_logical_gib=sum(r["gib"] for r in cand), cand_physical_gib=phys / 2**30, partial_inodes=partial,
                by_status={s: (sum(1 for r in rows if r["status"] == s), round(sum(r["gib"] for r in rows if r["status"] == s), 2)) for s in {r["status"] for r in rows}})
    json.dump(summ, open(base + ".json", "w"), indent=1); print(json.dumps(summ, indent=1)); print(base)
if __name__ == "__main__": main()

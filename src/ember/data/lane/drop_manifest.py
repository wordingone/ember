# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only DROP MANIFEST for packed sets (lead 82361/82373). Deletes nothing.
Per file under packed/<pack>/(shards|objects): size, st_nlink, whether <train-repo> text/<pack>/<sub>/<file> exists with equal size (the executor re-reads the server and recomputes the local sha256 per file before each delete),
and a class:
  KEEP-H49-UNION   st_nlink > 1: another name lives in the catalog train cache the next hour reads
  KEEP-NOT-ON-HF   no server copy of equal size
  DROP-FREE        an object (not an hour input), a consumed shard, or a shard of a pack dropped from admission  (the old clear_uploaded_shards class guard allows these)
  DROP-HF-ONLY     a shard of an ADMITTED pack that no hour has consumed yet: dropping makes that pool HF-only; the cost to bring it back is bytes / 3.7 MB/s (needs lead's waiver of the class guard)
Output: logs/drop-manifest-<ts>.tsv (class, gib, pack, sub, hf_path, path) and a per-pack summary on stdout.
Usage: python drop_manifest.py"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clear_uploaded_shards as C
from huggingface_hub import HfApi

BASE = C.ROOT; RATE = 3.7e6


def main():
    consumed = C.consumed_names(); dropped = C.dropped_packs()
    api = HfApi(); hf = {}
    for e in api.list_repo_tree(C.REPO, path_in_repo="text", recursive=True, expand=True, repo_type="dataset"):
        if e.__class__.__name__ == "RepoFile" and e.lfs: hf[e.path] = e.size
    rows = []
    for pack in sorted(os.listdir(BASE + "/packed")):
        if not os.path.isdir(f"{BASE}/packed/{pack}"): continue
        for sub in ("shards", "objects"):
            d = f"{BASE}/packed/{pack}/{sub}"
            if not os.path.isdir(d): continue
            for f in sorted(os.listdir(d)):
                p = f"{d}/{f}"; st = os.lstat(p); key = f"text/{pack}/{sub}/{f}"
                if st.st_nlink > 1: cls = "KEEP-H49-UNION"
                elif hf.get(key) != st.st_size: cls = "KEEP-NOT-ON-HF"
                else:
                    ok, _ = C.evictable(pack, sub, f, consumed, dropped)
                    cls = "DROP-FREE" if ok else "DROP-HF-ONLY"
                rows.append((cls, st.st_size, pack, sub, key, p))
    if "--complete-only" in sys.argv:      # drop a pack only when EVERY shard/object of it has a server copy (a half-uploaded pack stays whole locally)
        partial = {r[2] for r in rows if r[0] == "KEEP-NOT-ON-HF"}
        rows = [("HOLD-PARTIAL-PACK",) + r[1:] if r[0].startswith("DROP") and r[2] in partial else r for r in rows]
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()); out = f"{BASE}/logs/drop-manifest-{ts}.tsv"
    with open(out, "w", encoding="utf-8") as f:
        f.write("class\tgib\tpack\tsub\thf_path\tpath\n")
        for r in rows: f.write(f"{r[0]}\t{r[1]/2**30:.4f}\t{r[2]}\t{r[3]}\t{r[4]}\t{r[5]}\n")
    by = {}
    for cls, sz, pack, sub, key, p in rows:
        b = by.setdefault(pack, {}); b[cls] = b.get(cls, 0) + sz
    tot = {}
    for pack, b in by.items():
        for c, v in b.items(): tot[c] = tot.get(c, 0) + v
    print("TOTAL GiB by class:", {c: round(v / 2**30, 2) for c, v in tot.items()})
    print("%-34s %9s %9s %9s %9s  %s" % ("pack", "DROP-FREE", "HF-ONLY", "KEEP-H49", "NOT-ON-HF", "rehydrate HF-ONLY (min @3.7MB/s)"))
    for pack, b in sorted(by.items()):
        g = lambda c: b.get(c, 0) / 2**30
        if g("DROP-FREE") + g("DROP-HF-ONLY") + g("KEEP-H49-UNION") + g("KEEP-NOT-ON-HF") < 0.005: continue
        print("%-34s %9.2f %9.2f %9.2f %9.2f  %6.0f" % (pack, g("DROP-FREE"), g("DROP-HF-ONLY"), g("KEEP-H49-UNION"), g("KEEP-NOT-ON-HF"), b.get("DROP-HF-ONLY", 0) / RATE / 60))
    print(out)


if __name__ == "__main__":
    main()

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""READ-ONLY audit of what the nine standing-stop deleters removed in the past (lead 82450). Reads receipts/manifests under logs/ and audit/, the Hub file index (audit_hf_index.py) and stats local paths; deletes, uploads, repairs nothing.
One row per removed object: script, run, ts, path, size, sha256 (as recorded BEFORE the removal), the Hub copy found NOW, a verdict and the basis.
Verdicts (definitions, applied the same way to every row):
  VERIFIED_COPY_EXISTS  the record carries the local sha256, and the Hub tree today has an object with that exact LFS sha256 and size (at the recorded path or elsewhere).
  NO_COPY_FOUND         the record carries a sha256 (or names a Hub path) and the Hub tree has no object with that sha256 (path absent, or present with another sha256/size); or the record says the file was a failed/partial/regenerable one.
  CANNOT_TELL           the record has no sha256, or the Hub object is not an LFS object (no sha256 to compare): a same-name same-size object is only a hint, never a verdict.
Usage: python scripts/audit_deleters.py [--out DIR]   -> DIR/audit-rows.jsonl, DIR/audit-summary.json, DIR/audit-table.md  (default <m-root>/avir/<data>/state/audit-82450)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_RAW_REPO, HF_TRAIN_REPO, LANE_ROOT, M_ROOT, SEAT_DATA
import os, sys, json, glob, collections, time
from lane_config import LANE_ROOT as D; OUT = (M_ROOT + "/avir/" + SEAT_DATA + "/state/audit-82450")
RAW, TRAIN, CORPUS = ("wordingone/" + HF_RAW_REPO), ("wordingone/" + HF_TRAIN_REPO), "wordingone/ember-corpus"


def jl(f):
    return [json.loads(l) for l in open(f, encoding="utf-8-sig") if l.strip()] if os.path.exists(f) else []


def load_index(path):
    by_path, by_sha = {}, collections.defaultdict(list)
    for r in jl(path):
        by_path[(r["repo"], r["path"])] = (r["size"], r["sha256"])
        if r["sha256"]: by_sha[r["sha256"]].append((r["repo"], r["path"], r["size"]))
    return by_path, by_sha


def verdict(IDX, sha, size, ref=None, claim=None):
    """-> (verdict, basis). ref=(repo, path) the record names; claim = a fixed statement from the record when it carries no hash"""
    by_path, by_sha = IDX
    e = by_path.get(ref) if ref else None
    if sha:
        if e and e[1] == sha and e[0] == size: return "VERIFIED_COPY_EXISTS", "Hub %s:%s LFS sha256 == recorded sha256, size equal" % ref
        hits = [h for h in by_sha.get(sha, []) if h[2] == size]
        if hits: return "VERIFIED_COPY_EXISTS", "Hub %s:%s has the same sha256+size" % hits[0][:2] + ("" if not ref else " (not at the recorded path %s:%s)" % ref)
        if e and e[1] is None: return "CANNOT_TELL", "Hub has %s:%s but it is not an LFS object (no sha256 to compare); size %s" % (ref + ("equal" if e[0] == size else "DIFFERS",))
        if e: return "NO_COPY_FOUND", "Hub %s:%s exists with a DIFFERENT %s; no object anywhere has the recorded sha256" % (ref + ("sha256" if e[0] == size else "size+sha256",))
        return "NO_COPY_FOUND", ("no Hub object at %s:%s and none with the recorded sha256" % ref if ref else "no Hub object with the recorded sha256") + (" (" + claim + ")" if claim else "")
    if ref and e and e[0] != size: return "NO_COPY_FOUND", "record has no sha256; the Hub object at %s:%s has a DIFFERENT size (%s vs %s), so it is not a copy" % (ref + (e[0], size))
    if ref and e: return "CANNOT_TELL", "record has no sha256; Hub has %s:%s with the same size%s (a hint, not proof: equality cannot be re-proved now)" % (ref + ((", LFS sha256 " + e[1][:12]) if e[1] else ", non-LFS object",))
    if ref: return "NO_COPY_FOUND", "record has no sha256; no Hub object at %s:%s" % ref
    return "CANNOT_TELL", claim or "record has neither a sha256 nor a Hub path"


def split_ref(s):
    repo, _, p = s.partition(":"); return (repo, p) if p else None


def local_now(p):
    try: return "present %d B" % os.path.getsize(p)
    except OSError: return "absent"


def runs(rows, key="ts", gap=1800):
    """cluster rows into runs by timestamp gaps (> gap seconds starts a new run); rows without ts form one run"""
    def t(r):
        v = r.get(key)
        try: return time.mktime(time.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")) if v else 0
        except Exception: return 0
    out, last, n = {}, None, 0
    for i in sorted(range(len(rows)), key=lambda i: t(rows[i])):
        if last is None or t(rows[i]) - last > gap: n += 1
        out[i] = n; last = t(rows[i])
    return out


def build(IDX):
    R = []

    def add(script, runid, ts, path, size, sha, ref, claim=None, extra=""):
        v, b = verdict(IDX, sha, size, ref, claim)
        R.append(dict(script=script, run=runid, ts=ts, path=path, size=size, sha256=sha, verdict=v, basis=b, local_now=local_now(path) if path else "n/a", note=extra))

    def manifest(script, f, ref_of=None, sha_key="sha256", path_key="path", size_key="size", claim_of=None, extra_of=None):
        rows = jl(f); rn = runs(rows)
        for i, r in enumerate(rows):
            add(script, "%s#%d" % (os.path.basename(f), rn[i]), r.get("ts"), r.get(path_key), r.get(size_key), r.get(sha_key), ref_of(r) if ref_of else None, claim_of(r) if claim_of else None, extra_of(r) if extra_of else "")
    M = D + "/logs/manifests-20261108/"
    manifest("ckpt_lineage_delete", M + "ckpt-lineage-delete-manifest.jsonl", ref_of=lambda r: split_ref(r["hf_ref"]) if r.get("hf_ref") else None,
             claim_of=lambda r: "ruled probe/reproducible child: " + (r.get("verified_via") or "")[:90] if not r.get("hf_ref") else None, extra_of=lambda r: r.get("verified_via", "")[:60])
    manifest("ckpt_backup", M + "ckpt-delete-manifest.jsonl", ref_of=lambda r: (r["hf_repo"], r["hf_path"]))
    manifest("_pg_obj_del", M + "pg-objects-manifest.jsonl", ref_of=lambda r: (r["hf_repo"], r["hf_path"]))
    manifest("_wiki_del", M + "wikipedia-20220501-manifest.jsonl", claim_of=lambda r: "ruled: " + str(r.get("kind") or "") + " (refetchable/regenerable per the ruling)")
    manifest("_ws_del", M + "wikisource-manifest.jsonl", claim_of=lambda r: "ruled: refetch from " + str(r.get("archive_url") or "archive.org"))
    rec = json.load(open(D + "/logs/delete-approved-dirs-receipt.json", encoding="utf-8-sig"))
    for j in rec["jobs"]:
        manifest("delete_approved_dirs", j["manifest"], path_key="file", claim_of=lambda r: "ruled, regenerable: " + str(r.get("regenerate") or "")[:80], extra_of=lambda r, n=j["name"]: n)
    # drop_execute: tier 1 per file (hf repo:path, sha256, size); tier 2 per directory (file list with sizes only)
    rows = jl(D + "/logs/drop-exec-20261110T013103Z.jsonl")
    for r in rows:
        if r["tier"] == 1: add("drop_execute", "drop-exec-20261110T013103Z#1", r["ts"], r["path"], r["size"], r["sha256"], split_ref(r["hf"]), extra="tier1 " + r["cls"])
        else:
            for p, sz in r["files"]:
                pk = split_ref("%s:text/%s/%s" % (TRAIN, os.path.basename(r["dir"]).split("-pre-redaction")[0].split("-redacted")[0], p[len(r["dir"]) + 1:]))
                add("drop_execute", "drop-exec-20261110T013103Z#1", r["ts"], p, sz, None, pk if p.endswith((".zst", ".bin")) else None, claim="tier 2 intermediate dir %s: record lists size only" % os.path.basename(r["dir"]), extra="tier2 " + os.path.basename(r["dir"]))
    rr = jl(D + "/audit/raw-roll-receipts.jsonl"); rn = runs(rr)
    for i, r in enumerate(rr): add("raw_roll", "raw-roll-receipts#%d" % rn[i], r["ts"], r["local"], r["bytes"], r["sha256"], (r["repo"], r["path"]), extra="commit " + r["commit"][:10])
    fb = json.load(open(D + "/audit/free-b-receipt-20261107-095952.json", encoding="utf-8-sig"))
    for r in fb["deleted"]:
        p, w = r["path"], r["why"]; ref = None; claim = w[:120]
        if w.startswith("sha-verified on HF "):
            repo = w.split("HF ", 1)[1].strip()
            for pre in (D + "/upload/raw/", D + "/upload/train/"):
                if p.startswith(pre): ref = (repo, p[len(pre):])
            claim = "receipt: " + w + ("" if ref else "; Hub path not derivable from the local path")
        elif w.startswith("sha256-identical duplicate of "):
            other = w.split(" of ", 1)[1]; claim = "local duplicate %s: %s now (receipt carries no sha256)" % (other, local_now(other))
        if w.startswith(("failed partial download", "re-downloadable public source")):      # the receipt itself says there is no good copy to look for: a failed partial, or a public zip to re-download
            R.append(dict(script="free_b", run="free-b-receipt-20261107-095952#1", ts=fb["ts"], path=p, size=r["bytes"], sha256=None, verdict="NO_COPY_FOUND", basis="receipt: " + w[:110] + "; no Hub copy exists or was sought", local_now=local_now(p), note=w[:50])); continue
        add("free_b", "free-b-receipt-20261107-095952#1", fb["ts"], p, r["bytes"], None, ref, claim, extra=w[:50])
    return R


def table(R):
    by = collections.OrderedDict()
    for r in R: by.setdefault((r["script"], r["run"]), []).append(r)
    L = ["| script | run (evidence) | first ts | files | bytes | VERIFIED_COPY_EXISTS | NO_COPY_FOUND | CANNOT_TELL | still present locally |", "|---|---|---|---|---|---|---|---|---|"]
    for (s, run), rs in by.items():
        c = collections.Counter(r["verdict"] for r in rs); b = lambda v: sum(r["size"] or 0 for r in rs if r["verdict"] == v)
        g = lambda v: "%d (%.2f GiB)" % (c[v], b(v) / 2**30) if c[v] else "0"
        L.append("| %s | %s | %s | %d | %.2f GiB | %s | %s | %s | %d |" % (s, run, min((r["ts"] or "") for r in rs)[:19], len(rs), sum(r["size"] or 0 for r in rs) / 2**30, g("VERIFIED_COPY_EXISTS"), g("NO_COPY_FOUND"), g("CANNOT_TELL"), sum(1 for r in rs if r["local_now"] != "absent")))
    return "\n".join(L)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT; os.makedirs(out, exist_ok=True)
    IDX = load_index(out + "/hf-index.jsonl"); R = build(IDX)
    with open(out + "/audit-rows.jsonl", "w", encoding="utf-8") as f:
        for r in R: f.write(json.dumps(r) + "\n")
    tab = table(R); open(out + "/audit-table.md", "w", encoding="utf-8").write(tab + "\n")
    c = collections.Counter(r["verdict"] for r in R)
    json.dump(dict(rows=len(R), verdicts=c, index_files=len(IDX[0]), by_script={s: collections.Counter(r["verdict"] for r in R if r["script"] == s) for s in sorted({r["script"] for r in R})}), open(out + "/audit-summary.json", "w"), indent=1)
    print(tab); print("rows", len(R), dict(c), "->", out); return 0


if __name__ == "__main__":
    sys.exit(main())

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Redaction pass (lead 81713): the ember-train-private objects with credential-shaped spans become NEW objects '<name>-r1.jsonl.zst' (secret_scan.redact, <REDACTED_CREDENTIAL>).
Old objects are NEVER touched (H41 and other ledgers bind their hashes). Per file: stream from the private repo, sha256 == HF LFS oid, redact doc text, re-scan the new object (must be 0 hits),
upload as a new file next to the old one (never overwrites), verify the remote LFS sha. Manifest: redact-r1/MANIFEST.jsonl (old sha -> new sha, span counts per pattern, docs touched; no values)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import sys as _hs; _hs.path.insert(0, (LANE_ROOT + "/scripts")); import hf_push   # lead 82104: one funnel for HF writes
import os, sys, io, json, time, hashlib, requests
pass
import secret_scan, zstandard
from huggingface_hub import HfApi, get_token
REPO = "wordingone/ember-train-private"; from lane_config import LANE_ROOT as ROOT; OUTD = ROOT + "/redact-r1"; os.makedirs(OUTD, exist_ok=True)
AUDIT = ROOT + "/audit/secret-audit-ember-train-private.jsonl"; MAN = OUTD + "/MANIFEST.jsonl"
api = HfApi(); tok = get_token()
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
rows = {}
for l in open(AUDIT, encoding="utf-8"):
    r = json.loads(l)
    if r["status"] == "scanned": rows[r["path"]] = r
todo = sorted(p for p, r in rows.items() if r["hits"] and p.endswith(".jsonl.zst"))
done = set()
if os.path.exists(MAN):
    for l in open(MAN, encoding="utf-8"): done.add(json.loads(l)["old_path"])
log(f"{len(todo)} flagged object(s), {len(done)} already done")
for p in todo:
    if p in done: continue
    info = api.get_paths_info(REPO, [p], repo_type="dataset", expand=True)[0]; oid = info.lfs.sha256; size = info.size
    name = os.path.basename(p); loc = f"{OUTD}/{name}"; newname = name.replace(".jsonl.zst", "-r1.jsonl.zst"); newloc = f"{OUTD}/{newname}"; newp = p.rsplit("/", 1)[0] + "/" + newname
    have = os.path.getsize(loc) if os.path.exists(loc) else 0
    while have < size:
        try:
            with requests.get(f"https://huggingface.co/datasets/{REPO}/resolve/main/{p}", stream=True, timeout=(30, 90), headers={"Range": f"bytes={have}-", "Authorization": "Bearer " + tok, "User-Agent": "ember-redact/1.0"}) as r:
                r.raise_for_status()
                with open(loc, "ab") as f:
                    for c in r.iter_content(4 << 20): f.write(c); have += len(c)
        except Exception as e:
            log("drop", type(e).__name__, "resume", have); time.sleep(5); have = os.path.getsize(loc)
    h = hashlib.sha256()
    with open(loc, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h.update(c)
    if h.hexdigest() != oid: raise RuntimeError(f"{name} SHA MISMATCH vs HF oid; nothing written")
    counts = {}; ndocs = 0; nred = 0
    with open(loc, "rb") as fi, open(newloc, "wb") as fo:
        rd = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fi), encoding="utf-8")
        w = zstandard.ZstdCompressor(level=6).stream_writer(fo)
        for line in rd:
            d = json.loads(line); ndocs += 1
            c = {}; t = secret_scan.redact(d["text"], c)
            if c:
                nred += 1; d["text"] = t
                for k, v in c.items(): counts[k] = counts.get(k, 0) + v
            w.write((json.dumps(d, ensure_ascii=False) + "\n").encode("utf-8"))
        w.close()
    chk = secret_scan.scan_path(newloc)
    if chk["hits"]: raise RuntimeError(f"{newname} STILL HAS HITS after redaction {chk['hits']}; not uploaded")
    h2 = hashlib.sha256()
    with open(newloc, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h2.update(c)
    nsha = h2.hexdigest()
    if api.file_exists(REPO, newp, repo_type="dataset"):
        ri = api.get_paths_info(REPO, [newp], repo_type="dataset", expand=True)[0]
        if not (ri.lfs and ri.lfs.sha256 == nsha): raise RuntimeError(f"{newp} already exists with different bytes; not overwriting")
    else:
        hf_push.upload_file(api, path_or_fileobj=newloc, path_in_repo=newp, repo_id=REPO, repo_type="dataset", commit_message="redaction pass r1 (lead 81713): new object, old bytes kept for provenance")
        ri = api.get_paths_info(REPO, [newp], repo_type="dataset", expand=True)[0]
    if not (ri.lfs and ri.lfs.sha256 == nsha and ri.size == os.path.getsize(newloc)): raise RuntimeError(f"{newp} UPLOAD VERIFY FAILED")
    with open(MAN, "a", encoding="utf-8") as m:
        m.write(json.dumps(dict(old_path=p, old_sha256=oid, old_bytes=size, new_path=newp, new_sha256=nsha, new_bytes=os.path.getsize(newloc), docs=ndocs, docs_redacted=nred,
                                spans_by_pattern=counts, spans_total=sum(counts.values()), rescan_hits=0, scan_tool="secret_scan.py", placeholder=secret_scan.PLACEHOLDER)) + "\n")
    os.remove(loc); os.remove(newloc)
    log("OK", newname, "spans", sum(counts.values()), "docs_redacted", nred, "of", ndocs)
open(OUTD + "/ALL.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
log("ALL DONE", len(todo), "objects")

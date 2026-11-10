# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""One-time secret AUDIT of the PUBLIC repo wordingone/ember-corpus (lead 81676 item 2; local-first plan lead 81679). Read-only on HF and on the local copies.
1. HF tree with LFS sha256 + size (expand=True).  2. Local index: walk <m-root>/data and <m-root>/ember-data, hash (sha256, cached) only files whose SIZE equals some HF file size.
3. For each HF file: LFS sha256 matches a local file -> scan the LOCAL copy in place (zero download); no match -> download, scan, delete.
Streaming scan (scripts/secret_scan.py). Output: audit/secret-audit.jsonl, value-free (path, size, source local|download, hits{pattern:count}, scanned_bytes, skipped, status). Resumable.
Order: objects/ -> acquisition/heldout -> sources/staging/catalog -> acquisition/train -> rest. Skipped by design: checkpoints/**, tokens/**, avir-cli/**.
7z (stackexchange): streamed through py7zr if importable, else reported 'unscanned-7z'."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, time, hashlib
pass
import secret_scan
from huggingface_hub import HfApi, hf_hub_download
REPO = sys.argv[1] if len(sys.argv) > 1 else "wordingone/ember-corpus"; TAG = "" if REPO.endswith("ember-corpus") else "-" + REPO.split("/")[-1]
from lane_config import LANE_ROOT as ROOT; OUT = ROOT + f"/audit/secret-audit{TAG}.jsonl"; TMP = ROOT + "/audit-scan"; CACHE = ROOT + f"/audit/local-sha-cache{TAG}.jsonl"
LOCAL_BASES = [(M_ROOT + "/data"), (M_ROOT + "/ember-data"), (LANE_ROOT + "/packed"), (LANE_ROOT + "/bulk")]
os.makedirs(TMP, exist_ok=True); os.makedirs(ROOT + "/audit", exist_ok=True); os.environ["SECRET_SCAN_TMP"] = TMP
api = HfApi(); rev = api.dataset_info(REPO).sha
SKIP_PREFIX = ("checkpoints/", "tokens/", "avir-cli/")
def order(p):
    for i, pre in enumerate(("objects/", "acquisition/heldout/", "sources/", "staging/", "catalog/", "acquisition/train/")):
        if p.startswith(pre): return i
    return 9
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

files = []
for t in api.list_repo_tree(REPO, repo_type="dataset", recursive=True, expand=True):
    if hasattr(t, "size"): files.append((t.path, t.size, t.lfs.sha256 if getattr(t, "lfs", None) else None))
log(f"{len(files)} HF files at {rev[:8]}")
scan_set = [f for f in files if not f[0].startswith(SKIP_PREFIX)]
want_sizes = {}
for p, sz, sha in scan_set:
    if sha: want_sizes.setdefault(sz, set()).add(sha)

# ---- local index (size-gated hashing, cached) ----
cache = {}
if os.path.exists(CACHE):
    for l in open(CACHE, encoding="utf-8"):
        r = json.loads(l); cache[(r["path"], r["size"], r["mtime"])] = r["sha256"]
local = {}    # sha256 -> local path
nwalk = nhash = 0; t0 = time.time()
def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(8 << 20), b""): h.update(c)
    return h.hexdigest()
cf = open(CACHE, "a", encoding="utf-8")
for root in LOCAL_BASES:
    for dp, dn, fn in os.walk(root):
        for n in fn:
            p = os.path.join(dp, n).replace("\\", "/")
            try: st = os.stat(p)
            except OSError: continue
            nwalk += 1
            if st.st_size not in want_sizes: continue
            k = (p, st.st_size, int(st.st_mtime)); sha = cache.get(k)
            if sha is None:
                try: sha = hash_file(p)
                except OSError: continue
                nhash += 1; cf.write(json.dumps(dict(path=p, size=st.st_size, mtime=int(st.st_mtime), sha256=sha)) + "\n"); cf.flush()
            if sha in want_sizes[st.st_size]: local.setdefault(sha, p)
log(f"local walk: {nwalk} files seen, {nhash} hashed (size-gated), {len(local)} distinct HF LFS oids found locally, {time.time()-t0:.0f}s")

done = {}
if os.path.exists(OUT):
    for l in open(OUT, encoding="utf-8"):
        r = json.loads(l)
        if r.get("status") != "error": done[r["path"]] = r
todo = sorted([f for f in files if f[0] not in done], key=lambda f: (order(f[0]), f[0]))
log(f"{len(done)} already done; {len(todo)} to go; {sum(1 for f in todo if f[2] in local and not f[0].startswith(SKIP_PREFIX))} have a local copy")
def scan_7z(path):
    import py7zr, io
    hits = {}; tally = [0]
    with py7zr.SevenZipFile(path) as z:
        for name, bio in z.readall().items():
            secret_scan._scan_fileobj(bio, name, hits, tally, [])
    return {"hits": {k: v for k, v in hits.items() if v > 0}, "scanned_bytes": tally[0], "skipped": []}
import requests, threading
from concurrent.futures import ThreadPoolExecutor
wlock = threading.Lock()
from huggingface_hub import get_token
_TOKEN = get_token() if "private" in REPO else None   # private repo needs auth (token read from the local HF login, never logged)
def scan_remote(p, rev):
    """stream the HF file straight into the scanner (no disk, no cache); retry the whole file on a dropped connection"""
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/{p}"; last = None
    for attempt in range(4):
        try:
            hits = {}; tally = [0]; skipped = []
            with requests.get(url, stream=True, timeout=(30, 90), headers={"User-Agent": "ember-audit/1.0", **({"Authorization": "Bearer " + _TOKEN} if _TOKEN else {})}) as r:
                r.raise_for_status(); r.raw.decode_content = False
                if p.lower().endswith(".7z"):
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, dir=TMP, suffix=".7z") as t:
                        for c in r.iter_content(8 << 20): t.write(c)
                    try: res = scan_7z(t.name)
                    finally: os.remove(t.name)
                    return res
                secret_scan._scan_fileobj(r.raw, os.path.basename(p), hits, tally, skipped)
            return {"hits": {k: v for k, v in hits.items() if v > 0}, "scanned_bytes": tally[0], "skipped": skipped}
        except ImportError: raise
        except Exception as e: last = e; time.sleep(5 * (attempt + 1))
    raise last
def do(item):
    p, sz, sha = item
    row = dict(path=p, size=sz, rev=rev[:8], ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if p.startswith(SKIP_PREFIX): row.update(status="skipped-by-design", hits={}, scanned_bytes=0)
    else:
        try:
            src = local.get(sha) if sha else None
            if src is not None:
                row["source"] = "local"; r = scan_7z(src) if p.lower().endswith(".7z") else secret_scan.scan_path(src)
            else:
                row["source"] = "stream"; r = scan_remote(p, rev)
            row.update(status="scanned", hits=r["hits"], scanned_bytes=r["scanned_bytes"], skipped_n=len(r["skipped"]))
        except ImportError: row.update(status="unscanned-7z", hits={}, scanned_bytes=0)
        except Exception as e: row.update(status="error", err=f"{type(e).__name__} {str(e)[:120]}", hits={}, scanned_bytes=0)
    with wlock:
        with open(OUT, "a", encoding="utf-8") as f: f.write(json.dumps(row) + chr(10))
        if row["hits"]: log("HIT", p, row["hits"])
with ThreadPoolExecutor(int(os.environ.get('AUDIT_THREADS','1'))) as ex: list(ex.map(do, todo))   # 1 stream: leaves the Wi-Fi uplink room (lead 81761)
log("AUDIT DONE")
open(ROOT + f"/audit/secret-audit{TAG}.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

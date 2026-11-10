# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Zero-overlap gate (lead 81645 item 2). Union index of what is on the three HF repos; refuses duplicates BEFORE upload and logs them.
Keys: (1) file sha256 (LFS) -- byte-identical files; (2) doc id_key '<ns>:<id>' (pg:1, arxiv:0807.3315, wp:12) -- same document, different bytes;
(3) normalized-text hash (NFKC, lowercase, alnum words joined by one space; sha256[:16]) -- same text, different formatting/ids.
Index lives in <lane-root>/index/ (sqlite + sha list) and is mirrored to wordingone/ember-raw-private under index/ (HF is the authority copy).
CLI:  python overlap_gate.py build-files | build-docs | check-pack <packed/NAME> | selftest
Library: check_hashes([sha]) -> list of dups; check_docs([(id_key, text)]) -> list of dups; log_refusal(lane, path, key, dup)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, io, json, glob, time, sqlite3, hashlib, unicodedata, re

from lane_config import LANE_ROOT as ROOT; IDX = ROOT + "/index"; os.makedirs(IDX, exist_ok=True)
SHAS = IDX + "/files.sha256"; DB = IDX + "/docs.sqlite"; REFUSALS = ROOT + "/logs/overlap-refusals.jsonl"
_WORD = re.compile(r"[a-z0-9]+")
def norm_hash(text):
    t = unicodedata.normalize("NFKC", text).lower()
    return hashlib.sha256(" ".join(_WORD.findall(t)).encode()).digest()[:16]

_sha_cache = None
def _shas():
    global _sha_cache
    if _sha_cache is None: _sha_cache = set(open(SHAS).read().split()) if os.path.exists(SHAS) else set()
    return _sha_cache
def check_hashes(shas):
    """-> list of shas already present in the union index (byte-identical files). Empty list = clean."""
    s = _shas(); return [h for h in shas if h in s]
def add_hashes(shas):
    s = _shas(); new = [h for h in shas if h not in s]
    if new:
        s.update(new)
        with open(SHAS, "a") as f: f.write("\n".join(new) + "\n")

def _db():
    c = sqlite3.connect(DB, timeout=60); c.execute("create table if not exists docs(id_key text, nh blob, src text, bytes integer)")
    return c
def check_docs(items, src=None):
    """items = [(id_key, text)] -> list of (id_key, reason, existing_src). Same id_key OR same normalized-text hash counts as a duplicate."""
    c = _db(); out = []
    for k, t in items:
        r = c.execute("select src from docs where id_key=? limit 1", (k,)).fetchone()
        if r: out.append((k, "id", r[0])); continue
        r = c.execute("select src from docs where nh=? limit 1", (norm_hash(t),)).fetchone()
        if r: out.append((k, "text", r[0]))
    c.close(); return out
def log_refusal(lane, path, key, dup):
    with open(REFUSALS, "a", encoding="utf-8") as f: f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), lane=lane, path=path, key=str(key), dup=dup)) + "\n")

def iter_objects(pack_dir):
    import zstandard
    for p in sorted(glob.glob(pack_dir + "/objects/*.jsonl.zst")):
        with open(p, "rb") as fh:
            t = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in t:
                r = json.loads(line); yield r

def ns_key(pack_name, doc_id):
    if pack_name.startswith("pg-"): return "pg:" + doc_id.replace("pg-", "")
    if pack_name.startswith("wikipedia-"): return "wp:" + doc_id
    if pack_name.startswith("arxiv-") or doc_id.startswith("arxiv-"): return "arxiv:" + re.sub(r"v\d+$", "", doc_id.replace("arxiv-", ""))
    return doc_id   # text lanes (loc-/pes2o-/pubmed-...) already carry a namespaced id

def build_files():
    sys.path.insert(0, ROOT + "/scripts"); import hf_inventory as inv
    allsha = set()
    for key, repo in inv.REPOS.items():
        for path, size, sha in inv.tree(repo):
            if sha: allsha.add(sha)
    open(SHAS, "w").write("\n".join(sorted(allsha)) + "\n"); print("files.sha256:", len(allsha))

def iter_docs_index(pack_dir):
    import zstandard
    with open(pack_dir + "/docs-index.jsonl.zst", "rb") as fh:
        for l in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8"): yield json.loads(l)["id"]

def build_docs(packs=None):
    """index EVERY doc id of the packs on HF (from docs-index, complete) plus the normalized-text hash for each doc whose object is still local (nh NULL otherwise;
    the missing text hashes are filled by fill_hashes() from the HF objects). Local objects are byte-identical to the uploaded, sha-verified ones."""
    inv = json.load(open(ROOT + "/census/census-latest.json")); on_hf = {p["name"] for p in inv["repos"]["train"]["packs"]}
    c = _db(); c.execute("create index if not exists i_k on docs(id_key)"); c.execute("create index if not exists i_n on docs(nh)")
    have = {r[0] for r in c.execute("select distinct src from docs")}
    for name in sorted(on_hf if packs is None else packs):
        if name in have: print("skip (indexed)", name); continue
        t0 = time.time(); n = nh = 0; rows = []; seen = set()
        for r in iter_objects(f"{ROOT}/packed/{name}"):
            k = ns_key(name, r["id"]); seen.add(k)
            rows.append((k, norm_hash(r["text"]), name, len(r["text"].encode("utf-8")))); n += 1; nh += 1
            if len(rows) >= 20000: c.executemany("insert into docs values(?,?,?,?)", rows); c.commit(); rows = []
        for did in iter_docs_index(f"{ROOT}/packed/{name}"):
            k = ns_key(name, did)
            if k not in seen: rows.append((k, None, name, 0)); n += 1
            if len(rows) >= 20000: c.executemany("insert into docs values(?,?,?,?)", rows); c.commit(); rows = []
        if rows: c.executemany("insert into docs values(?,?,?,?)", rows); c.commit()
        print(f"indexed {name}: {n} docs ({nh} with text hash) in {time.time()-t0:.0f}s", flush=True)
    c.close()

def check_pack(pack_dir):
    name = os.path.basename(pack_dir.rstrip("/\\")); c = _db(); dups = []; n = 0
    for r in iter_objects(pack_dir):
        n += 1; k = ns_key(name, r["id"])
        row = c.execute("select src from docs where id_key=? and src<>? limit 1", (k, name)).fetchone()
        why = "id"
        if not row: row = c.execute("select src from docs where nh=? and src<>? limit 1", (norm_hash(r["text"]), name)).fetchone(); why = "text"
        if row: dups.append((k, why, row[0]))
    c.close()
    for k, why, src in dups[:2000]: log_refusal(name, pack_dir, k, [why, src])
    print(json.dumps(dict(pack=name, docs=n, duplicates=len(dups), verdict="PASS" if not dups else "REFUSE")))
    return not dups

def selftest():
    import tempfile
    global DB, SHAS, _sha_cache
    d = tempfile.mkdtemp(); DB = d + "/t.sqlite"; SHAS = d + "/t.sha"; _sha_cache = None
    c = _db(); c.execute("insert into docs values(?,?,?,?)", ("pg:1", norm_hash("The Declaration of Independence,  1971"), "pg-a", 10)); c.commit(); c.close()
    ok = True
    def chk(n, cond):
        nonlocal ok; print(("PASS " if cond else "FAIL ") + n); ok &= bool(cond)
    chk("same id different text -> refused (id)", check_docs([("pg:1", "totally different")]) == [("pg:1", "id", "pg-a")])
    chk("same text different id and formatting -> refused (text)", check_docs([("zz:9", "the DECLARATION of independence 1971!!")]) == [("zz:9", "text", "pg-a")])
    chk("fresh doc passes", check_docs([("pg:2", "something new entirely")]) == [])
    add_hashes(["a" * 64]); chk("planted file sha refused", check_hashes(["a" * 64, "b" * 64]) == ["a" * 64]); chk("clean sha passes", check_hashes(["c" * 64]) == [])
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"build-files": build_files, "build-docs": lambda: build_docs(), "selftest": selftest}.get(cmd, lambda: sys.exit(0 if (cmd == "check-pack" and check_pack(sys.argv[2])) else 1))()

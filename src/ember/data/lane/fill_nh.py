# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1581 data quality: fill docs.sqlite normalized-text hashes (nh) that are NULL (docs whose object was cleared locally when the index was built).
Pass 1 (this script, CPU-only): for every src with NULL nh, read the pack's LOCAL objects (byte-identical to the sha-verified uploaded ones) and fill the matching rows.
Pass 2 (--hf, needs the downlink; deferred while RESTORE-PRIORITY.flag): fetch the remaining objects from HF, hash in memory, delete the download. Resumable (only touches nh IS NULL rows). Report: logs/fill-nh-20261109.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, sqlite3
pass
import overlap_gate as G
BASE = G.ROOT
c = sqlite3.connect(G.DB, timeout=120); c.execute("pragma busy_timeout=120000")
todo = [r[0] for r in c.execute("select src from docs where nh is null group by src order by count(*) desc")]
rep = {}
for name in todo:
    t0 = time.time(); before = c.execute("select count(*) from docs where src=? and nh is null", (name,)).fetchone()[0]; filled = 0; rows = []
    d = f"{BASE}/packed/{name}"
    if not os.path.isdir(d + "/objects"):
        rep[name] = dict(null_before=before, filled=0, note="no local objects (needs --hf pass)"); continue
    for r in G.iter_objects(d):
        rows.append((G.norm_hash(r["text"]), G.ns_key(name, r["id"]), name))
        if len(rows) >= 20000:
            c.executemany("update docs set nh=? where id_key=? and src=? and nh is null", rows); c.commit(); filled += len(rows); rows = []
    if rows: c.executemany("update docs set nh=? where id_key=? and src=? and nh is null", rows); c.commit(); filled += len(rows)
    after = c.execute("select count(*) from docs where src=? and nh is null", (name,)).fetchone()[0]
    rep[name] = dict(null_before=before, null_after=after, local_docs_hashed=filled, secs=round(time.time() - t0))
    print(name, rep[name], flush=True)
json.dump(rep, open(BASE + "/logs/fill-nh-20261109.json", "w"), indent=1)
print("TOTAL null left:", c.execute("select count(*) from docs where nh is null").fetchone()[0])


def hf_pass():
    """--hf: for srcs still having NULL nh, stream each object from the train repo (text/<name>/objects/*), hash in memory, delete the download. Refuses while RESTORE-PRIORITY.flag exists."""
    if os.path.exists(BASE + "/loops/RESTORE-PRIORITY.flag"):
        print("DEFERRED: RESTORE-PRIORITY.flag (H39 restore owns the downlink)"); return
    import io, zstandard, shutil
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(); repo = ("wordingone/" + HF_TRAIN_REPO); tmp = BASE + "/scratch/fill-nh"; os.makedirs(tmp, exist_ok=True)
    for name in [r[0] for r in c.execute("select src from docs where nh is null group by src order by count(*) desc")]:
        base = "text/" + name.replace("-r1", "") + "/objects/"
        files = [f for f in api.list_repo_files(repo, repo_type="dataset") if f.startswith(base) and f.endswith(".jsonl.zst")]
        for f in files:
            p = hf_hub_download(repo, f, repo_type="dataset", local_dir=tmp); rows = []
            with open(p, "rb") as fh:
                for l in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8"):
                    r = json.loads(l); rows.append((G.norm_hash(r["text"]), G.ns_key(name, r["id"]), name))
            c.executemany("update docs set nh=? where id_key=? and src=? and nh is null", rows); c.commit(); os.remove(p)
        print(name, "left null:", c.execute("select count(*) from docs where src=? and nh is null", (name,)).fetchone()[0], flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if c.execute("select count(*) from docs where nh is null").fetchone()[0] == 0: open(BASE + "/logs/fill-nh.done", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if "--hf" in sys.argv:
    hf_pass()

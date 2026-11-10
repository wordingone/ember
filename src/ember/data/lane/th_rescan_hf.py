# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rescan every text-bearing file already on HF with TruffleHog (operator / lead 81934 item 3). Resumable ledger: logs/th-rescan.jsonl (one row per file; hits are detector COUNTS only, never values).
Source of bytes per file: the identical LOCAL copy when one exists (train repo packs under <lane-root>/packed/<pack>/..., verified by size + sha256 == HF LFS sha), else a download into
<lane-root>/scratch/th-dl that is deleted right after the scan (stream-through). Order: ember-train-private first (the alert was there), ember-raw-private text/, then ember-corpus text-bearing paths.
Skipped: checkpoints/, audio+image media, binary extensions (th_gate.SKIP_EXT). CPU: scan runs BelowNormal on CPUs 16-23.
Usage: python th_rescan_hf.py [repo_key ...]   (train | raw | public)      Summary: python th_rescan_hf.py summary"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, hashlib, shutil, collections
pass
import th_gate
from huggingface_hub import HfApi
import net_cap as _nc      # M-NET-2 (lead 82238): every lane download goes through the shared, cap-aware downloader (unthrottled while the cap is off)
def hf_hub_download(repo, path, repo_type="dataset", revision=None, local_dir=".", **kw): return _nc.download(repo, path, rev=revision, local_dir=local_dir, repo_type=repo_type)

from lane_config import LANE_ROOT as ROOT; LEDGER = ROOT + "/logs/th-rescan.jsonl"; DL = ROOT + "/scratch/th-dl"
REPOS = {"train": "wordingone/ember-train-private", "raw": "wordingone/ember-raw-private", "public": "wordingone/ember-corpus"}
SKIP_PREFIX = ("checkpoints/", "audio/", "image/", "sources/pd12m/", "sources/wikimedia-commons-pd/", "sources/librispeech-seed/", "avir-cli/", "tokens/", "catalog/", "staging/")
api = HfApi()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sha256f(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest()


def tree(repo):
    out = []
    for t in api.list_repo_tree(repo, repo_type="dataset", recursive=True, expand=True):
        if hasattr(t, "size"):
            l = getattr(t, "lfs", None)
            out.append((t.path, t.size, (l.sha256 if hasattr(l, "sha256") else l["sha256"]) if l else None))
    return out


def done_set():
    d = set()
    if os.path.exists(LEDGER):
        for l in open(LEDGER, encoding="utf-8"):
            try:
                r = json.loads(l); d.add((r["repo"], r["path"], r["size"]))
            except Exception:
                pass
    return d


def local_copy(key, path, size, sha):
    if key == "train" and path.startswith("text/"):
        p = ROOT + "/packed/" + path[len("text/"):]
        if os.path.exists(p) and os.path.getsize(p) == size and (sha is None or sha256f(p) == sha):
            return p
    return None


def main(keys):
    os.makedirs(DL, exist_ok=True); done = done_set()
    for key in keys:
        repo = REPOS[key]; files = tree(repo)
        todo = [(p, s, h) for p, s, h in files if not p.startswith(SKIP_PREFIX) and os.path.splitext(p.lower())[1] not in th_gate.SKIP_EXT and (repo, p, s) not in done]
        log(key, repo, "files", len(files), "to scan", len(todo), round(sum(s for _, s, _ in todo) / 2 ** 30, 1), "GiB")
        loc = {p: local_copy(key, p, s, h) for p, s, h in todo}          # local copies first (no bandwidth), then pubmed (the file HF flagged), then the rest by size
        todo.sort(key=lambda x: (loc[x[0]] is None, "pubmed" not in x[0], x[1]))
        from concurrent.futures import ThreadPoolExecutor
        ex = ThreadPoolExecutor(4); futs = {}; inflight_b = 0; nxt = 0
        def fetch(i, p):
            import reserve_plan      # harm-only disk wait (lead 82070): never stage a download that would take B: under the single floor
            while shutil.disk_usage("B:/").free / 2 ** 30 - 2.0 < reserve_plan.floor_gib() + 2 * 0:
                time.sleep(60)
            return hf_hub_download(repo, p, repo_type="dataset", local_dir=DL + "/" + str(i))
        for i, (p, s, h) in enumerate(todo):
            while nxt < len(todo) and nxt < i + 6 and (inflight_b < 8 * 2 ** 30 or nxt == i):      # sliding window of downloads, <= 8 GiB staged ahead
                q, qs, _ = todo[nxt]
                if loc[q] is None and nxt not in futs: futs[nxt] = ex.submit(fetch, nxt, q); inflight_b += qs
                nxt += 1
            t0 = time.time(); lp = loc[p]; src = "local"; dl = None
            try:
                if lp is None:
                    src = "download"; dl = futs.pop(i).result(); lp = dl; inflight_b -= s
                r = th_gate.scan_files([lp], timeout=6 * 3600); err = None
            except Exception as e:
                r = {"hits": {}, "files": {}}; err = (type(e).__name__ + ": " + str(e))[:200]
            finally:
                if dl: shutil.rmtree(DL + "/" + str(i), ignore_errors=True)
            row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), repo=repo, path=p, size=s, source=src, hits=r["hits"], error=err, secs=round(time.time() - t0, 1))
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            if r["hits"] or err:
                log("HIT" if r["hits"] else "ERR", key, p, r["hits"], err or "")
            if i % 25 == 0:
                log(key, i + 1, "/", len(todo))
        ex.shutdown(wait=False)
    log("RESCAN DONE", keys)


def summary():
    rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8")]
    hit = [r for r in rows if r["hits"]]; err = [r for r in rows if r["error"]]
    print(len(rows), "files scanned;", len(hit), "with hits;", len(err), "errors;", round(sum(r["size"] for r in rows) / 2 ** 30, 1), "GiB")
    c = collections.Counter()
    for r in hit:
        for k, v in r["hits"].items():
            c[k] += v
    print(dict(c))
    for r in hit[:40]:
        print(" ", r["repo"].split("/")[1], r["path"], r["hits"])


if __name__ == "__main__":
    if sys.argv[1:] == ["summary"]:
        summary()
    else:
        main(sys.argv[1:] or ["train", "raw", "public"])

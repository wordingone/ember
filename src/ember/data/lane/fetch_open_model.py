# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fetch an open-weight model repo for custody: safetensors + config + tokenizer + LICENSE + README only, pinned to the exact repo commit, every file sha256'd, receipt written.
Usage: python scripts/fetch_open_model.py ORG/NAME [--dest <m-root>/models] [--min-free-gib 300]
Rules (lead 82440): official org repo, public and ungated; no .bin/.pt/.pth/.pkl/.py/.gguf or any file outside the allow-list (no remote code is ever executed or even downloaded); the commit sha is read from the Hub API
and every download is pinned to it; LFS files must match the Hub-reported sha256; B: free space must stay above --min-free-gib after each file or the fetch stops; resumable (a file already present with the right size+sha is kept).
Receipt: <dest>/<name>/fetch-receipt.json (repo, commit sha, per-file size/sha256/seconds, license id from the card, total seconds)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT
import os, sys, re, json, time, shutil, hashlib, argparse, urllib.request

ALLOW_EXT = {".safetensors", ".json", ".txt", ".md"}
ALLOW_BARE = {"LICENSE", "LICENSE.txt", "NOTICE"}
SKIP = {".gitattributes"}
REFUSE_EXT = {".bin", ".pt", ".pth", ".pkl", ".pickle", ".py", ".gguf", ".ckpt", ".h5", ".onnx", ".msgpack", ".npz", ".zip", ".tar", ".sh", ".so", ".dll", ".exe"}


def classify(fn):
    """'fetch' | 'skip' | 'refuse' for one repo file name"""
    base = os.path.basename(fn)
    if fn in SKIP: return "skip"
    ext = os.path.splitext(base)[1].lower()
    if ext in REFUSE_EXT: return "refuse"
    if "/" in fn: return "refuse"                      # nested dirs hold code or alternate weights in these repos: never fetched blind
    if base in ALLOW_BARE or ext in ALLOW_EXT: return "fetch"
    return "refuse"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""): h.update(b)
    return h.hexdigest()


def free_gib(path): return shutil.disk_usage(os.path.splitdrive(os.path.abspath(path))[0] + "/").free / 2**30


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("repo"); ap.add_argument("--dest", default=(M_ROOT + "/models")); ap.add_argument("--min-free-gib", type=float, default=300.0)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", a.repo): print("REFUSED bad repo id"); return 2
    if a.repo.split("/")[0] != "Qwen": print("REFUSED: only the official Qwen org is allowed by the current fetch order"); return 2
    j = json.load(urllib.request.urlopen("https://huggingface.co/api/models/%s?blobs=true" % a.repo, timeout=60))
    if j.get("gated") or j.get("private"): print("REFUSED gated/private"); return 2
    sha = j["sha"]; lic = (j.get("cardData") or {}).get("license")
    plan = []; refused = []
    for s in j["siblings"]:
        c = classify(s["rfilename"])
        if c == "fetch": plan.append(s)
        elif c == "refuse": refused.append(s["rfilename"])
    if refused: print("REFUSED files in repo (never downloaded):", refused); return 2
    if not any(s["rfilename"].endswith(".safetensors") for s in plan): print("REFUSED: no safetensors weights in repo"); return 2
    name = a.repo.split("/")[1]; out = os.path.join(a.dest, name); os.makedirs(out, exist_ok=True)
    from huggingface_hub import hf_hub_download
    rows = []; t0 = time.time(); total = sum(s.get("size") or 0 for s in plan)
    print("plan %s @ %s: %d files, %.2f GB, license %s, B free %.1f GiB" % (a.repo, sha, len(plan), total / 1e9, lic, free_gib(out)), flush=True)
    for s in plan:
        fn, size = s["rfilename"], s.get("size") or 0
        lp = os.path.join(out, fn); t1 = time.time()
        want = (s.get("lfs") or {}).get("sha256")
        if os.path.exists(lp) and os.path.getsize(lp) == size and (not want or sha256_file(lp) == want):
            print("keep", fn, flush=True)
        else:
            if free_gib(out) - size / 2**30 < a.min_free_gib: print("STOP: B free would drop under %.0f GiB before %s" % (a.min_free_gib, fn)); return 3
            hf_hub_download(a.repo, fn, revision=sha, local_dir=out)
        dig = sha256_file(lp)
        if want and dig != want: print("FAIL sha256 mismatch vs Hub LFS record:", fn); return 4
        if os.path.getsize(lp) != size: print("FAIL size mismatch:", fn); return 4
        rows.append(dict(file=fn, bytes=size, sha256=dig, lfs_sha256_matches_hub=bool(want and dig == want), seconds=round(time.time() - t1, 1)))
        print("ok", fn, size, dig[:12], "%.0fs" % (time.time() - t1), flush=True)
    cache = os.path.join(out, ".cache")
    if os.path.isdir(cache): shutil.rmtree(cache, ignore_errors=True)     # hf_hub_download's resume metadata, inside the model dir only
    rec = dict(repo=a.repo, commit_sha=sha, license_from_card=lic, files=rows, total_bytes=sum(r["bytes"] for r in rows), download_seconds=round(time.time() - t0, 1),
               fetched=time.strftime("%Y-%m-%dT%H:%M:%S"), source_url="https://huggingface.co/" + a.repo + "/tree/" + sha, generation_config_in_repo=any(s["rfilename"] == "generation_config.json" for s in j["siblings"]),
               note="allow-list fetch: no pickle/bin/py/gguf; every file sha256 recorded; pinned to commit sha")
    json.dump(rec, open(os.path.join(out, "fetch-receipt.json"), "w"), indent=1)
    print("DONE", a.repo, sha, "%.1fs" % rec["download_seconds"], "B free %.1f GiB" % free_gib(out)); return 0


if __name__ == "__main__": sys.exit(main())

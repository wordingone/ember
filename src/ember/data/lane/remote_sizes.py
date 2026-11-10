# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Remote source sizes per lane, for the sources ledger (lead 82182 (4)): bytes_expected must be filled from the REMOTE size (HF API list_repo_tree), never invented.
LANE_SOURCES maps ledger lane id -> (repo, path prefix, recursive, filename filter). The 11 text lanes are PARSED from scripts/text_lane.py SPEC so the table cannot drift from the lane.
Lanes whose download volume is not an HF file listing (bulk-pd12m: images pulled from S3 per parquet row; se-drive: Stack Exchange sites; audio-mls-pack: plan-B 500 h subset) stay None on purpose: no number is invented.
Cache: loops/remote-sizes.json {lane: {repo, prefix, fetched, bytes_expected, files: {path: size}}}, refreshed when older than TTL_S; a failed refresh keeps the stale value.
bytes_done for these lanes = sum of the REMOTE sizes of the files the lane's state.json marks done (same unit as bytes_expected)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, re, json, time
from lane_config import LANE_ROOT as ROOT; CACHE = ROOT + "/loops/remote-sizes.json"; TTL_S = 12 * 3600


def _text_lane_specs():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "text_lane.py"), encoding="utf-8").read(); out = {}
    for m in re.finditer(r'^ "(\w+)": dict\(repo="([^"]+)", pref="([^"]*)", suffix="([^"]+)"', src, re.M):
        lane, repo, pref, suf = m.groups(); out["text-" + lane] = (repo, pref.rstrip("/"), True, lambda p, s=suf: p.endswith(s), f"bulk/{lane}/state.json")
    return out


def lane_sources():
    t = _text_lane_specs()
    t["bulk-mls"] = ("parler-tts/mls_eng", "data", False, lambda p: p.endswith(".parquet"), "bulk/mls/state.json")
    t["bulk-ccby"] = ("common-canvas/commoncatalog-cc-by", "", True, lambda p: p.endswith(".parquet"), "bulk/ccby/state.json")
    t["image-ccby-pack"] = ("wordingone/ember-raw-private", "image/commoncatalog-cc-by", True, lambda p: p.endswith(".parquet"), "staging/ccby-pack/state.json")
    return t


def _load():
    try: return json.load(open(CACHE, encoding="utf-8"))
    except Exception: return {}


def _list(repo, prefix, recursive, flt):
    from huggingface_hub import HfApi
    return {t.path: t.size for t in HfApi().list_repo_tree(repo, repo_type="dataset", path_in_repo=prefix, recursive=recursive) if hasattr(t, "size") and t.size is not None and flt(t.path)}


def refresh(lanes=None, now=None, lister=_list, force=False):
    """Fill/refresh the cache for the given ledger lane ids (default: all in LANE_SOURCES). Returns the cache dict. Never raises (a failed listing keeps the old entry)."""
    now = now or time.time(); src = lane_sources(); c = _load(); changed = False
    for lane in (lanes or list(src)):
        if lane not in src: continue
        repo, prefix, rec, flt, _ = src[lane]; e = c.get(lane)
        if e and not force and now - e.get("fetched", 0) < TTL_S and e.get("repo") == repo: continue
        try:
            files = lister(repo, prefix, rec, flt)
            if files: c[lane] = dict(repo=repo, prefix=prefix, fetched=now, bytes_expected=sum(files.values()), files=files); changed = True
        except Exception: pass
    if changed:
        tmp = CACHE + f".{os.getpid()}.tmp"; json.dump(c, open(tmp, "w", encoding="utf-8")); os.replace(tmp, CACHE)
    return c


def expected_done(lane, cache=None):
    """(bytes_expected, bytes_done) for a lane, or (None, None) when the lane has no remote listing (kept null on purpose) or the cache has no entry yet."""
    cache = cache if cache is not None else _load(); src = lane_sources().get(lane); e = cache.get(lane)
    if not src or not e: return None, None
    try: st = json.load(open(f"{ROOT}/{src[4]}", encoding="utf-8")).get("done", {})
    except Exception: st = {}
    done = sum(e["files"].get(p, 0) for p in st)
    return int(e["bytes_expected"]), int(min(done, e["bytes_expected"]))


if __name__ == "__main__":
    c = refresh(force="--force" in os.sys.argv)
    for lane in lane_sources():
        x, d = expected_done(lane, c); print(f"{lane:20s} expected {x if x is None else round(x/2**30,2)} GiB done {d if d is None else round(d/2**30,2)} GiB")

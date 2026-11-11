# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Hub-binding refresh (lead queue item; caselaw-00003-00004 lost PASS 11-11 03:18..05:44 because loops/scan-hub-binding.json was hand-written).
scan-hub-binding.json = {pack: Hub listing signature}. trainable_listing.scan_state binds a clean scan row to a Hub copy only when row["signature"] == binding[pack] (and the local shards are cleared).
The signature is th_pack_scan.signature's formula over the Hub listing text/<pack>/**: sha1 of json.dumps(sorted [(relpath, size)]).
refresh_one(pack): list ONLY that pack on the Hub (read-only), set its entry, write the file atomically under a lock. Called by tick.py upload right after a set is verified and dropped, so the binding is never hand-edited.
refresh_all(): rebuild every pack's entry from one recursive listing of text/ (the old table-82801/hub_sig.py step).
Refusals (nothing is written, the old entry stays): empty/unreadable Hub listing, an unreadable existing binding file when only one entry is refreshed (use refresh_all), lock not obtained.
Returns dicts with ok/why; never raises into the tick. Counts and names only. Usage: hub_binding.py PACK | --all"""
import os, sys, json, time, hashlib
from lane_config import LANE_ROOT as ROOT, HF_TRAIN_REPO

BINDING = os.environ.get("HB_BINDING", ROOT + "/loops/scan-hub-binding.json")
SCAN_ROWS = os.environ.get("HB_SCAN_DIR", ROOT + "/logs/th-scan")
REPO = os.environ.get("HB_REPO", HF_TRAIN_REPO)
LOCK_STALE_S = 600


def sig(rows):
    return hashlib.sha1(json.dumps(sorted(rows)).encode()).hexdigest()      # th_pack_scan.signature's formula over (relpath, size) tuples


def _lister(api=None):
    def ls(path):
        a = api
        if a is None:
            from huggingface_hub import HfApi
            a = HfApi()
        return [(e.path, e.size) for e in a.list_repo_tree(REPO, path_in_repo=path, repo_type="dataset", recursive=True) if getattr(e, "size", None) is not None]
    return ls


class _Lock:
    def __init__(self, path):
        self.p = path + ".lock"

    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                with open(self.p, "x") as _f: _f.write(str(os.getpid()))      # exclusive create: FileExistsError when another refresh holds the lock
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.p) > LOCK_STALE_S: os.remove(self.p); continue
                except OSError: pass
                if time.time() - t0 > 60: raise TimeoutError("binding lock busy")
                time.sleep(0.5)

    def __exit__(self, *a):
        try: os.remove(self.p)
        except OSError: pass


def _write(path, data):
    tmp = path + ".part"
    with open(tmp, "w") as f: json.dump(data, f, indent=1, sort_keys=True); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _row_sig(pack):
    try: return json.load(open(os.path.join(SCAN_ROWS, "train-%s.json" % pack))).get("signature")
    except Exception: return None


def refresh_one(pack, lister=None, binding=None):
    binding = binding or BINDING
    try:
        files = (lister or _lister())("text/" + pack)
        rows = [(p[len("text/" + pack + "/"):], s) for p, s in files if p.startswith("text/" + pack + "/")]
    except Exception as e:
        return dict(ok=False, why="hub listing failed (%s)" % type(e).__name__)
    if not rows: return dict(ok=False, why="hub listing of text/%s is empty: binding left unchanged" % pack)
    hs = sig(rows)
    try:
        with _Lock(binding):
            try: cur = json.load(open(binding))
            except FileNotFoundError: cur = {}
            except Exception as e: return dict(ok=False, why="existing binding unreadable (%s): use refresh_all" % type(e).__name__)
            if not isinstance(cur, dict): return dict(ok=False, why="existing binding is not an object: use refresh_all")
            old = cur.get(pack); cur[pack] = hs; _write(binding, cur)
    except Exception as e:
        return dict(ok=False, why="binding not written (%s: %s)" % (type(e).__name__, str(e)[:80]))
    rs = _row_sig(pack)
    return dict(ok=True, pack=pack, files=len(rows), sig=hs, changed=(old != hs), row_sig_eq_hub=(rs is not None and rs == hs))


def refresh_all(lister=None, binding=None):
    binding = binding or BINDING
    try: files = (lister or _lister())("text")
    except Exception as e: return dict(ok=False, why="hub listing failed (%s)" % type(e).__name__)
    by = {}
    for p, s in files:
        parts = p.split("/")
        if len(parts) >= 3 and parts[0] == "text": by.setdefault(parts[1], []).append(("/".join(parts[2:]), s))
    if not by: return dict(ok=False, why="hub listing of text/ is empty: binding left unchanged")
    new = {k: sig(v) for k, v in by.items()}
    try:
        with _Lock(binding): _write(binding, new)
    except Exception as e:
        return dict(ok=False, why="binding not written (%s)" % type(e).__name__)
    return dict(ok=True, packs=len(new), eq_row=sorted(k for k in new if _row_sig(k) == new[k]))


if __name__ == "__main__":
    if sys.argv[1:] == ["--all"]: print(json.dumps(refresh_all()))
    elif len(sys.argv) == 2: print(json.dumps(refresh_one(sys.argv[1])))
    else: print("usage: hub_binding.py PACK | --all")

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""M-NET-2 arbiter, smallest form (lead 82238): a saturated Wi-Fi downlink starves the uplink's ACKs (22:33: 13 MB/s up; later 0.15 MB/s up under 3.7 MB/s down).
RULE: while the upload queue is non-empty AND the measured uplink is < UP_LOW_MBPS (2 MB/s) for UP_LOW_S (120 s), the SUM of lane downloads is capped at CAP_MBPS (2.5 MB/s, ~70% of the ~3.6 MB/s ceiling); the cap lifts when the queue has been empty for OFF_S (30 s).
Pieces: net_arbiter.py (daemon; decides; writes loops/net-cap.json + appends on/off rows to loops/net-cap-ledger.jsonl) and this module (used by EVERY lane download):
  share_mbps()        -> per-downloader share (cap / active downloaders) while the cap is on, else None
  download(...)       -> throttled, Range-resumable replacement for hf_hub_download (unthrottled when the cap is off; the share is re-read every chunk, so a cap that turns on mid-file bites immediately)
  touch()             -> mark this process as an active downloader (loops/net-share/<pid>)
decide() is the pure state machine (red: scripts/tests/net_cap_red_test.py)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, json, time
from lane_config import LANE_ROOT as ROOT; STATE = ROOT + "/loops/net-cap.json"; LEDGER = ROOT + "/loops/net-cap-ledger.jsonl"; SHARE_PATH = ROOT + "/loops/net-share"
BASE = "https://huggingface.co"; CAP_MBPS = 2.5; UP_LOW_MBPS = 2.0; UP_LOW_S = 120; OFF_S = 30; ACTIVE_S = 15


def decide(st, now, queue_files, tx_mbps):
    """st: {'on': bool, 'low_since': float|None, 'empty_since': float|None}. Returns (new_state, action) with action in (None, 'on', 'off')."""
    st = dict(st); act = None
    if not st.get("on"):
        if queue_files > 0 and tx_mbps < UP_LOW_MBPS:
            st["low_since"] = now if st.get("low_since") is None else st["low_since"]
            if now - st["low_since"] >= UP_LOW_S: st.update(on=True, low_since=None, empty_since=None, since=now); act = "on"
        else: st["low_since"] = None
    else:
        if queue_files == 0:
            st["empty_since"] = now if st.get("empty_since") is None else st["empty_since"]
            if now - st["empty_since"] >= OFF_S: st.update(on=False, empty_since=None, low_since=None, since=now); act = "off"
        else: st["empty_since"] = None
    return st, act


def _state():
    try: return json.load(open(STATE, encoding="utf-8"))
    except Exception: return {}


def touch():
    try:
        os.makedirs(SHARE_PATH, exist_ok=True); open(f"{SHARE_PATH}/{os.getpid()}", "w").close(); os.utime(f"{SHARE_PATH}/{os.getpid()}", None)
    except Exception: pass


_acc = [0, 0.0]


def account(nbytes):
    """Per-process cumulative bytes fetched through the capped paths, flushed to <share dir>/<pid>.bytes at most once a second; the arbiter sums these into lane_mbps so the cap can be checked against the NIC's rx (lead 82238)."""
    _acc[0] += nbytes; now = time.time()
    if now - _acc[1] >= 1.0:
        _acc[1] = now
        try: os.makedirs(SHARE_PATH, exist_ok=True); open(f"{SHARE_PATH}/{os.getpid()}.bytes", "w").write(str(_acc[0]))
        except Exception: pass


def lane_bytes():
    """sum over the registry of each live-or-recent process's cumulative byte counter -> {pid: bytes}"""
    out = {}
    try:
        for f in os.listdir(SHARE_PATH):
            if f.endswith(".bytes"):
                try: out[f[:-6]] = int(open(f"{SHARE_PATH}/{f}").read() or 0)
                except Exception: pass
    except Exception: pass
    return out


def active_downloaders(now=None):
    now = now or time.time(); n = 0
    try:
        for f in os.listdir(SHARE_PATH):
            p = f"{SHARE_PATH}/{f}"
            if now - os.path.getmtime(p) < ACTIVE_S: n += 1
            elif now - os.path.getmtime(p) > 600:
                try: os.remove(p)
                except OSError: pass
    except Exception: pass
    return max(1, n)


def share_mbps(now=None):
    s = _state()
    if not s.get("on"): return None
    return float(s.get("cap_mbps", CAP_MBPS)) / active_downloaders(now)


def paced_sleep(got, t0, mbps):
    """seconds to sleep so that `got` bytes since t0 do not exceed mbps MB/s (MiB-based, like the text lane)"""
    return max(0.0, got / (mbps * 2**20) - (time.time() - t0))


import threading
_pl = threading.Lock(); _next = [0.0]


def pace(nbytes):
    """Thread-safe aggregate pacer for many-small-fetch lanes (pd12m: 8 threads pulling images from S3): call after each fetched object; sleeps so that the process's total stays <= its share while the cap is on."""
    touch(); account(nbytes); sh = share_mbps()
    if not sh: return
    with _pl:
        now = time.time(); t = max(_next[0], now); _next[0] = t + nbytes / (sh * 2**20)
    if t > now: time.sleep(t - now)


def download(repo, path, rev=None, local_dir=".", repo_type="dataset", token=None, chunk=1 << 20):
    """Drop-in for hf_hub_download(repo, path, repo_type=..., revision=..., local_dir=...) -> local path. Resumes from <file>.part with a Range request."""
    import requests
    from huggingface_hub import get_token
    loc = os.path.join(local_dir, *path.split("/")); part = loc + ".part"; os.makedirs(os.path.dirname(loc), exist_ok=True)
    if os.path.exists(loc) and not os.path.exists(part): return loc
    tok = token or get_token(); have = os.path.getsize(part) if os.path.exists(part) else 0
    url = f"{BASE}/{'datasets/' if repo_type == 'dataset' else ''}{repo}/resolve/{rev or 'main'}/{path}"
    hdr = {"User-Agent": "ember-data-lane/1.0"}
    if tok: hdr["Authorization"] = f"Bearer {tok}"
    if have: hdr["Range"] = f"bytes={have}-"
    with requests.get(url, stream=True, timeout=(30, 90), headers=hdr) as r:
        if r.status_code == 416 and have: os.replace(part, loc); return loc
        r.raise_for_status()
        if have and r.status_code != 206: have = 0                    # server ignored Range: start over
        total = (int(r.headers["Content-Range"].rsplit("/", 1)[1]) if r.status_code == 206 and "/" in r.headers.get("Content-Range", "") else int(r.headers.get("Content-Length") or 0) + have) or None
        t0 = time.time(); got = 0; rate = None
        with open(part, "ab" if have else "wb") as f:
            for c in r.iter_content(chunk):
                f.write(c); got += len(c); touch(); account(len(c))
                nr = share_mbps()
                if nr != rate: rate = nr; t0 = time.time(); got = 0           # cap on/off/changed: restart the window (no catch-up burst)
                if rate:
                    z = paced_sleep(got, t0, rate)
                    if z > 0: time.sleep(z)
    if total and os.path.getsize(part) != total: raise RuntimeError(f"{path}: got {os.path.getsize(part)} != {total} (kept as .part for resume)")
    os.replace(part, loc); return loc

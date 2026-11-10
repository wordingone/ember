# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reserve planner (lead 81875 / spec disk-custody-strategy-20261109 rule 3). ONE declaration file, read by every tick and lane:
  <lane-root>/loops/reserve.json = {"chain_start_utc": "2026-11-09T01:00:00Z", "chain_start_floor_gib": 292, "hour_writes_gib": 0, "publish_gib": 9, "declared_by": "training", "authority": "..."}
The next chain's declared need (chain-start floor + hour writes + publish) is reserved FIRST; lanes get only what is left: lane floor = the sum. Until the chain start has passed the file is the floor;
no file / stale file -> the standing default 315 (a declaration can only raise it). alarm(): 2 h before the chain start, if B free < the reserve, mail lead once per chain (mb_send, readback id).
Test overrides: RESERVE_FILE, RESERVE_STATE, RESERVE_TEST=1."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, SEAT_LEAD
import os, sys, json, time, shutil, calendar
from lane_config import LANE_ROOT as ROOT; F = os.environ.get("RESERVE_FILE", ROOT + "/loops/reserve.json"); S = os.environ.get("RESERVE_STATE", ROOT + "/upq/reserve-state.json"); BUILTIN = 315.0      # standing floor (lead 82357, 2026-11-10): the chain-start floor is 305 + ~8 GiB probe, so lane writes must keep B >= 315 at all times; was 301
FLOOR_FILE = os.environ.get("FLOOR_FILE", ROOT + "/loops/standing-floor.json")
def standing():
    """The standing floor, re-read from FLOOR_FILE on EVERY call (never cached at import): a lane process started before a floor change reads the new value on its next poll (2026-11-10: nine text_lane processes kept the 301 they had imported and wrote below the press floor). The file can only RAISE it above BUILTIN."""
    try: return max(BUILTIN, float(json.load(open(FLOOR_FILE))["standing_floor_gib"]))
    except Exception: return BUILTIN
def load():
    try:
        r = json.load(open(F)); t = calendar.timegm(time.strptime(r["chain_start_utc"], "%Y-%m-%dT%H:%M:%SZ"))
        need = float(r["chain_start_floor_gib"]) + float(r.get("hour_writes_gib", 0)) + float(r.get("publish_gib", 0))
        if time.time() > t + 3 * 3600: return None          # stale (chain started > 3 h ago and nobody re-declared): default
        return dict(r, start_epoch=t, need_gib=need)
    except Exception: return None
def floor_gib():
    r = load(); s = standing(); return max(r["need_gib"], s) if r else s      # a declaration can only RAISE the floor above the standing 315, never lower it
def describe():
    r = load()
    return f"reserve {r['need_gib']:.0f} GiB for chain @ {r['chain_start_utc']} (declared by {r.get('declared_by','?')})" if r else f"reserve default {standing():.0f} GiB (no live declaration)"
def alarm():
    r = load()
    if not r: return ""
    left = r["start_epoch"] - time.time(); free = shutil.disk_usage("B:/").free / 2**30
    if not (0 < left <= 2 * 3600) or free >= r["need_gib"]: return ""
    st = json.load(open(S)) if os.path.exists(S) else {}
    if st.get(r["chain_start_utc"]): return f" RESERVE UNMET (already mailed id {st[r['chain_start_utc']]})"
    sys.path.insert(0, ROOT + "/scripts"); import mb_send
    subj = ("[TEST red] " if os.environ.get("RESERVE_TEST") else "") + f"RESERVE UNMET: chain start in {left/60:.0f} min needs {r['need_gib']:.0f} GiB on B:, free {free:.1f}"
    body = f"Declared need {r['need_gib']:.0f} GiB = chain-start floor {r['chain_start_floor_gib']} + hour writes {r.get('hour_writes_gib',0)} + publish {r.get('publish_gib',0)} (declared by {r.get('declared_by','?')}). B free {free:.1f} GiB, short {r['need_gib']-free:.1f} GiB, chain starts {r['chain_start_utc']}. All lanes already hold at this reserve; the shortfall must come from checkpoint custody / dropping bound-free packed shards."
    mid = mb_send.send(SEAT_LEAD, subj, body); st[r["chain_start_utc"]] = mid; json.dump(st, open(S, "w")); return f" RESERVE UNMET mailed id {mid}"
RESTORE_FLAG = os.environ.get("RESTORE_FLAG", ROOT + "/loops/RESTORE-PRIORITY.flag")
def harm(kinds=("link", "disk"), free_gib=None):
    """lead 82070 (run-unaffected rule cl. 2): the ONLY reasons a lane of mine may wait are MEASURED harm: 'link' = RESTORE-PRIORITY.flag exists (the restore owns the saturated link),
    'disk' = B: free below floor_gib(). Returns a reason string or ''. There is no presence/quiet-window guard: other seats running code is never a reason to wait."""
    if "link" in kinds and os.path.exists(RESTORE_FLAG): return "link priority: RESTORE-PRIORITY.flag"
    if "disk" in kinds:
        free = free_gib() if free_gib else shutil.disk_usage("B:/").free / 2**30
        if free < floor_gib(): return f"disk floor: B free {free:.1f} GiB < {floor_gib():.0f}"
    return ""
def harm_wait(who="", log=print, cap_s=1800, kinds=("link", "disk"), free_gib=None, poll_s=5):
    """Block only while harm() is non-empty; capped so a bad file/flag can never wedge a lane."""
    t0 = time.time()
    while time.time() - t0 < cap_s:
        h = harm(kinds, free_gib)
        if not h: return
        log(f"{who} waiting on measured harm - {h}"); time.sleep(poll_s)

PRESS_MIN = 313.0      # lead 82373/82381: B must be >= 313 at the Studio press (chain start 305 + ~8 GiB probe); nothing of mine ever gates below it
SCAN_MARGIN = 1.5      # the pre-upload scan's scratch is transient and is the ONLY path to freeing space (scan -> upload -> verified drop); it may use up to 1.5 GiB of the band under the lane floor
def scan_floor_gib():
    """Floor for the pre-upload scan's scratch (th_gate). Lanes pin B at floor_gib(); without this band the scans starve behind them and no upload ever frees space (2026-11-10 deadlock)."""
    return max(PRESS_MIN, floor_gib() - SCAN_MARGIN)

def write_gate(who="", need_bytes=0, log=print, cap_s=6 * 3600, poll_s=30, free_gib=None, floor_fn=None):
    """lead 82324 class fix: EVERY lane write path (scratch, packs, textwork, redaction copies) calls this BEFORE writing. Waits (does not write) while B: free - need < floor_gib();
    returns True when the write may proceed, False after cap_s (caller must then NOT write). The reserve above the training floor belongs to training first."""
    t0 = time.time()
    while True:
        free = free_gib() if free_gib else shutil.disk_usage("B:/").free / 2**30
        fl = (floor_fn or floor_gib)()
        if free - need_bytes / 2**30 >= fl: return True
        if time.time() - t0 >= cap_s: return False
        log(f"{who} write-gate: B free {free:.1f} GiB - need {need_bytes/2**30:.2f} < floor {fl:.1f}; waiting (not writing)"); time.sleep(poll_s)

if __name__ == "__main__": print(describe(), alarm())

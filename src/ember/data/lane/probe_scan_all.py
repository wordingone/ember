# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Scan every local text pack's objects with probe_scan.py, once: logs/probe-scan-<pack>.json is the done-marker (resumable, one core, sequential).
Spawned by loops/tick.py intake whenever a pack has no result file; a hit (prompt_hits > 0) is surfaced by the tick line as PROBE_HIT <pack> and is a mail to the coordinator.
PROBE_SCAN_BASE overrides the lane root (tests)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, glob, subprocess
BASE = os.environ.get("PROBE_SCAN_BASE", LANE_ROOT)


def main():
    n = 0
    for d in sorted(glob.glob(BASE + "/packed/*/objects")):
        name = os.path.basename(os.path.dirname(d)); out = BASE + "/logs/probe-scan-%s.json" % name
        if os.path.exists(out) or not glob.glob(d + "/*.jsonl.zst"): continue
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_scan.py"), d, "--out", out, "--test", os.environ.get("PROBE_TEST", BASE + "/probes/v1/test.jsonl")], capture_output=True, text=True)
        print(name, "rc", r.returncode, flush=True); n += 1
    print("scanned", n, "packs"); return 0


if __name__ == "__main__": sys.exit(main())

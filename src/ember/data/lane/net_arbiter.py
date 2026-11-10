# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""M-NET-2 arbiter daemon (lead 82238). Every 10 s: queue = upq/*.job.json, uplink = NIC tx rate; net_cap.decide() flips the cap; state -> loops/net-cap.json, every on/off -> loops/net-cap-ledger.jsonl
{ts, action, queue_files, uplink_mbps, downlink_mbps, cap_mbps, active_downloaders}. 10 min after an 'on' row it appends a 'check' row with the uplink then (lead asked for that number). Started by the tick (BACKLOG net-arbiter)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, json, time, glob
pass; import net_cap as N
import psutil


def main(poll=10):
    st = N._state() or {}; st.setdefault("on", False); st.setdefault("cap_mbps", N.CAP_MBPS); check_at = None
    a = psutil.net_io_counters(); ta = time.time(); lb0 = N.lane_bytes()
    while True:
        time.sleep(poll); b = psutil.net_io_counters(); tb = time.time(); dt = max(tb - ta, 1e-3)
        tx = (b.bytes_sent - a.bytes_sent) / dt / 1e6; rx = (b.bytes_recv - a.bytes_recv) / dt / 1e6; a, ta = b, tb
        lb1 = N.lane_bytes(); lane = sum(max(0, v - lb0.get(k, v)) for k, v in lb1.items()) / dt / 1e6; lb0 = lb1      # MB/s fetched by the capped lane paths (NIC rx includes everything else on the PC)
        q = len(glob.glob((LANE_ROOT + "/upq/*.job.json"))); new, act = N.decide(st, tb, q, tx)
        row = None
        if act: row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tb)), action=act, queue_files=q, uplink_mbps=round(tx, 3), downlink_mbps=round(rx, 3), lane_mbps=round(lane, 3), cap_mbps=new["cap_mbps"] if act == "on" else None, active_downloaders=N.active_downloaders(tb), rule="queue>0 and uplink<2 MB/s for 120 s -> cap sum of downloads 2.5 MB/s; lift after queue empty 30 s (lead 82238)")
        if act == "on": check_at = tb + 600
        if check_at and tb >= check_at and new.get("on"): row = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tb)), action="check", queue_files=q, uplink_mbps=round(tx, 3), downlink_mbps=round(rx, 3), lane_mbps=round(lane, 3), cap_mbps=new["cap_mbps"], active_downloaders=N.active_downloaders(tb)); check_at = None
        if act == "off": check_at = None
        st = new; st["ts"] = tb; st["queue_files"] = q; st["uplink_mbps"] = round(tx, 3); st["downlink_mbps"] = round(rx, 3); st["lane_mbps"] = round(lane, 3)
        tmp = N.STATE + ".tmp"; json.dump(st, open(tmp, "w")); os.replace(tmp, N.STATE)
        if row:
            with open(N.LEDGER, "a", encoding="utf-8") as f: f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()

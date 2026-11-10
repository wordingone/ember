# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, time, json, psutil
os.environ.update(STALL_ALARM_S="90", STALL_ALARM_STATE=(LANE_ROOT + "/upq/alarm-state-test.json"), STALL_ALARM_TEST="1")
pass; import stall_alarm
if os.path.exists(os.environ["STALL_ALARM_STATE"]): os.remove(os.environ["STALL_ALARM_STATE"])
tgt = []
for p in psutil.process_iter(["pid", "cmdline"]):
    c = p.info["cmdline"] or []; j = " ".join(c)
    if c and "python" in c[0].lower() and ("upload_worker.py" in j or "upload_file" in j or ("hf.exe" in j and " upload " in j)): tgt.append(p)
print("pausing", [p.pid for p in tgt], flush=True)
for p in tgt: p.suspend()
try:
    for i in range(14):
        r = stall_alarm.run(); print(time.strftime("%H:%M:%S"), r, flush=True)
        if "ALARM" in r: break
        time.sleep(15)
finally:
    for p in tgt:
        try: p.resume()
        except Exception as e: print("resume", p.pid, e)
    print("resumed", flush=True)

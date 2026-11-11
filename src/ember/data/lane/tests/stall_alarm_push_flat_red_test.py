# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red: a single hung hf push is detected even while other pushes (and the global byte sum) keep moving (class fix: custody_other_opt_upload hung 70 min at 05:40, global alarm quiet).
Pure push_flat() cases, no live process, no mail. Run: python tests/stall_alarm_push_flat_red_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stall_alarm as S
ok = True
def chk(n, c):
    global ok; ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)
st = {}; T = 1800
S.push_flat([("1:a", "100"), ("2:b", "5")], st, 0, T)
r = S.push_flat([("1:a", "100"), ("2:b", "9")], st, 1000, T)
chk("moving process 2 resets; flat process 1 not yet over the threshold at 1000 s", r == [] and st["2:b"]["since"] == 1000)
r = S.push_flat([("1:a", "100"), ("2:b", "20")], st, 1900, T)
chk("process 1 flat 1900 s >= 1800 is reported while process 2 keeps moving", [k for k, _ in r] == ["1:a"])
r = S.push_flat([("1:a", "101"), ("2:b", "30")], st, 2000, T)
chk("process 1 moved again: clock restarts, nothing reported", r == [] and st["1:a"]["since"] == 2000)
S.push_flat([("2:b", "30")], st, 2100, T)
chk("a dead process is pruned from the state", "1:a" not in st)
st2 = {"_alerted": 5}; S.push_flat([("9:z", "1")], st2, 10, T)
chk("bookkeeping keys starting with _ survive and are never reported", st2.get("_alerted") == 5)
r = S.push_flat([("9:z", "1")], st2, 10 + 1801, T)
chk("a lone process flat 1801 s is reported (global sum cannot hide it: it is per process)", [k for k, _ in r] == ["9:z"])
# mutant: threshold check removed -> the flat case above must be missed
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stall_alarm.py"), encoding="utf-8").read().replace("\r\n", "\n")
old = 'if now - h["since"] >= thresh: out.append((k, now - h["since"]))'
assert src.count(old) == 1
ns = {"__name__": "mut"}; head = src[src.index("PUSH_FLAT_S ="):src.index("def _push_sigs")]
exec("import os\n" + head.replace(old, "pass"), ns)
stm = {}; ns["push_flat"]([("1:a", "1")], stm, 0, T); chk("mutant (threshold test removed) misses the hung push", ns["push_flat"]([("1:a", "1")], stm, 5000, T) == [])
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for loops/escalate_dedup.py (lead 83155): the same known escalation twice gives one ESCALATE; a change escalates again."""
import os, sys, json, shutil, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "loops"))
import escalate_dedup as E

res = []
def chk(name, cond):
    res.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

tmp = tempfile.mkdtemp(prefix="escdd_", dir="A:/data-scan" if os.path.isdir("A:/data-scan") else None)
st, lg = tmp + "/s.json", tmp + "/log.jsonl"
N1 = "pack-a: refused_hits (hits 3) (was PASS earlier: ESCALATE); pack-b: NOT PUSHED, defender guard"
try:
    n, sfx = E.apply(N1, 0, st, lg)
    chk("a) first sight of an escalating item keeps ESCALATE, non-escalating items untouched", "ESCALATE" in n and "pack-b: NOT PUSHED, defender guard" in n and not sfx)
    n, sfx = E.apply(N1, 0, st, lg)
    chk("b) the same input again: no ESCALATE word, the repeat is logged (one mail per known item)", "ESCALATE" not in n and "known repeat" in n and os.path.exists(lg) and "pack-a" in open(lg).read())
    n, sfx = E.apply(N1.replace("hits 3", "hits 4"), 0, st, lg)
    chk("c) a moving counter inside the item is still the known item (digits normalised)", "ESCALATE" not in n)
    n, sfx = E.apply("pack-c: refused_hits (hits 3) (was PASS earlier: ESCALATE)", 0, st, lg)
    chk("d) a different pack is a new item and escalates", "ESCALATE" in n)
    n, sfx = E.apply("pack-c: refused_hits (hits 3) (was PASS earlier: ESCALATE)", 0, st, lg)
    chk("e) ... once", "ESCALATE" not in n)
    n, sfx = E.apply("nothing to push", 0, st, lg)
    n, sfx = E.apply("pack-c: refused_hits (hits 3) (was PASS earlier: ESCALATE)", 0, st, lg)
    chk("f) an item that went away for a tick and came back inside 24 h is a known repeat (lead 83299)", "ESCALATE" not in n and "known repeat" in n)
    old = json.load(open(st)); old["seen"] = {k: "2026-01-01T00:00:00" for k in old["seen"]}; json.dump(old, open(st, "w"))
    n, sfx = E.apply("pack-c: refused_hits (hits 3) (was PASS earlier: ESCALATE)", 0, st, lg)
    chk("f2) the same item not seen for over 24 h escalates again", "ESCALATE" in n)
    json.dump({"items": ["pack-z: stuck (was pass earlier: escalate)"], "head": None, "ts": "2026-01-01T00:00:00"}, open(st, "w"))
    n, sfx = E.apply("pack-z: stuck (was PASS earlier: ESCALATE)", 0, st, lg)
    chk("f3) an old-format state file (items only, last tick) is read as seen at its ts; an old ts is stale so it escalates", "ESCALATE" in n)
    PN = "pack-p: persistent (was PASS earlier: ESCALATE)"; first = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 23 * 3600))
    json.dump({"items": [], "seen": {E.sig(PN): first}, "head": None, "ts": first}, open(st, "w"))
    n, sfx = E.apply(PN, 0, st, lg); n, sfx = E.apply(PN, 0, st, lg)
    chk("n) a persistent item first escalated 23 h ago is a known repeat and its first-escalated stamp is NOT refreshed by later ticks (lead 83381)", "ESCALATE" not in n and json.load(open(st))["seen"][E.sig(PN)] == first)
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 25 * 3600)); json.dump({"items": [], "seen": {E.sig(PN): old}, "head": None, "ts": old}, open(st, "w"))
    n, sfx = E.apply(PN, 0, st, lg)
    chk("n2) the same persistent item first escalated 25 h ago escalates again, with a fresh first-escalated stamp", "ESCALATE" in n and json.load(open(st))["seen"][E.sig(PN)] > old)
    n, sfx = E.apply("pack-d: STUCK x; y", 3, st, lg)
    chk("g) blocked-3-ticks suffix shown the first time", sfx is True)
    n, sfx = E.apply("pack-d: STUCK x; y", 4, st, lg)
    chk("h) blocked-3-ticks suffix suppressed while the blocking head is unchanged", sfx is False)
    n, sfx = E.apply("pack-e: other stuck", 5, st, lg)
    chk("i) a changed blocking head shows the suffix again", sfx is True)
    n, sfx = E.apply("pack-e: other stuck", 1, st, lg)
    chk("j) not blocked: no suffix", sfx is False)
    chk("k) the state file is valid json with the items key", isinstance(json.load(open(st)).get("items"), list))
    # mutant: state never remembered -> check b must fail
    real = E._load; E._load = lambda p: ({}, None)
    try:
        n, sfx = E.apply(N1, 0, st, lg)
        n2, sfx2 = E.apply(N1, 0, st, lg)
        chk("m) MUTANT state forgotten is caught (the second call would escalate again)", "ESCALATE" in n2)
    finally: E._load = real
    tick = open(os.path.join(os.path.dirname(HERE), "loops", "tick.py"), encoding="utf-8").read()
    chk("w) tick.done() routes its printed note through escalate_dedup.apply", "escalate_dedup" in tick and ".apply(" in tick)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
bad = [n for n, c in res if not c]
print("FAILCOUNT", len(bad), "of", len(res)); print("ALL PASS" if not bad else "FAILED"); sys.exit(1 if bad else 0)

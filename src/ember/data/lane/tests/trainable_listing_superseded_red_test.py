# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for the superseded rule (lead 83018): python tests/trainable_listing_superseded_red_test.py
 a) base + -r1 + -r2 is one pack: the newest (-r2) is kept, base and -r1 carry superseded_by = <newest>, the kept row carries None
 b) totals EXCLUDE superseded rows (counted once); superseded_not_counted holds their packs/tokens; sum of kept + superseded == all rows
 c) no suffix == rank 0: a lone pack (no -r) is never superseded; two unrelated bases never supersede each other (g00-r1 vs g10)
 d) a -r1 whose base is absent still stands (a -r1 alone is the newest); a name like 'x-r2x' is not a revision
 e) MUTANT: counting every row (no exclusion) is caught by check b
 f) end to end through main(): temp PACKED dir, listing JSON has superseded_by on each row and totals tokens == kept tokens
Temp dirs only; prints ALL PASS."""
import os, sys, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="tl-sup-red-")
os.environ["TL_PACKED"] = TMP + "/packed"; os.environ["TL_SCAN_DIR"] = TMP + "/scan"; os.environ["TL_BINDING"] = TMP + "/binding.json"; os.environ["TL_OUT"] = TMP + "/out.json"
os.makedirs(TMP + "/packed"); os.makedirs(TMP + "/scan")
import trainable_listing as tl

ok = True


def chk(msg, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + msg); ok = ok and bool(cond)


def mk(*names):
    return [dict(pack=n, tokens=100 * (i + 1), scan="PASS") for i, n in enumerate(names)]


try:
    rows = mk("wp-20220501", "wp-20220501-r1", "wp-20220501-r2", "solo", "wp-g00-r1", "wp-g10", "lone-r1", "x-r2x")
    n = tl.mark_superseded(rows); by = {r["pack"]: r["superseded_by"] for r in rows}
    chk("a) base and -r1 superseded by -r2; -r2 kept (None)", by["wp-20220501"] == "wp-20220501-r2" and by["wp-20220501-r1"] == "wp-20220501-r2" and by["wp-20220501-r2"] is None and n == 2)
    chk("c) a lone pack is never superseded; g00-r1 and g10 (different bases) are independent", by["solo"] is None and by["wp-g00-r1"] is None and by["wp-g10"] is None)
    chk("d) a lone -r1 stands; 'x-r2x' is not a revision", by["lone-r1"] is None and by["x-r2x"] is None)
    kept = sum(r["tokens"] for r in rows if not r["superseded_by"]); sup = sum(r["tokens"] for r in rows if r["superseded_by"])
    chk("b) kept + superseded tokens == all rows (nothing lost, nothing double counted)", kept + sup == sum(r["tokens"] for r in rows) and sup == 100 + 200)
    # end to end
    for name, tok in (("a-r1", 1000), ("a-r2", 2000), ("a", 500), ("b", 70)):
        d = TMP + "/packed/" + name; os.makedirs(d + "/shards"); json.dump(dict(shards=1, content_tokens=tok), open(d + "/intake.json", "w")); open(d + "/ledger.jsonl", "w").write("")
    tl.main(["--out", TMP + "/out.json"]); o = json.load(open(TMP + "/out.json"))
    sb = {r["pack"]: r["superseded_by"] for r in o["rows"]}
    allt = sum(v["tokens"] for v in o["totals"].values())
    chk("f) main(): a, a-r1 superseded by a-r2; totals count 2000 + 70 once", sb == {"a": "a-r2", "a-r1": "a-r2", "a-r2": None, "b": None} and allt == 2070)
    chk("f2) superseded_not_counted == 2 packs, 1500 tokens", o["superseded_not_counted"] == dict(packs=2, tokens=1500))
    # mutant: no exclusion -> totals would be 3570; the check above (allt == 2070) must be able to fail
    real = tl.mark_superseded; tl.mark_superseded = lambda rows: 0
    try:
        tl.main(["--out", TMP + "/out2.json"]); o2 = json.load(open(TMP + "/out2.json")); allt2 = sum(v["tokens"] for v in o2["totals"].values())
        chk("e) MUTANT no exclusion is caught (totals would be 3570, not 2070)", allt2 != 2070)
    finally: tl.mark_superseded = real
    # g) lead 83208: a PASS pack that is superseded is refused with "superseded by <name>"; the mutant without the refusal is caught
    from th_pack_scan import signature
    for name in ("c", "c-r1"):
        d = TMP + "/packed/" + name; os.makedirs(d + "/shards"); open(d + "/shards/v1-00000.bin", "wb").write(b"x" * 10)
        json.dump(dict(shards=1, content_tokens=9), open(d + "/intake.json", "w")); open(d + "/ledger.jsonl", "w").write("")
        json.dump(dict(signature=signature(d), clean=True, error="", ts="t", hit_files={}), open(TMP + "/scan/train-%s.json" % name, "w"))
    chk("g0) the old member c scans PASS on its own (the refusal below is not a scan problem)", tl.scan_state(TMP + "/packed/c", "c")[0] == "PASS")
    chk("g1) select_refusal(c) == 'superseded by c-r1' and select_ok(c) is False", tl.select_refusal("c") == "superseded by c-r1" and tl.select_ok("c") is False)
    chk("g2) the newest c-r1 (PASS) stays selectable", tl.select_ok("c-r1") is True and tl.select_refusal("c-r1") is None)
    tl.main(["--out", TMP + "/out3.json"]); o3 = {r["pack"]: r for r in json.load(open(TMP + "/out3.json"))["rows"]}
    chk("g3) the listing row of c is selectable False and says superseded by c-r1", o3["c"]["selectable"] is False and "superseded by c-r1" in o3["c"]["scan_detail"] and o3["c-r1"]["selectable"] is True)
    real_sb = tl.superseded_by; tl.superseded_by = lambda name, packed=None: None
    try: chk("g4) MUTANT without the refusal is caught (select_ok(c) would be True)", tl.select_ok("c") is True)
    finally: tl.superseded_by = real_sb
    chk("g5) after restoring, the refusal is back", tl.select_ok("c") is False)
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for trainable_listing.scan_state / select_ok (the hour-declaration secret-scan gate).
A pack is selectable ONLY with a clean scan row bound to the pack as it is now. REFUSED, NOT RUN, a stale signature, a shard-cleared stub without a Hub binding, and a scanner error are all refused;
a complete local pack that changed under the same name is NOT RUN even when an old Hub binding matches the old row.
Run: python tests/trainable_listing_red_test.py   (temp dirs only; prints ALL PASS)"""
import os, sys, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="tl-red-")
os.environ["TL_PACKED"] = TMP + "/packed"; os.environ["TL_SCAN_DIR"] = TMP + "/scan"; os.environ["TL_BINDING"] = TMP + "/binding.json"; os.environ["TL_OUT"] = TMP + "/out.json"
os.makedirs(TMP + "/packed"); os.makedirs(TMP + "/scan")
import trainable_listing as tl
from th_pack_scan import signature

ok = True


def chk(msg, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + msg); ok = ok and bool(cond)


def pack(name, shards=2, want=2):
    d = TMP + "/packed/" + name; os.makedirs(d + "/shards")
    for i in range(shards): open(d + "/shards/v1-%05d.bin" % i, "wb").write(b"x" * (10 + i))
    json.dump(dict(shards=want, content_tokens=5), open(d + "/intake.json", "w")); open(d + "/ledger.jsonl", "w").write("")
    return d


def row(name, d, **kw):
    r = dict(signature=signature(d), clean=True, error="", ts="t", hit_files={}); r.update(kw)
    json.dump(r, open(TMP + "/scan/train-%s.json" % name, "w"))


BIND = {}


def bind(name, sig): BIND[name] = sig; json.dump(BIND, open(TMP + "/binding.json", "w"))


try:
    d = pack("clean"); row("clean", d)
    chk("clean row on the complete local pack -> PASS and selectable", tl.scan_state(d, "clean")[0] == "PASS" and tl.select_ok("clean"))
    d = pack("none")
    chk("no scan row -> NOT RUN, not selectable", tl.scan_state(d, "none")[0] == "NOT RUN" and not tl.select_ok("none"))
    d = pack("refused"); row("refused", d, clean=False, hit_files={"o1": {"AWS": 2}})
    chk("clean=false -> REFUSED, not selectable", tl.scan_state(d, "refused")[0] == "REFUSED" and not tl.select_ok("refused"))
    d = pack("err"); row("err", d, clean=False, error="trufflehog crashed")
    st = tl.scan_state(d, "err")
    chk("scanner error -> REFUSED (fail closed), not selectable", st[0] == "REFUSED" and "scanner error" in st[1] and not tl.select_ok("err"))
    d = pack("errclean"); row("errclean", d, clean=True, error="partial")
    chk("clean=true WITH an error text is not a PASS", tl.scan_state(d, "errclean")[0] != "PASS" and not tl.select_ok("errclean"))
    d = pack("stale"); row("stale", d); open(d + "/shards/v1-99999.bin", "wb").write(b"new")
    chk("pack changed after the scan (signature differs) -> NOT RUN, not selectable", tl.scan_state(d, "stale")[0] == "NOT RUN" and not tl.select_ok("stale"))
    d = pack("stub", shards=0, want=2); row("stub", d)
    chk("shard-cleared stub with a clean row but no Hub binding -> NOT RUN", tl.scan_state(d, "stub")[0] == "NOT RUN" and not tl.select_ok("stub"))
    d = pack("hubpass", shards=0, want=2); row("hubpass", d, signature="hubsig"); bind("hubpass", "hubsig")
    chk("stub whose row signature equals the Hub copy's -> PASS", tl.scan_state(d, "hubpass")[0] == "PASS" and tl.select_ok("hubpass"))
    d = pack("hubrefused", shards=0, want=2); row("hubrefused", d, signature="hs2", clean=False, hit_files={"o": {"X": 1}}); bind("hubrefused", "hs2")
    chk("Hub-bound row with clean=false -> REFUSED, not selectable", tl.scan_state(d, "hubrefused")[0] == "REFUSED" and not tl.select_ok("hubrefused"))
    d = pack("swapped", shards=2, want=2); row("swapped", d, signature="oldhubsig"); bind("swapped", "oldhubsig")
    chk("complete local pack replaced under the same name, old Hub binding still matches the old row -> NOT RUN (the new files were never scanned)", tl.scan_state(d, "swapped")[0] == "NOT RUN" and not tl.select_ok("swapped"))
    chk("missing pack dir -> not selectable", not tl.select_ok("absent"))
    d = pack("badrow"); open(TMP + "/scan/train-badrow.json", "w").write("{not json")
    chk("unreadable scan row -> NOT RUN, not selectable", tl.scan_state(d, "badrow")[0] == "NOT RUN" and not tl.select_ok("badrow"))
    rc = tl.main(["--out", TMP + "/out.json"]); o = json.load(open(TMP + "/out.json"))
    sel = sorted(r["pack"] for r in o["rows"] if r["selectable"])
    chk("listing marks exactly the PASS packs selectable", rc == 0 and sel == ["clean", "hubpass"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

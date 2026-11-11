# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for PR 2467 review r1 items A, B and note 3 (trainable listing): python tests/trainable_listing_residual_red_test.py
 A) a scan row WITHOUT a signature, a pack absent from the Hub binding file and an incomplete local dir is NOT selectable (None == None is not a binding); an empty-string signature on either side is no binding either
 B) the listing never drops a pack silently and never aborts on one bad pack: temp PACKED dir with one good pack, one without intake.json, one with broken JSON, one without content_tokens:
    the listing is written, residual dirs_seen == dirs_classified + len(dirs_skipped), the skipped packs carry their reason, the malformed pack is a classified row with `error` and not selectable, only the good pack is selectable;
    a --trained path with no ledger file is a trained_errors entry, not an exception
 C) one rule for 'clean': pack_scan_status.record_clean is what the listing uses (a record with clean=true AND hits is not clean in either module)
Temp dirs only; prints ALL PASS."""
import os, sys, json, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="tl-resid-red-")
os.environ["TL_PACKED"] = TMP + "/packed"; os.environ["TL_SCAN_DIR"] = TMP + "/scan"; os.environ["TL_BINDING"] = TMP + "/binding.json"; os.environ["TL_OUT"] = TMP + "/out.json"
os.makedirs(TMP + "/packed"); os.makedirs(TMP + "/scan")
import trainable_listing as tl
import pack_scan_status as pss
from th_pack_scan import signature

ok = True


def chk(msg, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + msg); ok = ok and bool(cond)


def pack(name, shards=2, want=2, intake="ok"):
    d = TMP + "/packed/" + name; os.makedirs(d + "/shards")
    for i in range(shards): open(d + "/shards/v1-%05d.bin" % i, "wb").write(b"x" * (10 + i))
    if intake == "ok": json.dump(dict(shards=want, content_tokens=5), open(d + "/intake.json", "w"))
    elif intake == "broken": open(d + "/intake.json", "w").write("{not json")
    elif intake == "no_tokens": json.dump(dict(shards=want), open(d + "/intake.json", "w"))
    open(d + "/ledger.jsonl", "w").write("")
    return d


def row(name, d, **kw):
    r = dict(signature=signature(d), clean=True, error="", ts="t", hit_files={}); r.update(kw)
    json.dump(r, open(TMP + "/scan/train-%s.json" % name, "w"))


try:
    # A) fail-open on a missing signature
    d = pack("nosig", shards=0, want=2)
    json.dump(dict(clean=True, error="", ts="t", hit_files={}), open(TMP + "/scan/train-nosig.json", "w"))      # no `signature` key at all
    json.dump({}, open(TMP + "/binding.json", "w"))                                                             # pack absent from the binding file
    st = tl.scan_state(d, "nosig")
    chk("A) row without signature + pack absent from the binding + incomplete local dir -> not PASS (%s)" % (st,), st[0] != "PASS" and not tl.select_ok("nosig"))
    d = pack("emptysig", shards=0, want=2)
    json.dump(dict(signature="", clean=True, error="", ts="t", hit_files={}), open(TMP + "/scan/train-emptysig.json", "w"))
    json.dump({"emptysig": ""}, open(TMP + "/binding.json", "w"))
    chk("A) empty signature on both sides is no binding -> not selectable", not tl.select_ok("emptysig"))
    d = pack("nullbind", shards=0, want=2); row("nullbind", d, signature="s1")
    json.dump({"nullbind": None}, open(TMP + "/binding.json", "w"))
    chk("A) binding entry present but null -> not selectable", not tl.select_ok("nullbind"))
    # C) one rule
    d = pack("cleanhits"); row("cleanhits", d, clean=True, hits={"AWS": 2})
    rc_fn = getattr(pss, "record_clean", None)
    chk("C) clean=true carrying hits is not clean in pack_scan_status.record_clean", rc_fn is not None and rc_fn(dict(clean=True, hits={"AWS": 2})) is False)
    chk("C) clean=true carrying hits is not a PASS in the listing", tl.scan_state(d, "cleanhits")[0] != "PASS")
    chk("C) the listing imports the shared rule, no second copy", rc_fn is not None and getattr(tl, "record_clean", None) is rc_fn)
    # B) residual
    shutil.rmtree(TMP + "/packed"); os.makedirs(TMP + "/packed")
    good = pack("good"); row("good", good)
    pack("nointake", intake="none"); pack("broken", intake="broken"); pack("notokens", intake="no_tokens")
    rc = None
    try: rc = tl.main(["--out", TMP + "/out.json"])
    except Exception as e: print("FAIL B) listing aborted: %s: %s" % (type(e).__name__, e)); ok = False
    chk("B) listing written (rc 0)", rc == 0 and os.path.isfile(TMP + "/out.json"))
    o = json.load(open(TMP + "/out.json")) if os.path.isfile(TMP + "/out.json") else {}
    res = o.get("residual") or {}
    sk = {x["pack"]: x["reason"] for x in res.get("dirs_skipped", [])}
    chk("B) residual: seen 4 == classified + skipped (%s)" % res, res.get("dirs_seen") == 4 and res.get("dirs_seen") == res.get("dirs_classified", -1) + len(res.get("dirs_skipped", [])))
    chk("B) skipped reasons: no_intake_json / missing_content_tokens", sk == {"nointake": "no_intake_json", "notokens": "missing_content_tokens"})
    byname = {r["pack"]: r for r in o.get("rows", [])}
    chk("B) malformed intake.json is a classified row with `error`, not selectable", "broken" in byname and byname["broken"].get("error") and not byname["broken"]["selectable"])
    chk("B) only the good pack is selectable", sorted(r["pack"] for r in o.get("rows", []) if r["selectable"]) == ["good"])
    rc = None
    try: rc = tl.main(["--out", TMP + "/out2.json", "--trained", TMP + "/no-such-ledger.jsonl"])
    except Exception as e: print("FAIL B) --trained with no ledger aborted: %s: %s" % (type(e).__name__, e)); ok = False
    o2 = json.load(open(TMP + "/out2.json")) if os.path.isfile(TMP + "/out2.json") else {}
    chk("B) --trained with no ledger file: listing written, reason in trained_errors", rc == 0 and len(o2.get("trained_errors", [])) == 1 and "reason" in o2["trained_errors"][0])
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

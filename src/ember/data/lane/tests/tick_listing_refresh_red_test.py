# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for tick.py refresh_listing (lead 83208): loops/trainable-listing.json is rewritten by the intake tick and by the upload tick (after the scans it reads), never silently stale.
Executes the REAL refresh_listing source (sliced out of tick.py) against a temp lane root whose scripts/trainable_listing.py is a small stub, and checks the wiring (intake() and upload() call it
before their final done()). TICK_RL_STUB=1 swaps in a refresh that does nothing: the same assertions must FAIL (the test bites). Run: python tests/tick_listing_refresh_red_test.py"""
import os, sys, json, time, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(HERE, "loops", "tick.py"), encoding="utf-8").read()
i = SRC.index("def refresh_listing():"); j = SRC.index("\ndef done(status, note):")
FN = SRC[i:j]
if os.environ.get("TICK_RL_STUB") == "1": FN = "def refresh_listing():\n    return ''\n"
ok = True


def chk(n, c):
    global ok; ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


def lane(stub_body):
    root = tempfile.mkdtemp(prefix="tick_rl_"); os.makedirs(root + "/scripts"); os.makedirs(root + "/loops")
    if stub_body is not None: open(root + "/scripts/trainable_listing.py", "w").write(stub_body)
    return root


def call(root):
    g = dict(subprocess=subprocess, sys=sys, json=json, time=time, ROOT=root)
    exec(FN, g)
    return g["refresh_listing"]()


GOOD = "import json\njson.dump({'totals': {'PASS': {'packs': 2, 'tokens': 100}, 'REFUSED': {'packs': 1, 'tokens': 7}}}, open(__import__('os').getcwd().replace(chr(92), '/') + '/loops/trainable-listing.json', 'w'))\n"
r = call(lane(GOOD))
chk("success: receipt text says 'listing refreshed' with the PASS and REFUSED totals", "listing refreshed" in r and "PASS 2 packs 100 tok" in r and "REFUSED 1 packs 7 tok" in r)
r = call(lane("import sys\nsys.exit(3)\n"))
chk("nonzero exit: reported FAILED rc=3, old file kept, no exception", "FAILED rc=3" in r and "old file kept" in r)
r = call(lane(None))
chk("script missing: reported FAILED (python rc=2), no exception", "FAILED" in r and "old file kept" in r)
r = call(lane("open('loops/trainable-listing.json', 'w').write('{not json')\n"))
chk("garbled output file: reported FAILED, no exception", "FAILED" in r and "old file kept" in r)
for name in ("intake", "upload"):
    a = SRC.index("\ndef %s():" % name); b = SRC.index("\ndef ", a + 5); body = SRC[a:b]
    chk("%s() calls refresh_listing() before its final done()" % name, "refresh_listing()" in body)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

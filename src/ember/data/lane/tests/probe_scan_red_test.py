# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for probe_scan.py: a planted test prompt is found (whole line, embedded in a longer line, different case/spacing), a near-miss is not, answer-bearing is detected.
Run: python scripts/tests/probe_scan_red_test.py"""
import os, sys, io, json, subprocess, tempfile, shutil
import zstandard
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST = os.path.join(os.path.dirname(HERE), "probes", "v1", "test.jsonl")
ok = True


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


rows = [json.loads(l) for l in open(TEST, encoding="utf-8")]
pick = {}
for r in rows:
    pick.setdefault(r["type"], r)
d = tempfile.mkdtemp(); os.makedirs(d + "/objects")
p_word, p_ar, p_list = pick["word_transform"], pick["arithmetic"], pick["list_ops"]
docs = [
    {"text": "intro text\n" + p_word["prompt"] + "\n" + p_word["answer"] + "\nmore text"},                                   # whole line + answer next line
    {"text": "def f():\n    q = '" + p_ar["prompt"] + "' # example in code. nothing else"},                                   # embedded in a longer line
    {"text": "NOTE:   " + p_list["prompt"].upper().replace(" ", "   ") + "  trailing words after"},                          # case + spacing changed
    {"text": "Compute: 524881 + 39938x is not a prompt, and neither is how many letters are in the word"},                  # near misses
    {"text": "plain prose without any template phrase at all " * 50},
]
w = zstandard.ZstdCompressor().stream_writer(open(d + "/objects/t-0000.jsonl.zst", "wb"))
for x in docs: w.write((json.dumps(x) + "\n").encode("utf-8"))
w.close()
out = d + "/res.json"
subprocess.run([sys.executable, os.path.join(HERE, "probe_scan.py"), d + "/objects", "--out", out], capture_output=True, text=True, check=True)
res = json.load(open(out))
chk("GREEN 5 docs scanned", res["docs"] == 5)
chk("GREEN the whole-line, embedded and case/spacing-changed prompts are all found (3 hits)", res["prompt_hits"] == 3)
chk("GREEN hits are attributed to the right types", res["hits_by_type"] == {"word_transform": 1, "arithmetic": 1, "list_ops": 1})
chk("GREEN the answer on the next line counts as answer-bearing", res["prompt_hits_with_answer_within_300_chars"] >= 1)
chk("RED near misses and plain prose add no hits (still exactly 3)", res["prompt_hits"] == 3)
# probe_scan_all: scans a pack once, writes the done-marker, never re-scans, and the tick surfaces hits
b = tempfile.mkdtemp(); os.makedirs(b + "/packed/x/objects"); os.makedirs(b + "/logs"); os.makedirs(b + "/packed/media/objects")
shutil.copyfile(d + "/objects/t-0000.jsonl.zst", b + "/packed/x/objects/x-0000.jsonl.zst")
env = dict(os.environ, PROBE_SCAN_BASE=b, PROBE_TEST=TEST)
r = subprocess.run([sys.executable, os.path.join(HERE, "probe_scan_all.py")], capture_output=True, text=True, env=env)
mk = b + "/logs/probe-scan-x.json"
chk("GREEN probe_scan_all writes logs/probe-scan-<pack>.json with the 3 planted hits", os.path.exists(mk) and json.load(open(mk))["prompt_hits"] == 3)
chk("GREEN a directory without .jsonl.zst objects (media) is skipped", not os.path.exists(b + "/logs/probe-scan-media.json"))
m1 = os.path.getmtime(mk); subprocess.run([sys.executable, os.path.join(HERE, "probe_scan_all.py")], capture_output=True, text=True, env=env)
chk("RED a second run does not re-scan an already marked pack", os.path.getmtime(mk) == m1)
tsrc = open(os.path.join(HERE, "loops", "tick.py"), encoding="utf-8").read()
chk("GREEN tick intake spawns probe_scan_all.py and prints PROBE_HIT on a hit", 'spawn("python scripts/probe_scan_all.py"' in tsrc and '" PROBE_HIT "' in tsrc)
shutil.rmtree(b, ignore_errors=True)
shutil.rmtree(d, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

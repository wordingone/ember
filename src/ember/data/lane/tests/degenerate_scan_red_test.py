# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for degenerate_scan (lead 82716 item 3): synthetic packs (shard .bin little-endian uint16 + ledger.jsonl with source-stream spans) in a temporary tree.
Degenerate objects (period 1, 2, 16, a 1,144,723-token period-2 stand-in at the known real offsets, one straddling a shard boundary) are REFUSED and named by object sha256 and offsets;
short repeats (< RUN_MIN), zipf text and period-17 are KEPT. Run: python tests/degenerate_scan_red_test.py
DEGEN_SCAN_STUB=1 swaps in a scan that never refuses: the same assertions must then FAIL (proves the test bites)."""
import os, sys, json, hashlib, tempfile, subprocess
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(HERE, "degenerate_scan.py")
TMP = tempfile.mkdtemp(prefix="degen_red_")
if os.environ.get("DEGEN_SCAN_STUB") == "1":
    SCAN = os.path.join(TMP, "stub_scan.py")
    with open(SCAN, "w") as f:
        f.write("import sys\nprint('degenerate_scan: STUB never refuses')\nsys.exit(0)\n")
ok = True
rng = np.random.default_rng(20261111)


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


def text(n):
    return np.minimum(rng.zipf(1.3, n), 31999).astype(np.uint16) + np.uint16(1)       # natural-looking, id 0 unused


def cyc(pat, n):
    p = np.array(pat, dtype=np.uint16)
    return np.tile(p, n // len(p) + 1)[:n]


def sha(tag):
    return hashlib.sha256(tag.encode()).hexdigest()


def build(name, objs, shard_n, src_base=0):
    """objs: [(tag, tokens)] concatenated into one stream, cut into shards of shard_n tokens; ledger spans carry SOURCE coordinates (src_base + stream position)."""
    d = os.path.join(TMP, name); os.makedirs(os.path.join(d, "shards"))
    stream = np.concatenate([t for _, t in objs]); bounds = []; pos = 0
    for tag, t in objs:
        bounds.append((tag, pos, pos + len(t))); pos += len(t)
    rows = []; prev = "0" * 64
    for i, a in enumerate(range(0, len(stream), shard_n)):
        chunk = stream[a:a + shard_n]; nm = "v1-%05d-%012x.bin" % (i, i)
        chunk.astype("<u2").tofile(os.path.join(d, "shards", nm))
        spans = [dict(sha256=sha(tag), token_start=src_base + max(a, lo), token_end=src_base + min(a + len(chunk), hi)) for tag, lo, hi in bounds if max(a, lo) < min(a + len(chunk), hi)]
        rows.append(dict(index=i, n_tokens=len(chunk), name=nm, prev_row_sha256=prev, spans=spans))
    with open(os.path.join(d, "ledger.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    return d


def run(d, *extra, env=None):
    e = dict(os.environ); e.update(env or {})
    r = subprocess.run([sys.executable, SCAN, d, *extra], capture_output=True, text=True, env=e)
    named = [l.split("object=")[1].split()[0] for l in r.stdout.splitlines() if l.startswith("REFUSED ")]
    return r, named, [l for l in r.stdout.splitlines() if l.startswith("REFUSED ")]


def field(line, key):
    return line.split(key + "=")[1].split()[0]


# (a)(b)(c) degenerate objects, one pack each, normal text around them
for tag, pat, n in (("a-period2", [23, 186], 100_000), ("b-period1", [7], 100_000), ("c-period16", list(range(100, 116)), 100_000)):
    d = build(tag, [("pre", text(50_000)), (tag, cyc(pat, n)), ("post", text(50_000))], 1 << 20)
    r, named, lines = run(d)
    chk("%s: REFUSED (exit 1) and named" % tag, r.returncode == 1 and named == [sha(tag)])
    off = field(lines[0], "offsets").split("..") if lines else ["0", "0"]
    chk("%s: offsets/period/run reported (start ~50000, ~100000 tokens, period %d)" % (tag, len(pat)),
        lines and abs(int(off[0]) - 50_000) < 64 and abs(int(off[1].split()[0]) - 150_000) < 64 and field(lines[0], "period") == str(len(pat)) and abs(int(field(lines[0], "run_tokens")) - n) < 128)

# (d) short repeat below RUN_MIN inside normal text; (e) natural text; (f) period-17
d = build("d-short", [("short", np.concatenate([text(20_000), cyc([23, 186], 3000), text(20_000)]))], 1 << 20)
r, named, _ = run(d)
chk("(d) 3000-token repeat inside text is KEPT (exit 0)", r.returncode == 0 and named == [])
r, named, _ = run(d, "--run-min", "2000")
chk("(d) same pack with --run-min 2000 is REFUSED (flag works)", r.returncode == 1 and named == [sha("short")])
d = build("e-natural", [("nat%d" % i, text(300_000)) for i in range(3)], 1 << 20)
r, named, _ = run(d)
chk("(e) zipf tokens KEPT (exit 0)", r.returncode == 0 and named == [])
d = build("f-p17", [("p17", cyc(list(range(500, 517)), 100_000)), ("nat", text(50_000))], 1 << 20)
r, named, _ = run(d)
chk("(f) period-17 KEPT at default --max-period 16", r.returncode == 0 and named == [])
r, named, _ = run(d, "--max-period", "17")
chk("(f) period-17 REFUSED with --max-period 17", r.returncode == 1 and named == [sha("p17")])

# (g) degenerate object mid-shard between normal objects: only it is named
d = build("g-mix", [("n1", text(200_000)), ("bad", cyc([23, 186], 120_000)), ("n2", text(200_000)), ("n3", text(100_000))], 1 << 20)
r, named, _ = run(d)
chk("(g) only the degenerate object is named", r.returncode == 1 and named == [sha("bad")])

# (h) degenerate object straddling a shard boundary: each half < RUN_MIN would hide it without the carried tail
d = build("h-straddle", [("n1", text(8000)), ("bad", cyc([23, 186], 6000)), ("n2", text(8000))], 11_000)       # boundary at 11000 = 3000 tokens into the bad object
r, named, lines = run(d)
chk("(h) object straddling a shard boundary is REFUSED once, spanning both shards", r.returncode == 1 and named == [sha("bad")] and ".." in lines[0] and "v1-00001" in lines[0])

# (i) real layout: 4,194,304-token shard, ids 23/186 alternating, shard offsets 932,601..2,077,324 (1,144,723 tokens), source coordinates far from shard-relative ones
d = build("i-real", [("pre", text(932_601)), ("real", cyc([23, 186], 1_144_723)), ("post", text(4_194_304 - 2_077_324))], 4_194_304, src_base=777_000_000)
r, named, lines = run(d)
chk("(i) real-layout stand-in REFUSED and named", r.returncode == 1 and named == [sha("real")])
chk("(i) shard-relative offsets 932601..2077324 from cumulative span lengths (not token_start)", lines and abs(int(field(lines[0], "offsets").split("..")[0]) - 932_601) < 64 and abs(int(field(lines[0], "offsets").split("..")[1]) - 2_077_324) < 64)

# (j) missing shard is an error, not a clean pass; --allow-missing downgrades it; --json is confined
d = build("j-miss", [("n1", text(50_000))], 1 << 20)
os.remove(os.path.join(d, "shards", "v1-00000-000000000000.bin"))
r, named, _ = run(d)
chk("(j) missing shard -> exit 2 (cannot claim clean)", r.returncode == 2)
r, named, _ = run(d, "--allow-missing")
chk("(j) --allow-missing -> exit 0", r.returncode == 0)
d = build("k-json", [("bad", cyc([1, 2], 50_000))], 1 << 20)
r, _, _ = run(d, "--json", os.path.join(d, "out.json"))
chk("(k) --json inside the pack is refused (exit 2)", r.returncode == 2)
r, _, _ = run(d, "--json", os.path.join(TMP, "outside", "out.json"), env=dict(DEGEN_SCAN_OUT_ROOT=os.path.join(TMP, "outside")))
chk("(k) --json under an allowed root is written with the named object", r.returncode == 1 and os.path.isfile(os.path.join(TMP, "outside", "out.json")) and sha("bad") in open(os.path.join(TMP, "outside", "out.json")).read())

import shutil; shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""One-run, ruled application of the terminal-probe payload reclaim, generic form of probe_apply_82461.py (lead rulings 82461 / 82478).
Usage: python scripts/probe_apply.py --ruling 82478 --manifest <probe_manifest json> --only O-probe-... [--only ...] [--keep NAME ...] [--protect GLOB ...]
Steps (the ruling, in order):
 1. rename loops/CKPT-DELETE-FREEZE.flag -> CKPT-DELETE-FREEZE.flag.lifted-by-lead-<ruling>
 2. ckpt_lineage_delete.py --only-probes --expect-dirs <the ruled dirs> --ruling <ruling> [--keep ...] as a DRY RUN; refuse (restore the flag, exit 5) unless it selects exactly the ruled children and their dirs equal the manifest rows
 3. the same with --apply (the script writes each manifest row, sha256 + path, before the remove)
 4. restore the flag name in a finally block, whatever happened
 5. read back: flag present, the ruled payloads gone, the --protect globs unchanged (file count, bytes, newest mtime), B: free
Each ruled manifest row must be clause A or B with its terminal receipt file present on disk (clause A) before the flag is touched. Nothing else is touched.
Receipt: <m-root>/avir/<data>/state/probe-apply-<ruling>.json"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_DATA
import os, sys, json, re, time, glob, shutil, subprocess, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--ruling", required=True)
ap.add_argument("--manifest", required=True)
ap.add_argument("--only", action="append", required=True, help="manifest row name (O-probe-...) the ruling covers; repeatable")
ap.add_argument("--keep", action="append", default=[], help="enumerated child name to leave out of the selection (passed to --keep, last)")
ap.add_argument("--protect", action="append", default=[], help="glob of dirs that must be byte-for-byte unchanged")
A = ap.parse_args()

from lane_config import LANE_ROOT as DS
FLAG = DS + "/loops/CKPT-DELETE-FREEZE.flag"
LIFTED = FLAG + ".lifted-by-lead-" + A.ruling
EXPECT = DS + "/logs/probe-expect-%s.json" % A.ruling
LDM = DS + "/logs/manifests-20261108/ckpt-lineage-delete-manifest.jsonl"
OUTJ = (M_ROOT + "/avir/" + SEAT_DATA + "/state/probe-apply-%s.json") % A.ruling
BIG = 1 << 20
res = dict(ruling=A.ruling, started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), steps=[])


def log(msg):
    res["steps"].append(msg)
    print(msg, flush=True)


def sig(d):
    n = b = 0
    newest = 0.0
    for dp, _, fs in os.walk(d):
        for f in fs:
            try:
                st = os.stat(os.path.join(dp, f))
            except OSError:
                continue
            n += 1
            b += st.st_size
            newest = max(newest, st.st_mtime)
    return dict(files=n, bytes=b, newest_mtime=newest)


def payload_left(d):
    big = small = 0
    for dp, _, fs in os.walk(d):
        for f in fs:
            try:
                sz = os.stat(os.path.join(dp, f)).st_size
            except OSError:
                continue
            if sz >= BIG:
                big += 1
            else:
                small += 1
    return big, small


def run(args, outfile, timeout):
    with open(outfile, "w", encoding="utf-8") as fo:
        p = subprocess.run([sys.executable, DS + "/scripts/ckpt_lineage_delete.py"] + args, cwd=DS, stdout=fo, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, open(outfile, encoding="utf-8", errors="replace").read()


man = json.load(open(A.manifest))
by_name = {r["name"]: r for r in man["eligible"]}
missing = [n for n in A.only if n not in by_name]
assert not missing, "ruled rows not eligible in the manifest: %s" % missing
rows = [by_name[n] for n in A.only]
for r in rows:       # the condition of the ruling: the guard prints it as clause A/B and, for A, the consumer hour's terminal receipt is on disk
    assert r["clause"][:1] in ("A", "B"), r["clause"]
    if r["clause"].startswith("A"):
        assert r["terminal_receipts"] and all(os.path.exists(t) for t in r["terminal_receipts"]), "clause A without a terminal receipt on disk: %s" % r["name"]
want = sorted(r["path"].replace("\\", "/") for r in rows)
want_files = sum(r["files"] for r in rows)
json.dump(want, open(EXPECT, "w"), indent=1)
res["expected_dirs"] = want
res["expected_files"] = want_files
res["rows"] = [dict(name=r["name"], bytes=r["bytes"], clause=r["clause"], terminal=r["terminal_receipts"]) for r in rows]
prot = sorted({p.replace("\\", "/") for g in A.protect for p in glob.glob(g)})
res["b_free_before_gib"] = round(shutil.disk_usage("B:/").free / 2**30, 2)
res["protected_before"] = {p: sig(p) for p in prot}
assert os.path.exists(FLAG) and not os.path.exists(LIFTED), "freeze flag state unexpected before the lift"
rc_final = 0
try:
    os.rename(FLAG, LIFTED)
    log("1 freeze flag renamed to %s" % os.path.basename(LIFTED))
    extra = (["--keep"] + A.keep) if A.keep else []
    base = ["--only-probes", "--expect-dirs", EXPECT, "--ruling", A.ruling]
    rc, out = run(base + extra, DS + "/logs/probe-apply-%s.dry.out" % A.ruling, 3600)
    sel = sorted(l.split(" ", 2)[2].strip() for l in out.splitlines() if l.startswith("SELECTED "))
    m = re.search(r"children selected (\d+) \| files to delete (\d+) \| unique inodes (\d+) \| REAL freed ([0-9.]+) GiB", out)
    res["dry"] = dict(rc=rc, selected=len(sel), summary=m.group(0) if m else None, dry_run_line="DRY RUN" in out)
    ok = rc == 0 and "DRY RUN" in out and m and int(m.group(1)) == len(want) and sel == want and int(m.group(2)) == want_files
    if not ok:
        log("2 DRY RUN REFUSED: rc=%s selected=%d summary=%s equal_to_manifest=%s" % (rc, len(sel), m.group(0) if m else None, sel == want))
        rc_final = 5
    else:
        log("2 dry run ok: " + m.group(0))
        t0 = time.time()
        rc, out = run(["--only-probes", "--apply", "--expect-dirs", EXPECT, "--ruling", A.ruling] + extra, DS + "/logs/probe-apply-%s.apply.out" % A.ruling, 4 * 3600)
        tail = [l for l in out.splitlines() if l.startswith("deleted ") or l.startswith("could not remove") or l.startswith("REFUSED")]
        res["apply"] = dict(rc=rc, secs=round(time.time() - t0), tail=tail)
        log("3 apply rc=%s secs=%d %s" % (rc, time.time() - t0, tail))
        if rc != 0:
            rc_final = 6
finally:
    if os.path.exists(LIFTED) and not os.path.exists(FLAG):
        os.rename(LIFTED, FLAG)
    log("4 freeze flag restored: %s" % os.path.exists(FLAG))
res["flag_present"] = os.path.exists(FLAG) and not os.path.exists(LIFTED)
res["children"] = {}
for r in rows:
    big, small = payload_left(r["path"]) if os.path.isdir(r["path"]) else (0, 0)
    res["children"][r["path"]] = dict(expected_bytes=r["bytes"], big_files_left=big, small_files_left=small)
res["ruled_payloads_gone"] = all(v["big_files_left"] == 0 for v in res["children"].values())
res["protected_after"] = {p: sig(p) for p in prot}
res["protected_unchanged"] = all(res["protected_before"][p] == res["protected_after"][p] for p in prot)
deleted_rows = []
if os.path.exists(LDM):
    for l in open(LDM, encoding="utf-8"):
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if x.get("ts", "") >= res["started"] and x.get("probe_clause"):
            deleted_rows.append(x)
res["manifest_rows_written"] = len(deleted_rows)
res["manifest_rows_with_sha256"] = sum(1 for x in deleted_rows if x.get("sha256"))
res["manifest_rows_paths_gone"] = sum(1 for x in deleted_rows if not os.path.exists(x["path"]))
res["b_free_after_gib"] = round(shutil.disk_usage("B:/").free / 2**30, 2)
res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
json.dump(res, open(OUTJ, "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ("steps", "children", "protected_before", "protected_after", "expected_dirs", "rows")}, indent=1))
print("PROBE-APPLY-%s-DONE rc %s" % (A.ruling, rc_final))
sys.exit(rc_final)

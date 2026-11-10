# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Drift check for the lane (#2454, lead 82490): the lane must run from, or be byte-checked against, the reviewed tree copy, and a tick refuses on drift.
The lane executes the LIVE scripts; the repository holds the reviewed copy, GENERATED from the live scripts by export_lane.py. Drift = the export of the live scripts is not byte-identical
to the tree (src/ember/data/lane at the tree ref): an edited script, a new script, or a tree file the live lane does not have. Compared by git blob id, so line endings cannot hide a change.
  python lane_drift.py check [--ref REF] [--repo PATH] [--fetch] [--json]   exit 0 clean (or acknowledged), 1 drift, 2 cannot check
  python lane_drift.py export --dst DIR      the ONE canonical export command (values in lane-export.json), README included
  python lane_drift.py ack --ruling ID [--note TEXT] [--ttl-h N]   acknowledge exactly the CURRENT drift (content-bound: any later edit trips again; expires, default 48 h)
tick.py calls gate(loop) before it does anything else. FAIL CLOSED: if the check itself cannot run (git, the export, a bad config) the tick refuses too. The only waiver is drift-ack.json, which needs a ruling id,
names the exact exported blob ids it covers and expires. When drift is found the gate fetches the tree ref once (at most every 30 min; a failed fetch changes nothing) so a merged PR clears it by itself.
Red: python scripts/tests/lane_drift_red_test.py"""
import os, sys, json, time, hashlib, subprocess
SCRIPTS = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = os.path.dirname(SCRIPTS); L = ROOT + "/loops"
CFG = SCRIPTS + "/lane-export.json"; CACHE = L + "/drift-cache.json"; ACK = L + "/drift-ack.json"
FETCH_EVERY_S = 1800; ACK_TTL_H = 48
EXPORTABLE = (".py", ".sh", ".ps1")


def cfg():
    return json.load(open(CFG, encoding="utf-8"))


def blob_oid(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def lf(data):
    return data.replace(b"\r\n", b"\n")


def export_to(dst, src=None):
    """The canonical export: export_lane.py with the values of lane-export.json, then the README with LF line endings. Raises on any failure (the equivalence proof included)."""
    c = cfg(); src = src or SCRIPTS; cmd = [sys.executable, SCRIPTS + "/export_lane.py", "--src", src, "--dst", dst, "--m-root", c["m_root"], "--lane-dir", c["lane_dir"]]
    for k, flag in (("seat", "--seat"), ("word", "--word"), ("repo", "--repo"), ("exclude", "--exclude")):
        for v in c.get(k, []): cmd += [flag, v]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    if r.returncode != 0: raise RuntimeError("export failed rc=%d: %s" % (r.returncode, (r.stdout + r.stderr).strip()[-300:]))
    rd_src, rd_dst = c["readme"]
    if os.path.exists(src + "/" + rd_src):
        os.makedirs(dst, exist_ok=True); open(dst + "/" + rd_dst, "wb").write(lf(open(src + "/" + rd_src, "rb").read()))


def dir_oids(d):
    out = {}
    for dp, dn, fn in os.walk(d):
        for f in fn:
            p = os.path.join(dp, f); out[os.path.relpath(p, d).replace("\\", "/")] = blob_oid(open(p, "rb").read())
    return out


def live_key(src=None):
    """cheap fingerprint of everything the export reads: each exportable file (LF-normalised), the README, the export config and the exporter itself"""
    c = cfg(); src = src or SCRIPTS; rows = []
    for dp, dn, fn in os.walk(src):
        dn[:] = sorted(d for d in dn if d != "__pycache__")
        for f in sorted(fn):
            rel = os.path.relpath(os.path.join(dp, f), src).replace("\\", "/")
            if rel in c.get("exclude", []) or not (f.endswith(EXPORTABLE) or rel in (c["readme"][0], "lane-export.json")): continue
            rows.append((rel, hashlib.sha256(lf(open(os.path.join(dp, f), "rb").read())).hexdigest()))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def git(repo, *args, timeout=120):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError("git %s failed rc=%d: %s" % (" ".join(args[:2]), r.returncode, r.stderr.decode("utf-8", "replace").strip()[-200:]))
    return r.stdout


def tree_oids(repo, ref, sub):
    """(tree id, {relative path: blob id}) of ref:sub, read from git objects only"""
    spec = "%s:%s" % (ref, sub); tid = git(repo, "rev-parse", "--verify", spec).decode().strip(); out = {}
    for ent in git(repo, "ls-tree", "-r", "-z", spec).split(b"\0"):
        if not ent: continue
        meta, _, path = ent.partition(b"\t"); out[path.decode("utf-8")] = meta.split()[2].decode()
    return tid, out


def compare(exp, tree):
    return dict(changed=sorted(p for p in exp if p in tree and exp[p] != tree[p]), live_only=sorted(p for p in exp if p not in tree), tree_only=sorted(p for p in tree if p not in exp))


def check(src=None, repo=None, ref=None, exporter=None, tree_reader=None, use_cache=True, cache=None):
    """report dict: clean, changed/live_only/tree_only (lists of paths), oids (exported blob id of every changed/live_only path), tree (id), key, cached"""
    c = cfg(); t = c["tree"]; repo = repo or t["repo"]; ref = ref or t["ref"]; cache = cache or CACHE
    tid, toids = (tree_reader or tree_oids)(repo, ref, t["sub"]); key = live_key(src)
    if use_cache and os.path.exists(cache):
        try:
            old = json.load(open(cache, encoding="utf-8"))
            if old.get("key") == key and old.get("tree") == tid and old.get("report"): rep = dict(old["report"]); rep["cached"] = True; return rep
        except Exception: pass
    from scratch_dir import ScratchDir
    with ScratchDir("drift-export-") as d:
        (exporter or export_to)(d + "/out", src); exp = dir_oids(d + "/out")
    cmp_ = compare(exp, toids); rep = dict(clean=not any(cmp_.values()), tree=tid, key=key, ref=ref, oids={p: exp[p] for p in cmp_["changed"] + cmp_["live_only"]}, cached=False, **cmp_)
    os.makedirs(os.path.dirname(cache), exist_ok=True); json.dump(dict(key=key, tree=tid, report=rep), open(cache, "w", encoding="utf-8"))
    return rep


def summary(rep, n=4):
    def part(label, xs): return "%s %d%s" % (label, len(xs), " (" + ", ".join(xs[:n]) + (", ..." if len(xs) > n else "") + ")" if xs else "")
    return "; ".join(part(l, rep[k]) for l, k in (("changed", "changed"), ("not in tree", "live_only"), ("only in tree", "tree_only")) if rep[k]) or "clean"


def ack_covers(rep, ack, now=None):
    """a waiver covers the drift only if it names a ruling, has not expired, and lists the exact exported blob id of every drifted file (and the same tree-only set)"""
    now = time.time() if now is None else now
    if not isinstance(ack, dict) or not str(ack.get("ruling") or "").strip() or float(ack.get("expires_ts") or 0) < now: return False
    if sorted(ack.get("tree_only") or []) != rep["tree_only"]: return False
    return all(ack.get("oids", {}).get(p) == o for p, o in rep["oids"].items()) and set(ack.get("oids", {})) >= set(rep["oids"])


def maybe_fetch(repo, ref, cache=None, now=None, runner=None):
    """one `git fetch` of the tree remote at most every FETCH_EVERY_S, only when drift was seen; any failure is ignored (the verdict then stays 'drift')"""
    fp = (cache or CACHE) + ".fetch"; now = time.time() if now is None else now
    try: last = float(json.load(open(fp, encoding="utf-8")).get("fetched_ts") or 0)
    except Exception: last = 0
    if now - last < FETCH_EVERY_S: return False
    os.makedirs(os.path.dirname(fp), exist_ok=True); json.dump({"fetched_ts": now}, open(fp, "w", encoding="utf-8"))
    try: (runner or git)(repo, "fetch", "--quiet", ref.split("/")[0], ref.split("/", 1)[1] if "/" in ref else ref, timeout=90); return True
    except Exception: return False


def gate(loop="", now=None, ack_path=None, fetcher=None, **kw):
    """(ok, note) for tick.py. ok False = refuse the tick. Any exception = refuse (fail closed)."""
    try:
        rep = check(**kw)
        if rep["clean"]: return True, ""
        if (fetcher or maybe_fetch)(kw.get("repo") or cfg()["tree"]["repo"], kw.get("ref") or cfg()["tree"]["ref"]): rep = check(**kw)      # a merged PR clears itself
        if rep["clean"]: return True, "drift cleared after fetching the tree"
        try: ack = json.load(open(ack_path or ACK, encoding="utf-8"))
        except Exception: ack = None
        if ack_covers(rep, ack, now): return True, "DRIFT ACKNOWLEDGED (%s) until %s: changed %d, new %d, tree-only %d" % (ack["ruling"], time.strftime("%m-%d %H:%M", time.localtime(ack["expires_ts"])), len(rep["changed"]), len(rep["live_only"]), len(rep["tree_only"]))
        return False, "live lane differs from the tree at %s: %s. Land the change by PR, or acknowledge exactly this drift: python scripts/lane_drift.py ack --ruling ID" % (rep["ref"], summary(rep))
    except Exception as e:
        return False, "drift check could not run (%s: %s); the lane does not run unchecked" % (type(e).__name__, str(e)[:160])


def write_ack(rep, ruling, note="", ttl_h=ACK_TTL_H, path=None, now=None):
    if not str(ruling or "").strip(): raise ValueError("an acknowledgement needs a ruling id")
    now = time.time() if now is None else now
    ack = dict(ruling=ruling, note=note, ts=now, expires_ts=now + ttl_h * 3600, tree=rep["tree"], oids=rep["oids"], tree_only=rep["tree_only"])
    p = path or ACK; os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + ".part"; json.dump(ack, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, p); return ack


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv: print(__doc__.splitlines()[2]); return 2
    cmd, rest = argv[0], argv[1:]
    opt = lambda f, d=None: rest[rest.index(f) + 1] if f in rest else d
    if cmd == "export":
        dst = opt("--dst")
        if not dst: print("export needs --dst DIR"); return 2
        export_to(dst); print("exported ->", dst); return 0
    kw = dict(repo=opt("--repo"), ref=opt("--ref"))
    if cmd == "check":
        try:
            rep = check(**kw)
            if not rep["clean"] and "--fetch" in rest:
                maybe_fetch(kw["repo"] or cfg()["tree"]["repo"], kw["ref"] or cfg()["tree"]["ref"], now=time.time() + 10 * FETCH_EVERY_S); rep = check(**kw)
        except Exception as e: print("CANNOT CHECK %s: %s" % (type(e).__name__, str(e)[:200])); return 2
        ok, note = gate("cli", fetcher=lambda *a: False, **kw)
        if "--json" in rest: print(json.dumps(rep, indent=1))
        print(("CLEAN" if rep["clean"] else ("ACKNOWLEDGED " if ok else "DRIFT ") + summary(rep)) + (" | " + note if ok and note else "")); return 0 if ok else 1
    if cmd == "ack":
        ruling = opt("--ruling")
        if not ruling: print("ack needs --ruling ID"); return 2
        rep = check(**kw)
        if rep["clean"]: print("nothing to acknowledge: no drift"); return 0
        a = write_ack(rep, ruling, opt("--note", ""), float(opt("--ttl-h", ACK_TTL_H))); print("acknowledged %d changed/new + %d tree-only files until %s" % (len(a["oids"]), len(a["tree_only"]), time.strftime("%m-%d %H:%M", time.localtime(a["expires_ts"])))); return 0
    print("unknown command", cmd); return 2


if __name__ == "__main__":
    sys.exit(main())

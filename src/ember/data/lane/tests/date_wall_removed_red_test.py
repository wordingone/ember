# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test: the date wall is gone from the data-lane scripts (owner 2026-11-11, lead 83389): every date exclusion became recorded content_date_max metadata.
Offline. Per script: (a) STATIC: none of the old exclusion tokens remains and content_date_max is present where the script writes rows; (b) BEHAVIOURAL where the script can run on synthetic input
(pg_prep, gh_discover, gh_assemble.chain): a post-2022-10-31 item is KEPT and carries its date. (c) BITE: the same behavioural checks run against the pre-change copy (<script>.bak-datewall, if present
next to the script) and must FAIL there, so the checks are not vacuous.
Run: python tests/date_wall_removed_red_test.py   (exit 0 = ALL PASS)"""
import os, sys, re, io, json, gzip, csv, tempfile, subprocess, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True


def chk(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok = ok and bool(cond)


def src(n): return open(os.path.join(HERE, n), encoding="utf-8").read()


# ---------------- (a) static: forbidden exclusion tokens, required metadata tokens
FORBID = {
    "text_lane.py": [r"\bWALL\b", r"post_wall"], "pg_prep.py": [r"\bWALL\b", r"post_wall"], "se_prep.py": [r"\bWALL\b", r"post_wall"],
    "pdf_list.py": [r"pre_v1_only", r"stats\[\"post\"\]"], "ccby_manifest.py": [r"WALL_EPOCH", r"post_wall"], "ccby_pack.py": [r'"content_date_max": "2022-10-31"'],
    "bulk_lane.py": [r"\bCUT\b"], "a1_prov.py": [r"\bWALL\b", r'r\["post_wall"\]'], "gh_discover.py": [r"\bWALL\b", r"post_wall"],
    "gh_assemble.py": [r"\bWALL\b", r"clean_ok", r"post_wall"], "commons_pilot.py": [r"\bWALL\s*=", r"[<>]=? WALL\b", r'stat\["wall"\]'], "commons_pilot2.py": [r"\bWALL\s*=", r"[<>]=? WALL\b", r"rvstart=WALL", r"upload_ts\"\] <="],
    "librivox_pilot.py": [r"\bWALL\s*=", r"[<>]=? WALL\b", r"post_wall", r"\bpost\s*=", r"not in post"], "pack_prov_fix.py": [r"T\.WALL"],
    "gh_snapshot_fetch.py": [r'return self\._skip\(led, "history_dates_not_monotone"\)'],
}
REQUIRE = {
    "text_lane.py": ["content_date_max", "SPLIT_DATE"], "pg_prep.py": ["content_date_max"], "se_prep.py": ["content_date_max"], "ccby_pack.py": ["content_date_max"], "a1_prov.py": ["content_date_max"],
    "gh_discover.py": ["content_date_max"], "gh_assemble.py": ["content_date_max"], "librivox_pilot.py": ["content_date_max"], "pack_prov_fix.py": ["content_date_max"],
    "gh_snapshot_fetch.py": ["content_date_max", "history_dates_not_monotone"], "ccby_manifest.py": ["content_date_max"], "commons_pilot.py": ["content_date_max"], "commons_pilot2.py": ["content_date_max"],
}
for n, pats in FORBID.items():
    s = src(n)
    for p in pats: chk("static %s: no %r" % (n, p), re.search(p, s) is None)
for n, toks in REQUIRE.items():
    s = src(n)
    for t in toks: chk("static %s: records %s" % (n, t), t in s)
chk("static text_lane.py: the old wall swap hack (WALL = '9999-12-31') is gone", "9999-12-31" not in src("text_lane.py"))


# ---------------- (b)+(c) behavioural, run for a given scripts dir / suffix
def run_pg_prep(script):
    d = tempfile.mkdtemp(prefix="dw_pg_"); cat = d + "/cat.csv"
    with open(cat, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Text#", "Type", "Issued", "Language", "Title"]); w.writeheader()
        w.writerow({"Text#": "1", "Type": "Text", "Issued": "2024-03-05", "Language": "en", "Title": "late"}); w.writerow({"Text#": "2", "Type": "Text", "Issued": "2019-01-01", "Language": "en", "Title": "early"})
    shard = d + "/s.jsonl.gz"
    with gzip.open(shard, "wt", encoding="utf-8") as f:
        for i in ("1", "2"): f.write(json.dumps({"id": i, "text": "word " * 50 + "\n"}) + "\n")
    out = d + "/o.jsonl.zst"
    r = subprocess.run([sys.executable, script, shard, out], capture_output=True, text=True, env=dict(os.environ, PG_CATALOG=cat, PYTHONUTF8="1"))
    if r.returncode: return None
    import zstandard
    rows = [json.loads(l) for l in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(out, "rb")), encoding="utf-8")]
    return {x["id"]: x for x in rows}


def run_gh_discover(script):
    d = tempfile.mkdtemp(prefix="dw_gd_"); raw = d + "/raw"; os.makedirs(raw)
    def ev(num, merged):
        return {"type": "PullRequestEvent", "repo": {"name": "o/r"}, "actor": {"login": "human"},
                "payload": {"action": "closed", "pull_request": {"merged": True, "merged_at": merged, "created_at": merged, "number": num, "title": "fix", "body": "fixes #7", "user": {"login": "human", "type": "User"},
                                                                  "changed_files": 1, "additions": 1, "deletions": 1, "head": {"sha": "a" * 40}}}}
    with gzip.open(raw + "/h.json.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps(ev(1, "2023-06-01T00:00:00Z")) + "\n"); f.write(json.dumps(ev(2, "2022-05-01T00:00:00Z")) + "\n")
    out = d + "/c.jsonl"
    r = subprocess.run([sys.executable, script, out, raw], capture_output=True, text=True, env=dict(os.environ, PYTHONUTF8="1"))
    if r.returncode or not os.path.exists(out): return None
    return {x["pr"]: x for x in (json.loads(l) for l in open(out, encoding="utf-8"))}


def load_assemble(script):
    """exec gh_assemble.py up to `def main():` (the module runs main() at import) with sys.argv set; returns the namespace."""
    s = open(script, encoding="utf-8").read(); s = s[:s.index("\ndef main():")]
    ns = {"__name__": "gh_assemble_under_test", "__file__": script}; old = sys.argv; sys.argv = ["gh_assemble.py", os.devnull, os.devnull]
    try: exec(compile(s, script, "exec"), ns)
    finally: sys.argv = old
    return ns


def assemble_chain(script):
    ns = load_assemble(script)
    late = "2023-02-03T04:05:06Z"
    def u(n): return {"login": n, "type": "User"}
    pr = {"number": 5, "updated_at": late, "created_at": "2022-12-01T00:00:00Z", "merged_at": "2023-01-01T00:00:00Z", "user": u("a"), "title": "t", "body": "b", "base": {"ref": "main"}, "head": {"sha": "b" * 40}, "merged_by": u("m")}
    iss = {"number": 7, "updated_at": "2022-12-30T00:00:00Z", "created_at": "2022-11-30T00:00:00Z", "closed_at": "2023-01-02T00:00:00Z", "user": u("i"), "title": "bug", "body": "x"}
    com = [{"user": u("c"), "created_at": "2022-12-05T00:00:00Z", "updated_at": late, "body": "hi"}]
    def gh(path, accept=None, paginate=False):
        if accept: return "diff"
        if path.endswith("/pulls/5"): return pr
        if "/issues/7/comments" in path or "/issues/5/comments" in path: return com if "/issues/7/" in path else []
        if "/issues/7" in path: return iss
        if "/pulls/5/comments" in path or "/reviews" in path: return []
        if path.endswith("/pulls/5/commits?per_page=100"): return [{"sha": "c" * 40, "commit": {"author": {"date": "2022-12-02T00:00:00Z"}, "message": "m"}, "author": u("a")}]
        if "check-runs" in path or "/status" in path: return {}
        return None
    ns["gh"] = gh; ns["lic"] = lambda repo: "MIT"
    st = collections.Counter()
    return ns["chain"](dict(repo="o/r", pr=5, issues=[7]), st), st


for tag, sd in (("current", HERE), ("pre-change", None)):
    def path(n):
        return os.path.join(HERE, n) if sd else os.path.join(HERE, n + ".bak-datewall")
    if sd is None and not all(os.path.exists(path(n)) for n in ("pg_prep.py", "gh_discover.py", "gh_assemble.py")):
        print("SKIP bite checks: no .bak-datewall copies next to the scripts"); continue
    res = []
    r = run_pg_prep(path("pg_prep.py")); good = bool(r) and set(r) == {"pg-1", "pg-2"} and r["pg-1"].get("content_date_max") == "2024-03-05" and r["pg-2"].get("content_date_max") == "2019-01-01"; res.append(("pg_prep keeps a 2024 Issued doc and records content_date_max 2024-03-05", good))
    r = run_gh_discover(path("gh_discover.py")); good = bool(r) and set(r) == {1, 2} and r[1].get("content_date_max") == "2023-06-01T00:00:00Z"; res.append(("gh_discover keeps a PR merged 2023-06-01 with content_date_max", good))
    try:
        d, st = assemble_chain(path("gh_assemble.py")); good = bool(d) and d.get("content_date_max") == "2023-02-03T04:05:06Z"
    except Exception as e:
        good = False
    res.append(("gh_assemble chain keeps a chain with post-2022 PR/comment edits, content_date_max = the latest element date 2023-02-03T04:05:06Z", good))
    for name, good in res:
        if tag == "current": chk("behaviour (current) " + name, good)
        else: chk("BITE: the pre-change script FAILS this check (%s)" % name, not good)

print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

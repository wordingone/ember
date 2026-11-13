# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for gh_snapshot_fetch (D3, lead 82956; review r1 of PR 2468). Offline: synthetic git repos built in a temp tree (commits with GIT_COMMITTER_DATE / GIT_AUTHOR_DATE before and after the 2022-11-01 wall),
served as file:// remotes with uploadpack.allowFilter. All git / gh calls go through the injectable Runner; the fake Runner still ANSWERS gh_api (from git ls-tree / cat-file) so that a script that calls it is observed
rather than crashed: the production path must make zero gh_api calls. The lane root is forced to a temp dir (the live lane files are never read or written) and reserve_plan.write_gate is stubbed (B: free space is
not under test; the gate's shape is covered by write_gate_lint_red_test.py).
Each check names what it breaks. A scenario that crashes marks every check it owns FAIL (so a run against a broken module still counts). Mutants at the end re-run the scenarios against a deliberately broken
module and require the checks to FAIL (proves they bite).
Run: python tests/gh_snapshot_fetch_red_test.py   (exit 0 = ALL PASS)"""
import os, sys, re, io, json, time, base64, hashlib, tempfile, threading, subprocess, pathlib, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="snapfetch_red_")
os.environ["EMBER_LANE_ROOT"] = TMP + "/lane"                      # forced, never the live lane
for _k, _v in (("EMBER_M_ROOT", TMP), ("EMBER_SEAT_LEAD", "lead"), ("EMBER_SEAT_TRAIN", "train"), ("EMBER_SEAT_DATA", "data"), ("EMBER_HF_RAW_REPO", "x/raw"), ("EMBER_HF_TRAIN_REPO", "x/train")):
    os.environ.setdefault(_k, _v)
sys.path.insert(0, HERE)
import zstandard
import reserve_plan
import gh_snapshot_fetch as G

ok = True
GATE = []
GATE_RESULT = [True]
SOURCE_CLASS = "code, pre-wall snapshot"


def _fake_gate(who="", need_bytes=0, log=print, **kw):
    GATE.append((who, need_bytes)); return GATE_RESULT[0]


reserve_plan.write_gate = _fake_gate


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


# ------------------------------------------------------------------ synthetic remotes
MIT_BODY = ('Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, '
            'including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, '
            'subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.\n\n'
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. '
            'IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH '
            'THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n')
MIT = "MIT License\n\nCopyright (c) 2021 Someone\n\n" + MIT_BODY


def _wrapped():
    import textwrap
    paras = [textwrap.fill(" ".join(x.split()), 58) for x in MIT_BODY.strip().split("\n\n")]
    body = "\n\n".join(paras).replace('(the "Software")', "(the \u201cSoftware\u201d)").replace('"AS IS"', "\u201cAS IS\u201d")
    return "The MIT License (MIT)\n\nCopyright (c) 2019 A, B\nCopyright (c) 2020 C\n\n" + body + "\n"


MIT_WRAPPED = _wrapped()
MIT_RESTRICTED = MIT + "\nAdditionally, you may not use the Software for military purposes.\n"
APACHE_MIT = "Licensed under the Apache License, Version 2.0 (the \"License\"); you may not use this file except in compliance with the License.\nPortions of this work are derived from software under the MIT License.\n"
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n\nEveryone is permitted to copy and distribute verbatim copies of this licence document.\n"
WALL_ISO = "2022-11-01T00:00:00Z"
WALL = 1667260800                                                    # literal: mutants patch the module constant, the test must not follow it


def git(args, cwd, env=None, input=None):
    e = dict(os.environ); e.update(env or {})
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"] + args, cwd=cwd, check=True, capture_output=True, env=e, input=input).stdout.decode().strip()


def make_repo(fullname, commits):
    """commits: [(committer iso, {path: bytes | ("symlink", target bytes) | ("gitlink", sha)}[, author iso])]. -> (dir, [commit shas oldest first])"""
    d = "%s/remotes/%s" % (TMP, fullname.replace("/", "__")); os.makedirs(d)
    git(["init", "-q", "-b", "main"], d)
    for k, v in (("uploadpack.allowFilter", "true"), ("uploadpack.allowAnySHA1InWant", "true"), ("user.email", "t@example.invalid"), ("user.name", "t")):
        git(["config", k, v], d)
    shas, special = [], []
    for c in commits:
        iso, files = c[0], c[1]; aiso = c[2] if len(c) > 2 else iso
        special = []
        for p, b in files.items():
            if isinstance(b, tuple):
                special.append((p, b)); continue
            fp = os.path.join(d, p)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "wb") as f:
                f.write(b)
        git(["add", "-A"], d)
        for p, (kind, v) in special:                                   # symlinks / submodules go straight into the index (real symlinks are unreliable on Windows)
            if kind == "symlink":
                git(["update-index", "--add", "--cacheinfo", "120000,%s,%s" % (git(["hash-object", "-w", "--stdin"], d, input=v), p)], d)
            else:
                git(["update-index", "--add", "--cacheinfo", "160000,%s,%s" % (v, p)], d)
        git(["commit", "-q", "--allow-empty", "-m", "c"], d, env={"GIT_COMMITTER_DATE": iso, "GIT_AUTHOR_DATE": aiso})
        shas.append(git(["rev-parse", "HEAD"], d))
    return d, shas


def build_repos():
    R = {}
    R["o/walltest"] = make_repo("o/walltest", [
        ("2022-01-01T00:00:00Z", {"LICENSE": MIT.encode(), "a.py": b"pre = 1\n", "b.py": b"b-one\n"}),
        ("2022-10-30T12:00:00Z", {"b.py": b"b-prewall\n"}),
        (WALL_ISO, {"exact.py": b"exact = 1\n"}),                                   # committed AT the wall: not strictly before it
        ("2022-11-02T00:00:00Z", {"a.py": b"post = 2\n", "new_post.py": b"x = 'post'\n"}),
        ("2023-05-01T00:00:00Z", {"b.py": b"b-post\n"})])
    R["o/nolic"] = make_repo("o/nolic", [("2022-02-01T00:00:00Z", {"a.py": b"a = 1\n"}), ("2023-01-01T00:00:00Z", {"LICENSE": MIT.encode()})])
    R["o/gpl"] = make_repo("o/gpl", [("2022-02-01T00:00:00Z", {"LICENSE": GPL.encode(), "a.py": b"a = 1\n"}), ("2023-01-01T00:00:00Z", {"LICENSE": MIT.encode()})])
    R["o/perfile"] = make_repo("o/perfile", [
        ("2022-03-01T00:00:00Z", {"LICENSE": MIT.encode(), "good.py": b"def f():\n    return 1\n", "bin.py": b"a\x00b\n", "apache.py": b"# Licensed under the Apache License, Version 2.0\nx = 1\n",
                                  "gen.go": b"// Code generated by tool. DO NOT EDIT.\npackage x\n", "long.py": b"x = '" + b"a" * 20001 + b"'\n", "nb.ipynb": b"{}\n", "sub/LICENSE": GPL.encode(), "sub/x.py": b"y = 2\n",
                                  "sub2/LICENSE": MIT.encode(), "sub2/y.py": b"z = 3\n", "sub3/LICENSE": APACHE_MIT.encode(), "sub3/z.py": b"w = 4\n", "bad.txt": b"\xff\xfe\xfa\n", "pic.png": b"\x89PNG\x00",
                                  "vendor/v.py": b"v = 1\n", "empty.py": b"", "big.json": base64.b64encode(os.urandom(830000))}),
        ("2023-01-01T00:00:00Z", {"late.py": b"late = 1\n"})])
    R["o/restricted"] = make_repo("o/restricted", [("2022-02-01T00:00:00Z", {"LICENSE": MIT_RESTRICTED.encode(), "a.py": b"a = 1\n"})])
    R["o/mixed"] = make_repo("o/mixed", [("2022-02-01T00:00:00Z", {"LICENSE": GPL.encode(), "COPYING": MIT.encode(), "a.py": b"a = 1\n"})])
    R["o/apachemit"] = make_repo("o/apachemit", [("2022-02-01T00:00:00Z", {"LICENSE": APACHE_MIT.encode(), "a.py": b"a = 1\n"})])
    R["o/wrapped"] = make_repo("o/wrapped", [("2022-02-01T00:00:00Z", {"LICENSE.md": MIT_WRAPPED.encode("utf-8"), "a.py": b"a = 1\n"})])
    R["o/residual"] = make_repo("o/residual", [("2022-02-01T00:00:00Z", {"LICENSE": MIT.encode(), "README.md": b"# readme\n", "link": ("symlink", b"README.md"), "sub": ("gitlink", "1" * 40),
                                                                         "pic.png": b"\x89PNG\x00", "vendor/v.py": b"v = 1\n"})])
    R["o/edge"] = make_repo("o/edge", [("2022-01-01T00:00:00Z", {"LICENSE": MIT.encode(), "a.py": b"a = 1\n"}), ("2022-10-31T23:59:59Z", {"edge.py": b"edge = 1\n"}), (WALL_ISO, {"post.py": b"post = 1\n"})])
    R["o/backdated"] = make_repo("o/backdated", [("2022-01-01T00:00:00Z", {"LICENSE": MIT.encode(), "a.py": b"a = 1\n"}), ("2022-12-01T00:00:00Z", {"a.py": b"a = post\n"}),
                                                  ("2022-06-01T00:00:00Z", {"b.py": b"b = 1\n"})])                      # the tip claims June but sits on December history
    R["o/authordate"] = make_repo("o/authordate", [("2022-01-01T00:00:00Z", {"LICENSE": MIT.encode(), "a.py": b"a = 1\n"}), ("2022-06-01T00:00:00Z", {"a.py": b"a = post\n"}, "2022-12-15T00:00:00Z")])
    return R


REPOS = build_repos()
CORE = ["o/walltest", "o/nolic", "o/gpl", "o/perfile"]
GOOD = CORE + ["o/restricted", "o/mixed", "o/apachemit", "o/wrapped", "o/residual", "o/edge", "o/backdated", "o/authordate"]
SIG = dict(has_tests_root=True, has_ci=True, recent_commit_365d=True, not_fork=True, not_archived=True, awesome_or_dump_flag=False)


def cat_row(name, url, sha, spdx="MIT", size_kb=10, **sig):
    return dict(full_name=name, url=url, licence_spdx=spdx, commit_sha=sha, size_kb=size_kb, signals=dict(SIG, **sig))


def rows_for(names, size_kb=10):
    return [cat_row(n, pathlib.Path(REPOS[n][0]).as_uri(), REPOS[n][1][-1], size_kb=size_kb) for n in names]


def bad_rows():
    u = "file:///nowhere/"
    return [cat_row("o/notest", u + "a", "1" * 40, has_tests_root=False), cat_row("o/apache", u + "b", "2" * 40, spdx="Apache-2.0"), cat_row("o/forked", u + "c", "3" * 40, not_fork=False),
            cat_row("o/archived", u + "d", "4" * 40, not_archived=False), cat_row("o/awesome", u + "e", "5" * 40, awesome_or_dump_flag=True), cat_row("o/stale", u + "f", "6" * 40, recent_commit_365d=False),
            dict(full_name="o/nosignals", url=u + "g", licence_spdx="MIT", commit_sha="7" * 40, size_kb=10, signals={}), cat_row("o/noci", u + "h", "8" * 40, has_ci=False),
            cat_row("o/huge", u + "i", "9" * 40, size_kb=40 * 2**20),                                              # clean, but its predicted need (10 GiB) is above the 5 GiB staging cap: deferred
            cat_row("o/nosize", u + "j", "a" * 40, size_kb=None)]                                                  # clean, but no size_kb: the reservation would be a guess: deferred


def new_lane(rows):
    lane = tempfile.mkdtemp(prefix="lane_", dir=TMP).replace("\\", "/")
    os.makedirs(lane + "/catalog"); os.makedirs(lane + "/loops")
    with open(lane + "/catalog/gh-mit-candidates.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    return lane


class FakeRunner(G.Runner):
    """Real git against the local remotes; gh_api answered from ls-tree / cat-file (so a script that still calls it is OBSERVED in gh_calls). Records every call."""

    def __init__(self, forbid=()):
        G.Runner.__init__(self)
        self.calls, self.gh_calls, self.forbid = [], [], list(forbid)

    def git(self, args, cwd=None, input=None):
        self.calls.append(" ".join(args) + " | " + (cwd or ""))
        return super().git(args, cwd, input)

    def gh_api(self, path):
        self.calls.append(path); self.gh_calls.append(path)
        m = re.match(r"repos/([^/]+/[^/]+)/git/(trees|blobs)/([0-9a-f]{40})", path)
        d = REPOS[m.group(1)][0]
        if m.group(2) == "trees":
            out = subprocess.run(["git", "ls-tree", "-r", "-l", "-z", m.group(3)], cwd=d, capture_output=True, check=True).stdout
            ents = []
            for rec in out.split(b"\x00"):
                if not rec:
                    continue
                meta, path_b = rec.split(b"\t", 1); mode, typ, sha, size = meta.split()
                ents.append(dict(path=path_b.decode("utf-8"), mode=mode.decode(), type=typ.decode(), sha=sha.decode(), size=int(size) if size != b"-" else 0))
            return dict(truncated=False, tree=ents)
        b = subprocess.run(["git", "cat-file", "blob", m.group(3)], cwd=d, capture_output=True, check=True).stdout
        return dict(content=base64.b64encode(b).decode(), encoding="base64")

    def touched(self, fullname):
        pat = re.compile(re.escape(fullname.replace("/", "__")) + r"(?!\w)")                # o/apache must not match o/apachemit
        return [c for c in self.calls if pat.search(c) or ("repos/" + fullname + "/") in c]


def read_shard(path):
    with open(path, "rb") as f:
        return [json.loads(l) for l in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(f), encoding="utf-8")]


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def ledger(lane):
    return G.read_rows(lane + "/loops/code-snapshot-ledger.jsonl")


def errors(lane):
    return G.read_rows(lane + "/loops/code-snapshot-errors.jsonl")


def shards(lane):
    d = lane + "/code-snapshot/docs"
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def shard_of(lane, repo):
    s = [x for x in shards(lane) if x.startswith(repo.replace("/", "__") + "@") and x.endswith(".zst")]
    return read_shard(lane + "/code-snapshot/docs/" + s[0]) if s else []


def staging_left(lane):
    s = lane + "/code-snapshot/staging"
    return [os.path.join(w, x) for w in (os.listdir(s) if os.path.isdir(s) else []) for x in os.listdir(os.path.join(s, w))]


def quiet_engine(lane, runner, **kw):
    return G.Engine(lane, runner=runner, log=lambda *a: None, **kw)


# ------------------------------------------------------------------ scenarios (each appends (key, label, cond) to res)
def scenario_main(res):
    """a, c, d, e, h, i, l, r, w, s: one rolling run over the licence cases, the per-file case, the residual case, the wall cases and the walltest repo, with non-clean rows mixed into the catalogue."""
    rows = rows_for(GOOD) + bad_rows(); lane = new_lane(rows); run_r = FakeRunner(); GATE.clear()
    eng = quiet_engine(lane, run_r, workers=2)
    code = eng.run()
    led = {r["repo"]: r for r in ledger(lane)}
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    rec("run", "run finishes with exit 0 over the synthetic catalogue (breaks if a repo crashes or a worker dies)", code == 0 and not eng.errors)
    # a) wall commit selection
    c = REPOS["o/walltest"][1]; w = led.get("o/walltest", {})
    rows_w = shard_of(lane, "o/walltest"); by = {r["path"]: r for r in rows_w}
    rec("a1", "a) wall commit = last commit strictly before the wall, not the catalogue tip, not the commit AT the wall (breaks if the tip or a post-wall commit is chosen)", w.get("wall_commit") == c[1] and w.get("catalog_commit_sha") == c[4])
    rec("a2", "a) a file added only after the wall (new_post.py) or AT the wall (exact.py) is not in the output (breaks if post-wall files leak in)", rows_w and "new_post.py" not in by and "exact.py" not in by)
    rec("a3", "a) a post-wall change to existing files leaves the PRE-wall content: a.py 'pre = 1', b.py 'b-prewall' (breaks if blobs come from a later commit)", by.get("a.py", {}).get("text") == "pre = 1\n" and by.get("b.py", {}).get("text") == "b-prewall\n" and not any("post" in r["text"] for r in rows_w))
    rec("a4", "a) every row names its wall commit and blob sha as of that commit; id = repo@wall12:path (breaks if provenance is wrong)",
        rows_w and all(r["wall_commit"] == c[1] and r["spdx"] == "MIT" and r["id"] == "o/walltest@%s:%s" % (c[1][:12], r["path"]) and r["blob_sha"] == git(["rev-parse", "%s:%s" % (c[1], r["path"])], REPOS["o/walltest"][0]) for r in rows_w))
    rec("a5", "a) the file list is the clone's `git ls-tree -r -z <wall commit>` and nothing else: zero gh_api calls, no `ls-tree -l` (it would fetch every blob), no ls-tree of the catalogue tip (breaks if a GitHub answer or the tip's tree is used)",
        run_r.gh_calls == [] and any(("ls-tree -r -z %s" % c[1]) in x for x in run_r.calls) and not any(" ls-tree" in " " + x and (" -l" in x.split("|")[0] or c[4] in x.split("|")[0]) for x in run_r.calls if "ls-tree" in x))
    rec("a6", "a) every ledger row with a wall commit has committer time AND author time strictly < 1667260800 and records both (breaks if the wall is crossed or the author stamp is not kept)",
        all(r["wall_commit_ts"] < WALL and r.get("wall_commit_author_ts", WALL) < WALL for r in led.values() if r["wall_commit"] and not r.get("history_dates_not_monotone")) and w.get("wall_commit_ts") == 1667131200 and w.get("wall_commit_author_ts") == 1667131200)
    # w) the wall over the whole ancestry
    bd = led.get("o/backdated", {}); ad = led.get("o/authordate", {}); ed = led.get("o/edge", {}); rows_e = {r["path"]: r["text"] for r in shard_of(lane, "o/edge")}
    rec("w1", "w) NO DATE WALL (lead 83389): a back-dated tip (committer June) sitting on December history is NOT skipped: files kept, ledger history_dates_not_monotone True, content_date_max = 2022-12-01 (breaks if the repo is excluded again, or if only the chosen commit's stamp is read)",
        bd.get("skipped_reason") is None and bd.get("files_kept", 0) > 0 and bd.get("history_dates_not_monotone") is True and bd.get("content_date_max") == "2022-12-01" and shard_of(lane, "o/backdated") != [])
    rec("w2", "w) NO DATE WALL: a commit with a pre-wall committer time but a post-wall AUTHOR time in the ancestry is kept, flagged history_dates_not_monotone, content_date_max = the author date 2022-12-15 (breaks if author times are not read or the repo is skipped)",
        ad.get("skipped_reason") is None and ad.get("history_dates_not_monotone") is True and ad.get("content_date_max") == "2022-12-15" and shard_of(lane, "o/authordate") != [])
    rec("w4", "w) every kept row of the snapshot form carries the ledger's content_date_max, and a monotone repo (o/edge) records its wall commit day 2022-10-31 with the flag False (breaks if the date is not recorded per row)",
        ed.get("history_dates_not_monotone") is False and ed.get("content_date_max") == "2022-10-31" and all(r.get("content_date_max") == "2022-12-01" for r in shard_of(lane, "o/backdated")) and all(r.get("content_date_max") == "2022-10-31" for r in shard_of(lane, "o/edge")))
    rec("w3", "w) a commit one second before the wall (real git) is the wall commit and its files are kept; the commit AT the wall is not (breaks if the boundary is off by one)",
        ed.get("wall_commit") == REPOS["o/edge"][1][1] and ed.get("wall_commit_ts") == WALL - 1 and rows_e.get("edge.py") == "edge = 1\n" and "post.py" not in rows_e)
    # c) no licence file at the wall commit
    n = led.get("o/nolic", {})
    rec("c1", "c) licence added only after the wall -> skipped whole, reason no_licence_file_at_wall_commit (breaks if the HEAD licence is used)", n.get("skipped_reason") == "no_licence_file_at_wall_commit" and n.get("licence_file_sha") is None)
    rec("c2", "c) the skipped repo writes no docs shard and keeps no files (breaks if a partial shard is left)", shard_of(lane, "o/nolic") == [] and n.get("files_kept") == 0 and n.get("shard") is None)
    # d) licence not MIT at the wall commit
    g = led.get("o/gpl", {}); gsha = git(["rev-parse", "%s:LICENSE" % REPOS["o/gpl"][1][0]], REPOS["o/gpl"][0])
    rec("d1", "d) root licence not MIT at the wall commit (it turned MIT later) -> skipped whole, reason licence_not_mit_at_wall_commit (breaks if the later licence is used)", g.get("skipped_reason") == "licence_not_mit_at_wall_commit")
    rec("d2", "d) the wall-time licence blob sha is recorded and no docs are written for it (breaks if the sha is lost or files leak)", g.get("licence_file_sha") == gsha and shard_of(lane, "o/gpl") == [])
    # l) licence recognition
    rs, mx, am, wr = led.get("o/restricted", {}), led.get("o/mixed", {}), led.get("o/apachemit", {}), led.get("o/wrapped", {})
    rec("l1", "l) MIT text with an added restriction clause is NOT MIT -> skipped, no docs (breaks if a substring match admits it)", rs.get("skipped_reason") == "licence_not_mit_at_wall_commit" and shard_of(lane, "o/restricted") == [])
    rec("l2", "l) a GPL LICENSE beside a COPYING holding MIT text -> every root licence file must be MIT: skipped, reason licence_mixed_at_wall_commit (breaks if the first or any MIT match wins)", mx.get("skipped_reason") == "licence_mixed_at_wall_commit" and shard_of(lane, "o/mixed") == [])
    rec("l3", "l) an Apache LICENSE that merely mentions 'MIT License' is NOT MIT -> skipped, no docs (breaks if the phrase alone counts)", am.get("skipped_reason") == "licence_not_mit_at_wall_commit" and shard_of(lane, "o/apachemit") == [])
    rec("l4", "l) the real MIT text re-wrapped, with curly quotes, a 'The MIT License (MIT)' title and two copyright lines is still recognised and kept (breaks if the matcher is too literal)",
        wr.get("skipped_reason") is None and sorted(r["path"] for r in shard_of(lane, "o/wrapped")) == ["LICENSE.md", "a.py"])
    # e) per-file step
    p = led.get("o/perfile", {}); rows_p = shard_of(lane, "o/perfile")
    rec("e1", "e) binary (NUL), invalid UTF-8 (its own class), other-licence header, generated, over-long line, .ipynb and two non-MIT-LICENSE subtrees (GPL, and Apache mentioning MIT) are dropped, each counted under its own reason (breaks if a drop is missed or mislabelled)",
        p.get("files_dropped") == dict(binary=1, invalid_utf8=1, other_licence_header=1, generated=1, long_line=1, ipynb=1, subtree_non_mit_licence=2))
    rec("e2", "e) the clean file and the MIT-licensed subtree file are kept, nothing else (breaks if a dropped file leaks or a clean one is lost)", sorted(r["path"] for r in rows_p) == ["good.py", "sub2/y.py"] and p.get("files_kept") == 2)
    rec("e3", "e) bytes_kept equals the kept text bytes; ledger carries every spec field (breaks if the receipt is incomplete)",
        p.get("bytes_kept") == sum(len(r["text"].encode()) for r in rows_p) and {"repo", "catalog_commit_sha", "wall_commit", "wall_commit_ts", "licence_file_sha", "bytes_kept", "files_kept", "files_dropped", "skipped_reason", "fetch_s", "total_s", "ts"} <= set(p)
        and p.get("skipped_reason") is None and p.get("fetch_s") >= 0 and p.get("total_s") > 0 and "late.py" not in {r["path"] for r in rows_p})
    # r) residual
    rec("r1", "r) per-file and per-repo accounting: tree_entries == kept + sum(dropped) + sum(ineligible) for every repo that reached the file step; perfile has 18 entries (breaks if entries are skipped uncounted)",
        p.get("tree_entries") == 18 and all(r["tree_entries"] == r["files_kept"] + sum(r["files_dropped"].values()) + sum(r["ineligible"].values()) for r in led.values() if r.get("tree_entries") and not r["skipped_reason"] in ("licence_not_mit_at_wall_commit", "licence_mixed_at_wall_commit", "no_licence_file_at_wall_commit")))
    rec("r2", "r) a repo with a symlink, a submodule, a .png and a vendor/ file reports each class in `ineligible` and keeps only the README (breaks if symlinks / submodules / filtered files vanish uncounted)",
        led.get("o/residual", {}).get("ineligible") == dict(extension=2, symlink=1, submodule=1, skip_dir=1) and led.get("o/residual", {}).get("tree_entries") == 6 and [r["path"] for r in shard_of(lane, "o/residual")] == ["README.md"])
    rec("r3", "r) the perfile residual: licence files and the .png (extension 5), vendor/ (skip_dir 1), the empty file (empty 1) and the 1.1 MB json (too_large 1) are counted as ineligible, sizes judged on the fetched bytes (breaks if the size rule is dropped or the class is lost)",
        p.get("ineligible") == dict(extension=5, skip_dir=1, empty=1, too_large=1))
    # s) source class / scan state / rules version
    rec("s1", "s) source_class is a real field in every shard row and every ledger row; ledger rows carry scan_state NOT_SCANNED and the rules_version (breaks if the label lives only in a docstring)",
        rows_p and all(r.get("source_class") == SOURCE_CLASS for r in rows_p + rows_w) and all(r.get("source_class") == SOURCE_CLASS and r.get("scan_state") == "NOT_SCANNED" and r.get("rules_version") for r in led.values()))
    # h) staging removal
    stage = lane + "/code-snapshot/staging"; rem = G.read_rows(lane + "/loops/code-snapshot-removes.jsonl")
    rec("h1", "h) every repo's staging dir is gone after the run (breaks if clones pile up on B:)", staging_left(lane) == [])
    rec("h2", "h) one removal receipt per cloned repo, inside the staging tree, with bytes and the authority (breaks if a removal is unreceipted or outside)",
        len(rem) == len(GOOD) and all(r["path"].replace("\\", "/").lower().startswith(stage.replace("\\", "/").lower() + "/") and r["bytes"] > 0 and r["authority"] == "lead 82956" for r in rem) if rem else False)
    # i) selection
    sel = {r["full_name"] for r in G.select_repos(lane + "/catalog/gh-mit-candidates.jsonl")}
    rec("i1", "i) rows without every clean signal, or not MIT, are never selected (breaks if a flag is ignored)", sel == set(GOOD) | {"o/huge", "o/nosize"})
    dfr = {r["repo"]: r for r in G.read_rows(lane + "/loops/code-snapshot-deferred.jsonl")}
    rec("i2", "i) no git or gh call was made for any unselected or deferred repo; over-cap and size_kb-missing repos get a deferred row naming the reason, never a clone (breaks if a skipped row reaches the network or a missing size reserves a guess)",
        not any(run_r.touched(x) for x in ("o/notest", "o/apache", "o/forked", "o/archived", "o/awesome", "o/stale", "o/nosignals", "o/noci", "o/huge", "o/nosize")) and eng.deferred == 2 and len(led) == len(GOOD)
        and dfr.get("o/huge", {}).get("reason") == "need_over_staging_cap" and dfr.get("o/nosize", {}).get("reason") == "size_kb_missing")
    rec("g0", "the shard write and every clone ask the write gate with the predicted need (breaks if a bulk write skips reserve_plan.write_gate)",
        any(w.startswith("gh_snapshot_fetch shard ") and nb > 0 for w, nb in GATE) and sum(1 for w, nb in GATE if w.startswith("gh_snapshot_fetch clone ")) == len(GOOD))
    return lane, led, run_r


def scenario_hard(res):
    """b: a wall commit at or after the wall raises, through the Runner; the abort leaves a durable row."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))

    class Late(G.Runner):
        def __init__(self, ts): self.ts = ts
        def git(self, args, cwd=None, input=None):
            if args[0] == "rev-list": return b"c" * 40 + b"\n"
            if args[:2] == ["show", "-s"]: return ("%d\n" % self.ts).encode()
            raise AssertionError(args)
    for k, ts, bad in (("b1", WALL + 1, True), ("b2", WALL, True), ("b3", WALL + 86400 * 400, True), ("b4", WALL - 1, False)):
        try:
            r = G.select_wall_commit(Late(ts), "x", "y"); raised = False
        except G.WallViolation:
            raised = True
        rec(k, "b) committer time %s the wall %s (breaks if the hard check is not strict or missing)" % ("at/after" if bad else "one second before", "raises WallViolation" if bad else "is accepted"), raised == bad)

    class ViolatingRemote(FakeRunner):
        def git(self, args, cwd=None, input=None):
            if args[0] == "show" and args[1:2] == ["-s"]: self.calls.append("show"); return ("%d\n" % (WALL + 5)).encode()
            return super().git(args, cwd, input)
    lane = new_lane(rows_for(["o/walltest"])); r = ViolatingRemote(); eng = quiet_engine(lane, r, workers=1); code = eng.run()
    rec("b5", "b) through the whole run a post-wall wall commit aborts the run (exit 4), writes no ledger row, no docs shard and leaves no staging dir (breaks if the engine continues with it)",
        code == 4 and ledger(lane) == [] and shards(lane) == [] and staging_left(lane) == [] and not [c for c in r.calls if "ls-tree" in c])
    rec("b6", "b) the abort leaves a DURABLE row (errors file, kind wall_violation, repo and commit named) (breaks if a wall violation exists only on stderr)",
        any(e.get("kind") == "wall_violation" and e.get("repo") == "o/walltest" for e in errors(lane)))


def scenario_resume(res):
    """f: finished repos are never touched again; a repo without a ledger row is redone (stale staging dir included) and its shard is not duplicated; the resume key is (repo, catalogue commit, rules version)."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    lane = new_lane(rows_for(CORE))
    assert quiet_engine(lane, FakeRunner(), workers=2).run() == 0
    before = {s: sha_file(lane + "/code-snapshot/docs/" + s) for s in shards(lane)}; led0 = ledger(lane)
    r2 = FakeRunner(forbid=CORE); code2 = quiet_engine(lane, r2, workers=2).run()
    rec("f1", "f) second run makes ZERO git/gh calls for repos already in the ledger, kept or skipped (breaks if a done repo is fetched again)", code2 == 0 and r2.calls == [])
    rec("f2", "f) the docs shards are byte-identical and the ledger has no new rows after the second run (breaks if a shard is rewritten or duplicated)",
        before == {s: sha_file(lane + "/code-snapshot/docs/" + s) for s in shards(lane)} and len(ledger(lane)) == len(led0) == 4)
    keep = [r for r in led0 if r["repo"] != "o/perfile"]
    with open(lane + "/loops/code-snapshot-ledger.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(r) + "\n" for r in keep))
    stale = lane + "/code-snapshot/staging/w0/o__perfile-" + REPOS["o/perfile"][1][-1][:12]; os.makedirs(stale + "/junk")
    with open(stale + "/junk/x", "wb") as f:
        f.write(b"half a clone")
    r3 = FakeRunner(forbid=["o/walltest", "o/nolic", "o/gpl"]); code3 = quiet_engine(lane, r3, workers=1).run()
    rows_p = shard_of(lane, "o/perfile")
    rec("f3", "f) a repo with no ledger row is redone from scratch (calls made, stale staging dir cleared first, a new terminal row written) (breaks if a crashed repo is skipped or the stale dir blocks the clone)",
        code3 == 0 and r3.calls and len([r for r in ledger(lane) if r["repo"] == "o/perfile"]) == 1 and len(ledger(lane)) == 4 and not os.path.exists(stale) and staging_left(lane) == [])
    rec("f4", "f) the redone shard holds each kept file once (replaced, not appended), no .part left (breaks if rows are duplicated)",
        sorted(r["path"] for r in rows_p) == ["good.py", "sub2/y.py"] and not [s for s in shards(lane) if s.endswith(".part")] and len(shards(lane)) == 2)
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        c_st = G.main(["status"], lane=lane)
    st = json.loads(buf.getvalue())
    c_run = G.main(["run", "--workers", "1"], runner=FakeRunner(forbid=CORE), lane=lane)
    rec("f5", "f) the CLI: `status` reports 4 of 4 repos done with the terminal states, `run` on a finished catalogue exits 0 (breaks if the CLI wiring or the status numbers are wrong)",
        c_st == 0 and st["selected"] == 4 and st["in_ledger"] == 4 and st["remaining"] == 0 and st["terminal_states"].get("kept") == 2 and c_run == 0)
    # resume key: another rules version, or another catalogue commit, is NOT done
    rows = ledger(lane)
    for r in rows:
        if r["repo"] == "o/walltest": r["rules_version"] = "d3-r0-old"
        if r["repo"] == "o/nolic": r["catalog_commit_sha"] = "f" * 40
    with open(lane + "/loops/code-snapshot-ledger.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    r4 = FakeRunner(forbid=["o/gpl", "o/perfile"]); code4 = quiet_engine(lane, r4, workers=1).run()
    rec("f6", "f) the resume key is (repo, catalogue commit, rules version): a row from an older rules version, or for another catalogue commit, does not count as done and the repo is redone; the others are not touched (breaks if the repo name alone is the key)",
        code4 == 0 and r4.touched("o/walltest") and r4.touched("o/nolic") and not r4.touched("o/gpl") and not r4.touched("o/perfile"))


class Clock:
    def __init__(self): self.tl = threading.local()
    def __call__(self): return getattr(self.tl, "t", 0.0)
    def advance(self, s): self.tl.t = self.__call__() + s


class StepRunner(G.Runner):
    """Every git / gh call advances the calling thread's fake clock by `step`; each repo answers 'no commit before the wall' (3 calls)."""

    def __init__(self, clk, step): self.clk, self.step, self.calls = clk, step, []
    def git(self, args, cwd=None, input=None): self.calls.append(args[0]); self.clk.advance(self.step); return b""
    def gh_api(self, path): self.calls.append(path); self.clk.advance(self.step); return {}


def scenario_stop(res):
    """g: the timing stop rule."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    rows = [cat_row("o/r%03d" % i, "file:///nowhere/r%03d" % i, "%040x" % (i + 1)) for i in range(200)]
    lane = new_lane(rows); clk = Clock(); r = StepRunner(clk, 1000.0); eng = quiet_engine(lane, r, workers=4, clock=clk); code = eng.run()
    stop = json.load(open(lane + "/loops/code-snapshot-STOP.json")) if os.path.exists(lane + "/loops/code-snapshot-STOP.json") else {}
    nled = len(ledger(lane))
    rec("g1", "g) 50 finished repos with mean total_s 3000 predict 31.25 h > 8 h: STOP file written with the numbers, workers stop, exit code 3 (breaks if the rule never fires or exits 0)",
        code == 3 and stop.get("predicted_hours") == 31.25 and stop.get("mean_total_s") == 3000.0 and stop.get("repos_remaining") == 150 and stop.get("workers") == 4 and stop.get("finished") == 50)
    rec("g2", "g) the run stopped early: at least 50 and far fewer than 200 repos have rows (breaks if workers keep going after the stop)", 50 <= nled <= 54)
    r2 = StepRunner(clk, 1000.0); code2 = quiet_engine(lane, r2, workers=4, clock=clk).run()
    r3 = StepRunner(clk, 0.0); code3 = quiet_engine(lane, r3, workers=4, clock=clk).run(ignore_stop=True)
    rec("g3", "g) with the STOP file present a new run refuses (exit 3) without any call; --ignore-stop really continues: calls are made, the remaining repos finish (200 rows) and the exit is 0 (breaks if the stop does not stick or the override does nothing)",
        code2 == 3 and r2.calls == [] and code3 == 0 and r3.calls and len(ledger(lane)) == 200)
    lane2 = new_lane(rows); clk2 = Clock(); eng2 = quiet_engine(lane2, StepRunner(clk2, 1.0), workers=4, clock=clk2); code_ok = eng2.run()
    rec("g4", "g) the same 200 repos at 3 s each predict 0.03 h < 8 h: the run continues to the end, no STOP file, exit 0 (breaks if the rule fires on a fast run)",
        code_ok == 0 and len(ledger(lane2)) == 200 and not os.path.exists(lane2 + "/loops/code-snapshot-STOP.json") and eng2.stop_rule and eng2.stop_rule.get("fired") is False and eng2.stop_rule["predicted_hours"] < 0.1)


def scenario_staging(res):
    """h: removal stays inside the staging tree, receipt first; budget; gate."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    lane = new_lane([]); p = G.Paths(lane); os.makedirs(p.stage + "/w0/ok"); outside = tempfile.mkdtemp(prefix="outside_", dir=TMP)
    with open(outside + "/keep.txt", "w") as f:
        f.write("must survive")
    with open(p.stage + "/w0/ok/a", "w") as f:
        f.write("12345")
    raised = []
    for target in (outside, p.stage, p.stage + "/../" + os.path.basename(outside), p.stage + "/w0/../../../" + os.path.basename(outside)):
        try:
            G.remove_staging(target, p.stage, p.removes, "x"); raised.append(False)
        except G.StagingEscape:
            raised.append(True)
    rec("h3", "h) a removal target outside the staging tree, the tree itself, or reached through .. raises StagingEscape and removes nothing (breaks if the prefix is not asserted)",
        all(raised) and os.path.exists(outside + "/keep.txt") and os.path.isdir(p.stage) and not os.path.exists(p.removes))
    seen = []; real_rmtree = G.shutil.rmtree

    def spy(path, *a, **k):
        seen.append(len(G.read_rows(p.removes))); return real_rmtree(path, *a, **k)
    G.shutil.rmtree = spy
    try:
        n = G.remove_staging(p.stage + "/w0/ok", p.stage, p.removes, "x/y")
    finally:
        G.shutil.rmtree = real_rmtree
    rr = G.read_rows(p.removes)
    rec("h4", "h) a dir inside the staging tree is removed and receipted (bytes, path, authority) (breaks if the receipt is missing)", n == 5 and not os.path.exists(p.stage + "/w0/ok") and len(rr) == 1 and rr[0]["bytes"] == 5 and rr[0]["authority"] == "lead 82956")
    rec("h8", "h) the receipt row is on disk BEFORE the delete starts (breaks if the remove runs first and a crash leaves an unreceipted deletion)", seen == [1])
    rec("h5", "h) the resident staging cap is 5 GiB and the per-repo need is size_kb x 1024 x 0.25 + 64 MiB (breaks if the budget numbers drift)", G.BUDGET_CAP == 5 << 30 and G.predicted_need(dict(size_kb=1024)) == 262144 + (64 << 20))
    b = G.Budget(100); stop = threading.Event(); b.acquire(60, stop); got = []
    t = threading.Thread(target=lambda: got.append(bool(b.acquire(60, stop)))); t.start(); time.sleep(0.4)
    waited = not got; b.release(60); t.join(5)
    rec("h6", "h) a second repo whose need would pass the shared cap waits until the first releases (breaks if workers overshoot the 5 GiB resident budget)", waited and got == [True] and b.used == 60)
    lane2 = new_lane(rows_for(["o/perfile"])); r = FakeRunner(); GATE_RESULT[0] = False
    try:
        eng = quiet_engine(lane2, r, workers=1); code = eng.run()
    finally:
        GATE_RESULT[0] = True
    rec("h7", "h) when write_gate refuses (B: under the floor) the run exits 2 with no clone, no shard and no ledger row, and the stop leaves a durable row (errors file, kind disk_floor_stop) (breaks if a write happens below the floor or the stop is silent)",
        code == 2 and r.calls == [] and shards(lane2) == [] and ledger(lane2) == [] and any(e.get("kind") == "disk_floor_stop" for e in errors(lane2)))


def scenario_budget(res):
    """s/u: the staging bound is MEASURED, the gate sees budget in use + need, a blob that cannot be read is an error and is retried."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    old = G.NEED_BASE; G.NEED_BASE = 1000
    try:
        row = rows_for(["o/perfile"], size_kb=1)                                       # understated: the clone is ~1.2 MB, the reservation 1.2 KB
        lane = new_lane(row); eng = quiet_engine(lane, FakeRunner(), workers=1, budget_cap=300 << 20); code = eng.run(); led = ledger(lane)
        rec("m1", "m) an understated size_kb: the staging dir is measured after the clone and each fetch chunk and the reservation is RAISED to what is on disk (+ one chunk) under the cap: the run still finishes, budget peak and ledger staging_peak_bytes show the measured size (breaks if the bound is only predicted)",
            code == 0 and len(led) == 1 and getattr(eng.budget, "peak", 0) >= (64 << 20) and led[0].get("staging_peak_bytes", 0) > 700_000 and eng.budget.used == 0)
        lane2 = new_lane(row); r2 = FakeRunner(); eng2 = quiet_engine(lane2, r2, workers=1, budget_cap=10 << 20); code2 = eng2.run()
        rec("m2", "m) when the measured size cannot fit under the cap the repo ends as an error row staging_over_budget: no ledger row, no shard, staging removed, run exits 1 (breaks if the cap is exceeded or the repo is silently kept)",
            code2 == 1 and ledger(lane2) == [] and [s for s in shards(lane2) if not s.endswith(".part")] == [] and staging_left(lane2) == [] and any(e.get("kind") == "staging_over_budget" for e in errors(lane2)))
    finally:
        G.NEED_BASE = old
    lane3 = new_lane(rows_for(["o/walltest"])); GATE.clear(); eng3 = quiet_engine(lane3, FakeRunner(), workers=1); eng3.budget.used = 5_000_000
    try:
        eng3.process_repo(rows_for(["o/walltest"])[0], 0)
    except Exception:
        pass
    need = G.predicted_need(rows_for(["o/walltest"])[0]); cg = [nb for w, nb in GATE if w.startswith("gh_snapshot_fetch clone ")]
    rec("m3", "m) the clone's write gate is asked for the budget IN USE plus this repo's need, not the repo's need alone (breaks if four workers can each pass the gate against the same free space)", cg == [5_000_000 + need])
    # blob unavailable -> error row, retried on resume
    lane4 = new_lane(rows_for(["o/perfile"])); victim = git(["rev-parse", "%s:good.py" % REPOS["o/perfile"][1][0]], REPOS["o/perfile"][0])

    class Hole(FakeRunner):
        def git(self, args, cwd=None, input=None):
            if args[:2] == ["cat-file", "--batch"] and input and victim in input.decode().split():
                rest = [s for s in input.decode().split() if s != victim]
                out = super().git(args, cwd, ("\n".join(rest) + "\n").encode()) if rest else b""
                return out + (victim + " missing\n").encode()
            return super().git(args, cwd, input)
    eng4 = quiet_engine(lane4, Hole(), workers=1); code4 = eng4.run()
    first_ok = code4 == 1 and ledger(lane4) == [] and [s for s in shards(lane4) if not s.endswith(".part")] == [] and any(e.get("kind") == "blob_unavailable" for e in errors(lane4))
    code5 = quiet_engine(lane4, FakeRunner(), workers=1).run(); led4 = ledger(lane4)
    rec("u1", "u) a wanted blob that cannot be read makes an error row blob_unavailable (no ledger row, no shard), and a rerun redoes the repo and finishes it (breaks if the loss is folded into a finished row and never retried)",
        first_ok and code5 == 0 and len(led4) == 1 and led4[0]["files_kept"] == 2)


def run_all(res):
    for name, fn, keys in SCEN:
        mine = []
        try:
            fn(mine)
        except Exception as e:
            mine.append(("crash:" + name, "scenario %s crashed: %s: %s" % (name, type(e).__name__, str(e)[:120]), False))
        have = {k for k, l, c in mine}
        res.extend(mine)
        res.extend((k, "(scenario %s did not reach this check)" % name, False) for k in keys if k not in have)


SCEN = [("main", scenario_main, ["run", "a1", "a2", "a3", "a4", "a5", "a6", "w1", "w2", "w3", "c1", "c2", "d1", "d2", "l1", "l2", "l3", "l4", "e1", "e2", "e3", "r1", "r2", "r3", "s1", "h1", "h2", "i1", "i2", "g0"]),
        ("hard", scenario_hard, ["b1", "b2", "b3", "b4", "b5", "b6"]), ("resume", scenario_resume, ["f1", "f2", "f3", "f4", "f5", "f6"]), ("stop", scenario_stop, ["g1", "g2", "g3", "g4"]),
        ("staging", scenario_staging, ["h3", "h4", "h5", "h6", "h7", "h8"]), ("budget", scenario_budget, ["m1", "m2", "m3", "u1"])]


def mutant(name, patch, keys, scen):
    """Apply `patch` (module attributes) to gh_snapshot_fetch, re-run the named scenarios, require one of the `keys` checks to FAIL (or the run to blow up)."""
    saved = {k: getattr(G, k) for k in patch}
    for k, v in patch.items():
        setattr(G, k, v)
    res = []
    try:
        for nm, fn, ks in SCEN:
            if nm in scen:
                fn(res)
        bitten = any(not c for k, l, c in res if k in keys)
    except Exception:
        bitten = True
    finally:
        for k, v in saved.items():
            setattr(G, k, v)
    chk("mutant %s is caught by checks %s" % (name, "/".join(keys)), bitten)


if __name__ == "__main__":
    res = []; t0 = time.time(); run_all(res)
    for k, l, c in res:
        chk("%s %s" % (k, l), c)
    print("FAILCOUNT %d of %d" % (sum(1 for k, l, c in res if not c), len(res)))
    if os.environ.get("SNAP_NO_MUTANTS") != "1":
        mutant("wall = catalogue tip", dict(select_wall_commit=lambda r, c, s: (s, WALL - 1)), ("a1", "a2", "a3"), ("main",))
        mutant("hard check removed", dict(WALL_TS=1 << 40), ("b1", "b2", "b3"), ("hard",))
        mutant("licence always MIT", dict(is_mit=lambda t: True), ("d1", "l1", "l2", "l3"), ("main",))
        mutant("per-file step off", dict(classify=lambda p, b: (None, b.decode("utf-8", "replace"))), ("e1", "e2"), ("main",))
        mutant("staging never removed", dict(remove_staging=lambda *a, **k: 0), ("h1", "h2"), ("main",))
        mutant("stop rule off", dict(STOP_HOURS=1e9), ("g1",), ("stop",))
        mutant("ancestry check off", dict(history_times=lambda *a, **k: []), ("w1", "w2"), ("main",))
        mutant("staging never measured", dict(measure_staging=lambda *a, **k: None), ("m1", "m2"), ("budget",))
    print("elapsed %.1f s" % (time.time() - t0))
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

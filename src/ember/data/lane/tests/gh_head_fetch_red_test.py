# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for the HEAD form of gh_snapshot_fetch (D3, lead 83076 / 83077 / 83080 / 83135). Offline: synthetic git repos (real git, file:// remotes) built in a temp tree, every git call through the injectable Runner,
the lane root a temp dir, reserve_plan.write_gate stubbed (the synthetic-repo helpers and the stub come from tests/gh_snapshot_fetch_red_test.py, which this file imports; that file's own red must keep passing unchanged).
Covers: the tree read is the catalogue commit (no --before, no wall commit, no ancestry check, no no_pre_wall_history skip), the three _at_head licence reasons, agent_attribution (trailer / bot / instruction file / none_stated, never from code
style, dependabot is not an agent) on the ledger row and every shard row, separate ledger + resume key, one clone retry, the 100 MiB tranche cap, staging accounting, the timing report at 100 repos and the 8 h STOP, priority, the CLI.
Mutants at the end re-run the scenarios against a deliberately broken module and require the named checks to FAIL.
Run: python tests/gh_head_fetch_red_test.py   (exit 0 = ALL PASS; HEAD_NO_MUTANTS=1 skips the mutants)"""
import os, sys, re, io, json, time, calendar, tempfile, threading, subprocess, pathlib, collections, contextlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, HERE + "/tests")
import gh_snapshot_fetch_red_test as S                    # synthetic-git helpers + the write_gate stub + the forced temp lane root
import gh_snapshot_fetch as G

ok = True
SOURCE_CLASS = "post-wall public code"                    # literals: mutants patch the module constants, the test must not follow them
RULES = "d3h-r1"
LP_CALLS = []
REAL_LP = G.lower_priority


def _spy_lp(*a, **k):
    LP_CALLS.append(1); return True                         # the test process itself is never lowered


G.lower_priority = _spy_lp


def chk(n, c):
    global ok
    ok = ok and bool(c); print(("PASS " if c else "FAIL ") + n)


def epoch(iso):
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


# ------------------------------------------------------------------ synthetic remotes (with commit messages and identities)
HR = {}


def hrepo(name, commits):
    """commits: [dict(date=iso, files={path: bytes}, msg='c', a=(name, email), c=(name, email))] oldest first -> registered in HR as (dir, [shas])."""
    d = "%s/hremotes/%s" % (S.TMP, name.replace("/", "__")); os.makedirs(d)
    S.git(["init", "-q", "-b", "main"], d)
    for k, v in (("uploadpack.allowFilter", "true"), ("uploadpack.allowAnySHA1InWant", "true")):
        S.git(["config", k, v], d)
    shas = []
    for c in commits:
        for p, b in c.get("files", {}).items():
            fp = os.path.join(d, p); os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "wb") as f:
                f.write(b)
        S.git(["add", "-A"], d)
        an, ae = c.get("a", ("t", "t@example.invalid")); cn, ce = c.get("c", ("t", "t@example.invalid"))
        S.git(["commit", "-q", "--allow-empty", "-m", c.get("msg", "c")], d, env={"GIT_COMMITTER_DATE": c["date"], "GIT_AUTHOR_DATE": c["date"], "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae, "GIT_COMMITTER_NAME": cn, "GIT_COMMITTER_EMAIL": ce})
        shas.append(S.git(["rev-parse", "HEAD"], d))
    HR[name] = (d, shas)
    return HR[name]


MIT, GPL = S.MIT.encode(), S.GPL.encode()
BOT = ("copilot-swe-agent[bot]", "198982749+copilot-swe-agent[bot]@users.noreply.github.com")
D1, D2, D3 = "2023-02-01T00:00:00Z", "2023-06-01T00:00:00Z", "2024-01-15T00:00:00Z"
hrepo("h/postwall", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}), dict(date=D2, files={"b.py": b"b = 2\n"})])              # every commit after the wall: no pre-wall history at all
hrepo("h/lateadd", [dict(date="2021-03-01T00:00:00Z", files={"a.py": b"a = 1\n"}), dict(date=D2, files={"LICENSE": MIT})])                 # licence only in the latest commit
hrepo("h/nolic", [dict(date=D1, files={"a.py": b"a = 1\n"})])
hrepo("h/gpl", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}), dict(date=D2, files={"LICENSE": GPL})])                        # MIT earlier, not MIT at head
hrepo("h/mixed", [dict(date=D1, files={"LICENSE": GPL, "COPYING": MIT, "a.py": b"a = 1\n"})])
hrepo("h/trailer", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}),
                    dict(date=D2, files={"a.py": b"a = 2\n"}, msg="fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>"),
                    dict(date=D3, files={"a.py": b"a = 3\n"}, msg="more\n\nco-authored-by: GitHub Copilot <copilot@github.com>\nCo-authored-by: Claude Opus <noreply@anthropic.com>")])
hrepo("h/bot", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}), dict(date=D2, files={"a.py": b"a = 2\n"}, a=BOT, c=BOT), dict(date=D3, files={"a.py": b"a = 3\n"}, a=BOT),
                dict(date=D3, files={"a.py": b"a = 4\n"}, a=("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"), c=("GitHub", "noreply@github.com"))])
hrepo("h/instr", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n", "AGENTS.md": b"# agents\n", "CLAUDE.md": b"x\n", "GEMINI.md": b"g\n", ".cursorrules": b"r\n", ".github/copilot-instructions.md": b"c\n",
                                       ".cursor/rules/a.mdc": b"m\n", "pkg/AGENTS.md": b"p\n", "notes/agents.md": b"lower case is not an instruction file\n"})])
hrepo("h/none", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"# Generated with Claude Code\n# Co-Authored-By: Claude <noreply@anthropic.com>\ndef f():\n    '''Compute f. Written by an AI assistant.'''\n    return 1\n"}), dict(date=D2, files={"b.py": b"b = 1\n"}, msg="human commit")])
hrepo("h/robots", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}, a=("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com")),
                   dict(date=D2, files={"a.py": b"a = 2\n"}, a=("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"), c=("GitHub", "noreply@github.com")),
                   dict(date=D3, files={"a.py": b"a = 3\n"}, a=("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"))])
hrepo("h/perfile", [dict(date=D1, files={"LICENSE": MIT, "good.py": b"def f():\n    return 1\n", "bin.py": b"a\x00b\n", "apache.py": b"# Licensed under the Apache License, Version 2.0\nx = 1\n", "gen.go": b"// Code generated by tool. DO NOT EDIT.\npackage x\n",
                                       "long.py": b"x = '" + b"a" * 20001 + b"'\n", "nb.ipynb": b"{}\n", "sub/LICENSE": GPL, "sub/x.py": b"y = 2\n", "vendor/v.py": b"v = 1\n", "empty.py": b"", "pic.png": b"\x89PNG\x00"})])
hrepo("h/capedge", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"})])
hrepo("h/flaky", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"})])
hrepo("h/dead", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"})])
hrepo("h/gone", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"})])
hrepo("h/missing", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"})])
hrepo("h/human", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}, a=("Devin Smith", "devin@example.invalid"), c=("Claude Monet", "claude@example.invalid")),
                  dict(date=D2, files={"a.py": b"a = 2\n"}, a=("Gemini Rossi", "gemini@example.invalid"), c=("Cursor Lee", "cursor@example.invalid"))])     # humans whose first name is an agent word
hrepo("h/anthro", [dict(date=D1, files={"LICENSE": MIT, "a.py": b"a = 1\n"}, a=("Dev", "noreply@anthropic.com"))])      # the agent's own mail identity as author
MAIN = ["h/postwall", "h/lateadd", "h/nolic", "h/gpl", "h/mixed", "h/trailer", "h/bot", "h/instr", "h/none", "h/robots", "h/perfile", "h/capedge"]


def hrow(name, size_kb=10, **extra):
    r = S.cat_row(name, pathlib.Path(HR[name][0]).as_uri(), HR[name][1][-1], size_kb=size_kb); r.update(extra); return r


def tip(name):
    return HR[name][1][-1]


# ------------------------------------------------------------------ lane helpers (head files)
def HL(lane):
    return G.read_rows(lane + "/loops/code-head-ledger.jsonl")


def HE(lane):
    return G.read_rows(lane + "/loops/code-head-errors.jsonl")


def hshard(lane, repo):
    d = lane + "/code-head/docs"
    s = [x for x in (os.listdir(d) if os.path.isdir(d) else []) if x.startswith(repo.replace("/", "__") + "@") and x.endswith(".zst")]
    return S.read_shard(d + "/" + s[0]) if s else []


def hshards(lane):
    d = lane + "/code-head/docs"
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def hstaging_left(lane):
    s = lane + "/code-head/staging"
    return [os.path.join(w, x) for w in (os.listdir(s) if os.path.isdir(s) else []) for x in os.listdir(os.path.join(s, w))]


def heng(lane, runner, **kw):
    return G.Engine(lane, runner=runner, log=lambda *a: None, form="head", **kw)


def ev(row, signal):
    return [e for e in ((row.get("agent_attribution") or {}).get("evidence") or []) if e.get("signal") == signal]


# ------------------------------------------------------------------ scenarios
def scenario_main(res):
    """One rolling head run over every case, with non-clean and over-cap rows mixed into the catalogue."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    over = S.cat_row("h/overcap", "file:///nowhere/overcap", "b" * 40, size_kb=102401)                       # 100 MiB + 1 KB: not tranche 1
    rows = [hrow(n, size_kb=(102400 if n == "h/capedge" else 10)) for n in MAIN] + S.bad_rows() + [over]
    rows[0]["created_at"] = "2023-06-01T00:00:00Z"                                                         # a creation date after the wall must not matter (no created_at pre-filter)
    lane = S.new_lane(rows); run_r = S.FakeRunner(); S.GATE.clear(); eng = heng(lane, run_r, workers=2)
    with contextlib.redirect_stdout(io.StringIO()):
        code = eng.run()
    led = {r["repo"]: r for r in HL(lane)}
    rec("run", "run finishes with exit 0 over the synthetic head catalogue (breaks if a repo crashes, a worker dies or the head form raises)", code == 0 and not eng.errors and eng.fatal is None and len(led) == len(MAIN))
    # head tree, no wall
    pw = led.get("h/postwall", {}); rows_pw = hshard(lane, "h/postwall"); by = {r["path"]: r for r in rows_pw}
    rec("p1", "p) a repo whose every commit is after the wall is KEPT: files from the catalogue commit, no wall commit anywhere in the ledger row or the shard rows (breaks if the pre-wall skip or a wall field comes back)",
        pw.get("skipped_reason") is None and sorted(by) == ["a.py", "b.py"] and not any(k in pw for k in ("wall_commit", "wall_commit_ts", "wall_commit_author_ts")) and not any("wall_commit" in r for r in rows_pw)
        and all(r["head_commit"] == tip("h/postwall") and r["id"] == "h/postwall@%s:%s" % (tip("h/postwall")[:12], r["path"]) and r["spdx"] == "MIT" for r in rows_pw))
    rec("p2", "p) the head ledger row carries form head, head_commit_ts = the catalogue commit's committer time, the catalogue sha, rules version d3h-r1 and scan_state NOT_SCANNED (breaks if the head row is not labelled)",
        pw.get("form") == "head" and pw.get("head_commit_ts") == epoch(D2) and pw.get("catalog_commit_sha") == tip("h/postwall") and pw.get("rules_version") == RULES and pw.get("scan_state") == "NOT_SCANNED" and pw.get("source_class") == SOURCE_CLASS)
    rec("p3", "p) no `rev-list`, no `--before`, no `%ct %at` ancestry log in ANY call; the file list is `ls-tree -r -z <catalogue sha>` of every repo; no gh_api (breaks if a wall commit or the ancestry check is used)",
        not any(re.search(r"rev-list|--before|%ct %at", c) for c in run_r.calls) and all(("ls-tree -r -z %s" % tip(n)) in "\n".join(run_r.calls) for n in MAIN) and run_r.gh_calls == [])
    rec("p4", "p) no ledger row has a pre-wall-form skip (no_pre_wall_history, history_dates_not_monotone, catalog_commit_missing) (breaks if the snapshot skips fire in head form)",
        not [r for r in led.values() if r.get("skipped_reason") in ("no_pre_wall_history", "history_dates_not_monotone", "catalog_commit_missing")])
    la = led.get("h/lateadd", {})
    rec("p5", "p) the tree and the licence are read at the catalogue commit: a licence added only in the latest commit is found, the older tree is not used (breaks if an older commit is read)",
        la.get("skipped_reason") is None and sorted(r["path"] for r in hshard(lane, "h/lateadd")) == ["a.py"] and la.get("tree_entries") == 2 and la.get("licence_file_sha"))
    # licence reasons
    n_, g_, m_ = led.get("h/nolic", {}), led.get("h/gpl", {}), led.get("h/mixed", {})
    rec("c1", "c) licence reasons end _at_head: none -> no_licence_file_at_head, GPL at head (MIT earlier) -> licence_not_mit_at_head, GPL + MIT -> licence_mixed_at_head, no docs written (breaks if a reason keeps the wall-commit suffix or a skipped repo leaks files)",
        n_.get("skipped_reason") == "no_licence_file_at_head" and g_.get("skipped_reason") == "licence_not_mit_at_head" and m_.get("skipped_reason") == "licence_mixed_at_head"
        and not [r for r in led.values() if "wall_commit" in str(r.get("skipped_reason"))] and all(hshard(lane, x) == [] for x in ("h/nolic", "h/gpl", "h/mixed")))
    # attribution
    tr, bt, ins, no, rb = led.get("h/trailer", {}), led.get("h/bot", {}), led.get("h/instr", {}), led.get("h/none", {}), led.get("h/robots", {})
    tre = {e["family"]: e for e in ev(tr, "trailer")}
    rec("a1", "a) trailer: Co-Authored-By lines (any case) naming Claude / noreply@anthropic.com and Copilot -> state attributed, one trailer entry per family with the commit count (claude 2, copilot 1), where `git log` (breaks if trailers are not read or counted per commit)",
        (tr.get("agent_attribution") or {}).get("state") == "attributed" and tre.get("claude", {}).get("count") == 2 and tre.get("copilot", {}).get("count") == 1 and set(tre) == {"claude", "copilot"} and all(e["where"] == "git log" for e in tre.values()))
    be = ev(bt, "bot_contributor")
    rec("a2", "a) bot_contributor: a copilot-swe-agent[bot] author/committer on 2 commits -> attributed with count 2 and the bot name; the same commits are NOT also counted as trailers (breaks if bot identities are missed or double counted)",
        (bt.get("agent_attribution") or {}).get("state") == "attributed" and len(be) == 1 and be[0]["count"] == 2 and "copilot-swe-agent[bot]" in be[0]["names"] and ev(bt, "trailer") == [] and be[0]["where"] == "git log")
    ie = ev(ins, "instruction_file")
    rec("a3", "a) instruction_file: AGENTS.md / CLAUDE.md / GEMINI.md / .cursorrules / .github/copilot-instructions.md / .cursor/rules/* at any depth -> attributed, count 7, `where` the first 5 sorted paths; notes/agents.md (lower case) is not one (breaks if a pattern is missed, the cap is off or the match is too loose)",
        (ins.get("agent_attribution") or {}).get("state") == "attributed" and len(ie) == 1 and ie[0]["count"] == 7 and len(ie[0]["where"]) == 5 and ie[0]["where"] == sorted(ie[0]["where"])
        and ".cursor/rules/a.mdc" in ie[0]["where"] and "AGENTS.md" in ie[0]["where"] and not any("notes/" in p for p in ie[0]["where"]) and ev(ins, "trailer") == [] and ev(ins, "bot_contributor") == [])
    rec("a4", "a) none_stated: a repo with human commits and code whose text says 'Generated with Claude Code' / 'Co-Authored-By: Claude' inside a FILE is none_stated with empty evidence (breaks if the attribution is inferred from code or file content)",
        no.get("agent_attribution") == dict(state="none_stated", evidence=[]) and [r["path"] for r in hshard(lane, "h/none")] == ["a.py", "b.py"])
    rec("a5", "a) dependabot, renovate and github-actions are not agents: a repo of only their commits is none_stated; the dependabot commit in the bot repo adds nothing to its bot count (breaks if every [bot] counts)",
        rb.get("agent_attribution") == dict(state="none_stated", evidence=[]) and be and be[0]["count"] == 2)
    rec("a6", "a) every ledger row that reached the tree carries agent_attribution (a dict with state and evidence), skipped-by-licence repos included; every shard row of every repo carries the repo's agent_attribution and source_class (breaks if the label is only on one of them)",
        all(isinstance(r.get("agent_attribution"), dict) and r["agent_attribution"].get("state") in ("attributed", "none_stated") and isinstance(r["agent_attribution"].get("evidence"), list) for r in led.values())
        and all(r.get("source_class") == SOURCE_CLASS for r in led.values())
        and all(r["agent_attribution"] == led[n]["agent_attribution"] and r["source_class"] == SOURCE_CLASS for n in MAIN for r in hshard(lane, n)) and sum(len(hshard(lane, n)) for n in MAIN) > 15)
    rec("a7", "a) the commit log read is capped: every attribution runs `git log -n 20000` over the catalogue sha; history_commits is the number read (trailer repo 3) and history_truncated False (breaks if the log is unbounded or the counts are lost)",
        all(("log -n 20000 --format=" in "\n".join(c for c in run_r.calls if tip(n) in c.split("|")[0])) for n in MAIN) and tr.get("history_commits") == 3 and tr.get("history_truncated") is False and bt.get("history_commits") == 4)
    # ledger / output
    rec("l1", "l) the ledger row = snapshot row minus the wall fields plus form / source_class / head_commit_ts / agent_attribution / scan_state (breaks if a spec field is missing or a wall field remains)",
        {"repo", "catalog_commit_sha", "head_commit_ts", "history_commits", "history_truncated", "licence_file_sha", "tree_entries", "bytes_kept", "files_kept", "files_dropped", "ineligible", "skipped_reason", "fetch_s", "shard", "total_s", "ts", "staging_peak_bytes",
         "rules_version", "form", "source_class", "agent_attribution", "scan_state"} <= set(pw) and not [k for r in led.values() for k in r if k.startswith("wall_commit")])
    rec("o1", "o) output under code-head/: shard <owner>__<name>@<sha12>.jsonl.zst, ledger loops/code-head-ledger.jsonl; nothing under code-snapshot/ and no snapshot ledger (breaks if the head form writes into the snapshot form's files)",
        "h__postwall@%s.jsonl.zst" % tip("h/postwall")[:12] in hshards(lane) and pw.get("shard") == "h__postwall@%s.jsonl.zst" % tip("h/postwall")[:12] and not os.path.exists(lane + "/code-snapshot") and not os.path.exists(lane + "/loops/code-snapshot-ledger.jsonl")
        and not [s for s in hshards(lane) if s.endswith(".part")])
    stage = lane + "/code-head/staging"; rem = G.read_rows(lane + "/loops/code-head-removes.jsonl")
    rec("h1", "h) staging is code-head/staging/w<k>/: every clone dir is gone after the run, one receipt per cloned repo under the head staging tree with bytes and authority lead 83076 (breaks if clones pile up or the receipts go to the snapshot file)",
        hstaging_left(lane) == [] and len(rem) == len(MAIN) and all(re.search(r"/code-head/staging/w\d/", r["path"].replace("\\", "/")) and r["bytes"] > 0 and r["authority"] == "lead 83076" for r in rem) and not os.path.exists(lane + "/loops/code-snapshot-removes.jsonl"))
    # accounting
    pf = led.get("h/perfile", {})
    rec("r1", "r) accounting identity unchanged: tree_entries == kept + dropped + ineligible for every repo that reached the file step; perfile keeps only good.py and drops each class under its own reason (breaks if entries vanish uncounted)",
        all(r["tree_entries"] == r["files_kept"] + sum(r["files_dropped"].values()) + sum(r["ineligible"].values()) for r in led.values() if r.get("tree_entries") and not r["skipped_reason"] in ("no_licence_file_at_head", "licence_not_mit_at_head", "licence_mixed_at_head"))
        and [r["path"] for r in hshard(lane, "h/perfile")] == ["good.py"] and {"binary", "other_licence_header", "generated", "long_line", "ipynb", "subtree_non_mit_licence"} <= set(pf.get("files_dropped", {})) and pf.get("ineligible", {}).get("empty") == 1)
    # selection
    dfr = {r["repo"]: r for r in G.read_rows(lane + "/loops/code-head-deferred.jsonl")}
    rec("i1", "i) tranche cap: size_kb 102400 (100 MiB) is in, 102401 is not selected, a 40 GiB row is not selected (not deferred); no clean-signal row, no non-MIT row and no over-cap row reaches the network; a missing size_kb is deferred in code-head-deferred.jsonl; created_at is never looked at (breaks if the cap is off or a skipped row is cloned)",
        "h/capedge" in led and not any(run_r.touched(x) for x in ("h/overcap", "o/huge", "o/notest", "o/apache", "o/forked", "o/archived", "o/awesome", "o/stale", "o/nosignals", "o/noci", "o/nosize")) and eng.deferred == 1 and list(dfr) == ["o/nosize"]
        and dfr["o/nosize"]["reason"] == "size_kb_missing" and eng.max_size_kb == 102400 and "h/overcap" not in {r["full_name"] for r in G.select_repos(lane + "/catalog/gh-mit-candidates.jsonl", 102400)} and "h/overcap" in {r["full_name"] for r in G.select_repos(lane + "/catalog/gh-mit-candidates.jsonl")})
    rec("g0", "the shard write and every clone ask the write gate with the predicted need (breaks if a bulk write skips reserve_plan.write_gate)",
        any(w.startswith("gh_snapshot_fetch shard ") and nb > 0 for w, nb in S.GATE) and sum(1 for w, nb in S.GATE if w.startswith("gh_snapshot_fetch clone ")) == len(MAIN))
    return lane, led


class Flaky(S.FakeRunner):
    """Clone failures by remote url: fail[url] = how many times it fails first (a partial junk dir is left behind each time, like a half clone); gone = urls that answer 'repository not found'."""

    def __init__(self, fail=None, gone=()):
        S.FakeRunner.__init__(self); self.fail, self.gone, self.clones = dict(fail or {}), set(gone), collections.Counter()

    def git(self, args, cwd=None, input=None):
        if args[0] == "clone":
            url, dest = args[-2], args[-1]; self.clones[url] += 1
            if url in self.gone:
                raise G.RunnerError("git clone: remote: Repository not found.")
            if self.fail.get(url, 0) > 0:
                self.fail[url] -= 1; os.makedirs(dest + "/.git", exist_ok=True)
                with open(dest + "/.git/junk", "wb") as f:
                    f.write(b"half a clone")
                raise G.RunnerError("git clone: fatal: unable to access: connection reset")
        return super().git(args, cwd, input)


def scenario_retry(res):
    """One retry on a clone failure (head form only), then an error row; a repo-gone answer is final at once."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    rows = [hrow("h/flaky"), hrow("h/dead"), hrow("h/gone"), hrow("h/capedge")]; u = {r["full_name"]: r["url"] for r in rows}
    lane = S.new_lane(rows); fr = Flaky(fail={u["h/flaky"]: 1, u["h/dead"]: 99}, gone=[u["h/gone"]]); eng = heng(lane, fr, workers=1)
    with contextlib.redirect_stdout(io.StringIO()):
        code = eng.run()
    led = {r["repo"]: r for r in HL(lane)}; errs = [e for e in HE(lane) if e["repo"] == "h/dead"]
    rec("t1", "t) a clone that fails once is retried once (partial dir removed first) and the repo is KEPT: 2 clone calls, a ledger row, files in the shard (breaks if there is no retry or the half clone blocks it)",
        fr.clones[u["h/flaky"]] == 2 and led.get("h/flaky", {}).get("skipped_reason") is None and led.get("h/flaky", {}).get("files_kept") == 1 and [r["path"] for r in hshard(lane, "h/flaky")] == ["a.py"])
    rec("t2", "t) a clone that fails twice is an error row (errors file, repo named, no ledger row, no shard, staging cleared) after exactly 2 attempts, and the run exits 1 (breaks if it retries forever, retries 3 times or writes a finished row)",
        fr.clones[u["h/dead"]] == 2 and len(errs) == 1 and "h/dead" not in led and hshard(lane, "h/dead") == [] and hstaging_left(lane) == [] and code == 1)
    rec("t3", "t) a repo-gone answer is final at once: one clone call and a repo_unavailable ledger row (breaks if a dead repo is retried)", fr.clones[u["h/gone"]] == 1 and led.get("h/gone", {}).get("skipped_reason") == "repo_unavailable")
    rec("t4", "t) the other repos are unaffected: capedge is finished with one clone call (breaks if a failure stops the run)", fr.clones[u["h/capedge"]] == 1 and "h/capedge" in led)
    lane2 = S.new_lane([hrow("h/flaky")]); fr2 = Flaky(fail={u["h/flaky"]: 1}); eng2 = G.Engine(lane2, runner=fr2, log=lambda *a: None, workers=1); code2 = eng2.run()
    rec("t5", "t) the snapshot form is unchanged: one clone attempt, the failure is an error row in code-snapshot-errors.jsonl (breaks if the retry leaked into the snapshot form)",
        fr2.clones[u["h/flaky"]] == 1 and code2 == 1 and len(G.read_rows(lane2 + "/loops/code-snapshot-errors.jsonl")) == 1 and not os.path.exists(lane2 + "/loops/code-head-errors.jsonl"))


def scenario_resume(res):
    """Separate ledger and resume key: a snapshot ledger row never marks a head repo done; head rows are never fetched twice."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    names = ["h/postwall", "h/nolic", "h/none"]; lane = S.new_lane([hrow(n) for n in names])
    assert G.Engine(lane, runner=S.FakeRunner(), log=lambda *a: None, workers=1).run() == 0                        # the SNAPSHOT form first: 3 snapshot ledger rows
    snap0 = G.read_rows(lane + "/loops/code-snapshot-ledger.jsonl")
    r1 = S.FakeRunner(); c1 = heng(lane, r1, workers=2).run()
    rec("f1", "f) snapshot ledger rows do NOT mark head repos done: the head run touches all 3 repos, writes 3 head ledger rows and leaves the snapshot ledger byte-identical in content (breaks if the ledgers or keys are shared)",
        c1 == 0 and all(r1.touched(n) for n in names) and len(HL(lane)) == 3 and G.read_rows(lane + "/loops/code-snapshot-ledger.jsonl") == snap0 and {r["rules_version"] for r in HL(lane)} == {RULES} and {r["rules_version"] for r in snap0} == {"d3-r2"})
    r2 = S.FakeRunner(); c2 = heng(lane, r2, workers=2).run()
    rec("f2", "f) a second head run makes ZERO git calls and adds no row (breaks if finished head repos are fetched again)", c2 == 0 and r2.calls == [] and len(HL(lane)) == 3)
    rows = HL(lane)
    for r in rows:
        if r["repo"] == "h/nolic": r["rules_version"] = "d3-r2"                                                      # a snapshot-rules row sitting in the head ledger
        if r["repo"] == "h/none": r["catalog_commit_sha"] = "f" * 40                                                # another catalogue commit
    with open(lane + "/loops/code-head-ledger.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    r3 = S.FakeRunner(); c3 = heng(lane, r3, workers=1).run()
    rec("f3", "f) the head resume key is (repo, catalogue sha, rules version): a head-ledger row with the snapshot rules version, or for another catalogue commit, is not done and is redone; the untouched row is not (breaks if the repo name alone, or any rules version, is the key)",
        c3 == 0 and r3.touched("h/nolic") and r3.touched("h/none") and not r3.touched("h/postwall") and len(HL(lane)) == 5)


class HeadStep(S.StepRunner):
    """Every git call advances the calling thread's fake clock by `step`; a repo answers an empty tree (no licence file at head), an empty log and a commit time: 5 calls per repo."""

    def git(self, args, cwd=None, input=None):
        self.calls.append(args[0]); self.clk.advance(self.step)
        return b"1700000000\n" if args[:2] == ["show", "-s"] else b""


def scenario_timing(res):
    """Timing report after the first 100 repos; STOP above 8 h."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    rows = [S.cat_row("h/r%03d" % i, "file:///nowhere/r%03d" % i, "%040x" % (i + 1)) for i in range(200)]
    lane = S.new_lane(rows); clk = S.Clock(); r = HeadStep(clk, 1000.0); eng = heng(lane, r, workers=1, clock=clk); buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = eng.run()
    tp, sp = lane + "/loops/code-head-timing.json", lane + "/loops/code-head-STOP.json"
    tim = json.load(open(tp)) if os.path.exists(tp) else {}; stop = json.load(open(sp)) if os.path.exists(sp) else {}
    rec("g1", "g) 100 repos at 5000 s each (1 worker) -> rows_per_hour 0.72, predicted 138.889 h for the 100 left > 8 h: timing file written with repos, rows_per_hour, predicted_hours, attributed, none_stated and the skipped reasons, printed, STOP file written, exit 3 (breaks if the report is missing, wrong or the stop never fires)",
        code == 3 and tim.get("repos") == 100 and tim.get("rows_per_hour") == 0.72 and tim.get("predicted_hours") == 138.889 and tim.get("attributed") == 0 and tim.get("none_stated") == 100 and tim.get("skipped_reasons") == {"no_licence_file_at_head": 100}
        and stop.get("predicted_hours") == 138.889 and '"predicted_hours": 138.889' in buf.getvalue())
    rec("g2", "g) the run stopped right after the report: 100 ledger rows, not 200 (breaks if workers go on after the stop)", len(HL(lane)) == 100)
    r2 = HeadStep(clk, 1000.0); code2 = heng(lane, r2, workers=1, clock=clk).run()
    with contextlib.redirect_stdout(io.StringIO()):
        r3 = HeadStep(clk, 0.0); code3 = heng(lane, r3, workers=1, clock=clk).run(ignore_stop=True)
    rec("g3", "g) with the head STOP file present a new run refuses (exit 3, no call); --ignore-stop continues and finishes the other 100 (breaks if the stop does not stick or the override does nothing)", code2 == 3 and r2.calls == [] and code3 == 0 and r3.calls and len(HL(lane)) == 200)
    lane2 = S.new_lane(rows); clk2 = S.Clock(); eng2 = heng(lane2, HeadStep(clk2, 1.0), workers=1, clock=clk2)
    with contextlib.redirect_stdout(io.StringIO()):
        code_ok = eng2.run()
    tim2 = json.load(open(lane2 + "/loops/code-head-timing.json")) if os.path.exists(lane2 + "/loops/code-head-timing.json") else {}
    rec("g4", "g) the same 200 repos at 5 s each (720 rows/h) predict 0.139 h: the report is written, no STOP file, exit 0, all 200 done (breaks if the rule fires on a fast run)",
        code_ok == 0 and len(HL(lane2)) == 200 and not os.path.exists(lane2 + "/loops/code-head-STOP.json") and tim2.get("rows_per_hour") == 720.0 and tim2.get("predicted_hours") == 0.139)
    rec("g5", "g) the head form reports after 100 repos by default and the head files are separate from the snapshot ones (breaks if the head run uses the snapshot stop point of 50 or its STOP file)",
        heng(S.new_lane([]), S.FakeRunner()).stop_after == 100 and G.Engine(S.new_lane([]), runner=S.FakeRunner()).stop_after == 50 and not os.path.exists(lane + "/loops/code-snapshot-STOP.json") and not os.path.exists(lane + "/loops/code-snapshot-timing.json"))


def scenario_misc(res):
    """Priority, defaults, CLI, error rows, staging cap, log cap."""
    rec = lambda k, l, c: res.append((k, l, bool(c)))
    # priority
    LP_CALLS.clear(); lane = S.new_lane([hrow(n) for n in ("h/postwall", "h/nolic", "h/none")]); heng(lane, S.FakeRunner(), workers=3).run()
    lane_s = S.new_lane([hrow("h/postwall")]); G.Engine(lane_s, runner=S.FakeRunner(), log=lambda *a: None, workers=1).run()
    rec("x1", "x) the head run lowers the process priority exactly once at run start (not once per worker); the snapshot run does not (breaks if the head form runs at normal priority)", len(LP_CALLS) == 1)

    class Ps:
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        seen = []
        class Process:
            def nice(self, v): Ps.seen.append(v)
    class PsNone:
        class Process:
            def nice(self, v): raise AssertionError("must not be called without the constant")
    rec("x2", "x) lower_priority() sets psutil BELOW_NORMAL_PRIORITY_CLASS on the process and returns False (never raises) where the constant or psutil is missing (breaks if the class is wrong or a missing psutil kills the run)",
        REAL_LP(Ps) is True and Ps.seen == [0x4000] and REAL_LP(PsNone) is False and REAL_LP(object()) is False)
    cap = {}

    class P:
        returncode, stdout, stderr = 0, b"", b""
    real_run = G.subprocess.run
    G.subprocess.run = lambda cmd, **kw: (cap.update(kw), P())[1]
    try:
        G.Runner(low_priority=True).git(["status"]); lo = dict(cap); cap.clear(); G.Runner().git(["status"]); hi = dict(cap)
    finally:
        G.subprocess.run = real_run
    rec("x3", "x) the head Runner spawns git with creationflags 0x4000 (below normal) on Windows; the default Runner sets none (breaks if git children keep normal priority or the snapshot Runner changes)",
        (lo.get("creationflags") == 0x4000 and "creationflags" not in hi) if os.name == "nt" else ("creationflags" not in lo and "creationflags" not in hi))
    eh, es = G.Engine(S.new_lane([]), log=lambda *a: None, form="head"), G.Engine(S.new_lane([]), log=lambda *a: None)
    rec("x4", "x) defaults: head form = 8 workers, below-normal Runner, tranche cap 100 MiB, rules d3h-r1; snapshot form = 4 workers, normal Runner, no cap, rules d3-r2 (breaks if a default drifts or leaks across forms)",
        eh.workers == 8 and eh.runner.low_priority is True and eh.max_size_kb == 102400 and eh.rules == RULES and es.workers == 4 and not es.runner.low_priority and es.max_size_kb is None and es.rules == "d3-r2")
    # CLI
    lane = S.new_lane([hrow(n) for n in ("h/trailer", "h/none", "h/nolic", "h/bot")]); out = io.StringIO()
    with contextlib.redirect_stdout(out):
        c_run = G.main(["run", "--form", "head", "--workers", "2"], runner=S.FakeRunner(), lane=lane)
    summ = json.loads(out.getvalue()[out.getvalue().index("{\n"):]) if "{\n" in out.getvalue() else {}
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        c_st = G.main(["status", "--form", "head"], lane=lane)
    st = json.loads(out2.getvalue())
    rec("x5", "x) CLI: `run --form head` prints a summary with attributed 2, none_stated 2 and the skipped-reason counts, and `status --form head` reports the same plus 4 of 4 done (breaks if the aggregate lacks the attribution counts or the form flag is not wired)",
        c_run == 0 and summ.get("attributed") == 2 and summ.get("none_stated") == 2 and summ.get("form") == "head" and summ.get("skipped_reasons") == {"no_licence_file_at_head": 1}
        and c_st == 0 and st.get("attributed") == 2 and st.get("none_stated") == 2 and st.get("selected") == 4 and st.get("in_ledger") == 4 and st.get("remaining") == 0 and st.get("skipped_reasons") == {"no_licence_file_at_head": 1} and st.get("rules_version") == RULES)
    out3 = io.StringIO()
    with contextlib.redirect_stdout(out3):
        G.main(["status"], lane=lane)
    rec("x6", "x) the snapshot-form status of the same lane is untouched: it sees none of the head rows (0 in the ledger) and has no attribution keys (breaks if the forms share a ledger or the snapshot output changes)",
        json.loads(out3.getvalue()).get("in_ledger") == 0 and "attributed" not in json.loads(out3.getvalue()))
    lane = S.new_lane([hrow("h/human"), hrow("h/anthro")])
    with contextlib.redirect_stdout(io.StringIO()):
        heng(lane, S.FakeRunner(), workers=1).run()
    hl = {r["repo"]: r for r in HL(lane)}
    rec("x7", "x) a human whose first name is an agent word (Devin, Claude, Gemini, Cursor) in author/committer fields is NOT evidence (none_stated); the agent's own mail identity noreply@anthropic.com as author IS (attributed) (breaks if names are matched as text)",
        hl.get("h/human", {}).get("agent_attribution") == dict(state="none_stated", evidence=[]) and hl.get("h/anthro", {}).get("agent_attribution", {}).get("state") == "attributed")
    # missing catalogue commit
    row = hrow("h/missing"); row["commit_sha"] = "1" * 40; lane = S.new_lane([row]); rr = S.FakeRunner(); eng = heng(lane, rr, workers=1)
    with contextlib.redirect_stdout(io.StringIO()):
        code = eng.run()
    rec("m0", "m) an unreachable catalogue commit is an ERROR row catalogue_commit_missing (errors file, no ledger row, no shard, clone removed, exit 1), and nothing else is read from the clone (breaks if it becomes a finished row or the head is guessed)",
        code == 1 and HL(lane) == [] and any(e.get("kind") == "catalogue_commit_missing" for e in HE(lane)) and hshards(lane) == [] and hstaging_left(lane) == [] and not [c for c in rr.calls if "ls-tree" in c])
    # staging cap / accounting unchanged
    old = G.NEED_BASE; G.NEED_BASE = 1000
    try:
        lane = S.new_lane([hrow("h/perfile", size_kb=1)]); eng = heng(lane, S.FakeRunner(), workers=1, budget_cap=300 << 20)
        with contextlib.redirect_stdout(io.StringIO()):
            code1 = eng.run()
        led = HL(lane)
        rec("m1", "m) an understated size_kb: the staging dir is MEASURED and the reservation raised to it (+ one chunk): the head run finishes, ledger staging_peak_bytes shows the measured size, budget back to 0 (breaks if the head form only trusts the prediction)",
            code1 == 0 and len(led) == 1 and led[0].get("staging_peak_bytes", 0) > 1_000 and eng.budget.peak >= (64 << 20) and eng.budget.used == 0)
        lane = S.new_lane([hrow("h/perfile", size_kb=1)]); eng = heng(lane, S.FakeRunner(), workers=1, budget_cap=10 << 20)
        with contextlib.redirect_stdout(io.StringIO()):
            code2 = eng.run()
        rec("m2", "m) when the measured size cannot fit under the cap the head repo ends as an error row staging_over_budget: no ledger row, no shard, staging removed, exit 1 (breaks if the cap is exceeded)",
            code2 == 1 and HL(lane) == [] and [s for s in hshards(lane) if not s.endswith(".part")] == [] and hstaging_left(lane) == [] and any(e.get("kind") == "staging_over_budget" for e in HE(lane)))
    finally:
        G.NEED_BASE = old
    # log cap
    oldc = G.LOG_CAP; G.LOG_CAP = 2
    try:
        lane = S.new_lane([hrow("h/trailer")]); rr = S.FakeRunner()
        with contextlib.redirect_stdout(io.StringIO()):
            heng(lane, rr, workers=1).run()
        l = HL(lane)[0]
        rec("m3", "m) the log cap is honoured and recorded: with the cap at 2 a 3-commit history gives history_commits 2, history_truncated True and `log -n 2` (breaks if the cap is ignored or truncation is not flagged)",
            l.get("history_commits") == 2 and l.get("history_truncated") is True and any("log -n 2 " in c for c in rr.calls))
    finally:
        G.LOG_CAP = oldc


SCEN = [("main", scenario_main, ["run", "p1", "p2", "p3", "p4", "p5", "c1", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "l1", "o1", "h1", "r1", "i1", "g0"]), ("retry", scenario_retry, ["t1", "t2", "t3", "t4", "t5"]),
        ("resume", scenario_resume, ["f1", "f2", "f3"]), ("timing", scenario_timing, ["g1", "g2", "g3", "g4", "g5"]), ("misc", scenario_misc, ["x1", "x2", "x3", "x4", "x5", "x6", "x7", "m0", "m1", "m2", "m3"])]


def run_all(res, only=None):
    for name, fn, keys in SCEN:
        if only and name not in only:
            continue
        mine = []
        try:
            fn(mine)
        except Exception as e:
            import traceback; traceback.print_exc()
            mine.append(("crash:" + name, "scenario %s crashed: %s: %s" % (name, type(e).__name__, str(e)[:160]), False))
        have = {k for k, l, c in mine}
        res.extend(mine)
        res.extend((k, "(scenario %s did not reach this check)" % name, False) for k in keys if k not in have)


def mutant(name, patches, keys, scen):
    """patches: [(object, attribute, value)]. Apply, re-run the named scenarios, require one of `keys` to FAIL (or the run to blow up)."""
    saved = [(o, a, getattr(o, a)) for o, a, v in patches]
    for o, a, v in patches:
        setattr(o, a, v)
    res = []
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run_all(res, only=scen)
        bitten = any(not c for k, l, c in res if k in keys)
    except Exception:
        bitten = True
    finally:
        for o, a, v in saved:
            setattr(o, a, v)
    chk("mutant %s is caught by checks %s" % (name, "/".join(keys)), bitten)


if __name__ == "__main__":
    res = []; t0 = time.time(); run_all(res)
    for k, l, c in res:
        chk("%s %s" % (k, l), c)
    print("FAILCOUNT %d of %d" % (sum(1 for k, l, c in res if not c), len(res)))
    if os.environ.get("HEAD_NO_MUTANTS") != "1":
        orig_tree = G.list_tree
        mutant("attribution off", [(G, "agent_attribution", lambda *a, **k: (dict(state="none_stated", evidence=[]), 0, False))], ("a1", "a2", "a3"), ("main",))
        mutant("trailer lines not read", [(G, "_COAUTH", re.compile(r"(?!x)x"))], ("a1",), ("main",))
        mutant("no family matches", [(G, "_FAM_RE", {})], ("a1", "a2"), ("main",))
        mutant("dependabot / renovate count as agents", [(G, "_FAM_RE", dict(G._FAM_RE, bot=re.compile(r"dependabot|renovate|github-actions", re.I)))], ("a5",), ("main",))
        mutant("instruction files off", [(G, "instruction_paths", lambda ents: [])], ("a3",), ("main",))
        mutant("wall applied to head (post-wall tree read as empty)", [(G, "list_tree", lambda r, c, s: [] if int(r.git(["show", "-s", "--format=%ct", s], c).decode().strip()) >= 1667260800 else orig_tree(r, c, s))], ("p1", "p5"), ("main",))
        mutant("log read unbounded", [(G, "LOG_CAP", 10 ** 9)], ("a7",), ("main",))
        mutant("tranche cap off", [(G, "HEAD_MAX_SIZE_MB", 10 ** 9)], ("i1",), ("main",))
        mutant("licence reason keeps the wall suffix", [(G.Engine, "_skip", lambda self, led, reason: (led.__setitem__("skipped_reason", reason.replace("_at_head", "_at_wall_commit")), led)[1])], ("c1",), ("main",))
        mutant("clone retry off", [(G.Engine, "_clone", lambda self, row, clone: self.runner.git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", row["url"], clone]))], ("t1",), ("retry",))
        mutant("clone retried without clearing the half clone", [(G, "remove_staging", lambda *a, **k: 0)], ("t1",), ("retry",))
        mutant("catalogue commit missing is not an error row", [(G, "CatalogueCommitMissing", type("X", (RuntimeError,), {"kind": "other"}))], ("m0",), ("misc",))
        mutant("head shares the snapshot rules version", [(G, "HEAD_RULES_VERSION", G.RULES_VERSION)], ("f1", "f3"), ("resume",))
        mutant("timing report never due", [(G, "HEAD_STOP_AFTER", 10 ** 9)], ("g1", "g4"), ("timing",))
        mutant("stop rule off", [(G, "STOP_HOURS", 1e9)], ("g1",), ("timing",))
        mutant("priority never lowered", [(G, "lower_priority", lambda *a, **k: False)], ("x1",), ("misc",))
        mutant("git children at normal priority", [(G, "BELOW_NORMAL", 0)], ("x3",), ("misc",))
        mutant("staging never measured", [(G, "measure_staging", lambda *a, **k: None)], ("m1", "m2"), ("misc",))
    print("elapsed %.1f s" % (time.time() - t0))
    print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)

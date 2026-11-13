# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""NO DATE WALL (owner 2026-11-11, lead 83389): the 2022-11-01 instant below is the AS-OF version selector of the snapshot form (the licence must be read at the tree being taken), not a content filter. The only date rule that used to exclude whole repos,
the ancestry monotone check, is now metadata: every ledger and shard row records content_date_max (the latest committer/author date in the ancestry, snapshot form; the head commit date, head form) and the snapshot ledger records history_dates_not_monotone.

Pre-wall code snapshot fetch (D3, lead 82956): each clean-signal MIT repo of the catalogue taken AS OF its last commit before the 2022-11-01T00:00:00Z wall, kept only when every root licence file at that commit is MIT,
with a per-file licence step on the content, written as the source class "code, pre-wall snapshot".

Usage: python gh_snapshot_fetch.py run [--limit N] [--workers 4] [--ignore-stop]   |   python gh_snapshot_fetch.py status
Exit codes: 0 finished (or --limit reached), 1 finished but some repos errored (no ledger row; see loops/code-snapshot-errors.jsonl; rerun redoes them), 2 B: below the reserve floor (resumable), 3 timing stop rule fired (STOP file written) or a STOP file exists, 4 wall violation (a wall commit at or after the wall: nothing is written for it).

What the code establishes, and no more: the wall is a committer-time AND author-time wall over the WHOLE ancestry of the wall commit (every commit reachable from it is stamped strictly before 1667260800), and every file comes from that commit's tree by blob sha.
It does not establish that a file's content was written before the wall in any other sense (a pre-wall stamp can be forged; the check closes the honest back-dated / clock-reset cases).
Per repo (catalogue row = licence MIT and has_tests_root, has_ci, recent_commit_365d, not_fork, not_archived, not awesome_or_dump_flag; size_kb present):
  1. blobless clone (no checkout); wall commit = `git rev-list -1 --before=<2022-10-31T23:59:59Z> <catalogue commit>`. HARD CHECK its committer time < 1667260800 or WallViolation is raised (the run aborts, durable row kind wall_violation).
     No commit before the wall: skipped, reason no_pre_wall_history.
  2. ancestry: one `git log --format='%ct %at' <wall commit>`; content_date_max = the latest committer/author time in it; any ancestor (the wall commit included) with committer OR author time >= the as-of instant sets history_dates_not_monotone in the ledger row (a flag, no longer a skip). Both times of the wall commit go in the ledger.
  3. file list = `git ls-tree -r -z <wall commit>` in the clone (path, mode, type, sha). No GitHub API call anywhere. `ls-tree -l` is NOT used: in a blobless clone it fetches every blob of the tree (measured), so sizes are judged on the fetched bytes.
  4. licence: every root LICENSE / LICENCE / COPYING / UNLICENSE (optionally with extension) blob is read from the clone and must be the MIT text (case, whitespace, quotes normalised; only the title and copyright lines are free).
     None: no_licence_file_at_wall_commit. None MIT: licence_not_mit_at_wall_commit. Some MIT, some not: licence_mixed_at_wall_commit.
  5. every tree entry is accounted for: ineligible{submodule, symlink, non_blob, skip_dir, skip_file, extension, empty, too_large} + dropped{...} + kept == tree_entries (asserted), using the measure_sample filters (TEXT_EXT, SKIP_DIR, SKIP_FILE, 1 byte .. MAX_FILE).
  6. content is read BY BLOB SHA (batch `git fetch --stdin` of the wanted blobs into the promisor clone, then `git cat-file --batch`, each blob's git hash re-computed). A wanted blob that cannot be read is an error row (kind blob_unavailable), never a finished row.
  7. per-file licence step: .ipynb, subtrees holding a non-MIT LICENSE/COPYING, binary, invalid UTF-8, other-licence header, generated, over-long line. Each drop has a reason; counts go in the ledger row.
  8. output under <lane>/code-snapshot/docs/<owner>__<name>@<wall12>.jsonl.zst (one shard per repo, tmp + replace) and one terminal ledger row per repo in <lane>/loops/code-snapshot-ledger.jsonl, carrying source_class, rules_version and scan_state NOT_SCANNED.
SECRET SCAN: config files (.json .yaml .toml .ini .cfg .sh ...) are eligible, so the code-snapshot/docs shards must pass the pre-upload secret scan (th_gate, the scan queue) BEFORE any selection or packing; scan_state NOT_SCANNED means they have not.
Resumable: the key is (repo, catalogue commit, rules version): a ledger row with that key is never fetched again; a crashed repo (no row) is redone from scratch. All git calls go through one injectable Runner (lazy fetch is disabled for every call except clone and the explicit blob fetch).
Staging (<lane>/code-snapshot/staging/w<k>/) is capped at 5 GiB resident across workers. A repo reserves size_kb x 1024 x 0.25 + 64 MiB before it starts (missing size_kb or a need above the cap: a deferred row in loops/code-snapshot-deferred.jsonl, no clone),
the write gate is asked for budget in use + need, the dir is MEASURED after the clone and after every fetch chunk and the reservation is raised to what is on disk (+ one chunk) or the repo ends as an error row staging_over_budget.
Each repo's dir is removed right after its ledger row, inside the staging tree only, receipt row first (loops/code-snapshot-removes.jsonl).
Timing stop rule: after the first 50 repos of a run finish, predicted hours = mean total_s x repos remaining / workers / 3600; above 8.0 -> loops/code-snapshot-STOP.json and exit 3.
Packing into tokenized shards is a later step; this script never touches pack.py. No model anywhere.

HEAD FORM (--form head; lead 83076 / 83077 / 83080 / 83135): the source class "post-wall public code" = each tranche-1 catalogue repo (clean signals, MIT, size_kb <= --max-size-mb, default 100) at its catalogue commit sha itself.
Usage: python gh_snapshot_fetch.py run --form head [--limit N] [--workers 8] [--max-size-mb 100] [--ignore-stop]   |   python gh_snapshot_fetch.py status --form head
Same per-repo steps 1, 3-8 with these differences. NO created_at pre-filter, NO wall commit, NO ancestry / monotone check, NO no_pre_wall_history skip, NO WallViolation: the tree read is the catalogue commit (`git cat-file -e <sha>^{commit}`;
unreachable -> error row catalogue_commit_missing, no ledger row). Licence reasons: no_licence_file_at_head, licence_not_mit_at_head, licence_mixed_at_head. A clone failure is retried ONCE (a repo-gone answer is not retried), then an error row as in the snapshot form.
Files: <lane>/code-head/docs/<owner>__<name>@<sha12>.jsonl.zst, staging <lane>/code-head/staging/w<k>/, ledger loops/code-head-ledger.jsonl (resume key (repo, catalogue sha, HEAD_RULES_VERSION): the snapshot ledger and its rows never mark a head repo done),
loops/code-head-errors.jsonl, code-head-deferred.jsonl, code-head-removes.jsonl, code-head-STOP.json, code-head-timing.json. Ledger row = the snapshot row minus the wall fields plus form "head", source_class, head_commit_ts, history_commits, history_truncated, agent_attribution, scan_state NOT_SCANNED;
every shard row carries agent_attribution and source_class (and head_commit instead of wall_commit).
agent_attribution is stated by the repo, read locally from the clone, never inferred from code style: {"state": "attributed", "evidence": [{signal, where, count, ...}]} or {"state": "none_stated", "evidence": []}. Signals:
  trailer           Co-Authored-By lines (and an author / committer email of noreply@anthropic.com; a plain first name in an author field never counts) naming claude (incl. noreply@anthropic.com), copilot, cursor, devin, codex, aider, gemini or openhands, as whole words, case-insensitive; one evidence entry per family, count = commits.
  bot_contributor   author / committer name or email containing "[bot]" and one of those words (copilot-swe-agent[bot], claude[bot], devin-ai-integration[bot], cursor[bot], codex[bot], ...); dependabot, renovate, github-actions are not agents.
  instruction_file  tree paths AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules (any depth), .github/copilot-instructions.md, .cursor/rules/* ; where = the paths (at most 5), count = total.
The commit log read is capped (`git log -n 20000`); history_commits is the number read, history_truncated says the cap was reached. Priority: the run lowers its process priority to below normal (psutil) and spawns git with the below-normal creation flag (0x4000).
Timing report: after the first 100 repos of a run finish, loops/code-head-timing.json = {repos, rows_per_hour (wall clock), predicted_hours = remaining / rows_per_hour, attributed, none_stated, skipped reasons} is written and printed; predicted_hours > 8.0 writes the STOP file and exits 3.
The end-of-run summary (printed) and `status --form head` report attributed N, none_stated M and the skipped-reason counts."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, sys, re, json, time, base64, hashlib, shutil, stat, subprocess, threading, argparse, collections
import zstandard
import reserve_plan

WALL_TS = 1667260800                       # 2022-11-01T00:00:00Z: a commit is inside the wall only when its committer time is STRICTLY before this
BEFORE_ISO = "2022-10-31T23:59:59Z"        # rev-list --before is inclusive; one second earlier keeps `<= BEFORE` identical to `< WALL_TS`
AUTHORITY = "lead 82956"
HEAD_AUTHORITY = "lead 83076"
HEAD_RULES_VERSION = "d3h-r1"              # the head form's own resume key version: a snapshot row (rules d3-r2) can never mark a head repo done
HEAD_SOURCE_CLASS = "post-wall public code"
HEAD_STOP_AFTER = 100                      # head form: timing report (and stop rule) after this many repos of a run
HEAD_WORKERS = 8
HEAD_MAX_SIZE_MB = 100                     # tranche 1
LOG_CAP = 20000                            # git log -n: commits read for the attribution
BELOW_NORMAL = 0x4000                      # Windows creation flag BELOW_NORMAL_PRIORITY_CLASS
RULES_VERSION = "d3-r2"                    # part of the resume key: a change of rule is a new version, old rows do not count as done
SOURCE_CLASS = "code, pre-wall snapshot"
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"      # the empty file: its sha says it is empty, nothing to fetch
BUDGET_CAP = 5 << 30                       # resident staging bytes across all workers
NEED_FRACTION = 0.25
NEED_BASE = 64 << 20
STOP_AFTER = 50
STOP_HOURS = 8.0
CHUNK_BYTES = 64 << 20                     # blob bytes read per fetch + cat-file round
CHUNK_N = 200
LICENCE_READ_MAX = 200000
MAX_LINE = 20000

# the measure_sample filters, copied (not imported) so the snapshot measures what the sample measured
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".kt", ".scala", ".rb", ".php", ".cs", ".swift", ".sh", ".md", ".rst", ".txt", ".ipynb", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".json", ".sql", ".r", ".jl", ".lua", ".cu", ".proto", ".html", ".css"}
SKIP_DIR = re.compile(r"(^|/)(node_modules|vendor|third_party|dist|build|\.git|__pycache__|site-packages|\.venv|venv)(/|$)")
SKIP_FILE = re.compile(r"(\.min\.(js|css)|\.lock|package-lock\.json|yarn\.lock|poetry\.lock|\.map|\.svg)$", re.I)
MAX_FILE = 1 << 20
OTHER_LIC = re.compile(r"Apache License|GNU (Lesser |Affero )?General Public|Mozilla Public License|SPDX-License-Identifier:\s*(?!MIT)[A-Za-z]|BSD [23]-Clause|All rights reserved\.\s*(?!.*MIT)", re.I)
GENERATED = re.compile(r"DO NOT EDIT|Code generated|@generated")
LIC_ROOT = re.compile(r"^(licen[sc]e|copying|unlicense)(\.[a-z]+)?$", re.I)
LIC_ANY = re.compile(r"(^|/)(licen[sc]e|copying)(\.[a-z]+)?$", re.I)
GONE = re.compile(r"repository not found|returned error: 404|dmca|access blocked|repository unavailable", re.I)


def _log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class CatalogueCommitMissing(RuntimeError):
    """Head form: the catalogue commit is not reachable in the clone. An error row, no ledger row."""
    kind = "catalogue_commit_missing"


def _iso_day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))


class WallViolation(Exception):
    """A wall commit whose committer time is not strictly before the wall. Never continued with."""
    kind = "wall_violation"


class DiskFloor(Exception):
    """write_gate gave up: B: stayed below the reserve floor. Nothing was written; resumable."""
    kind = "disk_floor_stop"


class StagingEscape(Exception):
    """A removal target outside the staging tree (or the tree itself)."""


class StagingOverBudget(RuntimeError):
    """The measured staging size does not fit under the 5 GiB cap (or the wait for room ran out)."""
    kind = "staging_over_budget"


class BlobUnavailable(RuntimeError):
    """A blob wanted from the wall-commit tree could not be read: the repo is NOT finished (retried on resume)."""
    kind = "blob_unavailable"


class Stopped(Exception):
    """The run was told to stop while a repo waited for staging room."""


class RunnerError(Exception):
    pass


class Runner:
    """Every git subprocess of this script (there is no gh / GitHub API call). Tests inject a fake with the same method."""

    def __init__(self, git_timeout=1800, low_priority=False):
        self.git_timeout = git_timeout; self.low_priority = low_priority

    def git(self, args, cwd=None, input=None):
        """-> stdout bytes; RunnerError (with stderr) on a non-zero exit. Lazy promisor fetch is OFF for everything except clone and the explicit blob fetch: a missing object is then an error, never a silent per-object download."""
        cmd = ["git", "-c", "core.quotepath=false"] + (["-C", cwd] if cwd else []) + list(args)
        env = dict(os.environ); env["GIT_TERMINAL_PROMPT"] = "0"
        words = [a for a in args if not a.startswith("-") and "=" not in a]
        if not words or words[0] not in ("clone", "fetch"):
            env["GIT_NO_LAZY_FETCH"] = "1"
        kw = {"creationflags": BELOW_NORMAL} if getattr(self, "low_priority", False) and os.name == "nt" else {}
        p = subprocess.run(cmd, input=input, capture_output=True, timeout=self.git_timeout, env=env, **kw)
        if p.returncode != 0:
            raise RunnerError("git %s: %s" % (" ".join(map(str, args[:3])), p.stderr.decode("utf-8", "replace")[-300:]))
        return p.stdout


# ------------------------------------------------------------------ paths and files
class Paths:
    def __init__(self, lane, form="snapshot"):
        k = "code-head" if form == "head" else "code-snapshot"
        self.lane = lane.replace("\\", "/").rstrip("/")
        self.catalog = self.lane + "/catalog/gh-mit-candidates.jsonl"
        self.out = self.lane + "/" + k
        self.docs = self.out + "/docs"
        self.stage = self.out + "/staging"
        self.ledger = self.lane + "/loops/%s-ledger.jsonl" % k
        self.removes = self.lane + "/loops/%s-removes.jsonl" % k
        self.stop = self.lane + "/loops/%s-STOP.json" % k
        self.errors = self.lane + "/loops/%s-errors.jsonl" % k
        self.deferred = self.lane + "/loops/%s-deferred.jsonl" % k
        self.timing = self.lane + "/loops/%s-timing.json" % k


_IO = threading.Lock()


def append_row(path, row, sync=False):
    """One small jsonl row, one write call (receipts and ledgers: KB)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    line = json.dumps(row, sort_keys=True) + "\n"
    with _IO:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            if sync:
                f.flush(); os.fsync(f.fileno())


def read_rows(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue                                        # a torn last line from a crash: that repo has no row and is redone
            if isinstance(r, dict):
                rows.append(r)
    return rows


def now_z():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def select_repos(catalog_path, max_size_kb=None):
    """Catalogue rows that count: licence MIT and every clean signal (the 5,682-repo set); first row per repo wins. A missing signal key counts as NOT clean.
    max_size_kb (head form, tranche 1): a row whose size_kb is a number above it is not selected; a missing size_kb stays selected (it is deferred later, never guessed)."""
    out, seen = [], set()
    for r in read_rows(catalog_path):
        s = r.get("signals") or {}
        clean = (s.get("has_tests_root") and s.get("has_ci") and s.get("recent_commit_365d") and s.get("not_fork") and s.get("not_archived") and not s.get("awesome_or_dump_flag", True))
        if r.get("licence_spdx") != "MIT" or not clean or not r.get("full_name") or not r.get("commit_sha") or not r.get("url") or r["full_name"] in seen:
            continue
        seen.add(r["full_name"])
        if max_size_kb is not None and isinstance(r.get("size_kb"), (int, float)) and r["size_kb"] > max_size_kb:
            continue
        out.append(r)
    return out


def predicted_need(row):
    return int((row.get("size_kb") or 0) * 1024 * NEED_FRACTION) + NEED_BASE


def row_key(repo, catalog_sha, rules=None):
    return (repo, catalog_sha, RULES_VERSION if rules is None else rules)


def done_keys(ledger_path):
    return {row_key(r["repo"], r.get("catalog_commit_sha"), r.get("rules_version")) for r in read_rows(ledger_path) if r.get("repo")}


def dir_bytes(p):
    t = 0
    for dp, dn, fn in os.walk(p):
        for f in fn:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t


def remove_staging(path, stage, removes_path, repo="", authority=AUTHORITY, kind="code-snapshot staging clone, refetchable from the catalogue commit"):
    """Remove one repo's staging dir. The target must resolve strictly inside the staging tree (StagingEscape otherwise); the receipt row is written (fsynced) before the remove. -> bytes removed (0 when absent)."""
    rp = os.path.normcase(os.path.realpath(path)); rs = os.path.normcase(os.path.realpath(stage))
    if not rp.startswith(rs + os.sep) or rp == rs:
        raise StagingEscape("%s is not strictly inside the staging tree %s" % (path, stage))
    if not os.path.lexists(path):
        return 0
    n = dir_bytes(path)
    append_row(removes_path, dict(ts=now_z(), path=os.path.abspath(path).replace("\\", "/"), bytes=n, authority=authority, repo=repo, kind=kind), sync=True)

    def _writable(fn, p, exc):
        os.chmod(p, stat.S_IWRITE); fn(p)                       # git packs are read-only on Windows
    shutil.rmtree(path, onerror=_writable)
    return n


# ------------------------------------------------------------------ licence text
_QUOTES = re.compile("[“”‘’\"'`]")
_MIT_A = ('Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, '
          'including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, '
          'subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. '
          'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. '
          'IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH '
          'THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.')


def _norm(t):
    return " ".join(_QUOTES.sub("", t.lower()).split())


MIT_BODIES = {_norm(_MIT_A), _norm(_MIT_A.replace("THE AUTHORS OR COPYRIGHT HOLDERS", "THE COPYRIGHT HOLDERS"))}
_PREFIX_OK = re.compile(r"^(?:(?:the\s+)?(?:mit|expat)(?:\s+licen[sc]e)?(?:\s*\(mit\))?|licen[sc]e|copyright\b.*|\(c\)\s.*|©.*|spdx-license-identifier:\s*mit|all rights reserved\.?)$", re.I)


def is_mit(text):
    """The standard MIT permission text. Only a title line and copyright lines may come before it; the normalised body (case, whitespace, quote marks) must EQUAL the standard body, so an added clause, a different licence or a mere mention of 'MIT License' is not MIT."""
    t = text.lstrip("﻿")
    m = re.search(r"permission\s+is\s+hereby\s+granted", t, re.I)
    if not m:
        return False
    for line in t[:m.start()].splitlines():
        l = re.sub(r"^[#/*>\s]+", "", line.strip()).strip("*/ ")
        if l.strip("=-_ ") and not _PREFIX_OK.match(l):
            return False
    return _norm(t[m.start():]) in MIT_BODIES


# ------------------------------------------------------------------ git steps
def select_wall_commit(runner, clone, catalog_sha):
    """-> (wall sha, committer time) or None when the repo has no commit before the wall. WallViolation when the chosen commit is not strictly before it."""
    sha = runner.git(["rev-list", "-1", "--before=" + BEFORE_ISO, catalog_sha], clone).decode().strip()
    if not sha:
        return None
    ts = int(runner.git(["show", "-s", "--format=%ct", sha], clone).decode().strip())
    if not ts < WALL_TS:
        raise WallViolation("wall commit %s has committer time %d >= %d" % (sha, ts, WALL_TS))
    return sha, ts


def history_times(runner, clone, wall_sha):
    """[(committer time, author time)] of the wall commit (first) and every commit reachable from it: one `git log` over the blobless clone."""
    out = runner.git(["log", "--format=%ct %at", wall_sha], clone).decode()
    return [tuple(int(x) for x in ln.split()) for ln in out.splitlines() if ln.strip()]


def list_tree(runner, clone, wall_sha):
    """The wall commit's tree from the clone: [{path, mode, type, sha}] (no sizes: `ls-tree -l` would fetch every blob)."""
    ents = []
    for rec in runner.git(["ls-tree", "-r", "-z", wall_sha], clone).split(b"\x00"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1); mode, typ, sha = meta.decode("ascii").split()
        ents.append(dict(path=path.decode("utf-8", "replace"), mode=mode, type=typ, sha=sha))
    return ents


# ------------------------------------------------------------------ head form: agent attribution (read locally, never inferred from code style)
AGENT_FAMILIES = (("aider", r"aider"), ("claude", r"claude|noreply@anthropic\.com"), ("codex", r"codex"), ("copilot", r"copilot"), ("cursor", r"cursor"), ("devin", r"devin"), ("gemini", r"gemini"), ("openhands", r"openhands"))
_FAM_RE = {k: re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % v, re.I) for k, v in AGENT_FAMILIES}
_COAUTH = re.compile(r"^[ \t]*co-authored-by:(.*)$", re.I | re.M)
LOG_FORMAT = "%an%x09%ae%x09%cn%x09%ce%x09%B%x1e"
INSTRUCTION_BASENAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules"}


def instruction_paths(ents):
    """Tree paths (any depth) that are agent instruction files."""
    out = []
    for e in ents:
        if e["type"] != "blob":
            continue
        p = e["path"]; base = p.rsplit("/", 1)[-1]
        if base in INSTRUCTION_BASENAMES or p == ".github/copilot-instructions.md" or p.endswith("/.github/copilot-instructions.md") or p.startswith(".cursor/rules/") or "/.cursor/rules/" in p:
            out.append(p)
    return sorted(out)


def agent_attribution(runner, clone, commit, ents):
    """-> (attribution dict, commits read, truncated). Signals: trailer (Co-Authored-By lines, and non-bot author / committer names or emails, naming an agent), bot_contributor ([bot] identities naming an agent), instruction_file (tree paths).
    Every signal is read from the local clone (one `git log` over the catalogue commit, the tree already listed); no API call; code style is never looked at."""
    raw = runner.git(["log", "-n", str(LOG_CAP), "--format=" + LOG_FORMAT, commit], clone).decode("utf-8", "replace")
    recs = [x for x in raw.split("\x1e") if x.strip()]
    fam, bots, bot_names = collections.Counter(), 0, set()
    for rec in recs:
        f = rec.lstrip("\n").split("\t", 4); f += [""] * (5 - len(f)); ids, body = f[:4], f[4]
        hit = set()
        for line in _COAUTH.findall(body):
            hit.update(k for k, rx in _FAM_RE.items() if rx.search(line))
        isbot = False
        for i in ids:
            if any(rx.search(i) for rx in _FAM_RE.values()) and "[bot]" in i.lower():
                isbot = True; bot_names.add(i.strip())
            elif "[bot]" not in i.lower() and "noreply@anthropic.com" in i.lower():      # a human first name (Devin, Claude, Gemini) in an author field is never evidence; only the agent's own mail identity is
                hit.add("claude")
        for k in hit:
            fam[k] += 1
        bots += isbot
    ev = [dict(signal="trailer", where="git log", count=fam[k], family=k) for k, _ in AGENT_FAMILIES if fam[k]]
    if bots:
        ev.append(dict(signal="bot_contributor", where="git log", count=bots, names=sorted(bot_names)[:5]))
    ip = instruction_paths(ents)
    if ip:
        ev.append(dict(signal="instruction_file", where=ip[:5], count=len(ip)))
    return dict(state="attributed" if ev else "none_stated", evidence=ev), len(recs), len(recs) >= LOG_CAP


def lower_priority(psutil_mod=None):
    """Once per run: this process below normal priority (psutil); git children are spawned below normal by the Runner. -> True when applied."""
    try:
        ps = psutil_mod or __import__("psutil")
        flag = getattr(ps, "BELOW_NORMAL_PRIORITY_CLASS", None)
        if flag is None:
            return False
        ps.Process().nice(flag)
        return True
    except Exception:
        return False


def ineligible_class(e):
    """Why a tree entry is not a candidate file (None = candidate). Sizes are judged later on the fetched bytes (too_large)."""
    if e["type"] == "commit" or e["mode"] == "160000":
        return "submodule"
    if e["mode"] == "120000":
        return "symlink"
    if e["type"] != "blob":
        return "non_blob"
    if SKIP_DIR.search(e["path"]):
        return "skip_dir"
    if SKIP_FILE.search(e["path"]):
        return "skip_file"
    if os.path.splitext(e["path"])[1].lower() not in TEXT_EXT:
        return "extension"
    if e["sha"] == EMPTY_BLOB:
        return "empty"
    return None


def classify(path, data):
    """Per-file licence step on content. -> (None, text) when the file is kept, else (reason, None)."""
    if b"\x00" in data:
        return "binary", None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "invalid_utf8", None
    head = data[:2048].decode("utf-8", "replace")
    if OTHER_LIC.search(head):
        return "other_licence_header", None
    if GENERATED.search(head):
        return "generated", None
    if any(len(l) > MAX_LINE for l in text.split("\n")):
        return "long_line", None
    return None, text


def parse_batch(raw, wanted):
    """`git cat-file --batch` output -> {sha: bytes} for the blobs that came back AND hash to their name (git blob hash re-computed). A missing or corrupt blob is simply absent."""
    out, i, want = {}, 0, set(wanted)
    while i < len(raw):
        j = raw.find(b"\n", i)
        if j < 0:
            break
        head = raw[i:j].decode("ascii", "replace").split(); i = j + 1
        if len(head) < 3 or head[1] != "blob":
            continue
        n = int(head[2]); data = raw[i:i + n]; i += n + 1
        if head[0] in want and len(data) == n and hashlib.sha1(b"blob %d\x00" % n + data).hexdigest() == head[0]:
            out[head[0]] = data
    return out


def fetch_and_read(runner, clone, shas, after_chunk=None):
    """shas -> {sha: bytes}: the wanted blobs are fetched into the promisor clone CHUNK_N at a time, then read locally. after_chunk() runs after each chunk (the staging measurement)."""
    got, uniq = {}, list(dict.fromkeys(shas))
    for i in range(0, len(uniq), CHUNK_N):
        ch = uniq[i:i + CHUNK_N]; stdin = ("\n".join(ch) + "\n").encode()
        # the same options git's own lazy promisor fetch uses: without negotiation=noop GitHub answers 'did not send all necessary objects' for an explicit blob want
        runner.git(["-c", "fetch.negotiationAlgorithm=noop", "fetch", "origin", "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none", "--stdin"], clone, input=stdin)
        got.update(parse_batch(runner.git(["cat-file", "--batch"], clone, input=stdin), ch))
        if after_chunk:
            after_chunk()
    return got


# ------------------------------------------------------------------ output shard
class Shard:
    """One repo's docs shard: <name>.jsonl.zst.part, replaced into place on close (abort leaves only the .part, which the next attempt overwrites)."""

    def __init__(self, path, need_bytes, log=_log):
        self.path, self.part, self.need, self.log, self.w, self.fo = path, path + ".part", need_bytes, log, None, None

    def open(self):
        if not reserve_plan.write_gate("gh_snapshot_fetch shard " + os.path.basename(self.path), self.need, log=self.log, floor_fn=reserve_plan.floor_gib):
            raise DiskFloor("write_gate refused: B: below the reserve floor; shard not written")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fo = open(self.part, "wb")
        self.w = zstandard.ZstdCompressor(level=6).stream_writer(self.fo, closefd=False)
        return self

    def write(self, rows):
        self.w.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))

    def close(self):
        self.w.close(); self.fo.flush(); os.fsync(self.fo.fileno()); self.fo.close()
        os.replace(self.part, self.path)

    def abort(self):
        try:
            self.w.close(); self.fo.close()
        except Exception:
            pass


# ------------------------------------------------------------------ engine
class Reservation:
    def __init__(self, n):
        self.n, self.peak_dir = n, 0


class Budget:
    """Shared resident-bytes budget. A repo reserves its predicted need before it starts and waits while that would pass the cap (a lone repo always runs: its need is <= cap by construction);
    grow() raises one repo's reservation to what was MEASURED on disk, waiting for room, or raises StagingOverBudget."""

    def __init__(self, cap, wait_s=900):
        self.cap, self.wait_s, self.used, self.peak, self.cv = cap, wait_s, 0, 0, threading.Condition()

    def acquire(self, n, stop):
        with self.cv:
            while self.used and self.used + n > self.cap:
                if stop.is_set():
                    return None
                self.cv.wait(timeout=1.0)
            if stop.is_set():
                return None
            self.used += n; self.peak = max(self.peak, self.used)
            return Reservation(n)

    def grow(self, res, want, stop):
        with self.cv:
            if want > self.cap:
                raise StagingOverBudget("measured %d B (+ one chunk) does not fit under the %d B staging cap" % (want, self.cap))
            t0 = time.time()
            while self.used - res.n + want > self.cap:
                if stop.is_set() or time.time() - t0 > self.wait_s:
                    raise StagingOverBudget("no room to raise a reservation to %d B under the %d B cap (in use %d)" % (want, self.cap, self.used))
                self.cv.wait(timeout=1.0)
            self.used += want - res.n; res.n = want; self.peak = max(self.peak, self.used)

    def release(self, res):
        with self.cv:
            self.used -= res.n if isinstance(res, Reservation) else res; self.cv.notify_all()


def measure_staging(eng, res, clone):
    """The staging bound is MEASURED: dir size of the clone now; the reservation is raised to it plus one chunk of headroom when it is below that."""
    n = dir_bytes(clone); res.peak_dir = max(res.peak_dir, n)
    if n + CHUNK_BYTES > res.n:
        eng.budget.grow(res, n + CHUNK_BYTES, eng.stop)
    return n


class Engine:
    def __init__(self, lane, runner=None, workers=None, clock=time.time, budget_cap=None, log=_log, stop_after=None, stop_hours=None, grow_wait_s=900, form="snapshot", max_size_mb=None):
        self.form = form; self.head = form == "head"
        self.p = Paths(lane, form); self.runner = runner or Runner(low_priority=self.head); self.clock = clock; self.log = log
        self.workers = workers if workers is not None else (HEAD_WORKERS if self.head else 4)
        self.rules, self.source_class, self.authority = (HEAD_RULES_VERSION, HEAD_SOURCE_CLASS, HEAD_AUTHORITY) if self.head else (RULES_VERSION, SOURCE_CLASS, AUTHORITY)
        self.kind = ("code-head" if self.head else "code-snapshot") + " staging clone, refetchable from the catalogue commit"
        mb = max_size_mb if max_size_mb is not None else (HEAD_MAX_SIZE_MB if self.head else None); self.max_size_kb = None if mb is None else mb * 1024
        self.budget = Budget(BUDGET_CAP if budget_cap is None else budget_cap, grow_wait_s); self.stop = threading.Event(); self.lock = threading.Lock()
        default_after = HEAD_STOP_AFTER if self.head else STOP_AFTER
        self.stop_after, self.stop_hours = (default_after if stop_after is None else stop_after), (STOP_HOURS if stop_hours is None else stop_hours)
        self.totals, self.finished, self.pending_total, self.errors, self.deferred = [], 0, 0, 0, 0
        self.fatal, self.floor_hit, self.stop_rule = None, False, None
        self.run_t0 = None; self.states, self.attr = collections.Counter(), collections.Counter()

    # ---- one repo
    def process_repo(self, row, wid=0):
        """Everything for one repo: reserve staging, clone, wall commit, ancestry, licence, files, shard, ledger row, then the staging dir is removed. -> the ledger row.
        Raises WallViolation (nothing written for the repo), DiskFloor, StagingOverBudget, BlobUnavailable or RunnerError (no row: redone next run)."""
        t0 = self.clock(); repo = row["full_name"]; need = predicted_need(row)
        res = self.budget.acquire(need, self.stop)
        if res is None:
            raise Stopped()
        clone = "%s/w%d/%s-%s" % (self.p.stage, wid, repo.replace("/", "__"), row["commit_sha"][:12])
        try:
            if not reserve_plan.write_gate("gh_snapshot_fetch clone " + repo, max(self.budget.used, need), log=self.log, cap_s=3600, floor_fn=reserve_plan.floor_gib):
                raise DiskFloor("write_gate refused: B: below the reserve floor for the whole gate cap; %s not cloned" % repo)
            remove_staging(clone, self.p.stage, self.p.removes, repo, self.authority, self.kind)            # a crashed earlier attempt left its dir: redo from scratch
            led = self._snapshot(row, clone, res)
            led.update(total_s=round(self.clock() - t0, 3), ts=now_z(), staging_peak_bytes=res.peak_dir, rules_version=self.rules, source_class=self.source_class, scan_state="NOT_SCANNED")
            if self.head:
                led["form"] = "head"
            append_row(self.p.ledger, led, sync=True)
        finally:
            try:
                remove_staging(clone, self.p.stage, self.p.removes, repo, self.authority, self.kind)
            finally:
                self.budget.release(res)
        return led

    def _skip(self, led, reason):
        led["skipped_reason"] = reason
        return led

    def _clone(self, row, clone):
        """Blobless clone. Head form: one retry after a failure (the partial dir is removed first); a repo-gone answer is final at once."""
        for attempt in range(2 if self.head else 1):
            try:
                self.runner.git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", row["url"], clone])
                return
            except RunnerError as e:
                if GONE.search(str(e)) or attempt or not self.head:
                    raise
                self.log("clone of %s failed (%s); one retry" % (row["full_name"], str(e)[:120]))
                remove_staging(clone, self.p.stage, self.p.removes, row["full_name"], self.authority, self.kind)

    def _snapshot(self, row, clone, res):
        repo, csha, r, head = row["full_name"], row["commit_sha"], self.runner, self.head
        if head:
            led = dict(repo=repo, catalog_commit_sha=csha, head_commit_ts=None, content_date_max=None, history_commits=None, history_truncated=None, licence_file_sha=None, tree_entries=None, bytes_kept=0, files_kept=0,
                       files_dropped={}, ineligible={}, skipped_reason=None, fetch_s=0.0, shard=None, agent_attribution=None)
        else:
            led = dict(repo=repo, catalog_commit_sha=csha, wall_commit=None, wall_commit_ts=None, wall_commit_author_ts=None, content_date_max=None, history_dates_not_monotone=None, history_commits=None, licence_file_sha=None, tree_entries=None, bytes_kept=0, files_kept=0,
                       files_dropped={}, ineligible={}, skipped_reason=None, fetch_s=0.0, shard=None)
        os.makedirs(os.path.dirname(clone), exist_ok=True)
        try:
            self._clone(row, clone)
        except RunnerError as e:
            if GONE.search(str(e)):
                return self._skip(led, "repo_unavailable")
            raise
        measure_staging(self, res, clone)
        try:
            r.git(["cat-file", "-e", csha + "^{commit}"], clone)
        except RunnerError:
            if head:
                raise CatalogueCommitMissing("catalogue commit %s is not reachable in the clone of %s" % (csha, repo))
            return self._skip(led, "catalog_commit_missing")
        if head:
            wsha = csha                                          # the tree to read is the catalogue commit itself: no wall commit, no ancestry check
            led["head_commit_ts"] = int(r.git(["show", "-s", "--format=%ct", csha], clone).decode().strip() or 0)
            led["content_date_max"] = _iso_day(led["head_commit_ts"])
            ents = list_tree(r, clone, wsha); led["tree_entries"] = len(ents)
            attr, led["history_commits"], led["history_truncated"] = agent_attribution(r, clone, csha, ents); led["agent_attribution"] = attr
            suf = "_at_head"
        else:
            wall = select_wall_commit(r, clone, csha)
            if wall is None:
                return self._skip(led, "no_pre_wall_history")
            wsha, wts = wall; led["wall_commit"], led["wall_commit_ts"] = wsha, wts
            hist = history_times(r, clone, wsha)
            led["wall_commit_author_ts"], led["history_commits"] = hist[0][1], len(hist)
            led["history_dates_not_monotone"] = any(ct >= WALL_TS or at >= WALL_TS for ct, at in hist)      # metadata only (owner 2026-11-11): recorded, never a skip
            led["content_date_max"] = _iso_day(max(max(ct, at) for ct, at in hist))
            ents = list_tree(r, clone, wsha); led["tree_entries"] = len(ents)
            suf = "_at_wall_commit"
        # licence: EVERY root licence file must be the MIT text
        root_lic = sorted((e for e in ents if e["type"] == "blob" and e["mode"] != "120000" and "/" not in e["path"] and LIC_ROOT.match(e["path"])), key=lambda e: e["path"])
        if not root_lic:
            return self._skip(led, "no_licence_file" + suf)
        led["licence_file_sha"] = root_lic[0]["sha"]
        sub = [e for e in ents if e["type"] == "blob" and e["mode"] != "120000" and "/" in e["path"] and LIC_ANY.search(e["path"])]
        t = self.clock()
        lic = fetch_and_read(r, clone, [e["sha"] for e in root_lic + sub], after_chunk=lambda: measure_staging(self, res, clone))
        led["fetch_s"] += self.clock() - t
        miss = [e["path"] for e in root_lic + sub if e["sha"] not in lic]
        if miss:
            raise BlobUnavailable("licence blob(s) unreadable: %s" % ", ".join(miss[:5]))
        verdict = [len(lic[e["sha"]]) <= LICENCE_READ_MAX and is_mit(lic[e["sha"]].decode("utf-8", "replace")) for e in root_lic]
        if not any(verdict):
            return self._skip(led, "licence_not_mit" + suf)
        if not all(verdict):
            return self._skip(led, "licence_mixed" + suf)
        # a subtree holding a non-MIT licence file is dropped whole
        bad = sorted({e["path"].rsplit("/", 1)[0] for e in sub if not (len(lic[e["sha"]]) <= LICENCE_READ_MAX and is_mit(lic[e["sha"]].decode("utf-8", "replace")))})
        inel, drops, cand = collections.Counter(), collections.Counter(), []
        for e in ents:
            why = ineligible_class(e)
            if why:
                inel[why] += 1
            elif os.path.splitext(e["path"])[1].lower() == ".ipynb":
                drops["ipynb"] += 1
            elif any(e["path"].startswith(d + "/") for d in bad):
                drops["subtree_non_mit_licence"] += 1
            else:
                cand.append(e)
        shard, w12, kept, unavail = None, wsha[:12], 0, 0
        spath = "%s/%s@%s.jsonl.zst" % (self.p.docs, repo.replace("/", "__"), w12)
        try:
            for i in range(0, len(cand), CHUNK_N):
                part = cand[i:i + CHUNK_N]; t = self.clock()
                data = fetch_and_read(r, clone, [e["sha"] for e in part], after_chunk=lambda: measure_staging(self, res, clone))
                led["fetch_s"] += self.clock() - t
                rows = []
                for e in part:
                    b = data.get(e["sha"])
                    if b is None:
                        unavail += 1; continue
                    if len(b) > MAX_FILE:
                        inel["too_large"] += 1; continue
                    if len(b) == 0:
                        inel["empty"] += 1; continue
                    why, text = classify(e["path"], b)
                    if why:
                        drops[why] += 1; continue
                    if head:
                        rows.append(dict(id="%s@%s:%s" % (repo, w12, e["path"]), text=text, repo=repo, path=e["path"], blob_sha=e["sha"], head_commit=wsha, content_date_max=led["content_date_max"], spdx="MIT", source_class=HEAD_SOURCE_CLASS, agent_attribution=led["agent_attribution"]))
                    else:
                        rows.append(dict(id="%s@%s:%s" % (repo, w12, e["path"]), text=text, repo=repo, path=e["path"], blob_sha=e["sha"], wall_commit=wsha, content_date_max=led["content_date_max"], spdx="MIT", source_class=SOURCE_CLASS))
                    led["bytes_kept"] += len(b); kept += 1
                if rows:
                    if shard is None:
                        shard = Shard(spath, predicted_need(row), log=self.log).open()
                    shard.write(rows)
            if unavail:
                raise BlobUnavailable("%d wanted blob(s) of %s could not be read from the clone" % (unavail, repo))
            if kept + sum(drops.values()) + sum(inel.values()) != len(ents):
                raise RuntimeError("accounting: kept %d + dropped %d + ineligible %d != tree entries %d" % (kept, sum(drops.values()), sum(inel.values()), len(ents)))
            if shard is not None:
                shard.close(); led["shard"] = os.path.basename(spath)
        except BaseException:
            if shard is not None:
                shard.abort()
            raise
        led["files_kept"], led["files_dropped"], led["ineligible"], led["fetch_s"] = kept, dict(drops), dict(inel), round(led["fetch_s"], 3)
        if not kept:
            led["skipped_reason"] = "no_eligible_files"
        return led

    # ---- the rolling run
    def _finish_head(self, led):
        """Head form: tally the terminal state and attribution; after the first stop_after repos of the run write + print the timing report (wall-clock rows/hour); predicted hours above the limit write the STOP file."""
        with self.lock:
            self.finished += 1
            self.states[led["skipped_reason"] or "kept"] += 1
            a = led.get("agent_attribution"); self.attr[a["state"] if isinstance(a, dict) else "unattributable"] += 1
            if self.finished == self.stop_after and self.stop_rule is None:
                elapsed = max(self.clock() - self.run_t0, 1e-9); rate = self.finished / elapsed * 3600; remaining = max(0, self.pending_total - self.finished)
                hours = remaining / rate if rate > 0 else float("inf")
                self.stop_rule = dict(repos=self.finished, rows_per_hour=round(rate, 3), predicted_hours=round(hours, 3), repos_remaining=remaining, limit_hours=self.stop_hours, workers=self.workers,
                                      attributed=self.attr["attributed"], none_stated=self.attr["none_stated"], skipped_reasons={k: v for k, v in self.states.items() if k != "kept"}, kept=self.states["kept"], ts=now_z())
                os.makedirs(os.path.dirname(self.p.timing), exist_ok=True)
                with open(self.p.timing, "w", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(self.stop_rule, indent=1) + "\n")
                print(json.dumps(self.stop_rule, indent=1), flush=True)
                if hours > self.stop_hours:
                    with open(self.p.stop, "w", encoding="utf-8", newline="\n") as f:
                        f.write(json.dumps(self.stop_rule, indent=1) + "\n")
                    self.stop.set(); self.log("STOP RULE: predicted %.1f h > %.1f h; workers stop" % (hours, self.stop_hours))
                else:
                    self.stop_rule["fired"] = False

    def summary(self):
        return dict(form=self.form, finished=self.finished, errors=self.errors, deferred=self.deferred, attributed=self.attr["attributed"], none_stated=self.attr["none_stated"],
                    skipped_reasons={k: v for k, v in self.states.items() if k != "kept"}, kept=self.states["kept"])

    def _finish(self, total_s):
        with self.lock:
            self.finished += 1
            if len(self.totals) < self.stop_after:
                self.totals.append(total_s)
            if len(self.totals) == self.stop_after and self.stop_rule is None:
                mean = sum(self.totals) / len(self.totals); remaining = max(0, self.pending_total - self.finished)
                hours = mean * remaining / self.workers / 3600
                self.stop_rule = dict(finished=len(self.totals), mean_total_s=round(mean, 3), repos_remaining=remaining, workers=self.workers, predicted_hours=round(hours, 3), limit_hours=self.stop_hours, ts=now_z())
                if hours > self.stop_hours:
                    os.makedirs(os.path.dirname(self.p.stop), exist_ok=True)
                    with open(self.p.stop, "w", encoding="utf-8", newline="\n") as f:
                        f.write(json.dumps(self.stop_rule, indent=1) + "\n")
                    self.stop.set(); self.log("STOP RULE: predicted %.1f h > %.1f h; workers stop" % (hours, self.stop_hours))
                else:
                    self.stop_rule["fired"] = False

    def _durable(self, kind, row, e):
        append_row(self.p.errors, dict(ts=now_z(), kind=kind, repo=row["full_name"], catalog_commit_sha=row["commit_sha"], error="%s: %s" % (type(e).__name__, str(e)[:300])), sync=True)

    def _work(self, wid, it):
        while not self.stop.is_set():
            with self.lock:
                row = next(it, None)
            if row is None:
                return
            try:
                led = self.process_repo(row, wid)
                self.log("done %s %s kept=%d/%dB %s=%s" % (row["full_name"], led["skipped_reason"] or "kept", led["files_kept"], led["bytes_kept"], "head" if self.head else "wall", ((row["commit_sha"] if self.head else led["wall_commit"]) or "-")[:12]))
                if self.head:
                    self._finish_head(led)
                else:
                    self._finish(led["total_s"])
            except Stopped:
                return
            except WallViolation as e:
                self.fatal = e; self.stop.set(); self._durable("wall_violation", row, e); self.log("WALL VIOLATION", row["full_name"], e)
            except DiskFloor as e:
                self.floor_hit = True; self.stop.set(); self._durable("disk_floor_stop", row, e); self.log(str(e))
            except Exception as e:
                with self.lock:
                    self.errors += 1
                self._durable(getattr(e, "kind", "error"), row, e)
                self.log("ERROR %s %s: %s (no ledger row; redone next run)" % (row["full_name"], type(e).__name__, str(e)[:200]))

    def run(self, limit=0, ignore_stop=False):
        if os.path.exists(self.p.stop) and not ignore_stop:
            self.log("STOP file exists (%s): the timing stop rule fired earlier; read it, then rerun with --ignore-stop" % self.p.stop)
            return 3
        if self.head:
            lower_priority()
        self.run_t0 = self.clock()
        done = done_keys(self.p.ledger)
        sel = [r for r in select_repos(self.p.catalog, self.max_size_kb) if row_key(r["full_name"], r["commit_sha"], self.rules) not in done]
        fits, self.deferred = [], 0
        for r in sel:
            why = "size_kb_missing" if not isinstance(r.get("size_kb"), (int, float)) else ("need_over_staging_cap" if predicted_need(r) > self.budget.cap else None)
            if why:
                self.deferred += 1
                append_row(self.p.deferred, dict(ts=now_z(), repo=r["full_name"], catalog_commit_sha=r["commit_sha"], reason=why, size_kb=r.get("size_kb"), need=predicted_need(r), cap=self.budget.cap), sync=True)
            else:
                fits.append(r)
        self.pending_total = len(fits)
        self.log("to do %d, deferred %d (size_kb missing or need > staging cap), already done %d, workers %d" % (len(fits), self.deferred, len(done), self.workers))
        it = iter(fits[:limit] if limit else fits)
        threads = [threading.Thread(target=self._work, args=(k, it), daemon=True) for k in range(self.workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.log("run end: finished %d, errors %d, deferred %d" % (self.finished, self.errors, self.deferred))
        if self.head:
            self.log("run end: attributed %d, none_stated %d, skipped %s" % (self.attr["attributed"], self.attr["none_stated"], dict(self.summary()["skipped_reasons"])))
        if self.fatal:
            return 4
        if self.floor_hit:
            return 2
        if self.stop.is_set():
            return 3
        return 1 if self.errors else 0


def status(lane, form="snapshot", max_size_mb=None):
    head = form == "head"; rules = HEAD_RULES_VERSION if head else RULES_VERSION
    mb = max_size_mb if max_size_mb is not None else (HEAD_MAX_SIZE_MB if head else None)
    p = Paths(lane, form); sel = select_repos(p.catalog, None if mb is None else mb * 1024); led = {row_key(r["repo"], r.get("catalog_commit_sha"), r.get("rules_version")): r for r in read_rows(p.ledger) if r.get("repo")}
    mine = [led[row_key(r["full_name"], r["commit_sha"], rules)] for r in sel if row_key(r["full_name"], r["commit_sha"], rules) in led]
    reasons = collections.Counter(r["skipped_reason"] or "kept" for r in mine); dropped, inel = collections.Counter(), collections.Counter()
    for r in mine:
        dropped.update(r.get("files_dropped") or {}); inel.update(r.get("ineligible") or {})
    stage = sum(dir_bytes(os.path.join(p.stage, d)) for d in os.listdir(p.stage)) if os.path.isdir(p.stage) else 0
    out = dict(rules_version=rules, selected=len(sel), in_ledger=len(mine), remaining=len(sel) - len(mine), terminal_states=dict(reasons), files_kept=sum(r["files_kept"] for r in mine), bytes_kept=sum(r["bytes_kept"] for r in mine),
               files_dropped=dict(dropped), ineligible=dict(inel), mean_total_s=round(sum(r["total_s"] for r in mine) / len(mine), 2) if mine else None, mean_fetch_s=round(sum(r["fetch_s"] for r in mine) / len(mine), 2) if mine else None,
               staging_resident_bytes=stage, stop_file=os.path.exists(p.stop))
    if head:
        sts = collections.Counter((r.get("agent_attribution") or {}).get("state", "unattributable") for r in mine)
        out.update(form="head", attributed=sts["attributed"], none_stated=sts["none_stated"], unattributable=sts["unattributable"], skipped_reasons={k: v for k, v in reasons.items() if k != "kept"}, max_size_mb=mb)
    print(json.dumps(out, indent=1)); return 0


def main(argv=None, runner=None, lane=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--limit", type=int, default=0); r.add_argument("--workers", type=int, default=None, help="default 4 (snapshot form), 8 (head form)"); r.add_argument("--ignore-stop", action="store_true")
    r.add_argument("--form", choices=("snapshot", "head"), default="snapshot"); r.add_argument("--max-size-mb", type=int, default=None, help="tranche cap on size_kb; default 100 in head form, none in snapshot form")
    s = sp.add_parser("status"); s.add_argument("--form", choices=("snapshot", "head"), default="snapshot"); s.add_argument("--max-size-mb", type=int, default=None)
    a = ap.parse_args(argv); lane = lane or LANE_ROOT
    if a.cmd == "status":
        return status(lane, a.form, a.max_size_mb)
    eng = Engine(lane, runner=runner, workers=a.workers, form=a.form, max_size_mb=a.max_size_mb); code = eng.run(limit=a.limit, ignore_stop=a.ignore_stop)
    if a.form == "head":
        print(json.dumps(eng.summary(), indent=1), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())

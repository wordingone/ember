# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pre-wall code snapshot fetch (D3, lead 82956): each clean-signal MIT repo of the catalogue taken AS OF its last commit before the 2022-11-01T00:00:00Z wall, kept only when every root licence file at that commit is MIT,
with a per-file licence step on the content, written as the source class "code, pre-wall snapshot".

Usage: python gh_snapshot_fetch.py run [--limit N] [--workers 4] [--ignore-stop]   |   python gh_snapshot_fetch.py status
Exit codes: 0 finished (or --limit reached), 1 finished but some repos errored (no ledger row; see loops/code-snapshot-errors.jsonl; rerun redoes them), 2 B: below the reserve floor (resumable), 3 timing stop rule fired (STOP file written) or a STOP file exists, 4 wall violation (a wall commit at or after the wall: nothing is written for it).

What the code establishes, and no more: the wall is a committer-time AND author-time wall over the WHOLE ancestry of the wall commit (every commit reachable from it is stamped strictly before 1667260800), and every file comes from that commit's tree by blob sha.
It does not establish that a file's content was written before the wall in any other sense (a pre-wall stamp can be forged; the check closes the honest back-dated / clock-reset cases).
Per repo (catalogue row = licence MIT and has_tests_root, has_ci, recent_commit_365d, not_fork, not_archived, not awesome_or_dump_flag; size_kb present):
  1. blobless clone (no checkout); wall commit = `git rev-list -1 --before=<2022-10-31T23:59:59Z> <catalogue commit>`. HARD CHECK its committer time < 1667260800 or WallViolation is raised (the run aborts, durable row kind wall_violation).
     No commit before the wall: skipped, reason no_pre_wall_history.
  2. ancestry: one `git log --format='%ct %at' <wall commit>`; any ancestor (the wall commit included) with committer OR author time >= the wall: skipped, reason history_dates_not_monotone (a row, not an abort). Both times of the wall commit go in the ledger.
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
Packing into tokenized shards is a later step; this script never touches pack.py. No model anywhere."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import os, sys, re, json, time, base64, hashlib, shutil, stat, subprocess, threading, argparse, collections
import zstandard
import lane_config
import reserve_plan

WALL_TS = 1667260800                       # 2022-11-01T00:00:00Z: a commit is inside the wall only when its committer time is STRICTLY before this
BEFORE_ISO = "2022-10-31T23:59:59Z"        # rev-list --before is inclusive; one second earlier keeps `<= BEFORE` identical to `< WALL_TS`
AUTHORITY = "lead 82956"
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

    def __init__(self, git_timeout=1800):
        self.git_timeout = git_timeout

    def git(self, args, cwd=None, input=None):
        """-> stdout bytes; RunnerError (with stderr) on a non-zero exit. Lazy promisor fetch is OFF for everything except clone and the explicit blob fetch: a missing object is then an error, never a silent per-object download."""
        cmd = ["git", "-c", "core.quotepath=false"] + (["-C", cwd] if cwd else []) + list(args)
        env = dict(os.environ); env["GIT_TERMINAL_PROMPT"] = "0"
        words = [a for a in args if not a.startswith("-") and "=" not in a]
        if not words or words[0] not in ("clone", "fetch"):
            env["GIT_NO_LAZY_FETCH"] = "1"
        p = subprocess.run(cmd, input=input, capture_output=True, timeout=self.git_timeout, env=env)
        if p.returncode != 0:
            raise RunnerError("git %s: %s" % (" ".join(map(str, args[:3])), p.stderr.decode("utf-8", "replace")[-300:]))
        return p.stdout


# ------------------------------------------------------------------ paths and files
class Paths:
    def __init__(self, lane):
        self.lane = lane.replace("\\", "/").rstrip("/")
        self.catalog = self.lane + "/catalog/gh-mit-candidates.jsonl"
        self.out = self.lane + "/code-snapshot"
        self.docs = self.out + "/docs"
        self.stage = self.out + "/staging"
        self.ledger = self.lane + "/loops/code-snapshot-ledger.jsonl"
        self.removes = self.lane + "/loops/code-snapshot-removes.jsonl"
        self.stop = self.lane + "/loops/code-snapshot-STOP.json"
        self.errors = self.lane + "/loops/code-snapshot-errors.jsonl"
        self.deferred = self.lane + "/loops/code-snapshot-deferred.jsonl"


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


def select_repos(catalog_path):
    """Catalogue rows that count: licence MIT and every clean signal (the 5,682-repo set); first row per repo wins. A missing signal key counts as NOT clean."""
    out, seen = [], set()
    for r in read_rows(catalog_path):
        s = r.get("signals") or {}
        clean = (s.get("has_tests_root") and s.get("has_ci") and s.get("recent_commit_365d") and s.get("not_fork") and s.get("not_archived") and not s.get("awesome_or_dump_flag", True))
        if r.get("licence_spdx") != "MIT" or not clean or not r.get("full_name") or not r.get("commit_sha") or not r.get("url") or r["full_name"] in seen:
            continue
        seen.add(r["full_name"]); out.append(r)
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


def remove_staging(path, stage, removes_path, repo="", authority=AUTHORITY):
    """Remove one repo's staging dir. The target must resolve strictly inside the staging tree (StagingEscape otherwise); the receipt row is written (fsynced) before the remove. -> bytes removed (0 when absent)."""
    rp = os.path.normcase(os.path.realpath(path)); rs = os.path.normcase(os.path.realpath(stage))
    if not rp.startswith(rs + os.sep) or rp == rs:
        raise StagingEscape("%s is not strictly inside the staging tree %s" % (path, stage))
    if not os.path.lexists(path):
        return 0
    n = dir_bytes(path)
    append_row(removes_path, dict(ts=now_z(), path=os.path.abspath(path).replace("\\", "/"), bytes=n, authority=authority, repo=repo, kind="code-snapshot staging clone, refetchable from the catalogue commit"), sync=True)

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
    def __init__(self, lane, runner=None, workers=4, clock=time.time, budget_cap=None, log=_log, stop_after=None, stop_hours=None, grow_wait_s=900):
        self.p = Paths(lane); self.runner = runner or Runner(); self.workers = workers; self.clock = clock; self.log = log
        self.budget = Budget(BUDGET_CAP if budget_cap is None else budget_cap, grow_wait_s); self.stop = threading.Event(); self.lock = threading.Lock()
        self.stop_after, self.stop_hours = (STOP_AFTER if stop_after is None else stop_after), (STOP_HOURS if stop_hours is None else stop_hours)
        self.totals, self.finished, self.pending_total, self.errors, self.deferred = [], 0, 0, 0, 0
        self.fatal, self.floor_hit, self.stop_rule = None, False, None

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
            remove_staging(clone, self.p.stage, self.p.removes, repo)            # a crashed earlier attempt left its dir: redo from scratch
            led = self._snapshot(row, clone, res)
            led.update(total_s=round(self.clock() - t0, 3), ts=now_z(), staging_peak_bytes=res.peak_dir, rules_version=RULES_VERSION, source_class=SOURCE_CLASS, scan_state="NOT_SCANNED")
            append_row(self.p.ledger, led, sync=True)
        finally:
            try:
                remove_staging(clone, self.p.stage, self.p.removes, repo)
            finally:
                self.budget.release(res)
        return led

    def _skip(self, led, reason):
        led["skipped_reason"] = reason
        return led

    def _snapshot(self, row, clone, res):
        repo, csha, r = row["full_name"], row["commit_sha"], self.runner
        led = dict(repo=repo, catalog_commit_sha=csha, wall_commit=None, wall_commit_ts=None, wall_commit_author_ts=None, history_commits=None, licence_file_sha=None, tree_entries=None, bytes_kept=0, files_kept=0,
                   files_dropped={}, ineligible={}, skipped_reason=None, fetch_s=0.0, shard=None)
        os.makedirs(os.path.dirname(clone), exist_ok=True)
        try:
            r.git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", row["url"], clone])
        except RunnerError as e:
            if GONE.search(str(e)):
                return self._skip(led, "repo_unavailable")
            raise
        measure_staging(self, res, clone)
        try:
            r.git(["cat-file", "-e", csha + "^{commit}"], clone)
        except RunnerError:
            return self._skip(led, "catalog_commit_missing")
        wall = select_wall_commit(r, clone, csha)
        if wall is None:
            return self._skip(led, "no_pre_wall_history")
        wsha, wts = wall; led["wall_commit"], led["wall_commit_ts"] = wsha, wts
        hist = history_times(r, clone, wsha)
        led["wall_commit_author_ts"], led["history_commits"] = hist[0][1], len(hist)
        if any(ct >= WALL_TS or at >= WALL_TS for ct, at in hist):
            return self._skip(led, "history_dates_not_monotone")
        ents = list_tree(r, clone, wsha); led["tree_entries"] = len(ents)
        # licence: EVERY root licence file must be the MIT text
        root_lic = sorted((e for e in ents if e["type"] == "blob" and e["mode"] != "120000" and "/" not in e["path"] and LIC_ROOT.match(e["path"])), key=lambda e: e["path"])
        if not root_lic:
            return self._skip(led, "no_licence_file_at_wall_commit")
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
            return self._skip(led, "licence_not_mit_at_wall_commit")
        if not all(verdict):
            return self._skip(led, "licence_mixed_at_wall_commit")
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
                    rows.append(dict(id="%s@%s:%s" % (repo, w12, e["path"]), text=text, repo=repo, path=e["path"], blob_sha=e["sha"], wall_commit=wsha, spdx="MIT", source_class=SOURCE_CLASS))
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
                self.log("done %s %s kept=%d/%dB wall=%s" % (row["full_name"], led["skipped_reason"] or "kept", led["files_kept"], led["bytes_kept"], (led["wall_commit"] or "-")[:12]))
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
        done = done_keys(self.p.ledger)
        sel = [r for r in select_repos(self.p.catalog) if row_key(r["full_name"], r["commit_sha"]) not in done]
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
        if self.fatal:
            return 4
        if self.floor_hit:
            return 2
        if self.stop.is_set():
            return 3
        return 1 if self.errors else 0


def status(lane):
    p = Paths(lane); sel = select_repos(p.catalog); led = {row_key(r["repo"], r.get("catalog_commit_sha"), r.get("rules_version")): r for r in read_rows(p.ledger) if r.get("repo")}
    mine = [led[row_key(r["full_name"], r["commit_sha"])] for r in sel if row_key(r["full_name"], r["commit_sha"]) in led]
    reasons = collections.Counter(r["skipped_reason"] or "kept" for r in mine); dropped, inel = collections.Counter(), collections.Counter()
    for r in mine:
        dropped.update(r.get("files_dropped") or {}); inel.update(r.get("ineligible") or {})
    stage = sum(dir_bytes(os.path.join(p.stage, d)) for d in os.listdir(p.stage)) if os.path.isdir(p.stage) else 0
    out = dict(rules_version=RULES_VERSION, selected=len(sel), in_ledger=len(mine), remaining=len(sel) - len(mine), terminal_states=dict(reasons), files_kept=sum(r["files_kept"] for r in mine), bytes_kept=sum(r["bytes_kept"] for r in mine),
               files_dropped=dict(dropped), ineligible=dict(inel), mean_total_s=round(sum(r["total_s"] for r in mine) / len(mine), 2) if mine else None, mean_fetch_s=round(sum(r["fetch_s"] for r in mine) / len(mine), 2) if mine else None,
               staging_resident_bytes=stage, stop_file=os.path.exists(p.stop))
    print(json.dumps(out, indent=1)); return 0


def main(argv=None, runner=None, lane=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--limit", type=int, default=0); r.add_argument("--workers", type=int, default=4); r.add_argument("--ignore-stop", action="store_true")
    sp.add_parser("status")
    a = ap.parse_args(argv); lane = lane or lane_config.LANE_ROOT
    if a.cmd == "status":
        return status(lane)
    return Engine(lane, runner=runner, workers=a.workers).run(limit=a.limit, ignore_stop=a.ignore_stop)


if __name__ == "__main__":
    sys.exit(main())

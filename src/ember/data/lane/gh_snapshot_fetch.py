# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Pre-wall code snapshot fetch (D3, lead 82956): each clean-signal MIT repo of the catalogue taken AS OF its last commit before the 2022-11-01T00:00:00Z wall, kept only when the repo is MIT at that commit,
with a per-file licence step on the content, written as the source class "code, pre-wall snapshot".

Usage: python gh_snapshot_fetch.py run [--limit N] [--workers 4] [--ignore-stop]   |   python gh_snapshot_fetch.py status
Exit codes: 0 finished (or --limit reached), 1 finished but some repos errored (no ledger row; see loops/code-snapshot-errors.jsonl; rerun redoes them), 2 B: below the reserve floor (resumable), 3 timing stop rule fired (STOP file written) or a STOP file exists, 4 wall violation (a wall commit at or after the wall: nothing is written for it).

Per repo, in order (catalogue row = licence MIT and has_tests_root, has_ci, recent_commit_365d, not_fork, not_archived, not awesome_or_dump_flag):
  1. blobless clone (no checkout); wall commit = `git rev-list -1 --before=<2022-10-31T23:59:59Z> <catalogue commit>` (committer time, strictly before the wall); HARD CHECK committer time < 1667260800 or WallViolation is raised.
     No commit before the wall: skipped, reason no_pre_wall_history.
  2. tree at the wall commit from the GitHub git-trees API (blobs only); truncated: skipped, reason tree_truncated.
  3. licence at the wall commit: the root LICENSE / LICENCE / COPYING / UNLICENSE blob(s) read through the blobs API. None: no_licence_file_at_wall_commit. No MIT text: licence_not_mit_at_wall_commit.
  4. eligible files = the measure_sample filters (TEXT_EXT, SKIP_DIR, SKIP_FILE, 1 byte .. MAX_FILE) applied to that tree.
  5. content is read BY BLOB SHA out of that tree (batch `git fetch --stdin` of the wanted blobs into the promisor clone, then `git cat-file --batch`, each blob's git hash re-computed): no post-wall content can enter.
  6. per-file licence step: .ipynb, subtrees holding a non-MIT LICENSE/COPYING, binary, other-licence header, generated, over-long line. Each drop has a reason; counts go in the ledger row.
  7. output under <lane>/code-snapshot/docs/<owner>__<name>@<wall12>.jsonl.zst (one shard per repo, tmp + replace) and one terminal ledger row per repo in <lane>/loops/code-snapshot-ledger.jsonl.
Resumable: a repo with a ledger row is never fetched again; a crashed repo (no row) is redone from scratch. All git / gh calls go through one injectable Runner. Staging (<lane>/code-snapshot/staging/w<k>/) is capped at 5 GiB resident
across workers (predicted need = size_kb x 1024 x 0.25 + 64 MiB reserved per repo), each repo's dir is removed right after its ledger row, inside the staging tree only, with a receipt row (loops/code-snapshot-removes.jsonl).
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
BUDGET_CAP = 5 << 30                       # resident staging bytes across all workers
NEED_FRACTION = 0.25
NEED_BASE = 64 << 20
STOP_AFTER = 50
STOP_HOURS = 8.0
CHUNK_BYTES = 64 << 20                     # blob bytes read per fetch + cat-file round
CHUNK_N = 1500
LICENCE_READ_MAX = 200000
MAX_LINE = 20000

# the measure_sample filters, copied (not imported) so the snapshot measures what the sample measured
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".java", ".kt", ".scala", ".rb", ".php", ".cs", ".swift", ".sh", ".md", ".rst", ".txt", ".ipynb", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".json", ".sql", ".r", ".jl", ".lua", ".cu", ".proto", ".html", ".css"}
SKIP_DIR = re.compile(r"(^|/)(node_modules|vendor|third_party|dist|build|\.git|__pycache__|site-packages|\.venv|venv)(/|$)")
SKIP_FILE = re.compile(r"(\.min\.(js|css)|\.lock|package-lock\.json|yarn\.lock|poetry\.lock|\.map|\.svg)$", re.I)
MAX_FILE = 1 << 20
MIT_TEXT = re.compile(r"Permission is hereby granted, free of charge|MIT License", re.I)
OTHER_LIC = re.compile(r"Apache License|GNU (Lesser |Affero )?General Public|Mozilla Public License|SPDX-License-Identifier:\s*(?!MIT)[A-Za-z]|BSD [23]-Clause|All rights reserved\.\s*(?!.*MIT)", re.I)
GENERATED = re.compile(r"DO NOT EDIT|Code generated|@generated")
LIC_ROOT = re.compile(r"^(licen[sc]e|copying|unlicense)(\.[a-z]+)?$", re.I)
LIC_ANY = re.compile(r"(^|/)(licen[sc]e|copying)(\.[a-z]+)?$", re.I)
GONE = re.compile(r"repository not found|returned error: 404|dmca|access blocked|repository unavailable", re.I)


def _log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class WallViolation(Exception):
    """A wall commit whose committer time is not strictly before the wall. Never continued with."""


class DiskFloor(Exception):
    """write_gate gave up: B: stayed below the reserve floor. Nothing was written; resumable."""


class StagingEscape(Exception):
    """A removal target outside the staging tree (or the tree itself)."""


class RunnerError(Exception):
    pass


class Runner:
    """Every git and gh subprocess of this script. Tests inject a fake with the same two methods."""

    def __init__(self, git_timeout=1800, gh_timeout=300):
        self.git_timeout, self.gh_timeout = git_timeout, gh_timeout

    def git(self, args, cwd=None, input=None):
        """-> stdout bytes; RunnerError (with stderr) on a non-zero exit."""
        cmd = ["git", "-c", "core.quotepath=false"] + (["-C", cwd] if cwd else []) + list(args)
        env = dict(os.environ); env["GIT_TERMINAL_PROMPT"] = "0"
        p = subprocess.run(cmd, input=input, capture_output=True, timeout=self.git_timeout, env=env)
        if p.returncode != 0:
            raise RunnerError("git %s: %s" % (" ".join(map(str, args[:3])), p.stderr.decode("utf-8", "replace")[-300:]))
        return p.stdout

    def gh_api(self, path):
        """-> parsed json of `gh api <path>` (auth is the gh CLI's own keyring)."""
        p = subprocess.run(["gh", "api", path], capture_output=True, timeout=self.gh_timeout)
        if p.returncode != 0:
            raise RunnerError("gh api %s: %s" % (path.split("?")[0], p.stderr.decode("utf-8", "replace")[-300:]))
        return json.loads(p.stdout)


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
    """Remove one repo's staging dir. The target must resolve strictly inside the staging tree (StagingEscape otherwise); the receipt row is written before the remove. -> bytes removed (0 when absent)."""
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


def eligible(path, size):
    if SKIP_DIR.search(path) or SKIP_FILE.search(path) or size < 1 or size > MAX_FILE:
        return False
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def classify(path, data):
    """Per-file licence step on content. -> (None, text) when the file is kept, else (reason, None)."""
    if b"\x00" in data:
        return "binary", None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", None
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


def fetch_and_read(runner, clone, items):
    """items [(sha, size)] -> {sha: bytes}: the wanted blobs are fetched into the promisor clone in one batch per chunk, then read locally."""
    got, chunk, nb = {}, [], 0
    uniq = list(dict(items).items())

    def flush(ch):
        shas = [s for s, _ in ch]
        stdin = ("\n".join(shas) + "\n").encode()
        # the same options git's own lazy promisor fetch uses: without negotiation=noop GitHub answers 'did not send all necessary objects' for an explicit blob want
        runner.git(["-c", "fetch.negotiationAlgorithm=noop", "fetch", "origin", "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none", "--stdin"], clone, input=stdin)
        got.update(parse_batch(runner.git(["cat-file", "--batch"], clone, input=stdin), shas))
    for s, n in uniq:
        if chunk and (nb + n > CHUNK_BYTES or len(chunk) >= CHUNK_N):
            flush(chunk); chunk, nb = [], 0
        chunk.append((s, n)); nb += n
    if chunk:
        flush(chunk)
    return got


def blob_api(runner, repo, sha):
    j = runner.gh_api("repos/%s/git/blobs/%s" % (repo, sha))
    return base64.b64decode(j.get("content", "")) if j.get("encoding", "base64") == "base64" else j.get("content", "").encode("utf-8")


# ------------------------------------------------------------------ output shard
class Shard:
    """One repo's docs shard: <name>.jsonl.zst.part, replaced into place on close."""

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


# ------------------------------------------------------------------ engine
class Budget:
    """Shared resident-bytes budget: a repo reserves its predicted need before it starts and waits while that would pass the cap (a lone repo always runs: its need is <= cap by construction)."""

    def __init__(self, cap):
        self.cap, self.used, self.cv = cap, 0, threading.Condition()

    def acquire(self, n, stop):
        with self.cv:
            while self.used and self.used + n > self.cap:
                if stop.is_set():
                    return False
                self.cv.wait(timeout=1.0)
            if stop.is_set():
                return False
            self.used += n
            return True

    def release(self, n):
        with self.cv:
            self.used -= n; self.cv.notify_all()


class Engine:
    def __init__(self, lane, runner=None, workers=4, clock=time.time, budget_cap=None, log=_log, stop_after=None, stop_hours=None):
        self.p = Paths(lane); self.runner = runner or Runner(); self.workers = workers; self.clock = clock; self.log = log
        self.budget = Budget(BUDGET_CAP if budget_cap is None else budget_cap); self.stop = threading.Event(); self.lock = threading.Lock()
        self.stop_after, self.stop_hours = (STOP_AFTER if stop_after is None else stop_after), (STOP_HOURS if stop_hours is None else stop_hours)
        self.totals, self.finished, self.pending_total, self.errors, self.deferred = [], 0, 0, 0, 0
        self.fatal, self.floor_hit, self.stop_rule = None, False, None

    # ---- one repo
    def process_repo(self, row, wid=0):
        """Everything for one repo: clone, wall commit, licence, files, shard, ledger row, then the staging dir is removed. -> the ledger row. Raises WallViolation (nothing written for the repo) or DiskFloor / RunnerError (no row: redone next run)."""
        t0 = self.clock(); repo = row["full_name"]
        if not reserve_plan.write_gate("gh_snapshot_fetch clone " + repo, predicted_need(row), log=self.log, cap_s=3600, floor_fn=reserve_plan.floor_gib):
            raise DiskFloor("write_gate refused: B: below the reserve floor for the whole gate cap; %s not cloned" % repo)
        clone = "%s/w%d/%s-%s" % (self.p.stage, wid, repo.replace("/", "__"), row["commit_sha"][:12])
        try:
            remove_staging(clone, self.p.stage, self.p.removes, repo)            # a crashed earlier attempt left its dir: redo from scratch
            led = self._snapshot(row, clone)
            led["total_s"] = round(self.clock() - t0, 3); led["ts"] = now_z()
            append_row(self.p.ledger, led, sync=True)
        finally:
            remove_staging(clone, self.p.stage, self.p.removes, repo)
        return led

    def _skip(self, led, reason):
        led["skipped_reason"] = reason
        return led

    def _snapshot(self, row, clone):
        repo, csha, r = row["full_name"], row["commit_sha"], self.runner
        led = dict(repo=repo, catalog_commit_sha=csha, wall_commit=None, wall_commit_ts=None, licence_file_sha=None, bytes_kept=0, files_kept=0, files_dropped={}, skipped_reason=None, fetch_s=0.0, shard=None)
        os.makedirs(os.path.dirname(clone), exist_ok=True)
        try:
            r.git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", row["url"], clone])
        except RunnerError as e:
            if GONE.search(str(e)):
                return self._skip(led, "repo_unavailable")
            raise
        try:
            r.git(["cat-file", "-e", csha + "^{commit}"], clone)
        except RunnerError:
            return self._skip(led, "catalog_commit_missing")
        wall = select_wall_commit(r, clone, csha)
        if wall is None:
            return self._skip(led, "no_pre_wall_history")
        wsha, wts = wall; led["wall_commit"], led["wall_commit_ts"] = wsha, wts
        tree = r.gh_api("repos/%s/git/trees/%s?recursive=1" % (repo, wsha))
        if tree.get("truncated"):
            return self._skip(led, "tree_truncated")
        ents = [e for e in tree.get("tree", []) if e.get("type") == "blob" and e.get("mode") != "120000" and e.get("path")]
        root_lic = sorted((e for e in ents if "/" not in e["path"] and LIC_ROOT.match(e["path"])), key=lambda e: e["path"])
        if not root_lic:
            return self._skip(led, "no_licence_file_at_wall_commit")
        led["licence_file_sha"] = root_lic[0]["sha"]
        mit = None
        for e in root_lic[:4]:
            if MIT_TEXT.search(blob_api(r, repo, e["sha"]).decode("utf-8", "replace")):
                mit = e["sha"]; break
        if mit is None:
            return self._skip(led, "licence_not_mit_at_wall_commit")
        led["licence_file_sha"] = mit
        drops = collections.Counter(); t = self.clock()
        # non-root licence files: a subtree holding a non-MIT one is dropped whole
        sub = [e for e in ents if "/" in e["path"] and LIC_ANY.search(e["path"])]
        small = [(e["sha"], e.get("size", 0)) for e in sub if e.get("size", 0) <= LICENCE_READ_MAX]
        lic = fetch_and_read(r, clone, small) if small else {}
        bad = sorted({e["path"].rsplit("/", 1)[0] for e in sub if e["sha"] not in lic or not MIT_TEXT.search(lic[e["sha"]].decode("utf-8", "replace"))})
        led["fetch_s"] += self.clock() - t
        cand = []
        for e in ents:
            if not eligible(e["path"], e.get("size", 0)):
                continue
            if os.path.splitext(e["path"])[1].lower() == ".ipynb":
                drops["ipynb"] += 1
            elif any(e["path"].startswith(d + "/") for d in bad):
                drops["subtree_non_mit_licence"] += 1
            else:
                cand.append(e)
        shard, w12 = None, wsha[:12]
        spath = "%s/%s@%s.jsonl.zst" % (self.p.docs, repo.replace("/", "__"), w12)
        pos = 0
        while pos < len(cand):
            part, nb = [], 0
            while pos < len(cand) and len(part) < CHUNK_N and (not part or nb + cand[pos].get("size", 0) <= CHUNK_BYTES):
                part.append(cand[pos]); nb += cand[pos].get("size", 0); pos += 1
            t = self.clock()
            data = fetch_and_read(r, clone, [(e["sha"], e.get("size", 0)) for e in part])
            led["fetch_s"] += self.clock() - t
            rows = []
            for e in part:
                b = data.get(e["sha"])
                if b is None:
                    drops["blob_unavailable"] += 1; continue
                why, text = classify(e["path"], b)
                if why:
                    drops[why] += 1; continue
                rows.append(dict(id="%s@%s:%s" % (repo, w12, e["path"]), text=text, repo=repo, path=e["path"], blob_sha=e["sha"], wall_commit=wsha, spdx="MIT"))
                led["bytes_kept"] += len(b); led["files_kept"] += 1
            if rows:
                if shard is None:
                    shard = Shard(spath, predicted_need(row), log=self.log).open()
                shard.write(rows)
        if shard is not None:
            shard.close(); led["shard"] = os.path.basename(spath)
        led["files_dropped"] = dict(drops); led["fetch_s"] = round(led["fetch_s"], 3)
        if not led["files_kept"]:
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

    def _work(self, wid, it):
        while not self.stop.is_set():
            with self.lock:
                row = next(it, None)
            if row is None:
                return
            need = predicted_need(row)
            if not self.budget.acquire(need, self.stop):
                return
            try:
                led = self.process_repo(row, wid)
                self.log("done %s %s kept=%d/%dB wall=%s" % (row["full_name"], led["skipped_reason"] or "kept", led["files_kept"], led["bytes_kept"], (led["wall_commit"] or "-")[:12]))
                self._finish(led["total_s"])
            except WallViolation as e:
                self.fatal = e; self.stop.set(); self.log("WALL VIOLATION", row["full_name"], e)
            except DiskFloor as e:
                self.floor_hit = True; self.stop.set(); self.log(str(e))
            except Exception as e:
                with self.lock:
                    self.errors += 1
                append_row(self.p.errors, dict(ts=now_z(), repo=row["full_name"], error="%s: %s" % (type(e).__name__, str(e)[:300])))
                self.log("ERROR %s %s: %s (no ledger row; redone next run)" % (row["full_name"], type(e).__name__, str(e)[:200]))
            finally:
                self.budget.release(need)

    def run(self, limit=0, ignore_stop=False):
        if os.path.exists(self.p.stop) and not ignore_stop:
            self.log("STOP file exists (%s): the timing stop rule fired earlier; read it, then rerun with --ignore-stop" % self.p.stop)
            return 3
        done = {r["repo"] for r in read_rows(self.p.ledger) if r.get("repo")}
        sel = select_repos(self.p.catalog)
        fits = [r for r in sel if predicted_need(r) <= self.budget.cap]
        self.deferred = len(sel) - len(fits)
        todo = [r for r in fits if r["full_name"] not in done]
        self.pending_total = len(todo)
        self.log("selected %d, already in ledger %d, deferred (need > staging cap) %d, to do %d, workers %d" % (len(sel), len(done & {r["full_name"] for r in sel}), self.deferred, len(todo), self.workers))
        it = iter(todo[:limit] if limit else todo)
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
    p = Paths(lane); sel = select_repos(p.catalog); led = {r["repo"]: r for r in read_rows(p.ledger) if r.get("repo")}
    mine = [led[r["full_name"]] for r in sel if r["full_name"] in led]
    reasons = collections.Counter(r["skipped_reason"] or "kept" for r in mine); dropped = collections.Counter()
    for r in mine:
        dropped.update(r.get("files_dropped") or {})
    stage = sum(dir_bytes(os.path.join(p.stage, d)) for d in os.listdir(p.stage)) if os.path.isdir(p.stage) else 0
    out = dict(selected=len(sel), in_ledger=len(mine), remaining=len(sel) - len(mine), terminal_states=dict(reasons), files_kept=sum(r["files_kept"] for r in mine), bytes_kept=sum(r["bytes_kept"] for r in mine),
               files_dropped=dict(dropped), mean_total_s=round(sum(r["total_s"] for r in mine) / len(mine), 2) if mine else None, mean_fetch_s=round(sum(r["fetch_s"] for r in mine) / len(mine), 2) if mine else None,
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

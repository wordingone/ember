# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared helpers for the lane-14 CHK-adequacy hardening (R8 probe-faithfulness
audit, docs/goalforge-debate-ledger.md row R8; six hardenings queued there).

Not a probe itself -- filename deliberately does NOT start with "test_" so
src/ember/governance/scripts/ember_totality/ember_totality_spec.py's discover_tests() (which only
globs test_*.py in this directory, non-recursive) never tries to execute it
as a status probe. It IS still swept into the invariant_checksum's
enforcement_layer bucket (that walk is recursive over every *.py under this
package), so a silent edit here still shows up as a checksum change, same as
any probe file.

Two independent concerns live here:

  resolve_in_tree()   -- "reachable from the execution tree" (R8 finding:
                          "C4/C5 internally-consistent receipts, binding
                          artifacts off-tree"; docs/domains/governance/authority/GOAL.md's Execution-surface
                          row: "Imports owed FROM the live tree ... anti-gaming
                          S10"). A path that exists on disk elsewhere on this
                          machine but outside the probe's resolved ROOT is an
                          import-debt artifact, not verifiable evidence.

  parse_compact_ts()  -- shared parser for the "YYYYMMDDTHHMMSSZ" timestamp
                          convention used throughout this receipt corpus.
"""


import datetime
import hashlib
import os
import re
import subprocess
from pathlib import PurePosixPath


def redact_root(value):
    """Never let a resolved local absolute filesystem root (or a list of
    root candidates) reach a printed status line or receipt-bound reason
    string (issue #639: repo-guard's no-local-paths landing gate blocks any
    committed receipt containing one -- the #633 artifact-root plumbing
    introduced exactly this class of leak). Returns a diagnostic that
    discloses root IDENTITY via a short sha256 hash of the normalized value
    -- never the literal path -- so two runs against the same root are
    still comparable without ever naming the local disk layout (frozen
    spec, issue #639: token-or-hash, never the path).
    """
    def _hash_one(v):
        norm = str(v).strip().replace("\\", "/").rstrip("/").lower()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]

    if value is None:
        return "root=none"
    if isinstance(value, (list, tuple, set)):
        vals = [v for v in value if v]
        if not vals:
            return "0 candidate(s)"
        return f"{len(vals)} candidate(s) [sha12:" + ",".join(_hash_one(v) for v in vals) + "]"
    return f"sha12:{_hash_one(value)}"


def resolve_in_tree(path_str, root):
    """Return the absolute on-disk path if `path_str` resolves to a file that
    both EXISTS and is located under `root` (the execution tree); else None.

    Tries the path as given, with backslashes normalized, and as a
    WSL-mount-style rewrite of a Windows drive-letter path -- but in every
    case the final candidate must land under `root` or it is rejected. A
    file that verifiably exists on this machine at an absolute path outside
    `root` is treated exactly like a missing file: OFF-TREE, never trusted
    as in-tree evidence.
    """
    if not isinstance(path_str, str) or not path_str.strip():
        return None
    root_abs = os.path.abspath(root)
    raw = path_str.strip()
    norm = raw.replace("\\", "/")

    candidates = [raw, norm, os.path.join(root_abs, raw), os.path.join(root_abs, norm)]
    if len(norm) >= 2 and norm[1] == ":":
        drive = norm[0].lower()
        rest = norm[2:]
        candidates.append(f"/mnt/{drive}{rest}")
        candidates.append(f"/{drive}{rest}")

    for cand in candidates:
        try:
            cand_abs = os.path.abspath(cand)
        except (OSError, ValueError):
            continue
        if not os.path.isfile(cand_abs):
            continue
        try:
            common = os.path.commonpath([os.path.normcase(cand_abs), os.path.normcase(root_abs)])
        except ValueError:
            continue  # different drives on Windows -- definitely off-tree
        if os.path.normcase(common) == os.path.normcase(root_abs):
            return cand_abs
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

_REDACTION_PLACEHOLDER_RE = re.compile(r"<[^<>]*PATH[^<>]*>", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_LOCATOR_KEYS = {"schema_version", "repo_relative_path", "sha256"}


def is_redaction_degraded_locator(value):
    """True for historical display-redaction tokens, never real locators."""
    return isinstance(value, str) and bool(_REDACTION_PLACEHOLDER_RE.search(value))


def _check_content_locator(field, locator, root):
    if not isinstance(locator, dict) or set(locator) != _CONTENT_LOCATOR_KEYS:
        return False, f"{field}: content locator schema is not closed"
    if locator.get("schema_version") != "ember-content-locator-v1":
        return False, f"{field}: unsupported content locator schema"
    rel = locator.get("repo_relative_path")
    claimed_sha = locator.get("sha256")
    if is_redaction_degraded_locator(rel):
        return False, (
            f"REDACTION_DEGRADED: {field} carries historical placeholder "
            "evidence; AUDIT-PENDING until a resolvable content identity exists"
        )
    if (
        not isinstance(rel, str)
        or not rel
        or "\\" in rel
        or ":" in rel
        or not isinstance(claimed_sha, str)
        or not _SHA256_RE.fullmatch(claimed_sha)
    ):
        return False, f"{field}: malformed content locator"
    pure = PurePosixPath(rel)
    if (
        pure.is_absolute()
        or pure.as_posix() != rel
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        return False, f"{field}: content locator must be confined repo-relative"
    root_abs = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_abs, *pure.parts))
    try:
        common = os.path.commonpath(
            [os.path.normcase(candidate), os.path.normcase(root_abs)]
        )
    except ValueError:
        return False, f"{field}: content locator escapes the execution tree"
    if os.path.normcase(common) != os.path.normcase(root_abs):
        return False, f"{field}: content locator escapes the execution tree"
    if not os.path.isfile(candidate):
        return False, f"{field}: content locator target is missing"
    actual = sha256_file(candidate)
    if actual != claimed_sha:
        return False, (
            f"{field}: content locator sha256 {actual[:12]}.. != claimed "
            f"{claimed_sha[:12]}.."
        )
    return True, f"{field}: content locator resolved and hash-verified"


_COMPACT_TS_RE = re.compile(r"^(\d{8})T(\d{6})Z$")


def parse_compact_ts(s):
    """Parse 'YYYYMMDDTHHMMSSZ' -> naive UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    m = _COMPACT_TS_RE.match(s.strip())
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(0), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def check_path_sha_pairs(cand, root):
    """Verify legacy path/hash pairs or closed content-addressed locators.

    Historical redaction placeholders are explicitly degraded evidence and
    return a distinct fail-closed reason instead of behaving like ordinary
    missing files.
    """
    pairs = []
    locators = []
    for key in cand:
        if key.endswith("_path"):
            field = key[: -len("_path")]
            sha_key = f"{field}_sha256"
            if sha_key in cand:
                pairs.append((field, key, sha_key))
        elif key.endswith("_locator"):
            field = key[: -len("_locator")]
            locators.append((field, key))
    total = len(pairs) + len(locators)
    if not total:
        return False, 0, (
            "no <field>_path/<field>_sha256 pairs or closed content locators "
            "present on the candidate block"
        )

    details = []
    for field, locator_key in sorted(locators):
        ok, detail = _check_content_locator(field, cand.get(locator_key), root)
        if not ok:
            return False, total, detail
        details.append(detail)

    for field, path_key, sha_key in sorted(pairs):
        claimed_path = cand.get(path_key)
        claimed_sha = cand.get(sha_key)
        if is_redaction_degraded_locator(claimed_path):
            return False, total, (
                f"REDACTION_DEGRADED: {field}: {path_key} carries historical "
                "placeholder evidence; AUDIT-PENDING until a resolvable "
                "content identity exists"
            )
        if isinstance(claimed_path, str) and (
            os.path.isabs(claimed_path)
            or re.match(r"^[A-Za-z]:[\\/]", claimed_path)
        ):
            return False, total, (
                f"{field}: host-absolute path is noncanonical; content locator required"
            )
        if not (isinstance(claimed_sha, str) and claimed_sha):
            return False, total, f"{field}: {sha_key} missing/empty"
        on_disk = resolve_in_tree(claimed_path, root)
        if on_disk is None:
            return False, total, (
                f"{field}: {path_key}={claimed_path!r} resolves OFF-TREE/missing "
                f"under root ({redact_root(root)}) -- converges with docs/domains/governance/authority/GOAL.md's "
                "Execution-surface 'Imports owed FROM the live tree' row "
                "(anti-gaming S10 import debt); cannot verify in-tree"
            )
        actual = sha256_file(on_disk)
        if actual.lower() != claimed_sha.lower().replace("sha256:", ""):
            return False, total, (
                f"{field}: on-disk sha256 {actual[:12]}.. != claimed "
                f"{claimed_sha[:19]}.. at {path_key}"
            )
        details.append(f"{field}: path/sha pair verified in-tree")
    return True, total, f"{total} artifact binding(s) verified: " + "; ".join(details)


def sample_recompute_row(rows):
    """Pick the first row carrying a best_reward_table plus a
    b_template/c_selected_template pointer, and recompute b_score/c_score by
    looking up the matching template's `reward` field. Returns
    (ok: bool, detail: str). ok is False (not merely "unknown") when no row
    provides enough structure to recompute at all -- lane-14 hardening
    removes the free pass a stored-but-unverified score would otherwise get.
    """
    for idx, row in enumerate(rows):
        table = row.get("best_reward_table")
        if not isinstance(table, list) or not table:
            continue
        by_template = {}
        for entry in table:
            if isinstance(entry, dict) and "template" in entry and "reward" in entry:
                by_template[entry["template"]] = entry["reward"]
        if not by_template:
            continue

        checked = []
        ok = True
        for score_key, template_key in (("b_score", "b_template"),
                                         ("c_score", "c_selected_template")):
            claimed = row.get(score_key)
            template = row.get(template_key)
            if claimed is None or template is None:
                continue
            if template not in by_template:
                ok = False
                checked.append(f"{score_key}: template {template!r} not in best_reward_table")
                continue
            recomputed = by_template[template]
            if abs(float(recomputed) - float(claimed)) > 1e-6:
                ok = False
                checked.append(f"{score_key}: claimed={claimed} recomputed={recomputed} MISMATCH")
            else:
                checked.append(f"{score_key}={claimed} recomputed-match (template={template!r})")
        if not checked:
            continue
        return ok, f"row[{idx}] task_id={row.get('task_id')!r}: " + "; ".join(checked)

    return False, "no row carries a best_reward_table with a matching b/c template to recompute against"


def git_last_commit_time(repo_root, rel_or_abs_path):
    """Return (unix_ts_or_None, note). note is one of:
      'ok'            -- unix_ts is the last commit time (git log -1 %ct)
      'untracked'     -- git ran fine but the file has no commit history
      'git_unavailable' -- git missing / not a repo / call failed
    Never raises. Best-effort, disclosure-only helper -- callers decide
    whether/how to use the result; this function never fails a probe.
    """
    try:
        path_abs = os.path.abspath(rel_or_abs_path)
        rel = os.path.relpath(path_abs, repo_root)
    except (OSError, ValueError):
        return None, "git_unavailable"
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", rel],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "git_unavailable"
    if proc.returncode != 0:
        return None, "git_unavailable"
    out = (proc.stdout or "").strip()
    if not out:
        return None, "untracked"
    try:
        return int(out), "ok"
    except ValueError:
        return None, "git_unavailable"

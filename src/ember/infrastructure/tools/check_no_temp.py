#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_no_temp.py — the ember NO-TEMP policy gate.

Per operator direction (2026-07-20, verbatim): "Non of embers full stack, whether
current, past, or future should live in temp. none." The launch-blocker incident
(the owned-seat cockpit building its trusted-runtime snapshot in the OS-managed
system temp directory, whose casing on Windows does not match the real
filesystem case, breaking a case-sensitive path comparison) was a SYMPTOM. The
policy is: ember's stack must never use system temp at all.

This script scans ember source for the system-temp primitives named in the policy:
  - `os.tmpdir` / bare `tmpdir(` (TypeScript/JavaScript, `import { tmpdir } from "os"`)
  - `std::env::temp_dir` / `env::temp_dir` (Rust)
  - `mkdtemp` / `mkdtempSync` (Node) and `tempfile.mkdtemp` (Python)
  - `tempfile.gettempdir` (Python)
  - `tempfile.TemporaryDirectory(...)` / `tempfile.NamedTemporaryFile(...)` (or the
    bare `TemporaryDirectory(...)` / `NamedTemporaryFile(...)` forms after a
    `from tempfile import ...`) that do NOT pass an explicit in-tree `dir=` argument

A match is a violation UNLESS its file is listed in tools/no_temp_allowlist (one
relative POSIX path per line; the allowlist is a SHRINKING list — new files may never
be added to it going forward without an explicit exception; it exists only to let this
gate land before every known site is purged, per the policy's staged rollout).

FAIL-CLOSED: if matches exist anywhere in the scanned tree and the allowlist file is
missing, unreadable, or empty, this script exits non-zero. An empty allowlist is only
a valid "clean" state when the scan also finds zero matches.

Exit codes: 0 = clean (no unallowlisted matches); 1 = at least one unallowlisted
match (see stdout for path:line); 2 = usage/internal error.

The allowlist must shrink to empty. Every entry in it is a known, tracked debt site;
adding a NEW file to it without a purge plan is itself a policy violation.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "tools" / "no_temp_allowlist"

# Directories scanned (relative to repo root) — the current + prior + future ember
# stack surfaces named in the policy.
SCAN_DIRS = [
    "tools/ember-cli/src",
    "runtime/ember-lab/src",
    "tools/ember-restart-3b",
    "scripts",
]

# This script and its own allowlist file are self-referential (they must be allowed
# to say the words "tmpdir" / "temp_dir" / etc. in docstrings/comments/regexes
# without being flagged as violations of themselves).
SELF_EXCLUDE = {
    "src/ember/infrastructure/tools/check_no_temp.py",
    "tools/no_temp_allowlist",
}

# Extensions worth scanning; anything else (binaries, lockfiles, data) is skipped.
SCAN_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".rs"}

# Directories never descended into even under a scanned root.
SKIP_DIR_NAMES = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "target"}

SIMPLE_PATTERNS = [
    (re.compile(r"\bos\.tmpdir\s*\("), "os.tmpdir()"),
    (re.compile(r"(?<![.\w])tmpdir\s*\("), "tmpdir()"),
    (re.compile(r"std::env::temp_dir\s*\("), "std::env::temp_dir()"),
    (re.compile(r"(?<![.\w:])env::temp_dir\s*\("), "env::temp_dir()"),
    (re.compile(r"\bmkdtempSync\s*\("), "mkdtempSync()"),
    (re.compile(r"(?<![.\w])mkdtemp\s*\("), "mkdtemp()"),
    (re.compile(r"\bgettempdir\s*\("), "tempfile.gettempdir()"),
]

# Call-shaped patterns whose args must be inspected for an explicit dir= kwarg.
DIR_KWARG_PATTERN = re.compile(
    r"\b(TemporaryDirectory|NamedTemporaryFile)\s*\(([^)]*)\)"
)


def iter_scan_files():
    """Yield (absolute_path, repo_relative_posix_path) for tracked files under
    SCAN_DIRS only. Using `git ls-files` (rather than a filesystem walk) means
    untracked/gitignored scratch output (e.g. a throwaway probe file used to
    exercise this gate's fail-closed behavior) is never scanned, matching what
    CI actually sees in a checkout."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", *SCAN_DIRS],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"WARN: git ls-files failed ({exc}); falling back to filesystem walk", file=sys.stderr)
        for scan_dir in SCAN_DIRS:
            root = REPO_ROOT / scan_dir
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix not in SCAN_EXTENSIONS:
                    continue
                if any(part in SKIP_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts):
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                if rel in SELF_EXCLUDE:
                    continue
                yield path, rel
        return

    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel or rel in SELF_EXCLUDE:
            continue
        path = REPO_ROOT / rel
        if path.suffix not in SCAN_EXTENSIONS:
            continue
        if any(part in SKIP_DIR_NAMES for part in Path(rel).parts):
            continue
        if not path.is_file():
            continue
        yield path, rel


def load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.is_file():
        return set()
    entries: set[str] = set()
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return entries


LINE_COMMENT_MARKERS = {
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
    ".rs": "//",
    ".py": "#",
}

# Extensions with C-style /* ... */ block comments (JSDoc included).
BLOCK_COMMENT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs"}
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def blank_block_comments(text: str) -> str:
    """Blank the contents of /* ... */ block comments (JSDoc included) while
    preserving newlines, so line numbers stay accurate and a docstring that
    merely mentions a temp primitive (e.g. "replaces os.tmpdir()") is not
    itself flagged as a violation."""

    def _blank(match: re.Match) -> str:
        return "".join(ch if ch == "\n" else " " for ch in match.group(0))

    return BLOCK_COMMENT_RE.sub(_blank, text)


def strip_line_comment(line: str, marker: str | None) -> str:
    """Best-effort strip of a trailing line-comment so doc comments that merely
    MENTION a temp primitive (e.g. this gate's own source, or a helper's
    "replaces os.tmpdir()" docstring) are not themselves flagged as violations.
    Heuristic only: does not understand string literals containing the marker,
    nor block comments (/* */, \"\"\"...\"\"\"). Good enough for this gate's
    purpose — a real call site is executable code, not prose, and in practice
    does not collide with this trade-off."""
    if marker is None:
        return line
    idx = line.find(marker)
    return line if idx == -1 else line[:idx]


def find_violations_in_text(text: str, extension: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    marker = LINE_COMMENT_MARKERS.get(extension)
    if extension in BLOCK_COMMENT_EXTENSIONS:
        text = blank_block_comments(text)
    lines = text.splitlines()
    for lineno, raw_line in enumerate(lines, start=1):
        line = strip_line_comment(raw_line, marker)
        for pattern, label in SIMPLE_PATTERNS:
            if pattern.search(line):
                hits.append((lineno, label))
        for match in DIR_KWARG_PATTERN.finditer(line):
            call_name, args = match.group(1), match.group(2)
            if "dir=" not in args and "dir =" not in args:
                hits.append((lineno, f"{call_name}(...) without dir="))
    return hits


def main() -> int:
    allowlist = load_allowlist()
    allowlist_exists = ALLOWLIST_PATH.is_file()

    all_violations: dict[str, list[tuple[int, str]]] = {}
    for path, rel in iter_scan_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"WARN: could not read {rel}: {exc}", file=sys.stderr)
            continue
        hits = find_violations_in_text(text, path.suffix)
        if hits:
            all_violations[rel] = hits

    if not all_violations:
        print("check_no_temp: clean — no system-temp primitives found in scanned source.")
        return 0

    unallowlisted = {rel: hits for rel, hits in all_violations.items() if rel not in allowlist}

    if unallowlisted:
        print("check_no_temp: FAIL — system-temp usage found outside the allowlist:")
        for rel in sorted(unallowlisted):
            for lineno, label in unallowlisted[rel]:
                print(f"  {rel}:{lineno}: {label}")
        print(
            "\nEmber's NO-TEMP policy (per operator direction) forbids system temp anywhere "
            "in the stack. Route through emberScratchDir()/ember_scratch_dir(), or add the "
            "exact file to tools/no_temp_allowlist ONLY as a tracked, shrinking debt entry."
        )
        return 1

    if not allowlist_exists:
        # Matches exist, all of them happen to be in files that would be
        # allowlisted if the file existed — but it doesn't. Fail closed.
        print(
            "check_no_temp: FAIL (fail-closed) — matches exist but "
            f"{ALLOWLIST_PATH.relative_to(REPO_ROOT)} is missing.",
            file=sys.stderr,
        )
        return 1

    if not allowlist:
        # Allowlist file exists but is empty/all-comments, yet matches exist.
        print(
            "check_no_temp: FAIL (fail-closed) — matches exist but the allowlist is empty.",
            file=sys.stderr,
        )
        return 1

    print(
        f"check_no_temp: PASS — {sum(len(h) for h in all_violations.values())} match(es), "
        f"all covered by tools/no_temp_allowlist ({len(allowlist)} allowlisted file(s))."
    )
    for rel in sorted(all_violations):
        print(f"  allowlisted: {rel} ({len(all_violations[rel])} match(es))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

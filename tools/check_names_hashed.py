#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_names_hashed.py — hashed-denylist mode for tools/repo-guard.sh's names check.

Purpose: the plaintext names check (REPO_GUARD_NAMES env var or the git-ignored
tools/.repo-guard-denylist file) requires a secret or a local-only file, neither of
which is available in ordinary CI. This mode lets CI run the SAME check without ever
holding the plaintext names: a committed tools/repo-guard-denylist.sha256 file stores
one sha256 digest per lowercase name, never the name itself. This script tokenizes
tracked text files, hashes each candidate word, and compares against that committed
set. Nothing reversible is published; the denylist file can be safely committed.

Two modes:
  --generate            read a plaintext denylist (one name per line, '#'-comments and
                         blank lines ignored) and write its sha256 set. Use this to
                         (re)build tools/repo-guard-denylist.sha256 from a local-only
                         plaintext file; never run this in a context that would print
                         or commit the plaintext input.
  (default) check mode  tokenize tracked text files under --root and report any word
                         whose sha256 matches an entry in --denylist. This is the mode
                         tools/repo-guard.sh invokes.

Exit codes (check mode): 0 = clean; 1 = at least one match found (see stdout for
file:line); 3 = no usable denylist (file missing or empty after comment/blank
stripping) — the caller decides whether that is fail-closed (CI) or skip (local).
Exit codes (--generate mode): 0 = wrote the hash file; 3 = plaintext source missing
or empty.

Byte source for the scanned tracked-text CONTENT depends on REPO_GUARD_SCOPE,
mirroring the sibling legacy-name policy checker under tools/ and
tools/check_line_endings.py: under REPO_GUARD_SCOPE=staged (what
.githooks/pre-commit actually runs with), each file's content comes from the
git INDEX -- the exact bytes about to be committed, not the working tree.
Reading working-tree bytes unconditionally was a real gap: stage a name,
restore the working tree to a clean copy, and this check would scan the
(now clean) working tree while the commit that lands still carries the
staged name. The tracked-path LIST (`git ls-files`) is already index-derived
either way; only the per-file content read needed the scope branch.

Staged-scope reads are BATCHED via one `git cat-file --batch` process fed
every needed blob sha at once (`git ls-files -s` supplies the shas), not one
`git show :path` subprocess per file -- a per-file subprocess is correct but
measured too slow across a repo of this size. Non-staged scope is unchanged:
plain filesystem reads.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z]{3,}")

# Mirrors repo-guard.sh's own "${REPO_GUARD_SCOPE:-}" = "staged" test.
_STAGED = os.environ.get("REPO_GUARD_SCOPE", "") == "staged"

# Files the check never scans: the guard script and the hash list both legitimately
# mention the mechanism by name/shape without being a violation, and this script
# itself may carry example tokens in its own docstring/tests.
SELF_EXCLUDE = {
    "tools/repo-guard.sh",
    "tools/check_names_hashed.py",
    "tools/.repo-guard-denylist",
    "tools/.repo-guard-denylist.example",
    "tools/repo-guard-names-exclude.txt",
}
# Note: tools/repo-guard-denylist.sha256 is NOT excluded — its comments must be
# scanned to prevent raw names from appearing as metadata. Hash lines themselves
# are safe (hex tokens don't match founder names).

DEFAULT_NAMES_EXCLUDE = Path("tools/repo-guard-names-exclude.txt")


def sha256_lower(word: str) -> str:
    return hashlib.sha256(word.strip().lower().encode("utf-8")).hexdigest()


def load_denylist(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    hashes = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        hashes.add(line.lower())
    return hashes


def load_names_exclude_prefixes(path: Path) -> list[str]:
    """tools/repo-guard-names-exclude.txt: path-prefixes (one per line) exempt
    from the names scan only. Plaintext mode (tools/repo-guard.sh) reads the
    same file for its git-grep pathspec, so both modes exempt identically."""
    if not path.is_file():
        return []
    prefixes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefixes.append(line)
    return prefixes


def tracked_text_files(
    root: Path,
    exclude_prefixes: list[str] | None = None,
    *,
    scan_guard_surfaces: bool = False,
) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    prefixes = exclude_prefixes or []
    files = []
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if not rel or (not scan_guard_surfaces and rel in SELF_EXCLUDE):
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue
        files.append(rel)
    return files


def _staged_blob_shas(root: Path) -> dict[str, str]:
    """path -> index (stage 0) blob sha, via one `git ls-files -s` call for
    the whole tree -- avoids a subprocess per path."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s"], capture_output=True, text=True, check=True,
    )
    shas: dict[str, str] = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 2 or not path:
            continue
        shas[path] = parts[1]
    return shas


def _batch_read_blobs(root: Path, path_to_sha: dict[str, str]) -> dict[str, bytes]:
    """path -> blob bytes, via one `git cat-file --batch` process for every
    requested sha at once instead of one subprocess per file. Protocol per
    requested object: "<sha> <type> <size>\\n<content>\\n", or
    "<sha> missing\\n" if the object cannot be resolved (skipped)."""
    if not path_to_sha:
        return {}
    paths = list(path_to_sha.keys())
    stdin_data = ("\n".join(path_to_sha[p] for p in paths) + "\n").encode("utf-8")
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input=stdin_data, capture_output=True,
    )
    out = proc.stdout
    result: dict[str, bytes] = {}
    pos = 0
    for p in paths:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].decode("utf-8", errors="replace").split()
        if len(header) == 3:
            _sha, _type, size_s = header
            size = int(size_s)
            start = nl + 1
            result[p] = out[start:start + size]
            pos = start + size + 1  # skip the object's trailing newline
        else:
            # "<sha> missing" (or any other unexpected shape) -- one line, no body.
            pos = nl + 1
    return result


def is_probably_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def run_check(
    root: Path,
    denylist_path: Path,
    names_exclude_path: Path | None = None,
    *,
    scan_guard_surfaces: bool = False,
) -> int:
    denylist = load_denylist(denylist_path)
    if not denylist:
        print(f"skip [names-hashed] no usable denylist at {denylist_path}")
        return 3

    exclude_prefixes = load_names_exclude_prefixes(names_exclude_path or (root / DEFAULT_NAMES_EXCLUDE))
    rel_paths = tracked_text_files(
        root, exclude_prefixes, scan_guard_surfaces=scan_guard_surfaces
    )

    if _STAGED:
        shas = _staged_blob_shas(root)
        blobs = _batch_read_blobs(root, {rel: shas[rel] for rel in rel_paths if rel in shas})
        reader = blobs.get
    else:
        def reader(rel: str) -> bytes | None:
            try:
                return (root / rel).read_bytes()
            except OSError:
                return None

    findings: list[str] = []
    for rel in rel_paths:
        data = reader(rel)
        if data is None or not is_probably_text(data):
            continue
        try:
            lines = data.decode("utf-8", errors="strict").splitlines()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(lines, start=1):
            for tok in TOKEN_RE.findall(line):
                if sha256_lower(tok) in denylist:
                    findings.append(f"{rel}:{lineno}")
                    break  # one hit per line is enough to flag it

    if findings:
        print(f"FAIL [names-hashed] {len(findings)} match(es) against hashed denylist")
        for f in findings[:20]:
            print(f"      {f}")
        return 1
    print(f"ok   [names-hashed] none found ({len(denylist)} hashed entries checked)")
    return 0


def run_generate(plaintext_path: Path, out_path: Path) -> int:
    if not plaintext_path.is_file():
        print(f"FAIL [names-hashed:generate] plaintext source not found: {plaintext_path}")
        return 3
    names = []
    for line in plaintext_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    if not names:
        print(f"FAIL [names-hashed:generate] plaintext source has no usable entries: {plaintext_path}")
        return 3
    hashes = sorted({sha256_lower(n) for n in names})
    header = (
        "# repo-guard hashed name denylist — GENERATED, committed, contains NO names.\n"
        "# One sha256(lowercase-name) per line. Regenerate with:\n"
        "#   python tools/check_names_hashed.py --generate "
        "--denylist-plain <local-plaintext-file> --out tools/repo-guard-denylist.sha256\n"
    )
    out_path.write_text(header + "\n".join(hashes) + "\n", encoding="utf-8", newline="\n")
    print(f"ok   [names-hashed:generate] wrote {len(hashes)} hash(es) to {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, help="repo root to scan (default: git toplevel)")
    ap.add_argument("--denylist", default=None, help="path to the committed .sha256 file")
    ap.add_argument("--generate", action="store_true", help="build the .sha256 file from a plaintext source")
    ap.add_argument("--denylist-plain", default=None, help="(--generate mode) plaintext source, one name per line")
    ap.add_argument("--out", default=None, help="(--generate mode) output .sha256 path")
    ap.add_argument("--names-exclude", default=None, help="path-prefix exclusion list (default: tools/repo-guard-names-exclude.txt)")
    ap.add_argument(
        "--scan-guard-surfaces",
        action="store_true",
        help="scan subject guard/helper files when the trusted kernel is a separate checkout",
    )
    args = ap.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        root = Path(top.stdout.strip() or ".").resolve()

    if args.generate:
        plain = Path(args.denylist_plain) if args.denylist_plain else root / "tools" / ".repo-guard-denylist"
        out = Path(args.out) if args.out else root / "tools" / "repo-guard-denylist.sha256"
        return run_generate(plain, out)

    denylist_path = Path(args.denylist) if args.denylist else root / "tools" / "repo-guard-denylist.sha256"
    names_exclude_path = Path(args.names_exclude) if args.names_exclude else root / DEFAULT_NAMES_EXCLUDE
    return run_check(
        root,
        denylist_path,
        names_exclude_path,
        scan_guard_surfaces=args.scan_guard_surfaces,
    )


if __name__ == "__main__":
    sys.exit(main())

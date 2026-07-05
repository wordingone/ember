#!/usr/bin/env python3
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
"""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z]{3,}")

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


def tracked_text_files(root: Path, exclude_prefixes: list[str] | None = None) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    prefixes = exclude_prefixes or []
    files = []
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if not rel or rel in SELF_EXCLUDE:
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue
        files.append(rel)
    return files


def is_probably_text(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def run_check(root: Path, denylist_path: Path, names_exclude_path: Path | None = None) -> int:
    denylist = load_denylist(denylist_path)
    if not denylist:
        print(f"skip [names-hashed] no usable denylist at {denylist_path}")
        return 3

    exclude_prefixes = load_names_exclude_prefixes(names_exclude_path or (root / DEFAULT_NAMES_EXCLUDE))

    findings: list[str] = []
    for rel in tracked_text_files(root, exclude_prefixes):
        full = root / rel
        if not full.is_file() or not is_probably_text(full):
            continue
        try:
            lines = full.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeDecodeError):
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
    return run_check(root, denylist_path, names_exclude_path)


if __name__ == "__main__":
    sys.exit(main())

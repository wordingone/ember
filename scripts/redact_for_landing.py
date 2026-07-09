#!/usr/bin/env python3
"""Tracked, pin-aware redaction utility for landing lanes (ember issue #538).

The ONLY sanctioned redaction path for landing lanes. Rewrites only enumerated
path-valued JSON fields (or, for .md, whole lines) using a supplied term list.
A file whose sha256 is pinned by any receipt under receipts/ or
scripts/ember_totality/receipts-*/ is refused outright -- no override exists.

Usage:
    redact_for_landing.py --terms-file TERMS FILE [FILE ...]

Each output is written as a sibling "<stem>-redacted-edition<suffix>" file;
the input file itself is never modified (satisfies AC6 by construction).

Term-file format: one term per line, blank lines and '#' comments ignored.
"term<TAB>replacement" sets an explicit replacement; a bare term defaults to
the generic "<REDACTED>" placeholder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class RedactionRefusal(Exception):
    """Raised for any refusal path; carries the process exit code."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


# ---- AC3: in-script manifest of path-valued JSON field key names ----------
ENUMERATED_KEYS = {
    "path", "cache_source", "fork_dir", "receipt", "png",
    "capture_path", "cmdline", "script",
}
DOC_ALLOWLIST = {".md"}
DEFAULT_REPLACEMENT = "<REDACTED>"
_GLOB_CHARS = set("*?[")
_HEX64_RE = re.compile(rb"\b[0-9a-fA-F]{64}\b")
_JSON_STRING_RE = r'"(?:[^"\\]|\\.)*"'


def _build_kv_regex() -> "re.Pattern[str]":
    explicit = "|".join(sorted(re.escape(k) for k in ENUMERATED_KEYS))
    key_pattern = r'(?:' + explicit + r'|[A-Za-z0-9_]*_path)'
    pattern = (
        r'"(?P<key>' + key_pattern + r')"'
        r'(?P<sep>\s*:\s*)'
        r'(?P<value>' + _JSON_STRING_RE + r')'
    )
    return re.compile(pattern)


_KV_RE = _build_kv_regex()


def _check_not_glob(raw: str) -> None:
    if any(c in raw for c in _GLOB_CHARS):
        raise RedactionRefusal(
            f"glob pattern '{raw}' is refused -- pass explicit files only", 2
        )


def _check_file_arg(path: Path) -> None:
    if path.is_dir():
        raise RedactionRefusal(
            f"'{path}' is a directory -- explicit files only, no recursive mode", 2
        )
    if not path.exists():
        raise RedactionRefusal(f"no such file: '{path}'", 2)


def load_terms(terms_file: Path) -> List[Tuple[str, str]]:
    if not terms_file.is_file():
        raise RedactionRefusal(f"--terms-file not found: '{terms_file}'", 2)
    terms: List[Tuple[str, str]] = []
    for raw_line in terms_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            term, repl = line.split("\t", 1)
        else:
            term, repl = line, DEFAULT_REPLACEMENT
        term = term.strip()
        repl = repl.strip()
        if term:
            terms.append((term, repl))
    return terms


def apply_terms(text: str, terms: List[Tuple[str, str]]) -> str:
    """Word-boundary term substitution.

    A term matches only where neither the preceding nor following character
    is a word character -- implemented via lookaround rather than \\b so the
    boundary check is symmetric regardless of whether the term itself starts
    or ends on a word character (paths and bare names alike).
    """
    for term, repl in terms:
        if not term:
            continue
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])"
        )
        text = pattern.sub(repl, text)
    return text


def find_pin_source_files(repo_root: Path) -> List[Path]:
    files: List[Path] = []
    receipts_dir = repo_root / "receipts"
    if receipts_dir.is_dir():
        files.extend(sorted(receipts_dir.rglob("*.json")))
    totality_dir = repo_root / "scripts" / "ember_totality"
    if totality_dir.is_dir():
        for sub in sorted(totality_dir.glob("receipts-*")):
            if sub.is_dir():
                files.extend(sorted(sub.rglob("*.json")))
    return files


def build_pin_index(repo_root: Path) -> Dict[str, List[str]]:
    """hash (lowercase hex) -> relative paths of receipts that pin it."""
    index: Dict[str, List[str]] = {}
    for f in find_pin_source_files(repo_root):
        try:
            data = f.read_bytes()
        except OSError:
            continue
        for m in _HEX64_RE.finditer(data):
            h = m.group(0).decode("ascii").lower()
            try:
                rel = f.relative_to(repo_root).as_posix()
            except ValueError:
                rel = str(f)
            index.setdefault(h, []).append(rel)
    return index


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def redact_json_bytes(data: bytes, terms: List[Tuple[str, str]]) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RedactionRefusal(f"not valid UTF-8: {exc}", 2) from exc
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise RedactionRefusal(f"not valid JSON: {exc}", 2) from exc

    def _sub(m: "re.Match[str]") -> str:
        decoded = json.loads(m.group("value"))
        if not isinstance(decoded, str):
            return m.group(0)
        new_decoded = apply_terms(decoded, terms)
        if new_decoded == decoded:
            return m.group(0)
        new_literal = json.dumps(new_decoded, ensure_ascii=False)
        return f'"{m.group("key")}"{m.group("sep")}{new_literal}'

    new_text = _KV_RE.sub(_sub, text)
    return new_text.encode("utf-8")


_LINE_ENDING_RE = re.compile(r"(\r\n|\r|\n)$")


def redact_md_bytes(data: bytes, terms: List[Tuple[str, str]]) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RedactionRefusal(f"not valid UTF-8: {exc}", 2) from exc
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    for line in lines:
        m = _LINE_ENDING_RE.search(line)
        if m:
            body, ending = line[: m.start()], line[m.start():]
        else:
            body, ending = line, ""
        out.append(apply_terms(body, terms) + ending)
    return "".join(out).encode("utf-8")


def _detect_repo_root() -> Path:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return Path(res.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redact_for_landing.py",
        description="Tracked, pin-aware redaction utility for ember landing lanes (issue #538).",
    )
    parser.add_argument("files", nargs="+", help="explicit file paths -- no directories, no globs")
    parser.add_argument(
        "--terms-file", required=True, type=Path, dest="terms_file",
        help="one term per line; 'term<TAB>replacement', default replacement <REDACTED>",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=None, dest="repo_root",
        help="root for the pin-index scan (default: git toplevel, else cwd)",
    )
    return parser


def main(argv: List[str] = None, stdout=None, stderr=None) -> int:
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        for raw in args.files:
            _check_not_glob(raw)
        paths = [Path(raw) for raw in args.files]
        for p in paths:
            _check_file_arg(p)

        terms = load_terms(args.terms_file)
        repo_root = args.repo_root or _detect_repo_root()
        pin_index = build_pin_index(repo_root)

        # AC2: build the full pin index and check every input BEFORE
        # touching (writing) any of them -- refusal on one file must not
        # leave partial output from files processed earlier in argv.
        raw_bytes: Dict[Path, bytes] = {}
        for p in paths:
            data = p.read_bytes()
            raw_bytes[p] = data
            h = sha256_hex(data)
            if h in pin_index:
                pins = ", ".join(pin_index[h])
                raise RedactionRefusal(
                    f"'{p}' (sha256 {h}) is pinned by: {pins}", 3
                )

        for p in paths:
            data = raw_bytes[p]
            suffix = p.suffix.lower()
            if suffix == ".json":
                new_bytes = redact_json_bytes(data, terms)
            elif suffix in DOC_ALLOWLIST:
                new_bytes = redact_md_bytes(data, terms)
            else:
                raise RedactionRefusal(
                    f"unsupported file type '{suffix}' for '{p}'", 2
                )
            out_path = p.with_name(p.stem + "-redacted-edition" + p.suffix)
            out_path.write_bytes(new_bytes)
            print(f"redact_for_landing: wrote {out_path}", file=stdout)
    except RedactionRefusal as exc:
        print(f"redact_for_landing: REFUSED -- {exc.message}", file=stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())

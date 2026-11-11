#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reject redaction tokens that are executable string-format operands.

Scope under --staged (also the default under REPO_GUARD_SCOPE=staged, what
.githooks/pre-commit runs with): the verdict for a Python file is a function of
that file's bytes only, so a commit can change the verdict only for the .py
paths it stages. Staged scope therefore scans exactly the staged .py paths
(`git diff --cached --diff-filter=ACMRT`), reading the bytes that will be
committed from the git INDEX (one `git cat-file --batch`, not a `git show`
process per file). The tree-wide form (no flag, no REPO_GUARD_SCOPE) is
unchanged and is what CI (job `guard`, .github/workflows/repo-policy-gate.yml)
and the pre-push hook run: an offending .py file that is NOT staged is refused
there, not by the commit hook. Staged scope widens to every tracked .py (index
bytes) when a staged copy of this script changes the rule, or when git cannot
list the staged paths. Widening is announced and never narrows the check.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
from pathlib import Path

_PERCENT_REDACTION = re.compile(r"%<[^>\r\n]+>|%\[[^\]\r\n]+\]")
_BRACE_REDACTION = re.compile(r"\{<[^>}\r\n]+>\}|\{\[[^\]}\r\n]+\]\}")


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_source(source: str, *, display_path: str) -> list[str]:
    """Return actionable findings for one Python source string."""
    try:
        tree = ast.parse(source, filename=display_path)
    except SyntaxError:
        # This checker owns executable redaction semantics, not syntax.
        return []

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            template = _constant_string(node.left)
            if template:
                match = _PERCENT_REDACTION.search(template)
                if match:
                    findings.append(
                        f"{display_path}:{node.lineno}: redaction token "
                        f"{match.group(0)!r} is executable via percent formatting"
                    )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {"format", "format_map"}:
                continue
            template = _constant_string(node.func.value)
            if template:
                match = _BRACE_REDACTION.search(template)
                if match:
                    findings.append(
                        f"{display_path}:{node.lineno}: redaction token "
                        f"{match.group(0)!r} is executable via str.{node.func.attr}"
                    )
    return findings


def scan_python_file(path: Path, *, display_path: str | None = None) -> list[str]:
    source = path.read_text(encoding="utf-8-sig")
    return scan_source(source, display_path=display_path or path.as_posix())


def _tracked_python_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.py"],
        check=True,
        capture_output=True,
    )
    return [
        raw.decode("utf-8", errors="strict")
        for raw in proc.stdout.split(b"\0")
        if raw
    ]


def _index_sources(root: Path, relatives: list[str]) -> dict[str, str]:
    """path -> source as staged in the index, one `git ls-files -s -z` plus one
    `git cat-file --batch` for the whole set. A path with no stage-0 blob is
    absent from the result."""
    if not relatives:
        return {}
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z"], check=True, capture_output=True,
    )
    shas: dict[str, str] = {}
    for record in listing.stdout.split(b"\0"):
        meta, _, name = record.partition(b"\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[2] == b"0" and name:
            shas[name.decode("utf-8")] = parts[1].decode("ascii")
    wanted = [rel for rel in relatives if rel in shas]
    if not wanted:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=("\n".join(shas[rel] for rel in wanted) + "\n").encode("utf-8"),
        check=True,
        capture_output=True,
    )
    out = proc.stdout
    sources: dict[str, str] = {}
    pos = 0
    for rel in wanted:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].decode("utf-8", errors="replace").split()
        if len(header) == 3:
            size = int(header[2])
            start = nl + 1
            sources[rel] = out[start:start + size].decode("utf-8-sig", errors="strict")
            pos = start + size + 1  # skip the object's trailing newline
        else:
            pos = nl + 1  # "<sha> missing": one line, no body
    return sources


def check_repository(root: Path, *, staged: bool = False) -> list[str]:
    """Every tracked .py file: working-tree bytes, or index bytes when staged."""
    findings: list[str] = []
    relatives = _tracked_python_paths(root)
    if staged:
        for relative, source in _index_sources(root, relatives).items():
            findings.extend(scan_source(source, display_path=relative))
        return findings
    for relative in relatives:
        findings.extend(scan_python_file(root / relative, display_path=relative))
    return findings


def staged_changed_paths(root: Path) -> list[str] | None:
    """Paths the index adds, copies, modifies, renames (new name) or retypes against
    HEAD, or None when git cannot say (the caller then checks every tracked .py)."""
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return [n.decode("utf-8") for n in proc.stdout.split(b"\0") if n]
    except UnicodeDecodeError:
        return None


def scope_widening_reason(changed: list[str]) -> str | None:
    """Why staged scope must not be narrowed to `changed`, or None if it may be. The
    verdict for an unstaged .py file moves only if this rule moves."""
    own = Path(__file__).name
    for rel in changed:
        if rel.rsplit("/", 1)[-1].lower() == own.lower():
            return f"{rel} is staged (it decides the rule)"
    return None


def check_staged_changed(root: Path, changed: list[str]) -> list[str]:
    """Staged scope: only the staged .py paths, scanned on their index bytes."""
    python_paths = [rel for rel in changed if rel.lower().endswith(".py")]
    findings: list[str] = []
    for relative, source in _index_sources(root, python_paths).items():
        findings.extend(scan_source(source, display_path=relative))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--staged",
        action="store_true",
        default=os.environ.get("REPO_GUARD_SCOPE") == "staged",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.staged:
        changed = staged_changed_paths(root)
        reason = "git could not list the staged paths" if changed is None else scope_widening_reason(changed)
        if changed is not None and reason is None:
            findings = check_staged_changed(root, changed)
            note = (
                f"staged scope: {len([c for c in changed if c.lower().endswith('.py')])} staged .py of "
                f"{len(changed)} staged paths (tree-wide form runs in CI and pre-push)"
            )
        else:
            print(f"note [executable-redaction] staged scope widened to every tracked .py: {reason}")
            findings = check_repository(root, staged=True)
            note = "no executable redaction placeholders"
    else:
        findings = check_repository(root, staged=False)
        note = "no executable redaction placeholders"
    if findings:
        print("FAIL [executable-redaction] redaction placeholders are executable")
        for finding in findings[:20]:
            print(f"      {finding}")
        return 1
    print(f"PASS [executable-redaction] {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

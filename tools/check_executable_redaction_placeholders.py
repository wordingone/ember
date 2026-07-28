#!/usr/bin/env python3
"""Reject redaction tokens that are executable string-format operands."""

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


def _index_source(root: Path, relative: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f":{relative}"],
        check=True,
        capture_output=True,
    )
    return proc.stdout.decode("utf-8-sig", errors="strict")


def check_repository(root: Path, *, staged: bool = False) -> list[str]:
    findings: list[str] = []
    for relative in _tracked_python_paths(root):
        if staged:
            findings.extend(
                scan_source(_index_source(root, relative), display_path=relative)
            )
        else:
            findings.extend(
                scan_python_file(root / relative, display_path=relative)
            )
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
    findings = check_repository(Path(args.root).resolve(), staged=args.staged)
    if findings:
        print("FAIL [executable-redaction] redaction placeholders are executable")
        for finding in findings[:20]:
            print(f"      {finding}")
        return 1
    print("PASS [executable-redaction] no executable redaction placeholders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

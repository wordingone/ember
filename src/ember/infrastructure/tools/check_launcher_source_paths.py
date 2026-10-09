#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Refuse repository-root source paths that still name a pre-move location (#1116).

The CLI sources, the restart launch packet and the governance scripts moved under
src/ember/. A launcher that joins the old location from the repository root fails only
at run time ("This copy of the repository is incomplete"), so a clean checkout of
master could not start Ember. This check fails at review time instead.

Runtime STATE paths are deliberately not flagged: tools/ember-cli/state/ is a state
root that a writer (serving_registry.py) and its readers agree on, not a source path.

Usage: check_launcher_source_paths.py [ROOT]          scan tracked code under ROOT
       check_launcher_source_paths.py --text FILE...  scan the given files (reds)
Exit 0 = clean, 1 = stale path found, 2 = usage/IO error.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CODE_SUFFIXES = {".ts", ".ps1", ".cmd", ".bat", ".py", ".sh"}

# Each rule: (name, regex). A match is a stale source path joined from the repo root.
RULES = [
    # TS join form: join(x, "tools", "ember-cli", "src") or a bare installed-root marker,
    # unless the preceding segment is "infrastructure" or the next one is "state".
    ("ts-ember-cli-source",
     re.compile(r'(?<!"infrastructure", )"tools",\s*"ember-cli"(?!\s*,\s*"state")')),
    # PowerShell/cmd literal: "tools\ember-cli..." not preceded by infrastructure\.
    ("ps-ember-cli-source",
     re.compile(r'"(?:\.\\)?tools\\ember-cli(?!\\state)(?:\\[^"]*)?"')),
    # Moved restart launch packet.
    ("ts-launch-packet",
     re.compile(r'(?<!"infrastructure", )"tools",\s*"ember-restart-3b"')),
    # Moved governance scripts joined from the repository root.
    ("ts-governance-scripts",
     re.compile(r'(?<!"governance", )"scripts",\s*"ember_(?:restart|admission)"')),
]

# Lines that are comments carry history, not paths that run.
COMMENT = re.compile(r'^\s*(?://|#|\*|/\*|::|REM\b)', re.IGNORECASE)
# A deliberate pre-move fallback (read only when the canonical location is absent).
EXEMPT = "launcher-paths: legacy-fallback"
# Backslash literals are path syntax only in Windows shell files; in .py/.ts they are prose.
WINDOWS_SHELL = {".ps1", ".cmd", ".bat"}


def scan_text(path: str, text: str) -> list[str]:
    windows_shell = Path(path).suffix.lower() in WINDOWS_SHELL
    lines = text.splitlines()
    hits = []
    for number, line in enumerate(lines, 1):
        if COMMENT.match(line) or EXEMPT in line:
            continue
        # Join calls are often split one argument per line; read the next lines with
        # this one so `"scripts",\n    "ember_restart",` is seen as one join.
        # The previous lines are kept too, so a lookbehind segment ("infrastructure",)
        # on the line above still exempts this one. Only matches that START on this
        # line are reported, so each stale join is reported once.
        before = " ".join(p.strip() for p in lines[max(0, number - 4):number - 1])
        prefix = before + " " if before else ""
        current = line.strip()
        window = prefix + " ".join([current] + [p.strip() for p in lines[number:number + 3]])
        for name, rule in RULES:
            if name.startswith("ps-") and not windows_shell:
                continue
            for match in rule.finditer(window):
                if len(prefix) <= match.start() < len(prefix) + len(current):
                    hits.append(f"{path}:{number}: {name}: {current[:160]}")
                    break
    return hits


def tracked_code(root: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False)
    if out.returncode != 0:
        raise OSError(f"git ls-files failed rc={out.returncode}: {out.stderr.decode(errors='replace')[:200]}")
    files = []
    for rel in out.stdout.decode("utf-8").split("\0"):
        if not rel or Path(rel).suffix.lower() not in CODE_SUFFIXES:
            continue
        name = Path(rel).name
        # Tests may name old paths to prove they are refused; this file names them as rules.
        if ".test." in name or name.startswith("test_") or name == Path(__file__).name:
            continue
        files.append(root / rel)
    return files


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["--text"]:
            if len(argv) < 2:
                print("usage: --text FILE...", file=sys.stderr)
                return 2
            paths = [Path(p) for p in argv[1:]]
            label = {p: str(p) for p in paths}
        else:
            root = Path(argv[0] if argv else ".").resolve()
            paths = tracked_code(root)
            label = {p: p.relative_to(root).as_posix() for p in paths}
        hits = []
        for p in paths:
            hits += scan_text(label[p], p.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        print(f"LAUNCHER_SOURCE_PATHS_ERROR {exc}", file=sys.stderr)
        return 2
    if hits:
        print(f"LAUNCHER_SOURCE_PATHS_STALE {len(hits)}")
        print("\n".join(hits))
        return 1
    print(f"LAUNCHER_SOURCE_PATHS_OK files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

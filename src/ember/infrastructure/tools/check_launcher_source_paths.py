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

Usage: check_launcher_source_paths.py [--staged] [ROOT]  scan tracked code under ROOT
       check_launcher_source_paths.py --text FILE...     scan the given files (reds)
--staged reads the git INDEX bytes (what a commit lands), as repo-guard's REPO_GUARD_SCOPE=staged
requires; otherwise the working-tree bytes of the tracked files. Every git child is created with
no console window and its exit status and streams are checked.
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


def _hidden() -> dict:
    """Creation flags for a child with no console window (Windows); empty elsewhere."""
    if sys.platform != "win32":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startup}


def _git(root: Path, args: list[str], stdin: bytes | None = None) -> bytes:
    feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False, **feed, **_hidden())
    if out.returncode != 0:
        raise OSError(f"git {args[0]} failed rc={out.returncode}: {out.stderr.decode(errors='replace')[:200]}")
    return out.stdout


def tracked_code(root: Path) -> list[str]:
    files = []
    for rel in _git(root, ["ls-files", "-z"]).decode("utf-8").split("\0"):
        if not rel or Path(rel).suffix.lower() not in CODE_SUFFIXES:
            continue
        name = Path(rel).name
        # Tests may name old paths to prove they are refused; this file names them as rules.
        if ".test." in name or name.startswith("test_") or name == Path(__file__).name:
            continue
        files.append(rel)
    return files


def staged_bytes(root: Path, rels: list[str]) -> dict[str, bytes]:
    """Index bytes of each path, read in one `git cat-file --batch` child."""
    if not rels:
        return {}
    raw = _git(root, ["cat-file", "--batch"], stdin="".join(f":{rel}\n" for rel in rels).encode("utf-8"))
    result, offset = {}, 0
    for rel in rels:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise OSError(f"git cat-file: no staged blob for {rel}")
        size = int(header[2])
        result[rel] = raw[end + 1:end + 1 + size]
        offset = end + 1 + size + 1
    return result


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["--text"]:
            if len(argv) < 2:
                print("usage: --text FILE...", file=sys.stderr)
                return 2
            texts = {p: Path(p).read_text(encoding="utf-8", errors="replace") for p in argv[1:]}
        else:
            staged = argv[:1] == ["--staged"]
            rest = argv[1:] if staged else argv
            if len(rest) > 1:
                print("usage: [--staged] [ROOT]", file=sys.stderr)
                return 2
            root = Path(rest[0] if rest else ".").resolve()
            rels = tracked_code(root)
            if staged:
                texts = {rel: data.decode("utf-8", errors="replace") for rel, data in staged_bytes(root, rels).items()}
            else:
                texts = {rel: (root / rel).read_text(encoding="utf-8", errors="replace") for rel in rels}
        paths = list(texts)
        hits = []
        for label, text in texts.items():
            hits += scan_text(label, text)
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

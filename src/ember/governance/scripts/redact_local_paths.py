#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""First-landing JSON path hygiene for Ember receipts.

Every input is one explicitly named JSON file.  The writer converts paths
under the repository to forward-slash repo-relative paths and other
drive-rooted paths to ``local:<basename>``.  Existing files at the selected
base are refused unless a reasoned first-landing override is supplied.
"""

from __future__ import annotations

import argparse
import copy
import json
import ntpath
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ReceiptPathError(ValueError):
    """A receipt cannot be checked or normalized safely."""


_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_])([A-Z]:[\\/][^\s\"'<>|]*)"
)
_EXACT_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?is)^(\s*)([A-Z]:[\\/][^\r\n\"'<>|]*?)(\s*)$")
_TRAILING_PROSE = ".,;:)]}"
_NOTE_KEY = "redaction_note"
_NOTE_POLICY = "repo-relative-or-local-basename"


def _split_trailing_prose(token: str) -> tuple[str, str]:
    core = token
    trailing = ""
    while len(core) > 3 and core[-1] in _TRAILING_PROSE:
        trailing = core[-1] + trailing
        core = core[:-1]
    return core, trailing


def _repo_relative_or_local(token: str, repo_root: Path) -> str:
    core, trailing = _split_trailing_prose(token)
    native = os.path.normpath(core.replace("/", os.sep))
    repo_native = os.path.normpath(str(repo_root))
    try:
        inside = os.path.commonpath(
            [os.path.normcase(native), os.path.normcase(repo_native)]
        ) == os.path.normcase(repo_native)
    except ValueError:
        inside = False
    if inside:
        replacement = os.path.relpath(native, repo_native).replace("\\", "/")
    else:
        basename = ntpath.basename(core.replace("/", "\\"))
        replacement = f"local:{basename or 'drive-root'}"
    return replacement + trailing


def _rewrite_string(value: str, repo_root: Path) -> tuple[str, int]:
    exact = _EXACT_WINDOWS_ABSOLUTE_PATH.fullmatch(value)
    if exact:
        return (
            exact.group(1)
            + _repo_relative_or_local(exact.group(2), repo_root)
            + exact.group(3),
            1,
        )

    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _repo_relative_or_local(match.group(1), repo_root)

    return _WINDOWS_ABSOLUTE_PATH.sub(replace, value), count


def _normalize_value(value: Any, repo_root: Path) -> tuple[Any, int]:
    if isinstance(value, str):
        return _rewrite_string(value, repo_root)
    if isinstance(value, list):
        normalized: list[Any] = []
        count = 0
        for item in value:
            next_item, next_count = _normalize_value(item, repo_root)
            normalized.append(next_item)
            count += next_count
        return normalized, count
    if isinstance(value, dict):
        normalized_dict: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReceiptPathError("JSON object keys must be strings")
            next_key, key_count = _rewrite_string(key, repo_root)
            next_item, item_count = _normalize_value(item, repo_root)
            if next_key in normalized_dict:
                raise ReceiptPathError(
                    f"path normalization would collide at JSON key {next_key!r}"
                )
            normalized_dict[next_key] = next_item
            count += key_count + item_count
        return normalized_dict, count
    return value, 0


def normalize_json_paths(payload: Mapping[str, Any], repo_root: Path) -> tuple[dict[str, Any], int]:
    """Return a normalized copy and its path replacement count.

    The input must be a top-level object so the mandatory note can be added
    without changing the receipt's top-level type.
    """
    if not isinstance(payload, Mapping):
        raise ReceiptPathError("receipt JSON must be a top-level object")
    if _NOTE_KEY in payload:
        raise ReceiptPathError(
            "receipt already contains redaction_note; refusing to overwrite landing evidence"
        )
    root = Path(repo_root).resolve(strict=True)
    source = copy.deepcopy(dict(payload))
    normalized, count = _normalize_value(source, root)
    assert isinstance(normalized, dict)
    normalized[_NOTE_KEY] = {
        "policy": _NOTE_POLICY,
        "replacement_count": count,
    }
    return normalized, count


def _violation_locations(value: Any, location: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        if _WINDOWS_ABSOLUTE_PATH.search(value):
            found.append(location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_violation_locations(item, f"{location}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and _WINDOWS_ABSOLUTE_PATH.search(key):
                found.append(f"{location}.<key:{key}>")
            found.extend(_violation_locations(item, f"{location}.{key}"))
    return found


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptPathError(f"{path.name}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReceiptPathError(f"{path.name}: receipt JSON must be a top-level object")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _run_git(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _tracked_at_base(repo_root: Path, relative_path: str, base: str) -> bool:
    commit = _run_git(repo_root, ["cat-file", "-e", f"{base}^{{commit}}"])
    if commit.returncode != 0:
        raise ReceiptPathError(
            f"cannot resolve selected base {base!r}: {commit.stderr.strip()}"
        )
    listed = _run_git(repo_root, ["ls-tree", "-r", "--name-only", base, "--", relative_path])
    if listed.returncode != 0:
        raise ReceiptPathError(
            f"cannot inspect merge base {base!r}: {listed.stderr.strip()}"
        )
    return relative_path in listed.stdout.splitlines()


def _discover_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReceiptPathError("not inside a Git repository; pass --repo-root")
    return Path(result.stdout.strip()).resolve(strict=True)


def _validate_explicit_file(raw: str, repo_root: Path) -> tuple[Path, str]:
    if any(character in raw for character in "*?[]"):
        raise ReceiptPathError(f"{raw}: expected an explicit JSON file, not a glob")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if candidate.is_symlink():
        raise ReceiptPathError(f"{raw}: symlink inputs are forbidden")
    if not candidate.is_file() or candidate.suffix.lower() != ".json":
        raise ReceiptPathError(f"{raw}: expected an explicit JSON file")
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ReceiptPathError(f"{raw}: file is outside the repository") from exc
    return resolved, relative


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--first-landing-override",
        metavar="REASON",
        help="allow a base-tracked file only with a nonempty landing reason",
    )
    parser.add_argument("files", nargs="+", help="explicit JSON files; globs/directories refused")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo_root = (
            args.repo_root.resolve(strict=True)
            if args.repo_root is not None
            else _discover_repo_root()
        )
        if not repo_root.is_dir():
            raise ReceiptPathError("--repo-root must be a directory")
        if args.first_landing_override is not None and not args.first_landing_override.strip():
            raise ReceiptPathError("--first-landing-override requires a nonempty reason")

        report: list[dict[str, Any]] = []
        total = 0
        any_violation = False
        for raw in args.files:
            path, relative = _validate_explicit_file(raw, repo_root)
            payload = _load_json_object(path)
            violations = _violation_locations(payload)
            if args.check:
                count = len(violations)
                any_violation = any_violation or count > 0
                report.append(
                    {"path": relative, "redaction_count": count, "violations": violations}
                )
                total += count
                continue

            if _tracked_at_base(repo_root, relative, args.base) and not args.first_landing_override:
                raise ReceiptPathError(
                    f"{relative}: tracked at merge base {args.base}; "
                    "refusing append-only evidence rewrite"
                )
            normalized, count = normalize_json_paths(payload, repo_root)
            if args.first_landing_override:
                note = normalized[_NOTE_KEY]
                assert isinstance(note, dict)
                note["first_landing_override_reason"] = args.first_landing_override.strip()
            _atomic_write_json(path, normalized)
            report.append({"path": relative, "redaction_count": count})
            total += count

        print(
            json.dumps(
                {
                    "files": report,
                    "mode": "check" if args.check else "write",
                    "total_redactions": total,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1 if args.check and any_violation else 0
    except ReceiptPathError as exc:
        print(f"redact_local_paths: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

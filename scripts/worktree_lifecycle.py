#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed lifecycle manager for Ember's local Git worktrees."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence


STATE_NAME = "ember-worktree-lifecycle.json"
LOCK_NAME = "ember-worktree-lifecycle.lock"
DEFAULT_TARGET = 12


class LifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Worktree:
    path: str
    key: str
    head: str
    branch: str | None
    detached: bool


def canonical_path(value: str | Path) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def path_key(value: str | Path) -> str:
    return canonical_path(value).casefold()


def run_git(repo: Path, args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise LifecycleError("GIT_ERROR", f"git {' '.join(args)}: {detail}")
    return result


def parse_worktrees(text: str) -> list[Worktree]:
    rows: list[Worktree] = []
    fields: dict[str, Any] = {}

    def finish() -> None:
        if not fields:
            return
        raw_path = str(fields.get("worktree", ""))
        if not raw_path or not fields.get("HEAD"):
            raise LifecycleError("MALFORMED_GIT_OUTPUT", "incomplete git worktree record")
        resolved = canonical_path(raw_path)
        rows.append(
            Worktree(
                path=resolved,
                key=path_key(resolved),
                head=str(fields["HEAD"]),
                branch=fields.get("branch"),
                detached=bool(fields.get("detached", False)),
            )
        )

    for line in text.splitlines() + [""]:
        if not line:
            finish()
            fields = {}
        elif " " in line:
            name, value = line.split(" ", 1)
            fields[name] = value
        else:
            fields[line] = True
    return rows


def list_worktrees(repo: Path) -> list[Worktree]:
    result = run_git(repo, ["worktree", "list", "--porcelain"])
    rows = parse_worktrees(result.stdout)
    if not rows:
        raise LifecycleError("NO_WORKTREES", "Git returned no registered worktrees")
    return rows


def common_dir(repo: Path) -> Path:
    result = run_git(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    return Path(result.stdout.strip()).resolve(strict=True)


class RepositoryLock(AbstractContextManager["RepositoryLock"]):
    def __init__(self, path: Path):
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "RepositoryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise LifecycleError("LIFECYCLE_LOCKED", str(self.path)) from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def validate_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise LifecycleError("MALFORMED_STATE", "state must be a version-1 object")
    required = {"target", "ceiling", "main_path", "legacy_paths", "managed"}
    if not required.issubset(payload):
        raise LifecycleError("MALFORMED_STATE", "state is missing required fields")
    if not isinstance(payload["target"], int) or payload["target"] < 1:
        raise LifecycleError("MALFORMED_STATE", "target must be a positive integer")
    if not isinstance(payload["ceiling"], int) or payload["ceiling"] < payload["target"]:
        raise LifecycleError("MALFORMED_STATE", "ceiling must be an integer at or above target")
    if not isinstance(payload["legacy_paths"], list) or not all(
        isinstance(item, str) for item in payload["legacy_paths"]
    ):
        raise LifecycleError("MALFORMED_STATE", "legacy_paths must be a string list")
    if not isinstance(payload["managed"], dict):
        raise LifecycleError("MALFORMED_STATE", "managed must be an object")
    return payload


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return validate_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("MALFORMED_STATE", str(path)) from exc


def write_state(path: Path, state: dict[str, Any]) -> None:
    validate_state(state)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(state, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def new_state(worktrees: list[Worktree], target: int) -> dict[str, Any]:
    if target < 1:
        raise LifecycleError("INVALID_TARGET", "target must be positive")
    return {
        "version": 1,
        "target": target,
        "ceiling": max(len(worktrees), target),
        "main_path": worktrees[0].key,
        "legacy_paths": sorted(row.key for row in worktrees),
        "managed": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_or_initialize(repo: Path, state_file: Path, target: int = DEFAULT_TARGET) -> dict[str, Any]:
    state = load_state(state_file)
    if state is not None:
        return state
    state = new_state(list_worktrees(repo), target)
    write_state(state_file, state)
    return state


def audit_state(
    repo: Path,
    state: dict[str, Any],
    *,
    ratchet: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    worktrees = list_worktrees(repo)
    live = {row.key: row for row in worktrees}
    legacy = set(state["legacy_paths"])
    managed = state["managed"]
    known = legacy | set(managed)

    unmanaged = sorted(live.keys() - known)
    if unmanaged:
        raise LifecycleError("UNMANAGED_WORKTREE", ", ".join(live[key].path for key in unmanaged))
    missing_managed = sorted(set(managed) - live.keys())
    if missing_managed:
        raise LifecycleError("MISSING_MANAGED_WORKTREE", ", ".join(missing_managed))
    if len(worktrees) > state["ceiling"]:
        raise LifecycleError(
            "WORKTREE_CEILING",
            f"live={len(worktrees)} ceiling={state['ceiling']} target={state['target']}",
        )

    today = date.today()
    expired = []
    for key, record in managed.items():
        try:
            expiry = date.fromisoformat(record["expires"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LifecycleError("MALFORMED_STATE", f"invalid managed lease: {key}") from exc
        if expiry < today:
            expired.append(record.get("path", key))
    if expired:
        raise LifecycleError("EXPIRED_WORKTREE", ", ".join(sorted(expired)))

    if ratchet:
        state["legacy_paths"] = sorted(legacy & live.keys())
        state["ceiling"] = min(state["ceiling"], max(len(worktrees), state["target"]))
        state["updated_at"] = datetime.now(timezone.utc).isoformat()

    report = {
        "status": "PASS",
        "live": len(worktrees),
        "ceiling": state["ceiling"],
        "target": state["target"],
        "legacy": len(state["legacy_paths"]),
        "managed": len(managed),
    }
    return state, report


def install(repo: Path, state_file: Path, target: int) -> dict[str, Any]:
    if state_file.exists():
        state = validate_state(json.loads(state_file.read_text(encoding="utf-8")))
        _, report = audit_state(repo, state, ratchet=True)
        write_state(state_file, state)
        return report
    state = new_state(list_worktrees(repo), target)
    write_state(state_file, state)
    _, report = audit_state(repo, state, ratchet=False)
    return report


def create_worktree(repo: Path, state_file: Path, args: argparse.Namespace) -> dict[str, Any]:
    state = load_or_initialize(repo, state_file)
    # Audit WITHOUT ratchet: the ceiling is lowered ONLY by the explicit operator
    # `audit --ratchet` path, never on a growth attempt (and never by retire).
    # Ratcheting here would collapse the ceiling to max(live, target) == live whenever
    # live >= target, then the live >= ceiling check below would always fire -- making
    # managed create impossible in the headroom regime (target <= live < ceiling).
    state, _ = audit_state(repo, state, ratchet=False)
    worktrees = list_worktrees(repo)
    if len(worktrees) >= state["ceiling"]:
        raise LifecycleError(
            "WORKTREE_CEILING",
            f"live={len(worktrees)} ceiling={state['ceiling']}; retire one before creating another",
        )
    try:
        expiry = date.fromisoformat(args.expires)
    except ValueError as exc:
        raise LifecycleError("INVALID_EXPIRY", args.expires) from exc
    if expiry < date.today():
        raise LifecycleError("INVALID_EXPIRY", "expiry is already past")

    destination = Path(canonical_path(args.path))
    if destination.exists():
        raise LifecycleError("PATH_EXISTS", str(destination))
    key = path_key(destination)
    if key in state["managed"] or key in state["legacy_paths"]:
        raise LifecycleError("PATH_REGISTERED", str(destination))

    command = ["worktree", "add", "-b", args.branch, str(destination), args.start_point]
    run_git(repo, command)
    try:
        live = {row.key: row for row in list_worktrees(repo)}
        if key not in live:
            raise LifecycleError("CREATE_NOT_REGISTERED", str(destination))
        state["managed"][key] = {
            "path": canonical_path(destination),
            "branch": args.branch,
            "owner": args.owner,
            "purpose": args.purpose,
            "expires": args.expires,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "head": live[key].head,
        }
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_state(state_file, state)
    except Exception:
        run_git(repo, ["worktree", "remove", str(destination)], check=False)
        raise
    return {"status": "CREATED", "path": canonical_path(destination), "branch": args.branch}


def safe_ref_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return cleaned or "worktree"


def retire_worktree(repo: Path, state_file: Path, requested_path: str) -> dict[str, Any]:
    state = load_or_initialize(repo, state_file)
    state, _ = audit_state(repo, state, ratchet=False)
    key = path_key(requested_path)
    live = {row.key: row for row in list_worktrees(repo)}
    row = live.get(key)
    if row is None:
        raise LifecycleError("WORKTREE_NOT_FOUND", canonical_path(requested_path))
    if key == state["main_path"]:
        raise LifecycleError("MAIN_WORKTREE", row.path)
    if key not in state["legacy_paths"] and key not in state["managed"]:
        raise LifecycleError("UNMANAGED_WORKTREE", row.path)

    status = run_git(Path(row.path), ["status", "--porcelain", "--untracked-files=all"])
    if status.stdout:
        raise LifecycleError("DIRTY_WORKTREE", row.path)

    archive_ref: str | None = None
    if row.detached:
        name = safe_ref_component(Path(row.path).name)
        archive_ref = (
            f"refs/archive/worktree-retirement/{date.today():%Y%m%d}/"
            f"{name}-{row.head[:12]}"
        )
        run_git(repo, ["update-ref", archive_ref, row.head])
        resolved = run_git(repo, ["rev-parse", archive_ref]).stdout.strip()
        if resolved != row.head:
            raise LifecycleError("ARCHIVE_REF_MISMATCH", row.path)

    run_git(repo, ["worktree", "remove", row.path])
    if Path(row.path).exists():
        raise LifecycleError("REMOVE_INCOMPLETE", row.path)

    state["managed"].pop(key, None)
    state["legacy_paths"] = sorted(item for item in state["legacy_paths"] if item != key)
    # Retire frees a slot but does NOT lower the ceiling: the ceiling is a bounded
    # replacement pool, so a subsequent create can refill up to it. Ceiling reduction
    # happens ONLY through the explicit operator `audit --ratchet` path -- ordinary
    # create/retire never lower it. Previously retire clamped ceiling to the live
    # count which, combined with create's own clamp, made managed create impossible in
    # the headroom regime (target <= live < ceiling) and trapped the pool in a
    # shrink-only ramp: retiring toward target kept ceiling == live at every step, so
    # create could never refill. See create_worktree for the paired create-side fix.
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_state(state_file, state)
    return {
        "status": "RETIRED",
        "path": row.path,
        "head": row.head,
        "retained_ref": row.branch,
        "archive_ref": archive_ref,
        "ceiling": state["ceiling"],
    }


def emit(payload: dict[str, Any], quiet: bool) -> None:
    if not quiet:
        print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="any worktree in the target repository")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--target", type=int, default=DEFAULT_TARGET)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--ratchet", action="store_true")
    audit_parser.add_argument("--quiet", action="store_true")

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--path", required=True)
    create_parser.add_argument("--branch", required=True)
    create_parser.add_argument("--owner", required=True)
    create_parser.add_argument("--purpose", required=True)
    create_parser.add_argument("--expires", required=True)
    create_parser.add_argument("--start-point", default="HEAD")

    retire_parser = subparsers.add_parser("retire")
    retire_parser.add_argument("--path", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(canonical_path(args.repo))
    try:
        common = common_dir(repo)
        state_file = common / STATE_NAME
        with RepositoryLock(common / LOCK_NAME):
            if args.command == "install":
                payload = install(repo, state_file, args.target)
                emit(payload, False)
            elif args.command == "audit":
                state = load_or_initialize(repo, state_file)
                state, payload = audit_state(repo, state, ratchet=args.ratchet)
                if args.ratchet:
                    write_state(state_file, state)
                emit(payload, args.quiet)
            elif args.command == "create":
                emit(create_worktree(repo, state_file, args), False)
            elif args.command == "retire":
                emit(retire_worktree(repo, state_file, args.path), False)
            else:
                raise AssertionError(args.command)
        return 0
    except LifecycleError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

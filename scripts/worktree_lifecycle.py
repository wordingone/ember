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
import shutil
import subprocess
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


STATE_NAME = "ember-worktree-lifecycle.json"
LOCK_NAME = "ember-worktree-lifecycle.lock"
DEFAULT_TARGET = 12
RENEWAL_CAP_DAYS = 14

# The exact commands the custody census runs per registered worktree
# (`scripts/ember_01_custody/census.py`, `_git_material_paths`). The census's
# `registered_worktree_scan_failed` contradiction is one of these raising, so this is what
# `audit --strict` has to probe with: a cheaper stand-in like `rev-parse --git-dir` passes
# on registrations whose `ls-files` fails, and a green strict run that does not imply a
# green census is a detector that certifies the wrong thing.
CENSUS_MATERIAL_PROBES: tuple[tuple[str, ...], ...] = (
    ("ls-files", "--modified", "--others", "--exclude-standard", "-z"),
    ("diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB", "-z"),
    ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
)


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
    # Git marks a record `prunable` when its directory is gone but the administrative
    # metadata survives -- the exact shape produced by deleting a worktree by hand.
    # Defaults False so a git old enough not to emit the attribute reads as live, which
    # is the conservative direction: refusals stay refusals, nothing new is stepped over.
    prunable: bool = False


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
                prunable=bool(fields.get("prunable", False)),
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
    # Both fields postdate version 1's first states, so absence is legal and reads as
    # empty. Presence is validated strictly: a tombstone log that can hold non-records
    # is not an audit trail, and a removal journal that can hold non-records cannot be
    # replayed by the very check that exists to find interrupted removals.
    retired = payload.get("retired", {})
    if not isinstance(retired, dict) or not all(
        isinstance(item, dict) for item in retired.values()
    ):
        raise LifecycleError("MALFORMED_STATE", "retired must be an object of objects")
    pending = payload.get("pending_removals", {})
    if not isinstance(pending, dict) or not all(
        isinstance(item, dict) for item in pending.values()
    ):
        raise LifecycleError("MALFORMED_STATE", "pending_removals must be an object of objects")
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
        "retired": {},
        "pending_removals": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def retired_of(state: dict[str, Any]) -> dict[str, Any]:
    """The retirement log, keyed by path key, created on first use.

    This is the map the live state already carries: out-of-repo tooling has been writing
    dated, reasoned entries into `retired` since 2026-07-27. Adding a second, parallel log
    would have split custody history across two shapes in one file, so this writes into
    the existing one and widens the record instead.
    """
    return state.setdefault("retired", {})


def pending_removals_of(state: dict[str, Any]) -> dict[str, Any]:
    """In-flight removal intents, keyed by path key. See `begin_removal`."""
    return state.setdefault("pending_removals", {})


def record_retirement(
    state: dict[str, Any],
    *,
    key: str,
    record: dict[str, Any],
    verb: str,
    reason: str,
    origin: str,
) -> dict[str, Any]:
    """Write the dated, reasoned record of a registration that has left the registry.

    Custody history is the point: a row that simply disappears leaves no way to answer
    "what was registered here, who owned it, and why is it gone" months later, and the
    census contradictions this file exists to kill were themselves only legible because
    someone still had the paths. Retirement and reconciliation both write one of these,
    so every departure from the registry is accounted for by name.

    Keyed by path, matching the existing `retired` map. A path can legitimately be
    registered, retired, and registered again, so a collision does not overwrite: the
    prior record is carried forward under `superseded`, and nothing that was written is
    lost to a reuse of the same directory.
    """
    log = retired_of(state)
    entry = {
        "path": record.get("path", key),
        "key": key,
        "branch": record.get("branch"),
        # A null `branch` means two different things now that `create --detach` exists:
        # a detached row never had one, and a record reconstructed from a bare Git
        # registration may simply not know. Carrying the flag keeps the tombstone
        # unambiguous; None stays None where the source genuinely could not say.
        "detached": record.get("detached"),
        "owner": record.get("owner"),
        "purpose": record.get("purpose"),
        "head": record.get("head"),
        "created_at": record.get("created_at"),
        "retired_on": date.today().isoformat(),
        "retired_at": datetime.now(timezone.utc).isoformat(),
        "verb": verb,
        "reason": reason,
        "origin": origin,
    }
    previous = log.get(key)
    if previous is not None:
        carried = {name: value for name, value in previous.items() if name != "superseded"}
        entry["superseded"] = [*previous.get("superseded", []), carried]
    log[key] = entry
    return entry


def begin_removal(
    state: dict[str, Any],
    state_file: Path,
    *,
    key: str,
    path: str,
    verb: str,
) -> None:
    """Persist the INTENT to remove before anything on disk changes.

    Removing a worktree is two facts -- a directory and a Git registration -- and no
    filesystem gives us both in one write. The failure this file exists to kill is the
    interval between them going unnoticed: the tree is swept, the registration survives,
    and nothing says so until a census walks 224 registrations and finds thirteen paths
    that are not there.

    So the interval is made *declared* rather than eliminated. The intent lands first, is
    fsynced with the state, and is cleared only once the registration is verified gone.
    A process killed anywhere in between leaves this row behind, and `audit --strict`
    reports it as `interrupted_removal` with the exact cure. The window still exists; what
    no longer exists is a window that is silent.
    """
    pending_removals_of(state)[key] = {
        "path": path,
        "verb": verb,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_state(state_file, state)


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
    enforce_expiry: bool = True,
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
    if enforce_expiry and expired:
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

    # `--detach` exists for certification consumers: verify_ember01_completion.py runs its
    # executable legs only when the checkout is clean AND DETACHED (its inspect_checkout
    # reads `git symbolic-ref HEAD`), so a worktree created with `-b` can never certify --
    # every leg comes back UNRESOLVED "checkout not clean+detached". A detached row also
    # takes retire's archive-ref path, so its head is preserved without leaving a
    # permanent `refs/heads/...` behind for every run.
    detach = bool(getattr(args, "detach", False))
    if detach:
        command = ["worktree", "add", "--detach", str(destination), args.start_point]
    else:
        command = ["worktree", "add", "-b", args.branch, str(destination), args.start_point]
    run_git(repo, command)
    try:
        live = {row.key: row for row in list_worktrees(repo)}
        if key not in live:
            raise LifecycleError("CREATE_NOT_REGISTERED", str(destination))
        if detach and not live[key].detached:
            # Fail closed rather than register a row claiming a detachment git did not
            # perform: a consumer that trusted it would silently certify nothing.
            raise LifecycleError("DETACH_NOT_APPLIED", str(destination))
        state["managed"][key] = {
            "path": canonical_path(destination),
            "branch": None if detach else args.branch,
            "detached": detach,
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
    return {
        "status": "CREATED",
        "path": canonical_path(destination),
        "branch": None if detach else args.branch,
        "detached": detach,
    }


def safe_ref_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return cleaned or "worktree"


def retire_worktree(
    repo: Path,
    state_file: Path,
    requested_path: str,
    reason: str = "retired by owner",
    *,
    force_owner: str | None = None,
) -> dict[str, Any]:
    state = load_or_initialize(repo, state_file)
    # Expiry is a reason to retire, not a gate against retirement. Every other
    # repository-integrity gate remains active, and the selected worktree still
    # must be registered, non-main, and clean below.
    state, _ = audit_state(repo, state, ratchet=False, enforce_expiry=False)
    key = path_key(requested_path)
    live = {row.key: row for row in list_worktrees(repo)}
    row = live.get(key)
    if row is None:
        raise LifecycleError("WORKTREE_NOT_FOUND", canonical_path(requested_path))
    if key == state["main_path"]:
        raise LifecycleError("MAIN_WORKTREE", row.path)
    if key not in state["legacy_paths"] and key not in state["managed"]:
        raise LifecycleError("UNMANAGED_WORKTREE", row.path)

    # A dirty worktree normally refuses retirement: residue may be someone's unsaved work.
    # `--force --owner <name>` narrows that refusal to worktrees this owner created, and
    # exists for one situation: an automated pipeline whose leg was killed mid-run never
    # got to delete its own scratch, so its worktree is dirty with files only it wrote.
    # Refusing there does not protect work, it strands a worktree (and, in the incident
    # that motivated this, a 1.4GB temp file) that nothing else will ever clean up. The
    # owner match is the whole safety property: force NEVER applies to a row this caller
    # did not create, and never to a legacy (unowned) row.
    forced = False
    status = run_git(Path(row.path), ["status", "--porcelain", "--untracked-files=all"])
    if status.stdout:
        managed_record = state["managed"].get(key, {})
        if force_owner is not None and managed_record.get("owner") == force_owner:
            forced = True
        else:
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

    # Intent first: from here until the verified deregistration below, a crash is
    # discoverable by `audit --strict` instead of silently stranding a registration.
    record = dict(
        state["managed"].get(key)
        or {"path": row.path, "branch": row.branch, "detached": row.detached}
    )
    begin_removal(state, state_file, key=key, path=row.path, verb="retire")

    run_git(repo, ["worktree", "remove", *(["--force"] if forced else []), row.path])
    if Path(row.path).exists():
        raise LifecycleError("REMOVE_INCOMPLETE", row.path)
    # Deregistration is the half that used to be assumed. `git worktree remove` drops the
    # directory and the administrative record together, but "usually together" is what
    # produced thirteen stranded registrations, so the outcome is READ back rather than
    # inferred from the exit code. If the record survived, the pending intent is left on
    # disk deliberately -- the operator gets a named cure instead of a clean-looking exit.
    if any(other.key == key for other in list_worktrees(repo)):
        raise LifecycleError(
            "DEREGISTRATION_INCOMPLETE",
            f"{row.path} is still registered with Git after removal; removal intent retained",
        )

    record.setdefault("head", row.head)
    record_retirement(
        state,
        key=key,
        record=record,
        verb="retire",
        # A forced retirement DISCARDED uncommitted bytes. That is the one retirement
        # whose reason cannot be taken at face value later, so the tombstone says so
        # itself rather than leaving it inferable only from the owner field.
        reason=f"{reason} (forced: dirty tree discarded, owner {force_owner})"
        if forced
        else reason,
        origin="managed" if key in state["managed"] else "legacy",
    )
    pending_removals_of(state).pop(key, None)
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
        "forced": forced,
        "ceiling": state["ceiling"],
    }


def renew_worktree(repo: Path, state_file: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Extend ONE managed row's lease, under the same lock as create/retire.

    An expired lease's only cure used to be a hand-locked JSON edit -- the exact
    ad-hoc registry mutation this tool exists to eliminate (2026-08-04, verify
    cockpit worktree). This verb is the sanctioned form: exact path, managed rows
    only, bounded horizon, and the renewal is recorded on the row so audit can
    show it.

    * Expiry is the condition being cured, so -- like retire -- the audit runs
      with enforce_expiry=False. Every other integrity gate stays live: an
      unmanaged or missing worktree still refuses before anything is written.
    * The new expiry is bounded to RENEWAL_CAP_DAYS from today per invocation.
      A lease is a lease: extending forever in one call would make expiry
      decorative.
    * legacy_paths carry no lease and are not this verb's to edit.
    """
    state = load_or_initialize(repo, state_file)
    state, _ = audit_state(repo, state, ratchet=False, enforce_expiry=False)
    key = path_key(args.path)
    record = state["managed"].get(key)
    if record is None:
        if key in state["legacy_paths"]:
            raise LifecycleError("LEGACY_PATH", canonical_path(args.path))
        raise LifecycleError("NOT_MANAGED", canonical_path(args.path))

    today = date.today()
    if args.until is not None:
        try:
            new_expiry = date.fromisoformat(args.until)
        except ValueError as exc:
            raise LifecycleError("INVALID_EXPIRY", args.until) from exc
    else:
        if args.days < 1:
            raise LifecycleError("INVALID_EXPIRY", f"--days {args.days}: must be at least 1")
        new_expiry = today + timedelta(days=args.days)
    if new_expiry < today:
        raise LifecycleError("INVALID_EXPIRY", "expiry is already past")
    if new_expiry > today + timedelta(days=RENEWAL_CAP_DAYS):
        raise LifecycleError(
            "RENEWAL_CAP",
            f"{new_expiry.isoformat()} is more than {RENEWAL_CAP_DAYS} days out; "
            "renew again closer to the date instead",
        )

    previous = record.get("expires")
    record["expires"] = new_expiry.isoformat()
    record.setdefault("renewals", []).append(
        {
            "renewed_at": datetime.now(timezone.utc).isoformat(),
            "previous_expires": previous,
            "expires": new_expiry.isoformat(),
        }
    )
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_state(state_file, state)
    return {
        "status": "RENEWED",
        "path": record["path"],
        "previous_expires": previous,
        "expires": new_expiry.isoformat(),
        "renewals": len(record["renewals"]),
    }


def prune_one_worktree_metadata(repo: Path, target_path: str) -> bool:
    """Remove the administrative directory of ONE worktree, identified by its path.

    Git keeps a directory per linked worktree under ``$GIT_COMMON_DIR/worktrees/<name>``,
    and the ``gitdir`` file inside it records that worktree's ``.git`` location. Matching
    on that recorded path is how this stays exact: the caller names a path, and only the
    record pointing at that path is touched. ``git worktree prune`` would do the same
    thing for every stale record at once, which is the collateral this exists to avoid.

    Returns whether a record was found and removed. Absent is not an error -- git may have
    pruned it already, and reconcile's job is that the row and the metadata both end up
    gone, not that this call was the one to do it.
    """
    admin_root = common_dir(repo) / "worktrees"
    if not admin_root.is_dir():
        return False
    wanted = path_key(target_path)
    for entry in sorted(admin_root.iterdir()):
        pointer = entry / "gitdir"
        if not pointer.is_file():
            continue
        try:
            recorded = pointer.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not recorded:
            continue
        # `gitdir` points at the worktree's `.git` FILE; its parent is the worktree.
        if path_key(Path(recorded).parent) == wanted:
            shutil.rmtree(entry, ignore_errors=False)
            return True
    return False


def reconcile_worktree(
    repo: Path,
    state_file: Path,
    requested_path: str,
    reason: str = "registration stale: worktree directory no longer present",
    abandon_intent: bool = False,
) -> dict[str, Any]:
    """Clear ONE stale registration whose worktree is genuinely gone.

    MISSING_MANAGED_WORKTREE is raised by audit_state before it does anything, and
    audit runs first inside create, retire and the pre-push guard. So a row whose
    worktree no longer exists has no exit: every verb that could remove it refuses
    to run until the thing it would remove is put back. The only way out today is
    to physically reconstruct a worktree at the registered path -- absurd when the
    ROW is what is wrong -- and until someone does, the check blocks pushes
    repo-wide, so one owner's stale bookkeeping halts every other owner's
    unrelated work. That happened twice on 2026-07-26 within ten minutes.

    This verb is that exit, and it is deliberately the narrowest one that works:

    * an EXACT path is required, so it can never become a sweep;
    * it REFUSES when the worktree is live (that case is ``retire``, which has the
      clean-tree and archive-ref checks this one deliberately lacks);
    * it REFUSES when the path exists with any content, so it can never discard
      bytes someone is still holding -- an empty directory is the only on-disk
      state it will step over;
    * it never deletes the branch. The row goes; the ref stays; nothing that was
      committed can be lost by running this.

    Fail-closed stays fail-closed. What changes is that a stale row has an exit
    that is not "rebuild the directory you already deleted".

    ELIGIBILITY WAS ORIGINALLY ``managed`` ONLY, AND THAT MADE THE CURE UNREACHABLE.
    Restricting this verb to ``managed`` rows was a deliberate narrowing -- legacy
    paths are the install-time snapshot -- but measured against the registry it
    excluded the entire defect population. The live state holds 37 managed rows of
    which zero point at a missing directory, and 244 legacy paths of which 73 are
    missing on disk. So every stale registration the census reported raised
    LEGACY_PATH here, and `audit --strict` printed a cure that refused, forever: the
    "no exit" shape this verb exists to end, relocated onto the rows that actually
    have it.

    Eligibility is therefore the union of the three ways this repository can hold a
    record for a path -- a managed row, a legacy snapshot entry, or a bare Git
    registration the state never knew about. The SAFETY envelope is unchanged and is
    what makes the widening sound: exact path, refuses live, refuses any content on
    disk, target-scoped metadata removal, never deletes a branch, always writes a
    dated tombstone. What widened is which stale records can reach that envelope,
    not what the envelope permits.
    """
    state = load_or_initialize(repo, state_file)
    # Deliberately NOT audit_state(): audit raises on exactly the condition this
    # verb exists to clear, so calling it here would reproduce the deadlock.
    key = path_key(requested_path)

    if abandon_intent:
        # The removal was attempted, failed with the tree intact, and will not be
        # retried. Only the journal entry is cleared -- no directory, no metadata, no
        # registry row is touched -- so this is the one branch that may run against a
        # live worktree. Without it a permission-denied removal on Windows leaves an
        # intent that no verb can clear and `audit --strict` stays red until someone
        # hand-edits the state file.
        intent = pending_removals_of(state).pop(key, None)
        if intent is None:
            raise LifecycleError("NO_PENDING_REMOVAL", canonical_path(requested_path))
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_state(state_file, state)
        return {
            "status": "INTENT_ABANDONED",
            "path": intent.get("path", canonical_path(requested_path)),
            "abandoned": intent,
            "reason": reason,
        }

    if key == state.get("main_path"):
        raise LifecycleError("MAIN_WORKTREE", canonical_path(requested_path))

    record = state["managed"].get(key)
    origin = "managed"
    if record is None:
        if key in state["legacy_paths"]:
            origin = "legacy"
            record = {
                "path": canonical_path(requested_path),
                "purpose": "install-time legacy snapshot",
            }
        else:
            registered = {row.key: row for row in list_worktrees(repo)}
            row = registered.get(key)
            if row is None:
                raise LifecycleError("NOT_MANAGED", canonical_path(requested_path))
            origin = "unregistered"
            record = {
                "path": row.path,
                "branch": row.branch,
                "detached": row.detached,
                "head": row.head,
                "purpose": "registered with Git, absent from the registry",
            }

    # PRUNABLE IS NOT LIVE, and the metadata transition is TARGET-SCOPED.
    #
    # The incident this verb exists for is an owner deleting the directory without
    # retiring. That leaves git's administrative metadata behind, and a worktree with
    # stale metadata is still listed by `git worktree list --porcelain` -- as PRUNABLE,
    # but listed. Computing the live set first therefore classified exactly the failure
    # shape as WORKTREE_LIVE and refused, so the verb deadlocked on its own reason for
    # existing. `git worktree remove` clears the metadata cleanly, which is why a test
    # written around it could not see this: the test constructed the one input shape the
    # bug did not have.
    #
    # `git worktree prune` is the obvious answer and the wrong one. It is REPOSITORY-WIDE:
    # reconciling A would clear the metadata of every other prunable worktree too, while
    # this verb removes only A's row. Every other raw-deleted managed row would go from
    # "listed, quietly stuck" to "not listed, and now MISSING_MANAGED_WORKTREE" -- which
    # blocks pushes repo-wide. That is the same deadlock this verb exists to end, moved
    # onto someone else's row, and it is exactly what an exact-path contract forbids.
    #
    # So: read the state instead of mutating it. Git already tells us which records are
    # prunable, and a prunable record is not a live worktree. The refusal below now means
    # what it says without anything having been changed to make it true.
    #
    # The live check runs ahead of the emptiness check, and that ordering is load-bearing:
    # a LIVE worktree's directory is never empty, so checking emptiness first would refuse
    # every live path with PATH_NOT_EMPTY and the WORKTREE_LIVE refusal -- the one that
    # tells the caller to use `retire` -- would become unreachable. Live is the more
    # specific condition, so it is answered first.
    live = {row.key: row for row in list_worktrees(repo) if not row.prunable}
    if key in live:
        raise LifecycleError("WORKTREE_LIVE", live[key].path)

    destination = Path(record["path"])
    if destination.exists():
        try:
            leftovers = any(destination.iterdir())
        except OSError as exc:
            raise LifecycleError("PATH_UNREADABLE", f"{destination}: {exc}") from exc
        if leftovers:
            raise LifecycleError("PATH_NOT_EMPTY", str(destination))

    # The metadata for THIS path, and nothing else. Leaving it would make the path an
    # UNMANAGED_WORKTREE the moment its row is gone -- git still listing a worktree the
    # registry no longer knows -- so the row and its metadata have to leave together.
    # Removing the one administrative directory whose `gitdir` points at this path is
    # precisely what prune would have done for this record, scoped to it.
    prune_one_worktree_metadata(repo, record["path"])

    # VERIFY THE OUTCOME, not the call. The remover reports False both for "already gone"
    # and for "could not find or read the record", and those are opposite facts -- so its
    # return value cannot decide anything. Ask git instead, under the same lock: if the
    # path is still listed, the metadata survived, and popping the row here would turn a
    # managed-but-stale worktree into an UNMANAGED one, which blocks the repo again. Same
    # stranded state as the collateral bug, relocated onto the requested row.
    #
    # The re-list is authoritative in both directions, which is why it is the check rather
    # than the boolean: it passes for the legitimate already-pruned case and fails for
    # every way the removal can silently not happen.
    if any(row.key == key for row in list_worktrees(repo)):
        raise LifecycleError(
            "METADATA_REMOVAL_FAILED",
            f"{record['path']} is still registered with Git after target-scoped removal; row preserved",
        )

    # The row leaves the registry and enters the retirement log in the same write: a
    # stale row is cleared, never silently dropped, so custody history survives the cure.
    tombstone = record_retirement(
        state, key=key, record=record, verb="reconcile", reason=reason, origin=origin
    )
    pending_removals_of(state).pop(key, None)
    state["managed"].pop(key, None)
    state["legacy_paths"] = [item for item in state["legacy_paths"] if item != key]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_state(state_file, state)
    return {
        "status": "RECONCILED",
        "origin": origin,
        "reason": reason,
        "tombstone": tombstone,
        "path": record["path"],
        "owner": record.get("owner"),
        "retained_branch": record.get("branch"),
        "recorded_head": record.get("head"),
        "ceiling": state["ceiling"],
    }


def directory_is_empty(path: Path) -> bool:
    with os.scandir(path) as entries:
        return next(entries, None) is None


def linked_worktree_gitdir(candidate: Path) -> Path | None:
    """Resolve the administrative directory a linked-worktree `.git` FILE points at.

    Returns None when this is not a linked worktree at all -- a `.git` directory, a
    missing marker, an unreadable file, or a marker without a `gitdir:` line.
    """
    marker = candidate / ".git"
    if not marker.is_file():
        return None
    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip() == "gitdir":
            target = Path(value.strip())
            if not target.is_absolute():
                target = candidate / target
            return Path(canonical_path(target))
    return None


def is_within(child: Path, parent: Path) -> bool:
    child_key = path_key(child)
    parent_key = path_key(parent)
    return child_key == parent_key or child_key.startswith(parent_key.rstrip("\\/") + os.sep)


def known_roots(
    registrations: Sequence[Worktree],
    state: dict[str, Any],
    extra: Sequence[str] | None,
) -> list[Path]:
    """Directories that hold worktrees, derived from what is already registered.

    A root is not configured anywhere, and inventing a config file would only move the
    staleness problem into it. Every directory that currently parents a registration --
    plus every directory that parented one according to the state -- is a place worktrees
    demonstrably live, and that is exactly where an unregistered one would appear.
    """
    roots: dict[str, Path] = {}
    candidates = [Path(row.path).parent for row in registrations]
    candidates += [Path(str(record.get("path", key))).parent for key, record in state["managed"].items()]
    candidates += [Path(item) for item in (extra or [])]
    for candidate in candidates:
        resolved = Path(canonical_path(candidate))
        roots.setdefault(path_key(resolved), resolved)
    return [roots[key] for key in sorted(roots)]


def strict_report(
    repo: Path,
    state: dict[str, Any],
    extra_roots: Sequence[str] | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    """Find stale registrations MECHANICALLY, before a census has to find them by walking.

    This is the detection half of the class-kill. `audit` proper answers a different
    question -- is the managed pool within its bounds -- and it answers it by RAISING on
    the first violation, which is exactly wrong for an inventory: the operator needs every
    stale row at once, not the first one. It also raises on `MISSING_MANAGED_WORKTREE`,
    which would pre-empt the listing this mode exists to produce. So this scan is separate,
    read-only, and total.

    Four contradiction classes, matching what the custody census reports:

    * ``stale_registration`` -- Git lists a worktree whose directory is missing, empty, or
      which Git itself marks prunable. This is the census's ``registered_worktree_missing``.
    * ``unscannable_registration`` -- the directory is there but Git cannot read it as a
      worktree. This is the census's ``registered_worktree_scan_failed``. The probe is the
      census's OWN probe (see `CENSUS_MATERIAL_PROBES`), because a scan that merely
      resembles it proves nothing: `rev-parse --git-dir` succeeds on registrations whose
      `ls-files` fails, so a green `--strict` would not have implied a green census. The
      failing command and Git's error text are both carried through, so the cause is NAMED.
    * ``unregistered_worktree_dir`` -- a linked-worktree directory under a known root with
      no registration. The mirror image of a stale row. The marker's `gitdir:` must resolve
      inside THIS repository's common dir: a `.git` file is also what every OTHER repo's
      linked worktree looks like, and on this host the un-scoped test reported ~70 of them
      -- other repositories' live trees -- each with destructive advice attached.
    * ``interrupted_removal`` -- a removal intent that was never cleared. See `begin_removal`.

    SEVERITY. Contradictions carry `severity`: `error` for records this tool is responsible
    for (managed rows, its own removal intents, orphans under our own common dir) and
    `backlog` for pre-existing debt it inherited (legacy-snapshot and never-registered
    paths). Only errors fail by default; `--all` promotes everything. That split is what
    lets the check GATE something today rather than being wired in and immediately
    disabled: the live registry holds 73 missing legacy paths but zero missing managed
    rows, so the gate is green on arrival and goes red the moment a sweep strands a row
    the registry owns -- which is the class being killed. The backlog stays printed on
    every run, so it is paid down, not hidden.

    Nothing here mutates: this must be safe to run against a live repository that other
    owners are working in, and a detector that repairs things cannot be trusted to report.
    """
    registrations = list_worktrees(repo)
    registered = {row.key for row in registrations}
    contradictions: list[dict[str, Any]] = []
    main_key = state.get("main_path")
    managed = state["managed"]
    legacy = set(state["legacy_paths"])
    common = common_dir(repo)

    def provenance(key: str) -> tuple[str, str]:
        """Where the registry thinks this path came from, and how loudly to say so."""
        if key in managed:
            return "managed", "error"
        if key in legacy:
            return "legacy", "backlog"
        return "unregistered", "backlog"

    def contradiction(code: str, reason: str, row: Worktree, **extra: Any) -> dict[str, Any]:
        origin, severity = provenance(row.key)
        return {
            "code": code,
            "severity": severity,
            "origin": origin,
            "reason": reason,
            "path": row.path,
            "branch": row.branch,
            "cure": f"python scripts/worktree_lifecycle.py reconcile --path {row.path}",
            **extra,
        }

    for row in registrations:
        path = Path(row.path)
        if row.key == main_key:
            continue
        if not path.exists():
            contradictions.append(
                contradiction(
                    "stale_registration",
                    "registered directory does not exist",
                    row,
                    prunable=row.prunable,
                )
            )
            continue
        try:
            empty = path.is_dir() and directory_is_empty(path)
        except OSError as exc:
            contradictions.append(
                contradiction(
                    "unscannable_registration", f"registered directory is unreadable: {exc}", row
                )
            )
            continue
        if empty:
            contradictions.append(
                contradiction(
                    "stale_registration",
                    "registered directory is empty",
                    row,
                    prunable=row.prunable,
                )
            )
            continue
        if row.prunable:
            contradictions.append(
                contradiction(
                    "stale_registration",
                    "Git marks the administrative record prunable",
                    row,
                    prunable=True,
                )
            )
            continue
        # The census probe is three git invocations per registration, and the hooks run this
        # on every commit against a registry holding hundreds of rows -- roughly 670
        # subprocesses, which is a check nobody would leave enabled. Registrations the
        # registry OWNS are probed always, because those are what the gate protects; the
        # inherited backlog is probed under --all, which is the mode used to drain it.
        if provenance(row.key)[0] != "managed" and not deep:
            continue
        for arguments in CENSUS_MATERIAL_PROBES:
            probe = run_git(path, list(arguments), check=False)
            if probe.returncode:
                detail = probe.stderr.strip() or probe.stdout.strip() or "no output"
                contradictions.append(
                    contradiction(
                        "unscannable_registration",
                        f"git {' '.join(arguments)}: {detail}",
                        row,
                        failing_probe=" ".join(arguments),
                    )
                )
                break

    for root in known_roots(registrations, state, extra_roots):
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or path_key(child) in registered:
                continue
            gitdir = linked_worktree_gitdir(child)
            # Scoped to OUR repository. A `.git` file whose gitdir points elsewhere is
            # another repository's live worktree -- not a contradiction, and certainly not
            # something to attach "or remove the directory" to.
            if gitdir is None or not is_within(gitdir, common):
                continue
            contradictions.append(
                {
                    "code": "unregistered_worktree_dir",
                    "severity": "error",
                    "origin": "orphan",
                    "reason": f"linked-worktree directory with no Git registration (gitdir {gitdir})",
                    "path": canonical_path(child),
                    "cure": f"git -C {repo} worktree repair {child}, or retire the directory",
                }
            )

    def occupied(path: Path) -> bool:
        """The directory is there and holds bytes -- the state reconcile refuses to step over."""
        try:
            return path.is_dir() and not directory_is_empty(path)
        except OSError:
            return True

    def removal_cure(key: str, path: Path) -> tuple[str, str]:
        """Name the half that failed, and the exit that matches it.

        Removing a worktree is a directory and a registration, so an interrupted removal
        has three end states, not two, and each needs a different cure. Printing one
        unconditional `reconcile` for all of them is what produced an intent no verb could
        clear -- reconcile refuses a non-empty path, and retire refuses a row whose
        registration is already gone.
        """
        if not occupied(path):
            return ("the directory is gone", f"python scripts/worktree_lifecycle.py reconcile --path {path}")
        if key in registered:
            # Nothing happened on disk: the removal failed before Git was told.
            return (
                "the worktree is still present and still registered",
                f"python scripts/worktree_lifecycle.py retire --path {path}"
                f"  (or reconcile --path {path} --abandon-intent to give up on it)",
            )
        # Git deregistered and the delete failed -- the ordinary Windows permission-denied
        # shape. Both verbs refuse: retire has no registration left to work from, reconcile
        # will not discard the bytes. Deleting them here is exactly what this tool must
        # never do unasked, so the exit is an explicit human step, named.
        return (
            "Git deregistered it but the directory could not be deleted; nothing registers "
            "it now, so no verb will remove those bytes for you",
            f"inspect and remove {path} yourself, then "
            f"python scripts/worktree_lifecycle.py reconcile --path {path}",
        )

    intents = pending_removals_of(state)
    for key, intent in sorted(intents.items()):
        path = Path(str(intent.get("path", key)))
        detail, cure = removal_cure(key, path)
        contradictions.append(
            {
                "code": "interrupted_removal",
                "severity": "error",
                "origin": "intent",
                "reason": (
                    f"{intent.get('verb', 'removal')} intent from "
                    f"{intent.get('started_at')} was never completed: {detail}"
                ),
                "path": str(path),
                "tree_present": path.exists(),
                "still_registered": key in registered,
                "cure": cure,
            }
        )

    # A managed row whose path Git no longer registers. `audit` raises
    # MISSING_MANAGED_WORKTREE for this and stops there; the inventory has to carry it too,
    # with the cure that matches what is actually on disk. Skipped when an intent already
    # explains the same path -- one finding per fact.
    for key, record in sorted(managed.items()):
        if key in registered or key in intents:
            continue
        path = Path(str(record.get("path", key)))
        detail, cure = removal_cure(key, path)
        contradictions.append(
            {
                "code": "missing_registration",
                "severity": "error",
                "origin": "managed",
                "reason": f"managed row that Git does not register: {detail}",
                "path": str(path),
                "branch": record.get("branch"),
                "tree_present": path.exists(),
                "cure": cure,
            }
        )

    errors = [item for item in contradictions if item["severity"] == "error"]
    return {
        "status": "FAIL" if contradictions else "PASS",
        "registered": len(registrations),
        "main_path": main_key,
        "contradictions": contradictions,
        "contradiction_count": len(contradictions),
        "error_count": len(errors),
        "backlog_count": len(contradictions) - len(errors),
        "retired": len(retired_of(state)),
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
    audit_parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "read-only registry inventory: list EVERY stale registration, unscannable "
            "registration, unregistered worktree directory and interrupted removal, then "
            "exit nonzero on any `error`-severity finding. Runs the ordinary audit "
            "afterwards. Does not ratchet and does not mutate."
        ),
    )
    audit_parser.add_argument(
        "--all",
        dest="strict_all",
        action="store_true",
        help=(
            "with --strict: fail on inherited `backlog` findings too (legacy-snapshot and "
            "never-registered stale paths), not only on the records this tool owns"
        ),
    )
    audit_parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="extra directory to scan for unregistered worktrees (--strict only; repeatable)",
    )

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--path", required=True)
    create_parser.add_argument(
        "--branch",
        help="branch to create the worktree on; required unless --detach is given",
    )
    create_parser.add_argument(
        "--detach",
        action="store_true",
        help=(
            "create the worktree with a detached HEAD at --start-point. Required by "
            "certification consumers, which refuse to run on a branch-attached checkout."
        ),
    )
    create_parser.add_argument("--owner", required=True)
    create_parser.add_argument("--purpose", required=True)
    create_parser.add_argument("--expires", required=True)
    create_parser.add_argument("--start-point", default="HEAD")

    retire_parser = subparsers.add_parser("retire")
    retire_parser.add_argument("--path", required=True)
    retire_parser.add_argument(
        "--force-owner",
        help=(
            "retire even when the worktree is dirty, but ONLY if the managed row's owner "
            "equals this value. For automated owners whose scratch cleanup was interrupted."
        ),
    )
    retire_parser.add_argument(
        "--reason",
        default="retired by owner",
        help="recorded on the tombstone so the retirement stays auditable",
    )

    renew_parser = subparsers.add_parser("renew")
    renew_parser.add_argument("--path", required=True)
    horizon = renew_parser.add_mutually_exclusive_group(required=True)
    horizon.add_argument(
        "--days",
        type=int,
        help=f"extend the lease to today plus N days (1..{RENEWAL_CAP_DAYS})",
    )
    horizon.add_argument(
        "--until",
        help=f"extend the lease to an ISO date, at most {RENEWAL_CAP_DAYS} days out",
    )

    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument(
        "--path",
        required=True,
        help=(
            "exact registered path of a managed row whose worktree is gone; "
            "refuses when the worktree is live or the path has any content"
        ),
    )
    reconcile_parser.add_argument(
        "--reason",
        default="registration stale: worktree directory no longer present",
        help="recorded on the tombstone so the cleared row stays auditable",
    )
    reconcile_parser.add_argument(
        "--abandon-intent",
        action="store_true",
        help=(
            "clear ONLY a leftover removal intent for this path, changing nothing else. "
            "For a removal that failed with the worktree intact and will not be retried."
        ),
    )
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
                if args.strict:
                    # The inventory runs FIRST and in full. audit_state raises on its first
                    # violation, and on MISSING_MANAGED_WORKTREE in particular, either of
                    # which would truncate the listing this mode exists to print. It still
                    # runs afterwards, so --strict is a superset of the plain check and a
                    # hook can call one command and get both.
                    payload = strict_report(repo, state, args.root, deep=args.strict_all)
                    emit(payload, args.quiet)
                    fatal = [
                        item
                        for item in payload["contradictions"]
                        if args.strict_all or item["severity"] == "error"
                    ]
                    if fatal:
                        raise LifecycleError(
                            "REGISTRY_CONTRADICTION",
                            "; ".join(f"{item['code']} {item['path']}" for item in fatal),
                        )
                state, payload = audit_state(repo, state, ratchet=args.ratchet)
                if args.ratchet:
                    write_state(state_file, state)
                emit(payload, args.quiet or args.strict)
            elif args.command == "create":
                if args.detach and args.branch:
                    raise LifecycleError(
                        "DETACH_WITH_BRANCH",
                        "--detach creates a detached HEAD; --branch is meaningless with it",
                    )
                if not args.detach and not args.branch:
                    raise LifecycleError(
                        "BRANCH_REQUIRED", "pass --branch <name> or --detach"
                    )
                emit(create_worktree(repo, state_file, args), False)
            elif args.command == "retire":
                emit(
                    retire_worktree(
                        repo,
                        state_file,
                        args.path,
                        args.reason,
                        force_owner=args.force_owner,
                    ),
                    False,
                )
            elif args.command == "renew":
                emit(renew_worktree(repo, state_file, args), False)
            elif args.command == "reconcile":
                emit(
                    reconcile_worktree(
                        repo, state_file, args.path, args.reason, args.abandon_intent
                    ),
                    False,
                )
            else:
                raise AssertionError(args.command)
        return 0
    except LifecycleError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    from gate_provenance import emit_gate_provenance

    emit_gate_provenance(__file__)
    raise SystemExit(main())

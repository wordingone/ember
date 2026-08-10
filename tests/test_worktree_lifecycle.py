# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*args],
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if check and result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, cwd=repo, check=check)


def lifecycle(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(SCRIPT), "--repo", str(repo), *args, cwd=repo, check=check)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.name", "Ember Test")
    git(repo, "config", "user.email", "ember@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-m", "seed")
    return repo


def state_path(repo: Path) -> Path:
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common) / "ember-worktree-lifecycle.json"


def test_install_snapshots_legacy_worktrees_and_sets_target_floor(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    legacy = tmp_path / "legacy"
    git(repo, "worktree", "add", "-b", "legacy", str(legacy))

    result = lifecycle(repo, "install", "--target", "3")
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert state["version"] == 1
    assert state["target"] == 3
    assert state["ceiling"] == 3
    assert len(state["legacy_paths"]) == 2
    assert state["managed"] == {}


def test_audit_rejects_raw_unmanaged_worktree_after_install(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    raw = tmp_path / "raw"
    git(repo, "worktree", "add", "-b", "raw", str(raw))

    result = lifecycle(repo, "audit", check=False)

    assert result.returncode == 2
    assert "UNMANAGED_WORKTREE" in result.stderr
    assert str(raw.resolve()) in result.stderr


def test_audit_ratchets_ceiling_down_after_verified_removal(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    git(repo, "worktree", "add", "-b", "first", str(first))
    git(repo, "worktree", "add", "-b", "second", str(second))
    lifecycle(repo, "install", "--target", "1")
    git(repo, "worktree", "remove", str(second))

    lifecycle(repo, "audit", "--ratchet")
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert state["ceiling"] == 2
    assert str(second.resolve()).casefold() not in state["legacy_paths"]


def test_create_registers_custody_and_refuses_growth_at_ceiling(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    managed = tmp_path / "managed"

    lifecycle(
        repo,
        "create",
        "--path",
        str(managed),
        "--branch",
        "managed",
        "--owner",
        "founder-one",
        "--purpose",
        "bounded-test",
        "--expires",
        "2099-01-01",
    )
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    key = str(managed.resolve()).casefold()
    assert state["managed"][key]["owner"] == "founder-one"
    assert state["managed"][key]["purpose"] == "bounded-test"

    refused = lifecycle(
        repo,
        "create",
        "--path",
        str(tmp_path / "overflow"),
        "--branch",
        "overflow",
        "--owner",
        "founder-one",
        "--purpose",
        "must-refuse",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert refused.returncode == 2
    assert "WORKTREE_CEILING" in refused.stderr
    assert not (tmp_path / "overflow").exists()


def test_create_uses_ceiling_headroom_above_target(tmp_path: Path) -> None:
    """Regression: create must NOT ratchet the ceiling down to the live count before
    deciding whether it can grow. When ``target <= live < ceiling`` (headroom exists
    above target), create is obliged to use that headroom. The old create path called
    ``audit_state(..., ratchet=True)``, which collapsed ceiling to ``max(live, target)``
    == live, then failed its own ``live >= ceiling`` check -- so managed create could
    never add a worktree whenever live was at or above target, even with ceiling
    headroom. This fleet-wide blocker is fixed by matching ``retire`` (ratchet=False):
    the ceiling only ratchets down on verified removal, never on a growth attempt.
    """
    repo = make_repo(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    git(repo, "worktree", "add", "-b", "first", str(first))
    git(repo, "worktree", "add", "-b", "second", str(second))

    # Fresh install with 3 live worktrees (repo + first + second) and target 2:
    # ceiling = max(3, 2) = 3. install on a fresh state does NOT ratchet, so ceiling
    # persists at 3.
    lifecycle(repo, "install", "--target", "2")
    installed = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert installed["ceiling"] == 3
    assert installed["target"] == 2

    # Drop one worktree with a raw git removal (NOT the ratcheting retire command), so
    # the state file's ceiling stays 3 while live falls to 2. Now target(2) <= live(2)
    # < ceiling(3): genuine headroom above target for exactly one managed worktree.
    git(repo, "worktree", "remove", str(second))

    grown = tmp_path / "grown"
    result = lifecycle(
        repo,
        "create",
        "--path",
        str(grown),
        "--branch",
        "grown",
        "--owner",
        "founder-one",
        "--purpose",
        "headroom-growth",
        "--expires",
        "2099-01-01",
        check=False,
    )
    # On the old ratchet=True create path this raises WORKTREE_CEILING (the bug);
    # after the fix it succeeds and consumes the headroom up to the ceiling.
    assert result.returncode == 0, (
        "create must use ceiling headroom above target; "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert grown.exists()
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    key = str(grown.resolve()).casefold()
    assert state["managed"][key]["owner"] == "founder-one"
    # Ceiling was NOT ratcheted down by the growth attempt; live now equals ceiling.
    assert state["ceiling"] == 3

    # The ceiling is still a hard wall: a further create at live==ceiling must refuse.
    refused = lifecycle(
        repo,
        "create",
        "--path",
        str(tmp_path / "overflow"),
        "--branch",
        "overflow",
        "--owner",
        "founder-one",
        "--purpose",
        "must-refuse",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert refused.returncode == 2
    assert "WORKTREE_CEILING" in refused.stderr
    assert not (tmp_path / "overflow").exists()


def test_retire_frees_replacement_slot_within_ceiling(tmp_path: Path) -> None:
    """Acceptance (1): the bounded replacement slot. audit --ratchet at live N sets
    ceiling==N (the realistic fleet state where ceiling==live); retire drops to N-1
    WITHOUT lowering ceiling; create then refills the freed slot back to N. RED on old
    code (retire clamped ceiling to N-1, then create refused live==ceiling); GREEN with
    both ratchet sites corrected.
    """
    repo = make_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    git(repo, "worktree", "add", "-b", "a", str(a))
    git(repo, "worktree", "add", "-b", "b", str(b))  # live == 3 (repo + a + b)
    lifecycle(repo, "install", "--target", "2")  # ceiling = max(3, 2) = 3
    lifecycle(repo, "audit", "--ratchet")  # ceiling ratchets to live == 3
    assert json.loads(state_path(repo).read_text(encoding="utf-8"))["ceiling"] == 3

    lifecycle(repo, "retire", "--path", str(b))  # live -> 2; ceiling MUST stay 3
    after_retire = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert after_retire["ceiling"] == 3, "retire must preserve the ceiling as a slot"

    replacement = tmp_path / "replacement"
    result = lifecycle(
        repo,
        "create",
        "--path",
        str(replacement),
        "--branch",
        "replacement",
        "--owner",
        "founder-two",
        "--purpose",
        "refill-slot",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert result.returncode == 0, (
        "create must refill the freed replacement slot; "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert replacement.exists()
    assert len(git(repo, "worktree", "list").stdout.strip().splitlines()) == 3


def test_create_refuses_at_ceiling_bound(tmp_path: Path) -> None:
    """Acceptance (2): ceiling still bounds. At live == ceiling, create refuses.
    Invariant guard (green before and after the fix) -- proves the fix did not remove
    the hard wall.
    """
    repo = make_repo(tmp_path)
    git(repo, "worktree", "add", "-b", "a", str(tmp_path / "a"))
    git(repo, "worktree", "add", "-b", "b", str(tmp_path / "b"))  # live == 3
    lifecycle(repo, "install", "--target", "2")  # ceiling = 3 == live
    result = lifecycle(
        repo,
        "create",
        "--path",
        str(tmp_path / "overflow"),
        "--branch",
        "overflow",
        "--owner",
        "founder-two",
        "--purpose",
        "must-refuse",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert result.returncode == 2
    assert "WORKTREE_CEILING" in result.stderr
    assert not (tmp_path / "overflow").exists()


def test_audit_ratchet_reduces_ceiling_to_live_slack(tmp_path: Path) -> None:
    """Acceptance (3): explicit operator ratchet still works. With unused slack
    (live < ceiling), `audit --ratchet` reduces ceiling to live. Invariant guard
    (green before and after) -- proves ceiling reduction still happens through the one
    sanctioned path after retire stopped clamping.
    """
    repo = make_repo(tmp_path)
    git(repo, "worktree", "add", "-b", "a", str(tmp_path / "a"))
    keep = tmp_path / "b"
    git(repo, "worktree", "add", "-b", "b", str(keep))  # live == 3
    lifecycle(repo, "install", "--target", "2")  # ceiling = 3
    # Raw removal (bypasses the retire path) leaves ceiling == 3 with live == 2 slack.
    git(repo, "worktree", "remove", str(keep))
    lifecycle(repo, "audit", "--ratchet")
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert state["ceiling"] == 2


def test_repeated_create_cannot_exceed_ceiling(tmp_path: Path) -> None:
    """Acceptance (4): repeated create is bounded by ceiling. Fill every slot up to
    ceiling, then the next create refuses. Invariant guard (green before and after).
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")  # live == 1, ceiling = max(1, 3) = 3
    for name in ("m1", "m2"):  # fill to live == 3 == ceiling
        created = lifecycle(
            repo,
            "create",
            "--path",
            str(tmp_path / name),
            "--branch",
            name,
            "--owner",
            "founder-two",
            "--purpose",
            "fill",
            "--expires",
            "2099-01-01",
            check=False,
        )
        assert created.returncode == 0, f"{name}: {created.stderr}"
    refused = lifecycle(
        repo,
        "create",
        "--path",
        str(tmp_path / "m3"),
        "--branch",
        "m3",
        "--owner",
        "founder-two",
        "--purpose",
        "over-ceiling",
        "--expires",
        "2099-01-01",
        check=False,
    )
    assert refused.returncode == 2
    assert "WORKTREE_CEILING" in refused.stderr
    assert not (tmp_path / "m3").exists()


def expire_managed_worktrees(repo: Path, *worktrees: Path) -> None:
    path = state_path(repo)
    state = json.loads(path.read_text(encoding="utf-8"))
    for worktree in worktrees:
        key = str(worktree.resolve()).casefold()
        state["managed"][key]["expires"] = "2000-01-01"
    path.write_text(json.dumps(state), encoding="utf-8")


def test_retire_removes_exactly_one_of_two_expired_worktrees(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    first = tmp_path / "expired-first"
    second = tmp_path / "expired-second"
    for path, branch in ((first, "expired-first"), (second, "expired-second")):
        lifecycle(
            repo,
            "create",
            "--path",
            str(path),
            "--branch",
            branch,
            "--owner",
            "founder-one",
            "--purpose",
            "expiry-retirement-test",
            "--expires",
            "2099-01-01",
        )
    expire_managed_worktrees(repo, first, second)

    result = lifecycle(repo, "retire", "--path", str(first), check=False)

    assert result.returncode == 0, result.stderr
    assert not first.exists()
    assert second.exists()
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert str(first.resolve()).casefold() not in state["managed"]
    second_record = state["managed"][str(second.resolve()).casefold()]
    assert second_record["expires"] == "2000-01-01"

    audit = lifecycle(repo, "audit", check=False)
    assert audit.returncode == 2
    assert "EXPIRED_WORKTREE" in audit.stderr
    assert str(second.resolve()) in audit.stderr


def test_expiry_still_blocks_create(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    expired = tmp_path / "expired"
    lifecycle(
        repo,
        "create",
        "--path",
        str(expired),
        "--branch",
        "expired",
        "--owner",
        "founder-one",
        "--purpose",
        "expiry-create-test",
        "--expires",
        "2099-01-01",
    )
    expire_managed_worktrees(repo, expired)

    candidate = tmp_path / "must-not-create"
    result = lifecycle(
        repo,
        "create",
        "--path",
        str(candidate),
        "--branch",
        "must-not-create",
        "--owner",
        "founder-one",
        "--purpose",
        "expiry-must-block-create",
        "--expires",
        "2099-01-01",
        check=False,
    )

    assert result.returncode == 2
    assert "EXPIRED_WORKTREE" in result.stderr
    assert not candidate.exists()


def test_retire_still_refuses_dirty_expired_worktree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    expired = tmp_path / "expired-dirty"
    lifecycle(
        repo,
        "create",
        "--path",
        str(expired),
        "--branch",
        "expired-dirty",
        "--owner",
        "founder-one",
        "--purpose",
        "dirty-expired-test",
        "--expires",
        "2099-01-01",
    )
    (expired / "untracked.bin").write_bytes(b"do not delete")
    expire_managed_worktrees(repo, expired)

    result = lifecycle(repo, "retire", "--path", str(expired), check=False)

    assert result.returncode == 2
    assert "DIRTY_WORKTREE" in result.stderr
    assert expired.exists()
    assert (expired / "untracked.bin").read_bytes() == b"do not delete"


def test_retire_still_refuses_unmanaged_worktree_when_a_lease_is_expired(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    expired = tmp_path / "expired-managed"
    lifecycle(
        repo,
        "create",
        "--path",
        str(expired),
        "--branch",
        "expired-managed",
        "--owner",
        "founder-one",
        "--purpose",
        "unmanaged-guard-test",
        "--expires",
        "2099-01-01",
    )
    expire_managed_worktrees(repo, expired)
    raw = tmp_path / "raw-unmanaged"
    git(repo, "worktree", "add", "-b", "raw-unmanaged", str(raw))

    result = lifecycle(repo, "retire", "--path", str(raw), check=False)

    assert result.returncode == 2
    assert "UNMANAGED_WORKTREE" in result.stderr
    assert raw.exists()
    assert expired.exists()


def test_retire_refuses_dirty_worktree_without_force(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "2")
    managed = tmp_path / "managed"
    lifecycle(
        repo,
        "create",
        "--path",
        str(managed),
        "--branch",
        "managed",
        "--owner",
        "founder-one",
        "--purpose",
        "dirty-test",
        "--expires",
        "2099-01-01",
    )
    (managed / "untracked.bin").write_bytes(b"do not delete")

    result = lifecycle(repo, "retire", "--path", str(managed), check=False)

    assert result.returncode == 2
    assert "DIRTY_WORKTREE" in result.stderr
    assert managed.exists()
    assert (managed / "untracked.bin").read_bytes() == b"do not delete"


def test_retire_archives_detached_head_and_preserves_ceiling(tmp_path: Path) -> None:
    # CONTRACT CHANGE (was test_retire_archives_detached_head_and_ratchets): retire no
    # longer ratchets the ceiling down. It archives the detached head and frees a slot,
    # but the ceiling is preserved as a bounded replacement pool -- only the explicit
    # operator `audit --ratchet` path lowers it. Under the old code this asserted
    # ceiling == 1; with the shrink-only-ramp bug removed, ceiling stays at its
    # install-time value (2) so a subsequent create can refill the freed slot.
    repo = make_repo(tmp_path)
    detached = tmp_path / "detached"
    git(repo, "worktree", "add", "--detach", str(detached), "HEAD")
    head = git(detached, "rev-parse", "HEAD").stdout.strip()
    lifecycle(repo, "install", "--target", "1")

    result = lifecycle(repo, "retire", "--path", str(detached))
    payload = json.loads(result.stdout)
    archived = git(repo, "rev-parse", payload["archive_ref"]).stdout.strip()
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))

    assert archived == head
    assert not detached.exists()
    # install with 2 live worktrees (repo + detached), target 1 -> ceiling = 2; retire
    # preserves it. (Old contract clamped this to 1.)
    assert state["ceiling"] == 2


def test_hooks_and_agents_require_lifecycle_guard() -> None:
    pre_commit = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    pre_push = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    invocation = 'bash "$ROOT/tools/run-python-hidden.sh" "$ROOT/scripts/worktree_lifecycle.py" audit --strict --quiet'
    assert invocation in pre_commit
    assert invocation in pre_push
    assert "scripts/worktree_lifecycle.py create" in agents
    assert "scripts/worktree_lifecycle.py retire" in agents
    assert "Raw `git worktree add` and recursive worktree deletion are forbidden" in agents


def test_hooks_and_repo_guard_have_one_hidden_python_boundary() -> None:
    surfaces = [
        REPO_ROOT / ".githooks" / "pre-commit",
        REPO_ROOT / ".githooks" / "pre-push",
        REPO_ROOT / "tools" / "repo-guard.sh",
    ]
    for surface in surfaces:
        source = surface.read_text(encoding="utf-8")
        assert "run-python-hidden.sh" in source
        assert re.search(r"(?m)(^|[=( ])python(?:3)?\s", source) is None

    shell_launcher = (REPO_ROOT / "tools" / "run-python-hidden.sh").read_text(
        encoding="utf-8"
    )
    assert '"${OS:-}" = "Windows_NT"' in shell_launcher
    assert "-WindowStyle Hidden" in shell_launcher
    assert "-EncodedCommand \"$encoded_command\"" in shell_launcher
    assert "iconv -f UTF-8 -t UTF-16LE" in shell_launcher
    assert "run-python-hidden.ps1" not in shell_launcher


def test_windows_hidden_python_boundary_preserves_streams_args_and_exit(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        return
    child = tmp_path / "child.py"
    child.write_text(
        "import sys\n"
        "payload = sys.stdin.read()\n"
        "print('ARGS:' + repr(sys.argv[1:]))\n"
        "print('IN:' + payload)\n"
        "print('ERR:' + sys.argv[2], file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["EMBER_PYTHON_BIN"] = sys.executable
    env["EMBER_HIDDEN_HELPER"] = str(REPO_ROOT / "tools" / "run-python-hidden.sh")
    env["EMBER_HIDDEN_CHILD"] = str(child)
    env["EMBER_HIDDEN_ARG_SPACE"] = "alpha with space"
    env["EMBER_HIDDEN_ARG_QUOTE"] = "beta'quoted"
    result = subprocess.run(
        [
            "C:/Program Files/Git/bin/bash.exe",
            "-lc",
            'bash "$EMBER_HIDDEN_HELPER" "$EMBER_HIDDEN_CHILD" '
            '"$EMBER_HIDDEN_ARG_SPACE" "$EMBER_HIDDEN_ARG_QUOTE" ""',
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=env,
        input="stdin-value",
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert result.returncode == 7
    assert result.stdout == "ARGS:['alpha with space', \"beta'quoted\", '']\nIN:stdin-value\n"
    assert result.stderr == "ERR:beta'quoted\n"


# ---------------------------------------------------------------------------
# reconcile: the exit for a managed row whose worktree is genuinely gone
# ---------------------------------------------------------------------------


def path_key_of(value: Path) -> str:
    """Mirror of the tool's own registry key derivation (canonical + casefold)."""
    return str(Path(value).expanduser().resolve(strict=False)).casefold()


def _managed(repo: Path, tmp_path: Path, name: str) -> Path:
    """Create one managed worktree and return its path."""
    path = tmp_path / name
    lifecycle(
        repo, "create",
        "--path", str(path),
        "--branch", name,
        "--owner", "founder-one",
        "--purpose", f"managed-{name}",
        "--expires", "2099-01-01",
    )
    return path


def test_reconcile_clears_a_row_whose_worktree_was_deleted_outside_the_tool(
    tmp_path: Path,
) -> None:
    """The incident this verb exists for: an owner removes the directory without
    retiring, so audit -- and therefore create, retire and the push guard -- raise
    MISSING_MANAGED_WORKTREE with no way to clear the row. RED before reconcile
    existed: the only recovery was to physically reconstruct the worktree first.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "gone")

    # Remove it the way the incident did: git forgets it, the row survives.
    git(repo, "worktree", "remove", str(gone))
    assert not gone.exists()

    blocked = lifecycle(repo, "audit", check=False)
    assert blocked.returncode == 2
    assert "MISSING_MANAGED_WORKTREE" in blocked.stderr

    result = lifecycle(repo, "reconcile", "--path", str(gone))
    assert '"status": "RECONCILED"' in result.stdout
    # The branch is NOT deleted -- the row goes, the ref stays.
    assert "gone" in git(repo, "branch", "--list", "gone").stdout

    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert path_key_of(gone) not in state["managed"]
    # And the deadlock is cleared: audit passes again.
    assert lifecycle(repo, "audit", check=False).returncode == 0


def test_reconcile_clears_a_row_whose_directory_was_deleted_raw(tmp_path: Path) -> None:
    """The ACTUAL incident shape, which the test above does not reproduce.

    `git worktree remove` clears git's administrative metadata as it goes. The incident
    was an owner deleting the directory -- nothing tells git, so `.git/worktrees/<name>`
    survives and `git worktree list --porcelain` still lists the path, marked prunable.
    Reconcile computed its live set from that listing before pruning, so it classified
    exactly this shape as WORKTREE_LIVE and refused: the verb deadlocked on the one case
    it was written for, while a test built on `worktree remove` stayed green.

    RED before the ordering fix: this asserted WORKTREE_LIVE on the reconcile call.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "raw-deleted")

    # Delete the directory the way the incident did. Git is never told.
    shutil.rmtree(gone)
    assert not gone.exists()

    # The metadata git keeps is what distinguishes this from the `worktree remove` path,
    # so assert it is actually still there -- otherwise this test silently degrades into
    # a duplicate of the one above.
    listed = git(repo, "worktree", "list", "--porcelain").stdout
    assert str(gone) in listed or str(gone).replace("\\", "/") in listed.replace("\\", "/"), (
        "precondition: git must still list the deleted worktree, or this is not the shape"
    )

    # Measured, not assumed: in THIS shape audit still passes, because its live set comes
    # from the same listing and a prunable row counts as present. So the trap is not a
    # loud one -- it is that the row has no exit. Retire cannot run (git cannot chdir into
    # a directory that is gone), and reconcile refused it as WORKTREE_LIVE. Both verbs
    # out, and audit goes loud later anyway, the moment git's own gc prunes the metadata.
    stuck = lifecycle(repo, "retire", "--path", str(gone), check=False)
    assert stuck.returncode == 2
    assert "GIT_ERROR" in stuck.stderr, "retire is not the exit for a vanished directory"

    result = lifecycle(repo, "reconcile", "--path", str(gone))
    assert '"status": "RECONCILED"' in result.stdout
    # The retained branch survives, exactly as on the clean path.
    assert "raw-deleted" in git(repo, "branch", "--list", "raw-deleted").stdout

    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert path_key_of(gone) not in state["managed"]
    assert lifecycle(repo, "audit", check=False).returncode == 0


def test_reconcile_touches_only_the_requested_row_and_its_metadata(tmp_path: Path) -> None:
    """The exact-path contract, against the collateral shape that broke it.

    `git worktree prune` is repository-wide. Reconciling A with it cleared the metadata of
    every other prunable worktree too, while removing only A's row -- so B went from
    "listed, quietly stuck" to "not listed, and now MISSING_MANAGED_WORKTREE", which blocks
    pushes repo-wide. That is this verb's own deadlock, moved onto someone else's row.

    Two raw-deleted worktrees are the smallest case that can show it: with one, a global
    prune and a targeted one are indistinguishable.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    first = _managed(repo, tmp_path, "first-gone")
    second = _managed(repo, tmp_path, "second-gone")

    shutil.rmtree(first)
    shutil.rmtree(second)

    result = lifecycle(repo, "reconcile", "--path", str(first))
    assert '"status": "RECONCILED"' in result.stdout

    listed = git(repo, "worktree", "list", "--porcelain").stdout.replace("\\", "/")
    assert str(first).replace("\\", "/") not in listed, "the requested record must be gone"
    assert str(second).replace("\\", "/") in listed, "B's git metadata is not this call's to touch"

    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert path_key_of(first) not in state["managed"]
    assert path_key_of(second) in state["managed"], "B's row must survive"

    # And B is not stranded: audit is no worse than before, and B still has its own exit.
    assert lifecycle(repo, "audit", check=False).returncode == 0
    assert '"status": "RECONCILED"' in lifecycle(repo, "reconcile", "--path", str(second)).stdout
    assert lifecycle(repo, "audit", check=False).returncode == 0


def load_lifecycle_module():
    """Import the tool in-process, for the one negative that needs to fail its own removal."""
    import importlib.util

    name = "worktree_lifecycle_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves its annotations through sys.modules, and
    # an unregistered module makes that lookup return None mid-import.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_reconcile_preserves_the_row_when_the_metadata_survives(tmp_path: Path) -> None:
    """The row and its Git metadata leave together, or neither leaves.

    The target-scoped remover returns False for two opposite facts -- "already gone" and
    "could not find or read the record" -- so its return value cannot decide anything. If
    the metadata survives and the row is popped anyway, the exact path becomes an
    UNMANAGED_WORKTREE and blocks the repo: the same stranded state as the global-prune
    collateral, relocated onto the requested row.

    So the check is a re-list under the same lock, which is authoritative in both
    directions. Here the removal is made to do nothing, which is the production failure
    outcome, and reconcile must refuse rather than write.
    """
    module = load_lifecycle_module()
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "removal-fails")
    shutil.rmtree(gone)

    module.prune_one_worktree_metadata = lambda *_args, **_kwargs: False

    state_file = state_path(repo)
    try:
        module.reconcile_worktree(Path(repo), Path(state_file), str(gone))
    except module.LifecycleError as caught:
        assert caught.code == "METADATA_REMOVAL_FAILED"
    else:  # pragma: no cover - the assertion below reports it either way
        raise AssertionError("reconcile must refuse when the metadata survives")

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert path_key_of(gone) in state["managed"], "the row must survive a failed removal"

    # The registry is no worse than before: still managed, still listed, still recoverable
    # by a reconcile that CAN remove the metadata.
    assert lifecycle(repo, "audit", check=False).returncode == 0
    assert '"status": "RECONCILED"' in lifecycle(repo, "reconcile", "--path", str(gone)).stdout


def test_reconcile_refuses_a_live_worktree(tmp_path: Path) -> None:
    """A live worktree is retire's business -- retire carries the clean-tree and
    archive-ref checks this verb deliberately lacks. Reconcile must never become a
    way around them.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    live = _managed(repo, tmp_path, "live")

    result = lifecycle(repo, "reconcile", "--path", str(live), check=False)
    assert result.returncode == 2
    assert "WORKTREE_LIVE" in result.stderr
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert path_key_of(live) in state["managed"], "the row must survive a refusal"


def test_reconcile_refuses_when_the_path_still_has_content(tmp_path: Path) -> None:
    """The load-bearing safety property: reconcile steps over an EMPTY directory and
    nothing else. If bytes are there, someone may still be holding them, and clearing
    the row would strand them outside every check.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    stranded = _managed(repo, tmp_path, "stranded")

    # git no longer tracks it, but the directory has content.
    git(repo, "worktree", "remove", str(stranded))
    stranded.mkdir(parents=True, exist_ok=True)
    (stranded / "unsaved.txt").write_text("work nobody has copied out\n", encoding="utf-8")

    result = lifecycle(repo, "reconcile", "--path", str(stranded), check=False)
    assert result.returncode == 2
    assert "PATH_NOT_EMPTY" in result.stderr
    assert (stranded / "unsaved.txt").exists(), "reconcile must not touch bytes"
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    assert path_key_of(stranded) in state["managed"]


def test_reconcile_refuses_an_unregistered_path(tmp_path: Path) -> None:
    """Exact-path only, managed rows only: this can never become a blanket sweep."""
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")

    result = lifecycle(repo, "reconcile", "--path", str(tmp_path / "never-registered"), check=False)
    assert result.returncode == 2
    assert "NOT_MANAGED" in result.stderr


def test_reconcile_refuses_a_legacy_snapshot_path(tmp_path: Path) -> None:
    """legacy_paths are the install-time snapshot and are not this verb's to edit."""
    repo = make_repo(tmp_path)
    legacy = tmp_path / "legacy"
    git(repo, "worktree", "add", "-b", "legacy", str(legacy))
    lifecycle(repo, "install", "--target", "6")

    result = lifecycle(repo, "reconcile", "--path", str(legacy), check=False)
    assert result.returncode == 2
    # Live, so the live check fires first -- either refusal is correct, but it must
    # never succeed.
    assert "WORKTREE_LIVE" in result.stderr or "LEGACY_PATH" in result.stderr


# ---------------------------------------------------------------------------
# --detach (#1371): certification consumers refuse a branch-attached checkout
# ---------------------------------------------------------------------------


def test_create_detach_leaves_head_detached_and_mints_no_branch_ref(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = tmp_path / "detached-wt"

    result = lifecycle(
        repo,
        "create",
        "--path",
        str(target),
        "--detach",
        "--owner",
        "ember-cli-verify",
        "--purpose",
        "verify dispatch",
        "--expires",
        "2999-01-01",
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "CREATED"
    assert payload["detached"] is True
    assert payload["branch"] is None
    # The property the verifier actually reads: symbolic-ref fails on a detached HEAD.
    assert git(target, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0
    # No refs/heads/* accumulates per run -- the leak the attached mode caused.
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/").stdout.strip() == (
        "refs/heads/master"
    )
    state = json.loads(state_path(repo).read_text(encoding="utf-8"))
    row = next(iter(state["managed"].values()))
    assert row["detached"] is True
    assert row["branch"] is None


def test_create_refuses_detach_together_with_branch_and_refuses_neither(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")

    both = lifecycle(
        repo, "create", "--path", str(tmp_path / "a"), "--detach", "--branch", "x",
        "--owner", "o", "--purpose", "p", "--expires", "2999-01-01", check=False,
    )
    assert both.returncode == 2
    assert "DETACH_WITH_BRANCH" in both.stderr

    neither = lifecycle(
        repo, "create", "--path", str(tmp_path / "b"),
        "--owner", "o", "--purpose", "p", "--expires", "2999-01-01", check=False,
    )
    assert neither.returncode == 2
    assert "BRANCH_REQUIRED" in neither.stderr


def test_retire_of_a_detached_row_archives_its_head(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = tmp_path / "detached-retire"
    lifecycle(
        repo, "create", "--path", str(target), "--detach",
        "--owner", "ember-cli-verify", "--purpose", "p", "--expires", "2999-01-01",
    )

    payload = json.loads(lifecycle(repo, "retire", "--path", str(target)).stdout)

    assert payload["status"] == "RETIRED"
    assert payload["archive_ref"]
    assert git(repo, "rev-parse", payload["archive_ref"]).stdout.strip() == payload["head"]


# ---------------------------------------------------------------------------
# --force-owner retire (#1371 N3): a killed pipeline leaves its own scratch behind
# ---------------------------------------------------------------------------


def test_force_owner_retires_a_dirty_worktree_only_for_the_owner_that_created_it(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = tmp_path / "dirty-wt"
    lifecycle(
        repo, "create", "--path", str(target), "--detach",
        "--owner", "ember-cli-verify", "--purpose", "p", "--expires", "2999-01-01",
    )
    # Exactly the residue a timeout leaves: verifier scratch nobody else wrote.
    (target / ".ember01-verify-custody.tmp.json").write_text("{}", encoding="utf-8")

    plain = lifecycle(repo, "retire", "--path", str(target), check=False)
    assert plain.returncode == 2
    assert "DIRTY_WORKTREE" in plain.stderr

    wrong_owner = lifecycle(
        repo, "retire", "--path", str(target), "--force-owner", "someone-else", check=False,
    )
    assert wrong_owner.returncode == 2
    assert "DIRTY_WORKTREE" in wrong_owner.stderr
    assert target.exists()

    forced = json.loads(
        lifecycle(repo, "retire", "--path", str(target), "--force-owner", "ember-cli-verify").stdout
    )
    assert forced["status"] == "RETIRED"
    assert forced["forced"] is True
    assert not target.exists()


def test_force_owner_does_not_weaken_a_clean_retire(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = tmp_path / "clean-wt"
    lifecycle(
        repo, "create", "--path", str(target), "--detach",
        "--owner", "ember-cli-verify", "--purpose", "p", "--expires", "2999-01-01",
    )

    payload = json.loads(
        lifecycle(repo, "retire", "--path", str(target), "--force-owner", "ember-cli-verify").stdout
    )
    # Nothing was dirty, so nothing was forced -- force is a fallback, not a mode.
    assert payload["forced"] is False


# ---------------------------------------------------------------------------
# sweep-time deregistration: stale registrations must fail mechanically (#1366)
# ---------------------------------------------------------------------------


def read_state(repo: Path) -> dict:
    return json.loads(state_path(repo).read_text(encoding="utf-8"))


def strict(repo: Path) -> subprocess.CompletedProcess[str]:
    return lifecycle(repo, "audit", "--strict", check=False)


def contradictions_of(result: subprocess.CompletedProcess[str]) -> list[dict]:
    return json.loads(result.stdout)["contradictions"]


def test_strict_audit_reports_a_registration_whose_directory_is_gone(tmp_path: Path) -> None:
    """The defect, stated mechanically.

    Thirteen registrations pointed at directories that were not there, and nothing said so
    until a custody census walked every one of them and reported the contradictions. Plain
    `audit` cannot be that alarm: a raw-deleted worktree is still LISTED by git, so audit's
    live set counts it as present and passes. That silence is the bug.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "swept")
    shutil.rmtree(gone)

    # Measured, not assumed: the old check is blind to this shape.
    assert lifecycle(repo, "audit", check=False).returncode == 0

    result = strict(repo)
    assert result.returncode == 2
    assert "REGISTRY_CONTRADICTION" in result.stderr
    stale = [item for item in contradictions_of(result) if item["code"] == "stale_registration"]
    assert [item["path"] for item in stale] == [str(gone)]
    assert "does not exist" in stale[0]["reason"]
    assert "reconcile --path" in stale[0]["cure"], "a report without a cure is a nag"


def test_strict_audit_reports_an_empty_registered_directory(tmp_path: Path) -> None:
    """An empty directory is not a worktree. A sweep that leaves the shell behind is the
    same stranded registration wearing a directory entry, and existence alone would pass it.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    hollow = _managed(repo, tmp_path, "hollow")
    shutil.rmtree(hollow)
    hollow.mkdir()

    result = strict(repo)
    assert result.returncode == 2
    stale = [item for item in contradictions_of(result) if item["code"] == "stale_registration"]
    assert [item["path"] for item in stale] == [str(hollow)]
    assert "empty" in stale[0]["reason"]


def test_strict_audit_names_the_cause_of_an_unscannable_registration(tmp_path: Path) -> None:
    """The census's other contradiction class, `registered_worktree_scan_failed`, reported
    a code and no cause -- which is what made the one ValueError worktree a manual
    investigation. The error text git gives us is carried through verbatim instead.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    broken = _managed(repo, tmp_path, "unreadable")
    # Git marks the linked-worktree `.git` file hidden on Windows, and a hidden file
    # cannot be reopened for writing -- so replace it rather than rewrite it.
    marker = broken / ".git"
    marker.unlink()
    marker.write_text("gitdir: nowhere-at-all\n", encoding="utf-8")

    result = strict(repo)
    assert result.returncode == 2
    failed = [item for item in contradictions_of(result) if item["code"] == "unscannable_registration"]
    assert [item["path"] for item in failed] == [str(broken)]
    assert failed[0]["reason"], "the cause must be named, not just the class"
    # The failing command is named too, and it is one the census actually runs.
    assert tuple(failed[0]["failing_probe"].split()) in {
        tuple(probe) for probe in load_lifecycle_module().CENSUS_MATERIAL_PROBES
    }


def test_strict_audit_reports_an_unregistered_worktree_directory(tmp_path: Path) -> None:
    """The mirror image: a linked-worktree directory with nobody registering it, which is
    what a half-finished create or a repaired-by-hand tree leaves behind.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    _managed(repo, tmp_path, "anchor")  # establishes tmp_path as a known root

    orphan = tmp_path / "orphan"
    orphan.mkdir()
    # The gitdir must point into THIS repository's common dir -- that is what makes the
    # directory ours to report rather than another repo's live worktree.
    (orphan / ".git").write_text(
        f"gitdir: {repo / '.git' / 'worktrees' / 'orphan'}\n", encoding="utf-8"
    )

    result = strict(repo)
    assert result.returncode == 2
    found = [item for item in contradictions_of(result) if item["code"] == "unregistered_worktree_dir"]
    assert [item["path"] for item in found] == [str(orphan)]


def test_strict_audit_ignores_a_neighbouring_repository(tmp_path: Path) -> None:
    """A `.git` DIRECTORY is somebody else's repository that happens to share a parent.
    Flagging it would make the check noisy enough to be ignored, which is how a mechanical
    check quietly stops being one.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    _managed(repo, tmp_path, "anchor")

    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    git(neighbour, "init", "-b", "master")

    result = strict(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["contradictions"] == []


def test_strict_audit_is_green_after_reconcile_clears_the_stale_row(tmp_path: Path) -> None:
    """Acceptance: after reconcile, a census finds zero worktree-registry contradictions.

    This is the fixture form of that clause -- a registry holding a missing-path row, cured,
    then re-inventoried by the same scan that found it.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "cured")
    shutil.rmtree(gone)
    assert strict(repo).returncode == 2

    lifecycle(repo, "reconcile", "--path", str(gone))

    result = strict(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["contradictions"] == []
    listed = git(repo, "worktree", "list", "--porcelain").stdout.replace("\\", "/")
    assert str(gone).replace("\\", "/") not in listed


def test_reconcile_writes_a_dated_reasoned_tombstone(tmp_path: Path) -> None:
    """Cleared, never silently dropped: the row leaves `managed` and enters the retirement
    log in the same write, so custody history survives its own cure.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    gone = _managed(repo, tmp_path, "buried")
    shutil.rmtree(gone)

    lifecycle(repo, "reconcile", "--path", str(gone), "--reason", "swept by post-merge cleanup")

    state = read_state(repo)
    assert path_key_of(gone) not in state["managed"]
    tombstone = state["retired"][path_key_of(gone)]
    assert tombstone["verb"] == "reconcile"
    assert tombstone["reason"] == "swept by post-merge cleanup"
    assert tombstone["retired_on"], "a tombstone without a date is not custody history"
    assert tombstone["owner"] == "founder-one"
    assert tombstone["branch"] == "buried"


def test_retire_deregisters_and_leaves_no_removal_intent(tmp_path: Path) -> None:
    """The class-kill on the clean path: the directory, the Git registration and the
    registry row move together, and the intent that guards the interval is cleared only
    once the deregistration has been READ BACK from git rather than inferred.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    doomed = _managed(repo, tmp_path, "doomed")

    lifecycle(repo, "retire", "--path", str(doomed), "--reason", "lane finished")

    state = read_state(repo)
    assert path_key_of(doomed) not in state["managed"]
    assert state["pending_removals"] == {}, "a completed retirement leaves no intent behind"
    tombstone = state["retired"][path_key_of(doomed)]
    assert tombstone["verb"] == "retire"
    assert tombstone["reason"] == "lane finished"

    listed = git(repo, "worktree", "list", "--porcelain").stdout.replace("\\", "/")
    assert str(doomed).replace("\\", "/") not in listed
    result = strict(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_strict_audit_reports_an_interrupted_removal(tmp_path: Path) -> None:
    """A process killed between removing a tree and deregistering it used to leave nothing
    but a stale registration nobody would look for. It now leaves a declared intent, and
    the intent is itself a contradiction with a cure attached.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    interrupted = _managed(repo, tmp_path, "interrupted")

    state = read_state(repo)
    state["pending_removals"] = {
        path_key_of(interrupted): {
            "path": str(interrupted),
            "verb": "retire",
            "started_at": "2026-08-03T00:00:00+00:00",
        }
    }
    state_path(repo).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    result = strict(repo)
    assert result.returncode == 2
    found = [item for item in contradictions_of(result) if item["code"] == "interrupted_removal"]
    assert [item["path"] for item in found] == [str(interrupted)]
    assert "2026-08-03" in found[0]["reason"]


def test_reconcile_refusal_writes_no_tombstone(tmp_path: Path) -> None:
    """A refusal must be a no-op in the log too. A tombstone for a row that is still
    registered would make the retirement log lie in exactly the direction that costs the
    most: it would look like the cure had already been applied.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    holding = _managed(repo, tmp_path, "holding")
    git(repo, "worktree", "remove", str(holding))
    holding.mkdir(parents=True, exist_ok=True)
    (holding / "unsaved.txt").write_text("work nobody has copied out\n", encoding="utf-8")

    result = lifecycle(repo, "reconcile", "--path", str(holding), check=False)
    assert result.returncode == 2
    assert "PATH_NOT_EMPTY" in result.stderr

    state = read_state(repo)
    assert path_key_of(holding) in state["managed"]
    assert state.get("retired", {}) == {}
    assert state.get("pending_removals", {}) == {}


def test_agents_documents_the_mechanical_registry_check() -> None:
    """The check only kills the class if the next agent knows it exists."""
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/worktree_lifecycle.py audit --strict" in agents


def test_strict_audit_ignores_another_repositorys_linked_worktree(tmp_path: Path) -> None:
    """A `.git` FILE is not evidence of OUR worktree -- it is what EVERY repository's
    linked worktree looks like. The un-scoped marker test reported ~70 of them on this host
    -- other repositories' live trees, sharing a parent directory with ours -- each with
    "or remove the directory" attached, which is destructive advice aimed at someone else's
    work and enough noise to bury the real findings. The gitdir must resolve inside THIS
    repository's common dir.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    _managed(repo, tmp_path, "anchor")  # establishes tmp_path as a known root

    (tmp_path / "stranger-home").mkdir()
    stranger = make_repo(tmp_path / "stranger-home")
    stranger_worktree = tmp_path / "stranger-worktree"
    git(stranger, "worktree", "add", "-b", "stranger", str(stranger_worktree))
    assert (stranger_worktree / ".git").is_file(), "precondition: a linked-worktree marker"

    result = strict(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["contradictions"] == []


def test_strict_audit_reports_a_legacy_stale_row_and_the_printed_cure_clears_it(
    tmp_path: Path,
) -> None:
    """The defect population, which `_managed` fixtures cannot reach.

    The live registry holds 37 managed rows of which ZERO point at a missing directory, and
    244 legacy paths of which 73 are missing. So every stale registration the census
    reported was legacy -- and `reconcile` refused legacy rows, so `audit --strict` printed
    a cure that returned LEGACY_PATH and strict stayed red forever. This builds its stale
    row the way the registry actually got them: a raw `git worktree add` before install,
    then the directory swept.
    """
    repo = make_repo(tmp_path)
    legacy_stale = tmp_path / "legacy-stale"
    git(repo, "worktree", "add", "-b", "legacy-stale", str(legacy_stale))
    lifecycle(repo, "install", "--target", "6")
    assert path_key_of(legacy_stale) in read_state(repo)["legacy_paths"]
    shutil.rmtree(legacy_stale)

    result = strict(repo)
    stale = [item for item in contradictions_of(result) if item["code"] == "stale_registration"]
    assert [item["path"] for item in stale] == [str(legacy_stale)]
    # Inherited debt, so it is reported on every run but does not fail the gate; that split
    # is what lets the hooks enforce the class today instead of blocking on the backlog.
    assert stale[0]["severity"] == "backlog"
    assert stale[0]["origin"] == "legacy"
    assert result.returncode == 0, "backlog alone must not fail the default gate"
    assert lifecycle(repo, "audit", "--strict", "--all", check=False).returncode == 2

    # The cure the report printed must actually work. This is the assertion the previous
    # revision could not make.
    cure = lifecycle(repo, "reconcile", "--path", str(legacy_stale))
    assert '"status": "RECONCILED"' in cure.stdout
    assert '"origin": "legacy"' in cure.stdout

    state = read_state(repo)
    assert path_key_of(legacy_stale) not in state["legacy_paths"]
    assert state["retired"][path_key_of(legacy_stale)]["origin"] == "legacy"
    assert lifecycle(repo, "audit", "--strict", "--all", check=False).returncode == 0


def test_strict_audit_reports_an_unregistered_stale_registration_and_clears_it(
    tmp_path: Path,
) -> None:
    """The third population: registered with Git, unknown to the registry, directory gone.
    `reconcile` used to raise NOT_MANAGED for these, which is the same unreachable cure.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    rogue = tmp_path / "rogue"
    git(repo, "worktree", "add", "-b", "rogue", str(rogue))
    shutil.rmtree(rogue)

    result = strict(repo)
    stale = [item for item in contradictions_of(result) if item["code"] == "stale_registration"]
    assert [item["path"] for item in stale] == [str(rogue)]
    assert stale[0]["origin"] == "unregistered"

    cure = lifecycle(repo, "reconcile", "--path", str(rogue))
    assert '"status": "RECONCILED"' in cure.stdout
    assert read_state(repo)["retired"][path_key_of(rogue)]["origin"] == "unregistered"


def test_interrupted_removal_with_the_tree_intact_points_at_retire(tmp_path: Path) -> None:
    """The Windows shape: `git worktree remove` fails with Permission denied, the intent is
    retained by design, and the worktree is untouched. `reconcile` refuses a non-empty path,
    so printing it as the cure left an intent that no verb could clear -- red until someone
    hand-edited the state JSON. The cure has to branch on whether the tree survived.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    survivor = _managed(repo, tmp_path, "survivor")

    state = read_state(repo)
    state["pending_removals"] = {
        path_key_of(survivor): {
            "path": str(survivor),
            "verb": "retire",
            "started_at": "2026-08-04T04:52:20+00:00",
        }
    }
    state_path(repo).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    result = strict(repo)
    assert result.returncode == 2
    found = [item for item in contradictions_of(result) if item["code"] == "interrupted_removal"][0]
    assert found["tree_present"] is True
    assert found["still_registered"] is True
    assert "retire --path" in found["cure"]
    assert "still present and still registered" in found["reason"]

    # And the cure completes it: retire succeeds and the intent is gone.
    lifecycle(repo, "retire", "--path", str(survivor))
    assert read_state(repo)["pending_removals"] == {}
    assert strict(repo).returncode == 0


def test_abandon_intent_clears_the_journal_and_nothing_else(tmp_path: Path) -> None:
    """The other exit for the same shape: the removal will not be retried and the worktree
    stays. Only the journal entry is cleared -- the directory, the registration and the
    registry row are all untouched -- so no branch of `interrupted_removal` is a dead end.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    kept = _managed(repo, tmp_path, "kept")

    state = read_state(repo)
    state["pending_removals"] = {
        path_key_of(kept): {"path": str(kept), "verb": "retire", "started_at": "2026-08-04T04:52:20+00:00"}
    }
    state_path(repo).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    result = lifecycle(repo, "reconcile", "--path", str(kept), "--abandon-intent")
    assert '"status": "INTENT_ABANDONED"' in result.stdout

    state = read_state(repo)
    assert state["pending_removals"] == {}
    assert path_key_of(kept) in state["managed"], "the row must be untouched"
    assert kept.exists() and (kept / ".git").exists(), "the worktree must be untouched"
    assert str(kept).replace("\\", "/") in git(repo, "worktree", "list", "--porcelain").stdout.replace("\\", "/")
    assert strict(repo).returncode == 0


def test_abandon_intent_refuses_when_there_is_no_intent(tmp_path: Path) -> None:
    """It clears a journal entry and only that, so with nothing to clear it is an error --
    never a quiet no-op that could be mistaken for a completed removal.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    live = _managed(repo, tmp_path, "no-intent")

    result = lifecycle(repo, "reconcile", "--path", str(live), "--abandon-intent", check=False)
    assert result.returncode == 2
    assert "NO_PENDING_REMOVAL" in result.stderr


def _deregister_leaving_the_directory(repo: Path, path: Path) -> None:
    """Reproduce the partial removal: Git's record goes, the directory stays.

    This is what a failed `git worktree remove` actually leaves on this host -- the delete
    hit Permission denied AFTER the registration was dropped -- and it is the end state the
    reviewer's probe reached once its own file handle was released.
    """
    module = load_lifecycle_module()
    assert module.prune_one_worktree_metadata(repo, str(path)), "precondition: a record to remove"
    assert path.is_dir() and any(path.iterdir()), "precondition: the directory survives"


def test_partial_removal_that_left_the_directory_names_the_manual_step(tmp_path: Path) -> None:
    """The third end state, and the one that had no exit at all.

    Directory present, registration gone, row still managed. `retire` refuses
    (MISSING_MANAGED_WORKTREE -- there is no registration to work from) and `reconcile`
    refuses (PATH_NOT_EMPTY -- it will not discard bytes). Deleting them automatically is
    precisely what this tool must never do unasked, so the exit is a named human step
    rather than a verb, and the report has to say which half failed.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    partial = _managed(repo, tmp_path, "half-removed")

    state = read_state(repo)
    state["pending_removals"] = {
        path_key_of(partial): {
            "path": str(partial),
            "verb": "retire",
            "started_at": "2026-08-04T05:09:34+00:00",
        }
    }
    state_path(repo).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    _deregister_leaving_the_directory(repo, partial)

    # Both verbs refuse, which is why an unconditional cure was a dead end.
    assert "MISSING_MANAGED_WORKTREE" in lifecycle(repo, "retire", "--path", str(partial), check=False).stderr
    assert "PATH_NOT_EMPTY" in lifecycle(repo, "reconcile", "--path", str(partial), check=False).stderr

    found = [
        item for item in contradictions_of(strict(repo)) if item["code"] == "interrupted_removal"
    ][0]
    assert found["tree_present"] is True
    assert found["still_registered"] is False
    assert "could not be deleted" in found["reason"]
    assert "remove" in found["cure"] and "then" in found["cure"]
    assert "retire --path" not in found["cure"], "retire cannot run without a registration"

    # Follow the printed step: the operator removes the bytes, then reconcile clears the row.
    shutil.rmtree(partial)
    assert '"status": "RECONCILED"' in lifecycle(repo, "reconcile", "--path", str(partial)).stdout
    assert strict(repo).returncode == 0


def test_strict_reports_a_managed_row_that_git_does_not_register(tmp_path: Path) -> None:
    """The same fact without an intent to explain it: `audit` raises
    MISSING_MANAGED_WORKTREE and stops, so the inventory must carry the row itself.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "6")
    orphaned_row = _managed(repo, tmp_path, "row-only")
    _deregister_leaving_the_directory(repo, orphaned_row)

    result = strict(repo)
    assert result.returncode == 2
    found = [item for item in contradictions_of(result) if item["code"] == "missing_registration"]
    assert [item["path"] for item in found] == [str(orphaned_row)]
    assert found[0]["severity"] == "error"


def test_strict_probe_is_the_census_probe(tmp_path: Path) -> None:
    """Drift guard on the equivalence acceptance clause 4 depends on.

    The census raises `registered_worktree_scan_failed` out of `_git_material_paths`, which
    runs three specific `ls-files`/`diff` commands. `strict_report` probed with
    `rev-parse --git-dir`, which succeeds on registrations whose `ls-files` fails -- so a
    green `--strict` did not imply a green census, and the two detectors could drift apart
    silently. This reads the census's own command tuple and requires it to match.
    """
    import ast

    module = load_lifecycle_module()
    census = ast.parse((REPO_ROOT / "scripts" / "ember_01_custody" / "census.py").read_text(encoding="utf-8"))
    commands = None
    for node in ast.walk(census):
        if isinstance(node, ast.FunctionDef) and node.name == "_git_material_paths":
            for statement in ast.walk(node):
                if isinstance(statement, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "commands"
                    for target in statement.targets
                ):
                    commands = ast.literal_eval(statement.value)
    assert commands is not None, "census._git_material_paths no longer defines `commands`"
    assert tuple(commands) == module.CENSUS_MATERIAL_PROBES


# ---------------------------------------------------------------------------
# --detach (#1371) meets the strict registry inventory (#1366)
# ---------------------------------------------------------------------------


def _detached(repo: Path, tmp_path: Path, name: str, owner: str = "ember-cli-verify") -> Path:
    path = tmp_path / name
    lifecycle(
        repo, "create",
        "--path", str(path),
        "--detach",
        "--owner", owner,
        "--purpose", f"detached-{name}",
        "--expires", "2999-01-01",
    )
    return path


def test_strict_audit_is_green_on_a_healthy_detached_worktree(tmp_path: Path) -> None:
    """A detached worktree is a legitimate registration, not a contradiction.

    The strict inventory probes every managed row with the census's own git commands
    and reports each finding with the row's `branch`. A detached row has no branch,
    which is the one shape that did not exist when the inventory was written -- so the
    union of the two features is only sound if a healthy detached row reads as PASS
    rather than as a stale or unscannable registration.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    _detached(repo, tmp_path, "detached-live")

    result = strict(repo)

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "PASS"
    assert contradictions_of(result) == []


def test_strict_audit_reports_a_stale_detached_row_with_a_null_branch(tmp_path: Path) -> None:
    """And when a detached row DOES go stale, it is reported like any other.

    The finding carries `branch: null` -- the honest answer for a detached checkout --
    and the printed cure still clears it.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    gone = _detached(repo, tmp_path, "detached-doomed")
    shutil.rmtree(gone)

    result = strict(repo)
    findings = [item for item in contradictions_of(result) if item["path"].endswith("detached-doomed")]

    assert result.returncode != 0
    assert len(findings) == 1
    assert findings[0]["code"] == "stale_registration"
    assert findings[0]["severity"] == "error"
    assert findings[0]["branch"] is None

    lifecycle(repo, "reconcile", "--path", str(gone))
    assert strict(repo).returncode == 0


def test_retiring_a_detached_row_tombstones_it_as_detached(tmp_path: Path) -> None:
    """`branch: null` alone cannot distinguish "detached" from "unknown", so the
    tombstone records the flag. Without it the custody log loses the very property
    the certification consumers require."""
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = _detached(repo, tmp_path, "detached-retired")

    payload = json.loads(
        lifecycle(repo, "retire", "--path", str(target), "--reason", "certification finished").stdout
    )
    tombstone = read_state(repo)["retired"][path_key_of(target)]

    assert payload["status"] == "RETIRED"
    assert payload["archive_ref"], "a detached head must be archived before its row goes"
    assert tombstone["verb"] == "retire"
    assert tombstone["detached"] is True
    assert tombstone["branch"] is None
    assert tombstone["reason"] == "certification finished"


def test_a_forced_retirement_says_so_on_its_own_tombstone(tmp_path: Path) -> None:
    """Forcing discards uncommitted bytes. That is the one retirement whose stated
    reason is incomplete on its own, so the record discloses the force itself."""
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    target = _detached(repo, tmp_path, "detached-dirty")
    (target / "scratch.bin").write_text("interrupted leg residue", encoding="utf-8")

    payload = json.loads(
        lifecycle(
            repo, "retire",
            "--path", str(target),
            "--reason", "lane killed mid-run",
            "--force-owner", "ember-cli-verify",
        ).stdout
    )
    tombstone = read_state(repo)["retired"][path_key_of(target)]

    assert payload["forced"] is True
    assert tombstone["reason"].startswith("lane killed mid-run")
    assert "forced" in tombstone["reason"]
    assert "ember-cli-verify" in tombstone["reason"]
    assert strict(repo).returncode == 0, "a forced retirement must leave no removal intent"


# ---------------------------------------------------------------------------
# renew: the sanctioned lease extension (the exit that is not a hand-locked
# JSON edit)
# ---------------------------------------------------------------------------


def test_renew_extends_lease_and_records_the_renewal(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    managed = _managed(repo, tmp_path, "renewable")
    key = path_key_of(managed)

    result = lifecycle(repo, "renew", "--path", str(managed), "--days", "7")
    payload = json.loads(result.stdout)
    expected = (date.today() + timedelta(days=7)).isoformat()
    assert payload["status"] == "RENEWED"
    assert payload["expires"] == expected
    assert payload["previous_expires"] == "2099-01-01"

    record = read_state(repo)["managed"][key]
    assert record["expires"] == expected
    # The renewal is recorded on the row, so audit tooling can show it.
    assert len(record["renewals"]) == 1
    assert record["renewals"][0]["previous_expires"] == "2099-01-01"
    assert record["renewals"][0]["expires"] == expected
    assert "renewed_at" in record["renewals"][0]

    # --until works too, and the history accretes.
    until = (date.today() + timedelta(days=3)).isoformat()
    lifecycle(repo, "renew", "--path", str(managed), "--until", until)
    record = read_state(repo)["managed"][key]
    assert record["expires"] == until
    assert len(record["renewals"]) == 2
    assert record["renewals"][1]["previous_expires"] == expected


def test_renew_is_bounded_by_the_cap(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    managed = _managed(repo, tmp_path, "capped")

    for horizon in (("--days", "15"), ("--until", "2099-01-01")):
        result = lifecycle(repo, "renew", "--path", str(managed), *horizon, check=False)
        assert result.returncode == 2
        assert "RENEWAL_CAP" in result.stderr

    # A refused renewal writes nothing.
    record = read_state(repo)["managed"][path_key_of(managed)]
    assert record["expires"] == "2099-01-01"
    assert "renewals" not in record


def test_renew_refuses_an_unmanaged_path(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    legacy = tmp_path / "legacy"
    git(repo, "worktree", "add", "-b", "legacy", str(legacy))
    lifecycle(repo, "install", "--target", "3")

    never = lifecycle(
        repo, "renew", "--path", str(tmp_path / "never-registered"), "--days", "7", check=False
    )
    assert never.returncode == 2
    assert "NOT_MANAGED" in never.stderr

    # legacy_paths carry no lease; they are not this verb's to edit.
    snapshot = lifecycle(repo, "renew", "--path", str(legacy), "--days", "7", check=False)
    assert snapshot.returncode == 2
    assert "LEGACY_PATH" in snapshot.stderr


def test_renew_respects_the_repository_lock(tmp_path: Path) -> None:
    module = load_lifecycle_module()
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    managed = _managed(repo, tmp_path, "locked")

    lock = state_path(repo).with_name("ember-worktree-lifecycle.lock")
    with module.RepositoryLock(lock):
        result = lifecycle(repo, "renew", "--path", str(managed), "--days", "7", check=False)
    assert result.returncode == 2
    assert "LIFECYCLE_LOCKED" in result.stderr
    assert read_state(repo)["managed"][path_key_of(managed)]["expires"] == "2099-01-01"


def test_expired_then_renewed_worktree_passes_the_strict_audit(tmp_path: Path) -> None:
    """The 2026-08-04 incident shape: an expired lease hard-fails the strict audit
    (and therefore the push guard), and the only cure was an ad-hoc registry edit.
    renew is that cure in sanctioned form: audit fails EXPIRED_WORKTREE, renew
    extends the lease under the lock, audit passes.
    """
    repo = make_repo(tmp_path)
    lifecycle(repo, "install", "--target", "3")
    expired = _managed(repo, tmp_path, "expired-lease")
    expire_managed_worktrees(repo, expired)

    blocked = strict(repo)
    assert blocked.returncode == 2
    assert "EXPIRED_WORKTREE" in blocked.stderr

    renewed = lifecycle(repo, "renew", "--path", str(expired), "--days", "3")
    assert '"status": "RENEWED"' in renewed.stdout

    assert strict(repo).returncode == 0, strict(repo).stderr

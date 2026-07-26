# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*args], cwd=cwd, text=True, capture_output=True, encoding="utf-8"
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

    invocation = 'python "$ROOT/scripts/worktree_lifecycle.py" audit --quiet'
    assert invocation in pre_commit
    assert invocation in pre_push
    assert "scripts/worktree_lifecycle.py create" in agents
    assert "scripts/worktree_lifecycle.py retire" in agents
    assert "Raw `git worktree add` and recursive worktree deletion are forbidden" in agents


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

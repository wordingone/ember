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

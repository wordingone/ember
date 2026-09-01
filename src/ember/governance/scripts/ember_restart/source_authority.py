#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Source-identity binding for the R1 WARM-100 entry receipt (issue #1296 P1).

Two bindings, both fail-closed:

* ``source_root`` -> the canonical Ember checkout or one of its
  ``worktree_lifecycle.py``-managed worktrees (never a clone, fork, or ad-hoc
  ``git worktree add``).
* ``source_commit`` -> published governed-remote history, proven by contacting
  the pinned remote URL (``git ls-remote``) and walking real ancestry
  (``git merge-base --is-ancestor``) -- never an ``origin`` URL string
  comparison, which is spoofable in one config write.

  Env-hardening against config-based remote-contact spoofing (issue #1706):
  ``resolve_governed_master``'s ls-remote runs with no repository context at
  all (no ``-C``, an explicit unusable ``GIT_DIR``) and a stripped,
  system/global-silenced environment, so no git config from any source --
  local, global, system, or environment-injected -- can redirect it; this is
  the only call in the pinned-URL binding whose result is otherwise
  unconstrained (an attacker who controls what "master" resolves to can
  fabricate a whole history to be "ancestor" of). ``require_published_ancestry``'s
  fetch runs with the same stripped, system/global-silenced environment, but
  still binds to ``source_root`` (it fetches INTO that object store), so a
  repository-local rewrite is not excluded the same way for that call --
  it is safe regardless, because a fetch is content-addressed: redirecting
  its transport can only succeed if the redirected remote actually holds an
  object matching the exact sha already fixed by the (hardened) ls-remote
  above, which an attacker cannot forge.

No component here trusts a copied constant: the canonical root, the
worktree-lifecycle registry, and the governed remote's tip are all read fresh,
from live authorities, on every call.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DEFAULT_GOVERNED_REF = "refs/heads/master"

_WORKTREE_LIFECYCLE_MODULE_NAME = "_ember_source_authority_worktree_lifecycle"
_GIT_ENV_HARDENING_MODULE_NAME = "_ember_source_authority_git_env_hardening"


def _load_git_env_hardening():
    """Load scripts/git_env_hardening.py by file path (issue #1706).

    Same discipline as ``_load_worktree_lifecycle`` below and for the same
    reason: this module is executed both as ``scripts.ember_restart.source_authority``
    (package import) and directly (``python src/ember/governance/scripts/ember_restart/contract.py``,
    which falls back to a bare ``import source_authority`` -- see contract.py's
    own try/except). Under direct execution, ``sys.path[0]`` is
    ``scripts/ember_restart/``, not ``scripts/``, so a plain
    ``from scripts.git_env_hardening import ...`` would raise ModuleNotFoundError
    in that shape -- this failed exactly that way against the CLI-subprocess
    tests before being caught. File-path loading, relative to this module's
    own installation, works under every execution shape.
    """
    module_path = Path(__file__).resolve().parents[5] / "scripts" / "git_env_hardening.py"
    spec = importlib.util.spec_from_file_location(_GIT_ENV_HARDENING_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ValueError("source authority: git env hardening module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError as error:
        raise ValueError("source authority: git env hardening module is unreadable") from error
    return module


def hardened_git_env() -> dict[str, str]:
    return _load_git_env_hardening().hardened_git_env()

# An explicit, deliberately-unusable GIT_DIR for the one call
# (resolve_governed_master's ls-remote) that must consult NO repository's
# config, local included. `ls-remote <literal-url>` needs no repository
# context to succeed -- verified empirically for issue #1706 -- so pointing
# GIT_DIR at a path that is not a valid repository is safe: the call either
# resolves the literal URL with no git-directory work at all, or fails
# closed if git ever changes that behavior. Never created on disk.
_NO_REPO_CONTEXT_GIT_DIR = os.path.join(
    os.path.dirname(__file__), ".ember-1706-no-repo-context-sentinel-do-not-create"
)


def _run_git(root: Path, *git_args: str) -> subprocess.CompletedProcess:
    """Run a Git authority probe without creating a visible Windows console.

    Mirrors contract._run_git's discipline (shell=False, CREATE_NO_WINDOW).
    Kept local rather than imported: contract.py calls into this module, and
    an import back the other way would create a cycle. Env-hardened (issue
    #1706): closes the GIT_CONFIG_GLOBAL and GIT_CONFIG_COUNT/KEY_*/VALUE_*
    vectors for every call through this function. Still binds to `root` via
    `-C`, so a repository-local config rewrite is not excluded here -- see
    `_run_git_pinned_remote` for the one call that needs that too.
    """
    return subprocess.run(
        ["git", "-C", str(root), *git_args],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        env=hardened_git_env(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _run_git_pinned_remote(*git_args: str) -> subprocess.CompletedProcess:
    """Contact a pinned, literal remote URL with NO repository context at all.

    Issue #1706 (F2): unlike every other call in this module, this one never
    needs `-C source_root` -- `git ls-remote <url> <ref>` resolves a literal
    URL, not a locally-configured remote name, so no repository's config
    (local, global, or system) is relevant to it. Dropping repository
    context is what actually closes the local-`.git/config`
    `url.*.insteadOf` vector here: a command-line `-c` addition cannot
    retract a same-key entry a local config already defined (`insteadOf` is
    multi-valued and merges by longest-prefix-match across every source, so
    an empty `-c` override sits alongside the real rule rather than
    replacing it -- verified empirically), but omitting repository context
    means no such rule, from any repository, is ever read in the first
    place. Combined with `hardened_git_env` (system/global/env-injected
    vectors), all three vectors named in issue #1706 are closed for this
    one call.
    """
    return subprocess.run(
        ["git", *git_args],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        env={**hardened_git_env(), "GIT_DIR": _NO_REPO_CONTEXT_GIT_DIR},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _common_dir(root: Path) -> Path | None:
    result = _run_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if result.returncode != 0:
        return None
    try:
        return Path(result.stdout.strip()).resolve(strict=True)
    except OSError:
        return None


def _toplevel(root: Path) -> str | None:
    result = _run_git(root, "rev-parse", "--path-format=absolute", "--show-toplevel")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _load_worktree_lifecycle():
    """Load the real, currently-running worktree_lifecycle.py by file path.

    Loaded from this module's own installation (a peer of ``ember_restart/``
    inside ``scripts/``), never from a candidate ``source_root`` or
    ``canonical_root`` -- the lifecycle tool is a fixed, versioned authority,
    consumed read-only (issue #1296 spec section D non-goals), not something
    a candidate repository supplies its own copy of.
    """
    module_path = Path(__file__).resolve().parents[1] / "worktree_lifecycle.py"
    spec = importlib.util.spec_from_file_location(_WORKTREE_LIFECYCLE_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ValueError("source authority: worktree lifecycle module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # dataclasses' forward-ref resolution (Worktree's KW_ONLY-adjacent
    # annotations) looks the module up via sys.modules[cls.__module__] while
    # the class body executes, so the module must already be registered
    # before exec_module runs, not after.
    sys.modules[_WORKTREE_LIFECYCLE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except OSError as error:
        del sys.modules[_WORKTREE_LIFECYCLE_MODULE_NAME]
        raise ValueError("source authority: worktree lifecycle module is unreadable") from error
    return module


def resolve_canonical_root() -> Path:
    """The repository that owns the executing validator bytes (self-anchor).

    ``src/ember/governance/scripts/ember_restart/source_authority.py`` -> parents[1] is
    ``scripts/`` -> parents[2] is repo root (same derivation gate_provenance.py
    uses for tool identity, one level shallower because that tool lives
    directly in ``scripts/``).
    """
    return Path(__file__).resolve().parents[2]


def require_canonical_source_root(source_root: Path, *, canonical_root: Path) -> dict[str, Any]:
    """Bind source_root to the canonical checkout or one of its managed worktrees.

    Returns ``{"worktree_identity": "MAIN" | "MANAGED" | "LEGACY"}``.
    Raises ``ValueError`` (fail-closed) for a foreign repository, an
    unmanaged/ad-hoc worktree, or a missing/malformed registry.
    """
    canonical_common = _common_dir(canonical_root)
    if canonical_common is None:
        raise ValueError("source authority: canonical checkout git identity is unavailable")
    source_common = _common_dir(source_root)
    if source_common is None:
        raise ValueError("source authority: source_root git identity is unavailable")
    if str(source_common).casefold() != str(canonical_common).casefold():
        raise ValueError(
            "source authority: source_root does not share the canonical object store "
            "(foreign repository, clone, or fork)"
        )

    source_toplevel = _toplevel(source_root)
    canonical_toplevel = _toplevel(canonical_root)
    if source_toplevel is None or canonical_toplevel is None:
        raise ValueError("source authority: source_root toplevel is unavailable")

    lifecycle = _load_worktree_lifecycle()

    # MAIN determination: source_root owns its own common dir directly. A
    # genuine main checkout's (or a fresh, non-worktree clone's) `.git` is a
    # real directory that IS the common dir; `git worktree add` -- ad-hoc or
    # lifecycle-managed alike -- produces a `.git` FILE that points
    # elsewhere. This must work with no worktree-lifecycle registry
    # installed at all (e.g. a fresh CI clone that has never run
    # `worktree_lifecycle.py install`) -- a genuine main checkout is
    # canonical by construction, not by registry membership.
    #
    # The prior check instead compared source_toplevel to canonical_toplevel
    # (source_root literally IS canonical_root). That is trivially true when
    # an ad-hoc `git worktree add` invokes ITS OWN copy of this validator --
    # canonical_root self-anchors to wherever the executing bytes live,
    # which is the ad-hoc worktree itself -- and short-circuited straight to
    # MAIN without ever consulting the registry: exactly the "ad-hoc
    # worktree refused" guarantee this module claims to enforce (found in
    # review, issue #1296).
    own_git_entry = Path(source_toplevel) / ".git"
    if own_git_entry.is_dir():
        try:
            if own_git_entry.resolve(strict=True) == source_common:
                return {"worktree_identity": "MAIN"}
        except OSError:
            pass

    state_path = canonical_common / lifecycle.STATE_NAME
    try:
        state = lifecycle.load_state(state_path)
    except Exception as exc:  # LifecycleError or any load-time failure
        raise ValueError(f"source authority: worktree registry is unavailable: {exc}") from exc
    if state is None:
        raise ValueError("source authority: worktree registry is unavailable")

    source_key = lifecycle.path_key(source_toplevel)
    if source_key == lifecycle.path_key(state.get("main_path", "")):
        return {"worktree_identity": "MAIN"}
    managed = state.get("managed", {})
    if isinstance(managed, dict) and source_key in managed:
        return {"worktree_identity": "MANAGED"}
    legacy = state.get("legacy_paths", [])
    if isinstance(legacy, list) and source_key in legacy:
        return {"worktree_identity": "LEGACY"}
    raise ValueError(
        "source authority: source_root shares the canonical object store but is not "
        "registered in the managed-worktree lifecycle (ad-hoc worktree refused)"
    )


def resolve_governed_master(
    source_root: Path,
    governed_remote: str,
    *,
    ref: str = DEFAULT_GOVERNED_REF,
) -> str:
    """Resolve the governed remote's ref by contact (tree_provenance pattern).

    Never reads the candidate's configured ``origin`` -- the remote to
    contact is always the caller-supplied, governed value.

    ``source_root`` is accepted for call-site stability and because this
    function conceptually answers "what does the governed remote say,
    on behalf of this candidate" -- but it is deliberately UNUSED in the git
    invocation itself (issue #1706): contacting ``governed_remote`` runs
    with no repository context at all, so ``source_root``'s configuration,
    local or otherwise, is never consulted. See ``_run_git_pinned_remote``.
    """
    del source_root
    result = _run_git_pinned_remote("ls-remote", "--exit-code", governed_remote, ref)
    if result.returncode != 0:
        raise ValueError("source authority: governed remote did not resolve")
    rows = [line for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("source authority: governed remote ref did not resolve exactly once")
    sha, separator, row_ref = rows[0].partition("\t")
    if separator != "\t" or row_ref != ref:
        raise ValueError("source authority: governed remote response was malformed")
    sha = sha.strip().lower()
    if not COMMIT_RE.fullmatch(sha):
        raise ValueError("source authority: governed remote sha is malformed")
    return sha


CENSUS_WINDOW_ENV = "EMBER_CENSUS_WINDOW"
CENSUS_WINDOW_MARKER_NAME = "census-window.lock"


def _census_window_active(source_root: Path) -> bool:
    """True if a census window is declared for source_root's object store.

    Checked immediately before the one write this module performs (the
    ``git fetch`` below), never earlier: a call that never needs to fetch
    (commit already local) is genuinely read-only and must not be refused.
    A missing/unresolvable common dir reads as no marker, not as an error --
    this is an additional safety gate on top of the write, not a new
    identity check (that remains ``require_canonical_source_root``'s job).
    """
    if os.environ.get(CENSUS_WINDOW_ENV):
        return True
    common = _common_dir(source_root)
    if common is None:
        return False
    return (common / CENSUS_WINDOW_MARKER_NAME).exists()


def require_published_ancestry(
    source_root: Path,
    source_commit: str,
    remote_master_sha: str,
    *,
    governed_remote: str,
) -> str:
    """Prove source_commit is published history (ancestor-or-equal of governed master).

    Returns ``"EQUAL"`` or ``"ANCESTOR"``. Fails closed (ValueError) on a
    missing commit object, an unreachable remote, or unproven ancestry --
    "no evidence" never reads as "related" (certified_train_launch.py
    read_commit_is_ancestor's shape).

    MUTATING (issue #1708): when ``remote_master_sha``'s commit object is not
    already present in ``source_root``, this runs ``git fetch --no-tags
    --quiet <governed_remote> <remote_master_sha>``, writing into
    ``source_root``'s object store. Both ``build_r1_warm100_entry`` and
    ``validate_r1_warm100_entry`` reach this call (via
    ``bind_source_identity``), so a "just validate this receipt" call is not
    actually read-only. Before that write, this function refuses fail-closed
    if a census window is declared -- either the ``EMBER_CENSUS_WINDOW``
    environment variable is set, or a ``census-window.lock`` marker file
    exists at ``source_root``'s git common directory -- so it never writes
    into a registered worktree while one is active.
    """
    if not COMMIT_RE.fullmatch(source_commit) or not COMMIT_RE.fullmatch(remote_master_sha):
        raise ValueError("source authority: commit shas must be lowercase 40-hex")
    if source_commit == remote_master_sha:
        return "EQUAL"
    exists = _run_git(source_root, "cat-file", "-e", f"{remote_master_sha}^{{commit}}")
    if exists.returncode != 0:
        if _census_window_active(source_root):
            raise ValueError(
                "source authority: census window declared; validate performs "
                "a git fetch into source_root and is held"
            )
        fetched = _run_git(source_root, "fetch", "--no-tags", "--quiet", governed_remote, remote_master_sha)
        if fetched.returncode != 0:
            raise ValueError("source authority: governed master commit object is unavailable")
    ancestor = _run_git(source_root, "merge-base", "--is-ancestor", source_commit, remote_master_sha)
    if ancestor.returncode == 0:
        return "ANCESTOR"
    if ancestor.returncode == 1:
        raise ValueError("source authority: source_commit is not published in governed history")
    raise ValueError("source authority: source_commit ancestry to governed master is unprovable")


def bind_source_identity(
    source_root: Path,
    source_commit: str,
    *,
    canonical_root: Path | None,
    governed_remote: str,
    governed_ref: str,
) -> dict[str, Any]:
    """Run both bindings, root first, then commit -- a foreign repo must fail
    on identity before any network or ancestry work happens."""
    root = canonical_root if canonical_root is not None else resolve_canonical_root()
    identity = require_canonical_source_root(source_root, canonical_root=root)
    remote_master_sha = resolve_governed_master(source_root, governed_remote, ref=governed_ref)
    ancestry = require_published_ancestry(
        source_root, source_commit, remote_master_sha, governed_remote=governed_remote
    )
    return {
        "canonical_common_dir_bound": True,
        "worktree_identity": identity["worktree_identity"],
        "governed_remote": governed_remote,
        "remote_master_sha": remote_master_sha,
        "ancestry": ancestry,
    }

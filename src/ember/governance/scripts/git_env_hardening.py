#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared subprocess-environment hardening for git invocations (issue #1706).

F2 (adversarial review of #1702/#1296): a candidate repo's `git` config can
redirect a governed-remote contact to an attacker-controlled server via
`url.<attacker-remote>.insteadOf <governed-url>`, from three independent
sources -- a repository-local `.git/config`, an inherited `GIT_CONFIG_GLOBAL`
pointing somewhere attacker-writable, or an inherited
`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*` set of
environment-injected config entries. `hardened_git_env` closes the second and
third: it strips the environment-injected config mechanism entirely (not
just the `insteadOf` case -- those variables can define ANY config key, so
removing the mechanism is more complete than filtering for one abused key),
and it overrides `GIT_CONFIG_GLOBAL` to the null device so an inherited value
can never be read. Verified empirically for issue #1706 (real `git`, a real
second bare repo standing in as the attacker remote, a real inherited
`GIT_CONFIG_GLOBAL`/`GIT_CONFIG_COUNT` pair): both vectors redirect
`git ls-remote` to the attacker's history when unguarded, and both stop doing
so under this environment.

It does NOT close the first vector (a repository-LOCAL `.git/config`
rewrite): empirically, no per-invocation git switch suppresses a specific
repository's own local config while that repository is still the `-C`/
`--git-dir` target of the same invocation -- `GIT_CONFIG_NOSYSTEM` and
`GIT_CONFIG_GLOBAL` only ever govern the system and global scopes, never
local, and a command-line `-c url.<X>.insteadOf=` addition does not retract
a same-key entry already defined at the local-config level (`insteadOf` is
multi-valued and merges by longest-prefix-match across every source, so an
empty `-c` addition sits alongside the real one rather than replacing it --
verified empirically, see `src/ember/governance/scripts/ember_restart/source_authority.py`'s
`resolve_governed_master` for the one call site where this is closed
instead, by omitting local repository context from that call entirely,
since it is the sole call in this codebase that never needed it).

That residual is an accepted boundary, not a gap left open by omission: it
only reaches calls that still bind to a repository (`-C`/`--git-dir`), and
every governed-remote call in this codebase is one of two shapes. The
network-trust-critical shape -- resolving *which* commit is the governed
tip -- is exactly the shape the local-config rewrite cannot touch, because
`resolve_governed_master` already runs with no repository context at all.
The other shape -- `require_published_ancestry`'s fetch in
`source_authority.py`, and the `origin`-remote contact in
`src/ember/governance/scripts/ember_totality/tree_provenance.py` -- does need repository context
(a fetch must land in a real object store; a named remote must be resolved
from a real config), so it is not context-free, but it is sha-anchored: the
commit it is fetching was already fixed by the prior, context-free
`resolve_governed_master` contact, and Git's content addressing means a
commit's ancestry is a function of its hash, not of which remote happened to
deliver the bytes. A local-config rewrite on the contextual call can at
worst redirect it to a server that has no object matching that hash (the
fetch then fails closed) or to a server that, by construction, can only
satisfy the request by returning the true object for that hash (an attacker
cannot forge a second, different history for a hash they do not control).
Either way the contextual call cannot fabricate ancestry -- it can only deny
service on ancestry that was already correctly pinned upstream of it.
"""
from __future__ import annotations

import os

_STRIP_EXACT = ("GIT_CONFIG_COUNT",)
_STRIP_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def hardened_git_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """A subprocess environment with the env-injected git config vectors closed.

    ``base_env`` defaults to a copy of the current process environment. Every
    ``GIT_CONFIG_COUNT``/``GIT_CONFIG_KEY_*``/``GIT_CONFIG_VALUE_*`` entry is
    removed, ``GIT_CONFIG_NOSYSTEM`` is set, and ``GIT_CONFIG_GLOBAL`` is
    pointed at the null device. Safe to apply unconditionally to any git
    subprocess call in this repository: none of this codebase's git
    invocations rely on system or global git configuration, or on
    environment-injected config, to behave correctly.
    """
    env = dict(os.environ if base_env is None else base_env)
    for key in list(env):
        if key in _STRIP_EXACT or key.startswith(_STRIP_PREFIXES):
            del env[key]
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env

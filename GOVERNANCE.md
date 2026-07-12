<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Governance

## Authority

INVARIANT.md is the sole unamendable identity surface. GOAL.md is the highest
amendable authority. The named subordinate contracts listed in GOAL.md may
operationalize it but cannot reduce it. Receipts, ledgers, research notes,
configs, historical documents, issues, branches, and agent state are never goal
authority.

master is the canonical public branch. A worktree, mirror, backup, or deleted
branch cannot self-declare authority. Current state must name its commit and
custody boundary.

## Change conservation

A governing change must pass scripts/verify_authority_conservation.py and its
mutation suite. INVARIANT.md bytes and hash remain unchanged. Goal edits and
evidence receipts do not share a commit.

Superseded material remains in Git history or an explicit historical class.
Research mechanisms, negative results, benchmark obligations, and provenance
are preserved. Repository hygiene cannot delete them merely because a current
configuration does not use them.

## Pull requests and artifacts

Every pull request states:

- Goal-ID
- Next-executed-outcome
- authority or artifact class
- verification commands
- evidence and custody boundary

Every experiment, config, receipt, and control artifact carries the same goal
and outcome binding. Merge and dispatch gates fail closed on absence or
disagreement.

Branches use type/slug where type is feat, fix, exp, chore, or docs. Commits are
small, reviewable, and evidence-backed. Issues can describe work but cannot
close an invariant or kill a research family.

## Provenance and privacy

Tracked public files contain no personal/operator names, credentials, machine-
specific absolute paths, or private-repository locations. Public evidence uses
repository-relative paths and redacted custody identifiers. Paper authorship is
handled by the release process without weakening repository privacy.

Borrowed models are frozen references only. External learned or evaluative
signals never enter an owned lineage.

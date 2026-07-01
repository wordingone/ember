# Baseline Shipping Discipline Contract

Status: ACTIVE_COMPLETION_GATE for overall `/baseline` delivery. This contract
cannot complete the baseline by itself.

## Rule

The baseline is not delivered by prose, local files, a staging packet, a branch
push, or an unmerged PR. Branch existence, local commits, in-session promises,
private-only proof, or unmerged PRs cannot satisfy completion.

Overall baseline delivery requires all of the following to be true in the same
verifier run:

1. The strict baseline verifier reports PASS for every mandatory baseline
   family.
2. The publication-surface verifier reports public/private `/baseline` parity.
3. The public repo exposes the reviewed `/baseline` subtree on default
   `master`, or a human-authored tracked receipt names a different final public
   branch.
4. The private backup repo exposes the same reviewed `/baseline` subtree on
   default `master`, or the same human-authored tracked receipt names a
   different final private branch.
5. Remote proof receipts record commit hashes, branch names, PR or merge
   identifiers, and `/baseline` content probes for both repos.
6. Line-ending receipts prove tracked baseline text is LF-only.
7. Negative evidence and NOT_COMPLETION receipts remain visible.
8. Operator acceptance is present as an external human-authored object, not an
   agent-authored assertion.

## Staging Branches

Short-lived staging branches are allowed only as review and evidence transport.
They must be named for the scoped baseline increment and contain organized
commits. A staging branch is not a completion surface.

Invalid completion evidence includes:

- a branch exists remotely;
- a local worktree contains `/baseline`;
- an unmerged PR exists;
- a private repo has evidence that the public repo lacks;
- a public repo branch has evidence that `master` lacks, unless a
  human-authored tracked receipt names that branch as final;
- an in-session promise says the work will be merged later;
- a verifier says STAGING, FAIL, NOT COMPLETION, incomplete, or missing
  operator acceptance.

## Merge Discipline

Merges to `master` must include only reviewed baseline files and their receipts
unless the PR explicitly scopes a wider change. Unrelated dirty work is not
allowed in baseline promotion commits.

This contract is a gate: if it is violated, the correct verdict is NOT
COMPLETION even when other baseline families pass.
# Ember Agent Rules

This file is the default-branch rule surface for agentic collaborators working
in the public Ember repository.

## Public Baseline Shipping

- The `/baseline` directory on `master` is not proof of completion unless the
  strict baseline verifier, publication-surface verifier, line-ending verifier,
  public/private remote proof receipts, and current family receipts all report
  completion in the same reviewed state.
- A branch push, local worktree, in-session promise, private-only receipt, or
  unmerged pull request is progress only. It cannot satisfy baseline delivery.
- A staging branch may carry incomplete evidence for review, but it must remain
  visibly staged or draft until the verifiers agree.
- Do not merge incomplete baseline evidence into `master` as if it were final.
  Default-branch updates before completion may only add governance, guardrails,
  negative evidence, or clearly marked staging artifacts.
- Negative evidence and NOT_COMPLETION receipts must remain visible. Do not
  delete them to make the baseline appear complete.

## Public Hygiene

- Do not commit operator names, private prompt text, secrets, local absolute
  filesystem paths, or machine-specific paths.
- Tracked text must be LF-only.
- Public artifacts must be reproducible from repository-relative paths,
  citations, hashes, and receipts.
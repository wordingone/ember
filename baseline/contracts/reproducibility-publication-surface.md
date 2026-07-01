# Reproducibility Publication Surface Contract V1

Status: BASELINE_COMPLETE for `reproducibility_publication_surface` as a publication/parity baseline family only. This is not operator acceptance and not overall `/baseline` completion.
Claim family: `reproducibility_publication_surface`.
Access date: 2026-06-29.

## Contract

Build or run Ember artifact `X_publication_surface` that beats manual publication/reproducibility comparator `Y_manual_packet` on replayability, citation completeness, parity, receipt integrity, line-ending stability, remote proof, and reviewer auditability metric `Z_publication_auditability` by threshold `T`, while preserving public/private repo boundaries, source pins, manifests, negative-result visibility, and no-private-only public-claim constraints `C`, under budget `B`, verified by `baseline/scripts/validate_publication_surface.py`, `baseline/scripts/verify_completion.py`, source and line-ending receipts `V`, producing PASS, FAIL, or INVALID-RUN.

## Required Surfaces

- public `/baseline` tree in `wordingone/ember`;
- private `/baseline` tree in `wordingone/ember-backup`;
- identical mandatory-family scope in both trees;
- source ledger with access dates, versions, commits, or scoped exclusion notes where available;
- line-ending receipts proving LF-only tracked baseline text;
- remote refs or PR URLs;
- baseline tree hash or manifest hash;
- report that agrees with `completion-lock.json`;
- receipt proving remote content exists after push;
- no private-only evidence used as the sole basis for a public field-level claim.

## Locked Publication Lanes

### Lane PUB-LOCAL-PACKET

Comparator: local folder or staging packet.

Threshold: invalid unless the packet is tracked under top-level `/baseline`, has required files, has source and line-ending receipts, and is published through public/private remote refs or PR URLs.

### Lane PUB-DUAL-REMOTE-PARITY

Comparator: manual public/private copy.

Threshold: public and private remotes must expose `/baseline` on recorded refs. The validator must record remote content checks for both repos and a branch/ref proof receipt.

### Lane PUB-REPLAY-AUDIT

Comparator: prose report.

Threshold: reviewer must be able to run the named validators, inspect receipts, and see remaining global blockers without relying on chat context.

### Lane PUB-BOUNDARY

Comparator: hidden private proof or agent assertion.

Threshold: private-only data cannot satisfy a public field-level claim. Operator acceptance cannot be written by the agent.

## Required Evidence

A valid publication-surface receipt must report:

- local git branch and current HEAD;
- local baseline tree hash;
- public and private remote refs or PR URLs;
- public and private remote content probes for `/baseline` and at least one current family receipt;
- source ledger validation verdict and source count;
- line-ending verifier verdict;
- publication report path;
- completion-lock family status and verifier receipt;
- explicit statement that operator acceptance remains separate.

## Rejection Rules

Invalid publication evidence includes:

- local-only packets;
- unpushed refs;
- hidden private-only proof for public claims;
- human-readable reports that disagree with the lock;
- line-ending drift;
- missing source access dates;
- missing remote proof receipts;
- a publication validator that sets or assumes operator acceptance.

## Current Verdict

PUBLICATION_SURFACE_BASELINE_COMPLETE for the publication/parity baseline family only.

This means the `/baseline` surface has a validator, source receipt, line-ending receipt, remote-proof receipt, and public/private parity report. It does not mean Ember has beaten the baseline, does not mean the overall baseline is accepted, and does not complete the goal without explicit operator acceptance.
<!-- goal_id: EMBER-01 -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# EMBER-01 — public completion certificate record

EMBER-01 (custody, identity, and experiment spine) holds a verified completion
certificate, minted 2026-08-05. The certifying verifier run resolved all nine
certificate legs true (`VERIFIER_EXIT=0`, zero unresolved failures) against the
public repository pinned at commit
`323be9da58a7527f3526d4a9a839ae2b5765bfd1`, an ancestor of `master`.

This document is the public record of that certificate. The certificate's
canonical bytes and its evidence artifacts live in private operator custody;
this record binds them by SHA-256 so any custody holder can re-verify the
exact bytes, and it cites only public, repo-relative evidence for everything
else.

## The certificate (redacted transcription)

```json
{
  "artifact_sha256": {
    "custody-sidecar8.json": "8242f5db7d65ac092c684a8f1eaeeda7ef8af4d0d74979c518a3d74bae59d612",
    "receipt9.json": "7306d591c8a7a60f3629870747fe79832d20a528ef7576ede310fd21155390e2",
    "run9b.sh": "a3fb95a691726e39eba93b0f32331cfb9b1604a64fc8b0e97f74c503e77313f2"
  },
  "executed_commands": [
    "bash <custody>/census-assembly-20260802/run9b.sh",
    "python -B scripts/verify_ember01_completion.py --root <custody>/ember01-verify --selection <custody>/EMBER-GOAL-RESUME.md --receipt receipt9.json --run-custody --issue-census issue-census9.json <16 ROOT bindings> --run-seat --identity-manifest bundle_v2/model-identity.json --checkpoint-manifest bundle_v2/checkpoint/checkpoint-manifest.json --model-config bundle_v2/config.json"
  ],
  "node_id": "EMBER-01",
  "public_commit_sha1": "323be9da58a7527f3526d4a9a839ae2b5765bfd1",
  "schema_version": "ember-goal-certificate-v1",
  "unresolved_failures": [],
  "verifier_results": [
    {
      "evidence_sha256": "7306d591c8a7a60f3629870747fe79832d20a528ef7576ede310fd21155390e2",
      "name": "verify_ember01_completion (9/9 legs resolved-true, authority ok, VERIFIER_EXIT=0)",
      "status": "PASS"
    }
  ]
}
```

## Redaction disclosure

The transcription above differs from the private canonical certificate bytes in
exactly one way: inside the two `executed_commands` strings, machine-local
absolute path prefixes (an operator home-directory worktree root and the
operator project-drive goal-authority root) are replaced with the `<custody>`
placeholder, per this repository's standing redaction convention
(`REDACTIONS.md`; the same convention the in-tree receipts under
`receipts/ember-02-r1-exits/` use for the off-tree custody root). Every other
byte, including every hash, is transcribed verbatim.

The private canonical certificate JSON hashes to:

    sha256 954d8deef8d6590479a565e1a0c2b54f36e2618fd8e77b833f4f5dd74aa8efb9

## Custody bindings

| Artifact | Custody class | SHA-256 |
|---|---|---|
| Completion certificate (canonical JSON) | private operator custody | `954d8deef8d6590479a565e1a0c2b54f36e2618fd8e77b833f4f5dd74aa8efb9` |
| `receipt9.json` — the nine-leg completion receipt the certificate cites as evidence | private operator custody, `<custody>/census-assembly-20260802/` | `7306d591c8a7a60f3629870747fe79832d20a528ef7576ede310fd21155390e2` |
| `custody-sidecar8.json` — bounded custody-census sidecar (census receipt binding per `docs/custody/ember-01-custody-README.md`) | private operator custody, `<custody>/census-assembly-20260802/` | `8242f5db7d65ac092c684a8f1eaeeda7ef8af4d0d74979c518a3d74bae59d612` |
| `run9b.sh` — the exact script that executed the certifying verifier run | private operator custody, `<custody>/census-assembly-20260802/` | `a3fb95a691726e39eba93b0f32331cfb9b1604a64fc8b0e97f74c503e77313f2` |

A claim names which custody classes were inspected and never infers one from
another (`CONTINUITY.md`, custody boundaries). This record claims: the public
repository class at the bound commit, plus the three private artifacts above by
exact hash.

## The nine certificate legs

The milestone contract's completion certificate
(`docs/roadmap/milestones/EMBER-01.md`, clauses `EMBER-01.CERT.002` through
`EMBER-01.CERT.010`) defines nine legs. The verifier
(`scripts/verify_ember01_completion.py`) evaluates them in contract order;
every leg resolved true in the certifying run:

| # | Verifier leg | Contract clause |
|---|---|---|
| 1 | custody root census (operator-machine roots) | `EMBER-01.CERT.002` |
| 2 | artifact custody census | `EMBER-01.CERT.003` |
| 3 | identity round-trip on real checkpoint | `EMBER-01.CERT.004` |
| 4 | identity fail-closed on tampered checkpoint | `EMBER-01.CERT.005` |
| 5 | reference model seat resolves and serves | `EMBER-01.CERT.006` |
| 6 | benchmark registry freeze | `EMBER-01.CERT.007` |
| 7 | 3B launch packet readiness | `EMBER-01.CERT.008` |
| 8 | authority conservation certificate | `EMBER-01.CERT.009` |
| 9 | public issue census freeze | `EMBER-01.CERT.010` |

## What this certificate does not claim

Per the contract's own outcome boundary (`EMBER-01.OUTCOME.002`,
`EMBER-01.CERT.009`): EMBER-01 trains no model and earns no research progress,
model birth, or capability credit. No current checkpoint is an admissible Ember
model. The EMBER-02 execution boundary in `CONTINUITY.md` is unchanged by this
certificate; EMBER-01's completion is what makes EMBER-02's prerequisite spine
available, nothing more.

## Re-verification

The verifier is public. From a clean detached checkout, the certifying command
shape is:

    python -B scripts/verify_ember01_completion.py --root <checkout> \
      --selection <operator goal selection> --receipt <receipt.json> \
      --run-custody --issue-census <census.json> <ROOT bindings> --run-seat \
      --identity-manifest bundle_v2/model-identity.json \
      --checkpoint-manifest bundle_v2/checkpoint/checkpoint-manifest.json \
      --model-config bundle_v2/config.json

Custody and seat legs require the operator-machine ROOT bindings; without them
those legs honestly report UNRESOLVED rather than green — that is the designed
proof that the legs bind to real operator state. `ember-cli /verify` dispatches
the same verifier (#1360).

## Reopening rule

Per `EMBER-01.REOPEN.001`: if later work discovers a unique uncustodied
artifact or a consumer that bypasses the identity manifest, EMBER-01 reopens
and dependent claims stop until the spine passes again. This record then gains
a dated supersession note; it is never silently rewritten.

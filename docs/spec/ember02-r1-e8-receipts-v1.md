# EMBER-02 R1-E8 receipt schemas v1

This document freezes the pure-validation packet for the A1 discriminating
gate in `ember02-preregistration-v1.md` §4-A1. It does not authorize a model
implementation or claim that an A1 run has occurred.

All JSON receipt objects are closed: unknown or missing fields refuse. Every
`{path, sha256}` reference is packet-relative, may not traverse its packet
root, and is reopened from raw bytes. Receipt `receipt_sha256` values are the
SHA-256 of canonical JSON (`sort_keys=true`, separators `,` and `:`, UTF-8)
after removing that field. Derived decimals use 12 places and round-half-even.

## Schemas

- `ember02-r1-e8-run-v1` binds terminal certified-launch identity, arm/tier,
  source, architecture and parameter counts, optimizer coverage/offload,
  matched data identity, energy coverage, and checkpoint. A1 requires total
  and active parameters both at least 3,000,000,000 and no router or experts.
  Tier 1 requires full-state AdamW, CPU offload, and optimizer coverage equal
  to the complete parameter count.
- `ember02-r1-e8-liveness-series-v1` binds a run-receipt digest to contiguous
  raw step rows containing tokens, whole-boundary seconds, and proxy joules.
- `ember02-r2-charged-budget-contract-v1` is the canonical external authority
  for the two projected R2 token counts. The E8 validator never derives or
  selects a charged-budget formula. The contract is reopened and hash-bound
  to both run receipts and their comparison identity. Absence is permanently
  `EVIDENCE_MISSING`, regardless of measured throughput.
- `ember02-r1-e8-liveness-v1` binds the threshold document, charged-budget
  contract, Tier-1/A3 runs, and both raw liveness series. The validator derives
  T-06 and T-08 from the bound threshold document, recomputes tokens/second,
  joules/token and the contract-projected token ratio, then adjudicates
  `TIER1_LIVE` or `FALLBACK_REQUIRED`.
- `ember02-r1-e8-parity-series-v1` binds a candidate/reference run digest to
  exactly T-09 contiguous loss and gradient-norm rows.
- `ember02-r1-e8-parity-v1` is legal only after a bound liveness receipt says
  `FALLBACK_REQUIRED`. It binds the Tier-2 candidate, Tier-1 AdamW reference,
  raw series, and a green R1-E7 receipt containing both required sigma values.
  The validator derives T-09, T-20, and F-11 inputs from the bound threshold
  document and recomputes both inequalities.

## Battery composition

`scripts/r1_exit_battery.py::check_r1_e8` is the first real consumer. It may
return `MET` only for either (a) a valid Tier-1 liveness receipt with no parity
receipt, or (b) a valid below-floor liveness receipt plus a valid parity PASS.
Missing authority remains `EVIDENCE_MISSING`; malformed, stale, swapped,
subscale, arithmetically inconsistent, or route-confused evidence is
`REFUSED`; a valid parity FAIL is `NOT_MET`.

This source carrier leaves real execution unresolved: no receipt here proves
that a certified dense >=3B A1 model, full-state CPU-offloaded AdamW, or a
matched Tier-2/reference segment has run.

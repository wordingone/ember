# Issue #113 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical W2 G-arm vehicle. The
surviving growth/control obligations are conserved by the canonical EMBER-05
contract and roadmap parent #1119.

Source master: `3cc9c1634a91d04059242c6765e1cd025bc88147`.

## Historical scope and completed portion

Issue #113 specified a two-part W2 grown-arm lane for a historical rung-1
checkpoint:

1. a CPU dry run that exercised growth, refusal gates, the frozen dump
   contract, and S-arm derivation; and
2. a real GPU leg that grew the old rung-1 subject to approximately 2.2B
   parameters, trained it, and produced the comparison receipts.

The file-set reconciliation landed in PR #117 (merge
`7087a0398467984a277e650bb3a0eff92cb8c094`). The CPU dry-run implementation
landed in PR #209 (merge `7e32941cd5fb68199634c5e3519e6a8b671aa7e5`).
The issue's 2026-07-06 acceptance comment records that dry-run boundary as
complete. Current master retains the fail-closed historical runner at
`src/ember/governance/scripts/w2_garm_runner.py`.

No real #113 GPU-leg receipt exists. This ruling therefore makes no growth,
training, checkpoint, capability, or matched-control result claim.

## Why the remaining vehicle is obsolete

The first live dispatch attempt established that `w2_garm_runner.py` has no
live implementation by design. The proposed substitute was the old cbase
rung-2 growth chain, but that path depended on the same historical sub-3B
subject and an exact-duplication grow operator that issue #280 measured as
capacity-null.

Current `GOAL.md` and `docs/domains/governance/roadmap/milestones/EMBER-05.md` prohibit newly
created, trained, grown, evaluated, or served Ember research networks below 3B.
The former 2.2B/cbase subject is read-only history; allocating a second live
launcher or reviving the old chain would violate both the current model floor
and the single-authority rule.

This is an architectural supersession, not an inference that the planned G arm
would have won or lost.

## Lossless obligation transfer

The following unique #113 obligations transfer to canonical roadmap parent
#1119 and the version-controlled EMBER-05 contract:

- growth must begin from an exact sufficiently trained, clean-genesis 3B Ember
  checkpoint, never the historical cbase/rung-1 subject;
- the growth mechanism must be function-preserving at the boundary and must
  create differentiated usable capacity rather than exact-duplicate twins;
- the pre-grow and post-grow checkpoints, manifests, parameter ownership,
  tokenizer, corpus, optimizer, runtime, source, and receipts must share one
  content-addressed identity spine;
- the grown/verified arm must be compared at frozen equal tokens, effective
  clean tokens, training FLOPs, data access, initialization evidence,
  evaluation, stopping, and tuning allowance against dense restart,
  predetermined schedule growth, and ungated expert accumulation;
- a responsible deletion or rollback must remove the attributed gain, and the
  comparison must include held-out retention, transfer, native reasoning, and
  unrelated-regression checks;
- current Ember Lab dispatch and the governed runner remain the only launch,
  lease, process, and receipt authority. The historical runner may be inspected
  or tested as history but may not mint current execution credit.

These requirements are already conjunctive in EMBER-05 WORK.005, WORK.009,
WORK.012, WORK.013, WORK.017, WORK.018 and CERT.006, CERT.007, CERT.010. Issue #113 owned
only the prohibited W2/cbase execution instance; it is not retained as a second
tracker.

## Closure effect

Close #113 as not planned/superseded after this ruling lands on public master
and the transfer is linked from #1119. The CPU dry-run remains useful
historical apparatus evidence, and #280 remains historical negative evidence
about exact-duplicate growth. Neither can authorize a sub-3B run or satisfy the
current EMBER-05 certificate.

`NO_NEW_PARALLEL_AUTHORITY`

Claim boundary: historical vehicle disposition and obligation conservation
only. No GPU execution, training, checkpoint, capability, benchmark, or
milestone completion is claimed.

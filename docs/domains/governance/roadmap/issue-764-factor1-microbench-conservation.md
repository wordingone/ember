# Issue #764 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the 434M/2.2B micro-benchmark
vehicle. The surviving optimizer-state and transition-equivalence obligations
are conserved by canonical issue #707 and the EMBER-05 contract.

Source master: `e2869608bc339860b6395efbc45d11680baf7aaf`.

## Historical scope and evidence boundary

Issue #764 specified a FACTOR-1 lever micro-benchmark on the historical 434M
pilot and exact 2.2B optimizer-state shapes. Its acceptance required production
L0, compiled L1, a counterbalanced subprocess L2 thread sweep, and governed
single-tenant CUDA L3/L3a evidence, followed by transition-equivalence and
quality/cure gates.

The issue comments contain useful historical apparatus findings: exact
per-family shape accounting, a 24.90297 GiB file-backed inner-step working-set
bound, physical-memory and bandwidth gates, the current environment's
`L1_UNAVAILABLE` compiler result, several corrected CUDA timing/watchdog
boundaries, and a final code/selftest clearance for the historical L3a path.
They do not contain a closure-grade full execution satisfying every acceptance
clause.

PR #1511 later proposed a current-native harness and one governed 434M CPU
L0/L2 receipt, while explicitly leaving exact-scale CPU, governed GPU L3,
precision/factorization/equivalence, and cure A/B unbound. PR #1511 was closed
without merge. Its branch evidence therefore is not public-master execution
credit and is not used to claim #764 completion.

No #764 GPU result, end-to-end speedup, quality result, capability result, or
completed 2.2B benchmark is claimed by this ruling.

## Why the named vehicle is obsolete

The 434M and 2.2B networks in #764 are historical sub-3B subjects. Current
`GOAL.md`, `docs/domains/governance/roadmap/milestones/EMBER-01.md`, and the EMBER-05 contract
prohibit creating, training, growing, evaluating, or serving sub-3B research
networks as current Ember work. The 2.2B/cbase path is read-only history, and
the old optimizer-state identity cannot authorize a present 3B experiment.

The current optimizer question also changed materially. #707 is the canonical
FACTOR-1 carrier and records that the historical factored-state hypothesis does
not directly match Ember's Muon-routed matrices, which carry momentum rather
than a second moment. It now owns the current-native question: optimizer-state
precision/capacity, full Muon deletion versus full AdamW and Adafactor controls,
explicit precision variants, update-survival, transition equivalence, and
quality attribution on an admissible clean-genesis 3B-or-larger subject.

Running #764's frozen 2.2B fixture would violate the active model floor.
Relabeling its old shape inventory as 3B would silently change the experiment.
This is architectural supersession, not evidence that any lever wins or loses.

## Lossless obligation transfer

The following unique #764 obligations transfer to canonical issue #707 and the
version-controlled EMBER-05 contract:

- derive the optimizer parameter/state inventory from the exact admitted
  current checkpoint, preserving per-tensor shape, orientation, ownership,
  dtype, optimizer group, and source-byte identity rather than total-numel
  surrogates;
- establish a production-path baseline and isolate each proposed lever without
  timing sibling reimplementations, eager fallbacks, or sequentially mutated
  optimizer trajectories;
- use identical forked parameter, gradient, and optimizer state for every arm,
  and admit timing only after frozen finite/max-absolute/max-relative/cosine,
  update-norm, scalar-step, and unchanged-input equivalence checks pass;
- preflight and receipt physical memory, commit, disk, paging, IO, CPU affinity,
  effective thread count, and same-process roofline calibration; use fresh,
  counterbalanced subprocess replicates for thread comparisons;
- reject analytically infeasible full GPU residency before allocation; for any
  tiled or compressed CUDA arm, bind persistent versus transient bytes,
  completed H2D/kernel/D2H wall boundaries, all requested tile sizes,
  full-coverage transition equivalence, peak allocated/reserved memory, and
  single-tenant lease evidence;
- name precision and optimizer-mechanism variants explicitly, keep systems and
  quality legs on the same variant, preserve `foreach=False` or an equivalent
  bounded implementation, measure per-class update survival, and never label
  the Adafactor bundle contrast as factorization-only evidence;
- compare current baseline, Muon-deletion control, and candidate mechanism at
  frozen equal initialization, data order, tokens, evaluation, stopping, and
  tuning allowance; retain spike, regression, deletion, and rollback gates;
- route any current experiment exclusively through Ember Lab, the governed
  runner, and the current custody/receipt spine. No historical daemon, cbase
  launcher, parallel lease, or parallel receipt authority may be revived.

Issue #707 already owns the hypothesis, current precision/mechanism variants,
pre-freeze constraints, leg sequencing, kill conditions, and claim grammar.
EMBER-05 owns the admissible 3B-or-larger growth and verification boundary.
#764 owned only the retired scale-specific micro-benchmark vehicle; no unique
obligation remains after this transfer.

## Closure effect

Close #764 as not planned/superseded after this ruling is on public master and
the transfer is linked from #707. Historical receipts and comments remain
provenance, not current execution authority. This closure does not close #707,
claim a FACTOR-1 win or loss, authorize GPU work, or grant training, benchmark,
checkpoint, capability, or milestone credit.

`NO_NEW_PARALLEL_AUTHORITY`

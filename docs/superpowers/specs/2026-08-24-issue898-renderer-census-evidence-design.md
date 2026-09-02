# Issue #898 Renderer-Census Evidence Design

## Status and authority

Approved by the independent review seat. This design adds an
issue-specific evidence consumer. It does not add a production runtime authority,
select a memory cure, or authorize issue closure.

The consumer reads a terminal standard installed-cockpit soak receipt and its raw
poll ledger together with the renderer diagnostic JSONL. It writes a new receipt
into a distinct sibling evidence directory. Arm custody is always read-only.

## Question

For one installed-cockpit arm, how does total admitted commit growth relate to
elapsed time, renderer calls and passes, rendered frame construction, diff work,
and bytes submitted to stdout?

The matched RM0/RM1 adjudication needs one frozen consumer so both arms use the
same identity checks, join rule, windows, regressions, ratios, and receipt hash.

## Considered approaches

1. **Step-held cumulative anchors (selected).** At every census timestamp, select
   the latest renderer row at or before that timestamp. This never reads future
   renderer work, preserves the renderer's actual 30-second emission cadence, and
   retains intervals with zero renderer advance.
2. Linear interpolation between renderer rows. This invents when work occurred
   between emissions and can manufacture correlations.
3. Nearest renderer row. This is simple but leaks future renderer state into a
   census observation.

## Files and boundaries

- `src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts` owns parsing,
  validation, anchoring, fits, receipt construction, exclusive writing, and receipt
  verification.
- `tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts` owns the
  focused behavioral and refusal tests.
- `tools/ember-cli/src/scripts/issue898-renderer-census-evidence.ts` is a thin Bun
  entrypoint over the service. It accepts exact input, identity, and output paths;
  it contains no independent evidence logic.

No existing soak producer, renderer producer, census adapter, wall consumer, or
runtime path changes.

## Invocation contract

The script requires:

- `--soak-receipt <absolute path>`
- `--polls <absolute path>`
- `--renderer <absolute path>`
- `--output <absolute path>`
- `--source-commit <40 lowercase hex>`
- `--cockpit-pid <positive integer>`
- `--cockpit-process-start-token <positive decimal>`
- `--receipt-written-at <canonical ISO timestamp>`

The output parent is the evidence root. Its parent must equal the arm custody
root's parent, and it must not equal or descend from the arm custody root. The
evidence root and output file are exclusive-created; an existing output parent or
file is refused. This gives one no-overwrite receipt root per arm without mutating
the arm.

## Input admission

Before joining, the consumer:

1. Reopens and verifies the standard soak receipt.
2. Reopens the polls ledger and verifies its SHA-256 against the standard receipt.
3. Requires both JSONL inputs to end in a newline and contain at least three rows.
4. Validates exact row schemas, zero-based contiguous sequences, strictly increasing
   timestamps, and nondecreasing cumulative renderer counters.
5. Requires every census row to admit exactly one cockpit and one brain server,
   with zero ownership overlap. Every cockpit PID and kernel-derived process start
   token must match the caller's pins.
6. Requires every renderer row to match the pinned source commit and cockpit PID.
7. Requires one constant renderer runtime-origin token. Its difference from the
   kernel process start token must be in the inclusive interval `[0, 5000 ms]`.
   The receipt records `runtime_origin_tolerance_ms: 5000`. The runtime token is a
   sanity check only and never an identity or join key.

The admitted commit series is the sum of commit bytes for the exactly admitted
cockpit and owned brain-server samples, matching the standard soak receipt.

## Join semantics

For each census timestamp at or after the first renderer timestamp, select the
latest renderer row whose `captured_at_ms` is less than or equal to the census
timestamp. The selected row must already satisfy the pinned PID and source checks.

The consumer retains every interval between adjacent census anchors, including
intervals where both anchors select the same renderer sequence. Such an interval
has exact zero renderer deltas and can show positive memory growth during zero
renderer work. Dropping it would selection-bias the result.

Each interval records:

- start/end timestamps and elapsed seconds;
- start/end renderer sequences;
- end-anchor renderer staleness in milliseconds and `stale_over_60s`;
- commit delta and commit bytes per second;
- deltas and per-second rates for render calls, render passes, rendered-frame UTF-8
  bytes, diff cells, optimized runs, submitted UTF-8 bytes, stream writes,
  backpressured coalesces, write-false events, and drain repaints.

Renderer staleness is never negative. Values greater than 60,000 ms are flagged
and counted but not discarded.

## Fits, windows, and ratios

Ordinary least squares uses elapsed seconds as `x` and cumulative values as `y`.
Every fit records sample count, slope, intercept, r-squared, and slope standard
error. A fit needs at least three distinct timestamps. Slope standard error is:

`sqrt((SS_residual / (n - 2)) / SS_xx)`.

The receipt contains:

- one full-run fit over every admitted anchor, including startup; and
- non-overlapping 300-second settled windows beginning 60 seconds after the first
  admitted anchor. A window is emitted only when it contains at least three anchors.

Every fit group covers total commit bytes and cumulative renderer calls, passes,
rendered-frame bytes, diff cells, optimized runs, stream writes, submitted bytes,
backpressured coalesces, write-false events, and drain repaints.

Normalized ratios are computed from fitted slopes:

- commit bytes per render pass; and
- commit bytes per submitted stdout byte.

A normalized ratio is `null` when the denominator slope is exactly zero, its slope
standard error is unavailable, or `abs(slope) <= slope_standard_error`. This avoids
claiming an extreme ratio from a denominator statistically indistinguishable from
zero.

## Receipt

The receipt schema is `ember-issue898-renderer-census-evidence-v1` with verdict
`MEASURED_NEEDS_INDEPENDENT_ADJUDICATION`. It contains:

- exact input paths, SHA-256 hashes, and byte counts for the standard soak receipt,
  polls ledger, and renderer ledger;
- source commit, cockpit PID, kernel process-start token, renderer runtime-origin
  token, runtime-origin delta, and the named 5000 ms tolerance;
- the step-hold join contract and 60-second staleness threshold;
- anchor, interval, stale-interval, zero-renderer-advance, and
  zero-renderer-advance-with-positive-commit counts;
- every interval row;
- the full-run fit group and settled 300-second fit groups;
- `receipt_written_at`; and
- `receipt_sha256`, computed over canonical sorted-key JSON excluding that field.

The file is written as formatted JSON plus one final newline. The self hash is not
the file hash; both are reported by custody review.

The verifier checks exact top-level and nested keys, schema/verdict, canonical
self hash, input bindings, identity pins, count consistency, fit finiteness, window
ordering, and ratio rules. It can rehash the three supplied input files to prove the
receipt still binds the same immutable custody.

## Failure behavior

All validation is fail-closed with stable `ISSUE898_RENDERER_CENSUS_*` error names.
No partial receipt is written. Input validation and receipt construction complete
before exclusive output creation. If the final write fails, the incomplete new
evidence root may be preserved for diagnosis but is never a valid receipt.

## TDD evidence

The first RED fixture contains a sealed standard soak, renderer rows, and a positive
commit interval whose renderer sequence does not advance. The expected API and
receipt assertions fail because the consumer module is absent.

GREEN and refusal coverage proves:

- no-future step-held anchoring;
- retention and counting of zero-advance positive-commit intervals;
- correct per-interval rates, full-run OLS, settled windows, slope standard error,
  and ratio nulling;
- staleness flags without row dropping;
- standard-receipt and raw-input binding;
- PID, kernel token, source, and runtime-origin tolerance refusals;
- nonmonotone timestamps, renderer sequence gaps, and cumulative counter rollback
  refusals;
- no-overwrite sibling custody; and
- receipt tamper and input-substitution refusals.

Focused tests, the existing installed-cockpit soak tests, renderer diagnostic tests,
and TypeScript typecheck are rerun before publication.

## Claim boundary

This receipt measures association in one arm. The matched RM0/RM1 pair can
discriminate the reduced-motion factor only after both independently sealed receipts
are compared. Neither an individual receipt nor the consumer itself proves a causal
memory cure, authorizes a production change, or satisfies issue #898.

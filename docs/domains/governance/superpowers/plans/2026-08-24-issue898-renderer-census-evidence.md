# Issue #898 Renderer-Census Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frozen, executable, self-hashed evidence consumer that joins one sealed installed-cockpit census ledger to its renderer diagnostic ledger without future leakage.

**Architecture:** A service validates the standard soak receipt and both immutable JSONL inputs, step-holds renderer cumulative counters onto census timestamps, derives interval rows and OLS fit groups, then exclusive-writes a sibling evidence receipt. A thin Bun script parses command-line pins and delegates all evidence logic to the service.

**Tech Stack:** TypeScript, Bun, `bun:test`, Node `fs`/`path`/`crypto`, existing `linearFit` and installed-cockpit soak verifiers.

**Spec:** `docs/domains/governance/superpowers/specs/2026-08-24-issue898-renderer-census-evidence-design.md`

## Global Constraints

- Source baseline is exact public master `0129fe44b94a3586b146e7214ccda1ebfc696400`.
- The consumer is issue-specific evidence code, not production runtime or cure authority.
- Arm custody inputs are read-only; output is exclusive-created in a distinct sibling evidence directory.
- Kernel census PID/start token is sole identity authority; renderer runtime-origin tolerance is exactly 5000 ms and sanity-only.
- Renderer anchoring uses latest row at or before each census timestamp; zero-advance intervals are retained.
- Full-run OLS includes startup; settled windows are non-overlapping 300-second windows beginning 60 seconds after the first anchor.
- A normalized ratio is null when its denominator slope is zero, lacks standard error, or `abs(slope) <= slope_standard_error`.
- Every new behavior follows RED, observed expected failure, minimal GREEN, and fresh verification.
- All non-Ember Python remains forbidden; test and execution commands use Bun and hidden/no-window ownership rules.

---

### Task 1: RED happy-path join contract

**Files:**
- Create: `tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts`
- Create after RED only: `src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts`

**Interfaces:**
- Consumes: `verifyInstalledCockpitSoakCustody(receiptText, pollsText)` and `linearFit(points)`.
- Produces: `sealIssue898RendererCensusEvidence(input): Issue898RendererCensusEvidenceReceipt` and `verifyIssue898RendererCensusEvidenceReceipt(text, bindings?): Issue898RendererCensusEvidenceReceipt`.

- [ ] **Step 1: Write the fixture helpers and failing happy-path test**

Use the existing standard-soak fixture shape to create 121 one-minute census rows,
one cockpit sample plus one owned brain sample, exact healthy walls, and a valid
standard receipt. Create renderer rows every 30 seconds with cumulative counters.
Include census anchors at which the selected renderer sequence repeats while total
commit increases.

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  sealIssue898RendererCensusEvidence,
  verifyIssue898RendererCensusEvidenceReceipt,
} from "./issue898-renderer-census-evidence.ts";

test("joins by prior renderer row and retains zero-advance positive-commit intervals", () => {
  const fixture = createEvidenceFixture();
  const receipt = sealIssue898RendererCensusEvidence(fixture.input);

  expect(receipt.schema_version).toBe("ember-issue898-renderer-census-evidence-v1");
  expect(receipt.verdict).toBe("MEASURED_NEEDS_INDEPENDENT_ADJUDICATION");
  expect(receipt.join.zero_renderer_advance_positive_commit_count).toBeGreaterThan(0);
  const zero = receipt.intervals.find((row) =>
    row.renderer_start_sequence === row.renderer_end_sequence && row.commit_delta_bytes > 0
  );
  expect(zero?.render_pass_delta).toBe(0);
  expect(zero?.submitted_utf8_byte_delta).toBe(0);
  expect(receipt.full_run.fits.commit_bytes.slope_per_second).toBeFinite();
  expect(receipt.settled_windows.length).toBeGreaterThan(0);
  expect(verifyIssue898RendererCensusEvidenceReceipt(
    readFileSync(fixture.input.outputPath, "utf8"), fixture.bindings,
  )).toEqual(receipt);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
bun test tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts
```

Expected: FAIL because `issue898-renderer-census-evidence.ts` does not exist. This
is the named RED; a syntax or fixture error is not acceptable.

- [ ] **Step 3: Route the RED receipt to the review seat before production code**

Report exact test-file SHA-256, command, pass/fail/expect counts, and the missing
module failure. Wait for the review seat's executable-byte confirmation when host execution is
required.

---

### Task 2: GREEN parser, anchor, interval, fit, and receipt core

**Files:**
- Create: `src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts`
- Modify: `tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts`

**Interfaces:**
- Consumes: paths and pins in `Issue898RendererCensusEvidenceInput`.
- Produces: the service API from Task 1 and schema `ember-issue898-renderer-census-evidence-v1`.

- [ ] **Step 1: Define exact public input and binding types**

```ts
export const ISSUE898_RUNTIME_ORIGIN_TOLERANCE_MS = 5_000;
export const ISSUE898_RENDERER_STALE_MS = 60_000;
export const ISSUE898_SETTLE_MS = 60_000;
export const ISSUE898_WINDOW_MS = 300_000;

export interface Issue898RendererCensusEvidenceInput {
  soakReceiptPath: string;
  pollsPath: string;
  rendererPath: string;
  outputPath: string;
  sourceCommit: string;
  cockpitPid: number;
  cockpitProcessStartToken: string;
  receiptWrittenAt: string;
}

export interface Issue898RendererCensusEvidenceBindings {
  soakReceiptText: string;
  pollsText: string;
  rendererText: string;
  sourceCommit: string;
  cockpitPid: number;
  cockpitProcessStartToken: string;
}
```

- [ ] **Step 2: Implement only the admitted happy-path reader**

Read all three inputs before creating output and call
`verifyInstalledCockpitSoakCustody(soakReceiptText, pollsText)`. Parse the valid,
sealed fixture rows and expose only the data needed by the Task 1 assertions. Do
not add new stable refusal branches here: JSONL, stream, identity, runtime, custody,
and verifier refusal behavior belongs to Task 3 and must follow its family RED.

- [ ] **Step 3: Implement step-held anchors and interval rows**

Advance one renderer cursor while `renderer[cursor + 1].captured_at_ms <= censusMs`.
Skip only census rows before renderer row zero. Keep adjacent anchors even when the
selected renderer sequence is unchanged.

```ts
const stalenessMs = censusMs - selected.captured_at_ms;
const interval = {
  started_at: previous.observedAt,
  ended_at: current.observedAt,
  elapsed_seconds: (current.observedAtMs - previous.observedAtMs) / 1_000,
  renderer_start_sequence: previous.renderer.sequence,
  renderer_end_sequence: current.renderer.sequence,
  renderer_staleness_ms: stalenessMs,
  stale_over_60s: false, // threshold behavior follows its Task 3 RED
  commit_delta_bytes: current.commitBytes - previous.commitBytes,
  commit_bytes_per_second: (current.commitBytes - previous.commitBytes) / elapsedSeconds,
  render_pass_delta: current.renderer.render_passes - previous.renderer.render_passes,
  render_passes_per_second:
    (current.renderer.render_passes - previous.renderer.render_passes) / elapsedSeconds,
  render_call_delta: current.renderer.render_calls - previous.renderer.render_calls,
  render_calls_per_second:
    (current.renderer.render_calls - previous.renderer.render_calls) / elapsedSeconds,
  rendered_frame_utf8_byte_delta:
    current.renderer.rendered_frame_utf8_bytes - previous.renderer.rendered_frame_utf8_bytes,
  rendered_frame_utf8_bytes_per_second:
    (current.renderer.rendered_frame_utf8_bytes - previous.renderer.rendered_frame_utf8_bytes) / elapsedSeconds,
  diff_cell_delta: current.renderer.diff_cells - previous.renderer.diff_cells,
  diff_cells_per_second:
    (current.renderer.diff_cells - previous.renderer.diff_cells) / elapsedSeconds,
  optimized_run_delta: current.renderer.optimized_runs - previous.renderer.optimized_runs,
  optimized_runs_per_second:
    (current.renderer.optimized_runs - previous.renderer.optimized_runs) / elapsedSeconds,
  stream_write_delta: current.renderer.stream_write_calls - previous.renderer.stream_write_calls,
  stream_writes_per_second:
    (current.renderer.stream_write_calls - previous.renderer.stream_write_calls) / elapsedSeconds,
  submitted_utf8_byte_delta:
    current.renderer.submitted_utf8_bytes - previous.renderer.submitted_utf8_bytes,
  submitted_utf8_bytes_per_second:
    (current.renderer.submitted_utf8_bytes - previous.renderer.submitted_utf8_bytes) / elapsedSeconds,
  backpressured_coalesce_delta:
    current.renderer.backpressured_coalesces - previous.renderer.backpressured_coalesces,
  backpressured_coalesces_per_second:
    (current.renderer.backpressured_coalesces - previous.renderer.backpressured_coalesces) / elapsedSeconds,
  write_false_event_delta:
    current.renderer.write_false_events - previous.renderer.write_false_events,
  write_false_events_per_second:
    (current.renderer.write_false_events - previous.renderer.write_false_events) / elapsedSeconds,
  drain_repaint_delta: current.renderer.drain_repaints - previous.renderer.drain_repaints,
  drain_repaints_per_second:
    (current.renderer.drain_repaints - previous.renderer.drain_repaints) / elapsedSeconds,
};
```

- [ ] **Step 4: Implement OLS with slope standard error**

```ts
function evidenceFit(points: ReadonlyArray<{ x: number; y: number }>): EvidenceFit {
  const fit = linearFit(points);
  const meanX = points.reduce((sum, point) => sum + point.x, 0) / points.length;
  const sxx = points.reduce((sum, point) => sum + (point.x - meanX) ** 2, 0);
  const ssResidual = points.reduce(
    (sum, point) => sum + (point.y - (fit.intercept + fit.slope * point.x)) ** 2,
    0,
  );
  return {
    sample_count: points.length,
    slope_per_second: fit.slope,
    intercept: fit.intercept,
    r2: fit.r2,
    slope_standard_error: Math.sqrt((ssResidual / (points.length - 2)) / sxx),
  };
}

function normalizedRatio(numerator: EvidenceFit, denominator: EvidenceFit): number | null {
  const ratio = numerator.slope_per_second / denominator.slope_per_second;
  return Number.isFinite(ratio) ? ratio : null;
}
```

The statistical near-zero denominator rule is deliberately deferred to its Task 3
behavior RED.

- [ ] **Step 5: Build full and settled fit groups**

Full-run uses all anchors. Settled windows start at `firstAnchorMs + 60_000` and
advance by 300,000 ms. Select anchors in each window by timestamp; emit only windows
with at least three anchors. Each group fits commit bytes and every cumulative
renderer metric, then derives both normalized ratios.

- [ ] **Step 6: Implement canonical self hash and happy-path output**

Construct the canonical self hash, create the fixture's absent output directory,
write formatted JSON plus one newline, and fsync. Do not add sibling-custody,
no-overwrite, tamper, or binding refusal behavior before the Task 3 family RED.

```ts
const base = {
  schema_version: "ember-issue898-renderer-census-evidence-v1",
  verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION",
  inputs,
  identity,
  join_contract,
  join,
  intervals,
  full_run,
  settled_windows,
  receipt_written_at: input.receiptWrittenAt,
};
const receipt = { ...base, receipt_sha256: sha256(canonicalJson(base)) };
```

- [ ] **Step 7: Run focused test and verify GREEN**

Run the same focused Bun command. Expected: all happy-path assertions PASS with no
warnings or errors.

---

### Task 3: Family-batched RED/GREEN refusal and tamper coverage

**Files:**
- Modify: `tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts`

**Interfaces:**
- Consumes: service and verifier from Task 2.
- Produces: stable refusal behavior for every identity, monotonicity, custody, and
  binding gate in the spec.

- [ ] **Step 1: Add family A tests for JSONL seal, parse, and length**

Cover renderer and poll missing-final-newline, malformed JSON, and too-short streams.
Run the whole family against the stripped Task 2 candidate. Every named assertion
must be RED because its stable gate is absent. Then add only family A gates and run
the family plus the happy path GREEN.

- [ ] **Step 2: Add family B tests for the renderer stream**

Cover sequence/schema, canonical and monotonic time, cumulative counter validity and
rollback, and pool-size validity. Observe every named family B test RED before adding
only the renderer-stream gates; then run family B plus the happy path GREEN.

- [ ] **Step 3: Add family C tests for the poll stream**

Cover sequence/schema, canonical and monotonic census time, exact two-class
cardinality with zero ownership overlap, kernel token/PID, and nonnegative safe
commit bytes. Rebind the standard soak receipt after each poll mutation so existing
soak custody passes and the new consumer gate is the actual falsifier. Observe every
named family C test RED, add only family C gates, then run family C plus happy GREEN.

- [ ] **Step 4: Add family D tests for identity and runtime band**

Cover input pin shapes and canonical receipt time, source/PID identity, constant renderer runtime-origin token, runtime-origin
before the kernel token, runtime-origin more than the named 5,000 ms tolerance after
it, and standard-soak identity mismatch. Observe every named family D test RED, add
only family D gates, then run family D plus happy GREEN.

Families B-D include these required cases:

```ts
test.each([
  ["kernel token drift", mutatePollToken, "COCKPIT_IDENTITY_DRIFT"],
  ["runtime origin before kernel", mutateRuntimeBeforeKernel, "RUNTIME_ORIGIN_OUT_OF_RANGE"],
  ["runtime origin above tolerance", mutateRuntimeAboveTolerance, "RUNTIME_ORIGIN_OUT_OF_RANGE"],
  ["renderer sequence gap", mutateRendererSequence, "RENDERER_SEQUENCE_INVALID"],
  ["renderer counter rollback", mutateRendererCounterRollback, "COUNTER_ROLLBACK"],
  ["renderer timestamp rollback", mutateRendererTimestampRollback, "RENDERER_TIME_NONMONOTONE"],
])("refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});
```

- [ ] **Step 5: Add family E tests for output custody and no-overwrite**

Assert existing evidence root, output inside the arm root, output outside the arm's
parent, and pre-existing output bytes are refused with stable errors and remain
unchanged. Observe every named family E test RED, add only family E gates including
sibling-root derivation and `wx`, then run family E plus happy GREEN.

- [ ] **Step 6: Add family F tests for receipt and binding verification**

After a valid receipt, mutate JSON/schema/verdict/self hash, soak text, polls text,
renderer text, source commit, cockpit PID, and kernel token binding. Observe every
named family F test RED, add only family F gates, then run family F plus happy GREEN.

- [ ] **Step 7: Add RED/GREEN behavior tests for staleness and ratio nulling**

Create a renderer gap greater than 60 seconds and assert the interval remains while
`stale_over_60s` and the count increment. Create a constant submitted-byte series
and assert `commit_bytes_per_submitted_utf8_byte === null`; create a noisy near-zero
series whose absolute slope does not exceed its standard error and assert null.

- [ ] **Step 8: Run the complete focused suite**

Run all six refusal families, both behavior tests, and the original happy path in one
focused command. Confirm zero failures and confirm every failed validation creates
no new output root or overwritten bytes.

For verifier binding coverage, mutate the receipt, polls text, renderer text, source commit,
PID, and token one at a time. Assert the verifier rejects self-hash tampering and
input substitution.

---

### Task 4: RED/GREEN executable Bun entrypoint

**Files:**
- Create: `tools/ember-cli/src/scripts/issue898-renderer-census-evidence.test.ts`
- Create after RED: `tools/ember-cli/src/scripts/issue898-renderer-census-evidence.ts`

**Interfaces:**
- Consumes: `sealIssue898RendererCensusEvidence` from Task 2.
- Produces: `parseIssue898RendererCensusArgs(argv)` and a Bun `import.meta.main`
  execution path.

- [ ] **Step 1: Write failing argument parser tests**

```ts
test("parses the exact evidence invocation", () => {
  expect(parseIssue898RendererCensusArgs([
    "--soak-receipt", "B:\\root\\soak\\soak-receipt.json",
    "--polls", "B:\\root\\soak\\polls.jsonl",
    "--renderer", "B:\\root\\renderer.jsonl",
    "--output", "B:\\evidence\\renderer-census-receipt.json",
    "--source-commit", "a".repeat(40),
    "--cockpit-pid", "31808",
    "--cockpit-process-start-token", "639231623825394551",
    "--receipt-written-at", "2026-08-24T12:05:49.000Z",
  ])).toEqual({
    soakReceiptPath: "B:\\root\\soak\\soak-receipt.json",
    pollsPath: "B:\\root\\soak\\polls.jsonl",
    rendererPath: "B:\\root\\renderer.jsonl",
    outputPath: "B:\\evidence\\renderer-census-receipt.json",
    sourceCommit: "a".repeat(40),
    cockpitPid: 31808,
    cockpitProcessStartToken: "639231623825394551",
    receiptWrittenAt: "2026-08-24T12:05:49.000Z",
  });
});
```

- [ ] **Step 2: Run script test and verify missing-module RED**

Run:

```powershell
bun test tools/ember-cli/src/scripts/issue898-renderer-census-evidence.test.ts
```

- [ ] **Step 3: Implement strict parser and main path**

Reject missing, duplicate, or unknown flags. Parse positive safe-integer PID without
coercion. On `import.meta.main`, call the service, print one canonical JSON summary
containing schema, verdict, output path, and self hash, and exit nonzero on refusal.

- [ ] **Step 4: Run script and service tests to GREEN**

Run both focused test files together and require pristine output.

---

### Task 5: Verification, freeze, and publication packet

**Files:**
- Verify: the two new service/script files and two tests
- Verify: `tools/ember-cli/src/services/issue898-installed-cockpit-soak.test.ts`
- Verify: `tools/ember-cli/src/ink/rendering-pipeline-diagnostic.test.ts`
- Create locally for handoff: exact PR body/evidence packet after independent GREEN acceptance

**Interfaces:**
- Consumes: all implementation and tests from Tasks 1-4.
- Produces: immutable reviewed head and executable consumer for RM0/RM1 sealing.

- [ ] **Step 1: Run focused and neighboring suites**

```powershell
bun test tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts tools/ember-cli/src/scripts/issue898-renderer-census-evidence.test.ts
bun test tools/ember-cli/src/services/issue898-installed-cockpit-soak.test.ts tools/ember-cli/src/ink/rendering-pipeline-diagnostic.test.ts
```

- [ ] **Step 2: Run repository TypeScript typecheck and compare clean-base control**

Use the repository's existing typecheck command. If it is nonzero, run the identical
command against clean baseline `0129fe44` and prove zero diff-caused diagnostics;
never relabel baseline failures as GREEN.

- [ ] **Step 3: Run diff and source-boundary checks**

```powershell
git diff --check
git status --short
git diff -- src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts tools/ember-cli/src/services/issue898-renderer-census-evidence.test.ts tools/ember-cli/src/scripts/issue898-renderer-census-evidence.ts tools/ember-cli/src/scripts/issue898-renderer-census-evidence.test.ts
```

Confirm no runtime producer, existing receipt schema, or arm custody path changed.

- [ ] **Step 4: Freeze hashes and route GREEN to the review seat**

Route exact source/test hashes, RED and GREEN commands/counts, neighbor results,
typecheck comparison, claim boundary, and current worktree/base. The review seat independently
reruns and returns P0/P1 or PASS.

- [ ] **Step 5: Commit/push/PR through the shared-git and publication gates**

After independent PASS, the integrator executes staging/commit/push/PR actions. The PR body must
say the consumer leaves #898 open and must not use close/fix/resolve near the issue
number. Verify exact five labels, milestone, bare base/head SHA pins, fresh CI, and
independent exact-head review before merge.

- [ ] **Step 6: Execute frozen consumer only after standard arm seal**

Run the reviewed merged consumer against the terminal standard soak receipt,
`polls.jsonl`, and `renderer.jsonl`, writing to a new sibling evidence root. Reopen
and verify self/file/input hashes before any owned cleanup. For RM1, invoke the same
published consumer with the RM1 standard receipt, polls ledger, renderer ledger,
source commit, cockpit PID, and kernel start-token pins; do not change consumer bytes.

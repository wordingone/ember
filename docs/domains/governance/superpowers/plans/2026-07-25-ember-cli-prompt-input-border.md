# Ember CLI Prompt Input Border Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Ember CLI's rule-framed prompt with a closed rounded input box that contains the real status row and remains correct through a compiled-binary 80-to-40-to-80 ConPTY resize.

**Architecture:** `PromptInput` owns the visual container and accepts the existing `StatusLine` as a React node, while `screens/repl.ts` remains the owner of status state and construction. A small capture utility launches the exact compiled binary in ConPTY, reconstructs each terminal frame, and emits content-addressed raw-byte/frame evidence.

**Tech Stack:** TypeScript, React 19, Bun test/build, Ember's Ink-compatible reconciler, node-pty/Windows ConPTY, `@xterm/headless`, SHA-256 JSON receipts.

## Global Constraints

- Implement only issue #243; do not carry PR #806's tool-result digest or stale issue-#242 prose.
- Keep notifications and processing shimmer outside the border.
- Keep stash, input, queue, overflow, and the real `StatusLine` inside the border.
- Preserve current input, cursor, suggestion, queue, keybinding, transcript, telemetry, and operator-surface behavior.
- Use `PANEL_BORDER_STYLE`, the existing primary interaction color, `paddingX: 1`, and the supplied main-column width.
- Width arithmetic is `max(0, floor(width) - 2 border - 2 padding - 2 prompt prefix)`.
- The narrow 40-column viewport must be strictly positive.
- Unit/component results do not authorize issue closure; the compiled binary's ConPTY bytes do.
- Niko and Vera remain paused; execute this plan inline without subagents.

---

### Task 1: PromptInput closed container and width contract

**Files:**
- Modify: `tools/ember-cli/src/components/prompt-input.ts`
- Modify: `src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts`

**Interfaces:**
- Consumes: existing `Box`, `Text`, `computeInputViewport`, `color`, and `PANEL_BORDER_STYLE`.
- Produces: `promptInputViewportWidth(width: number): number` and `PromptInputProps.statusLine?: React.ReactNode`.

- [ ] **Step 1: Write failing structure and width tests**

Add tests that inspect the returned element tree:

```ts
it("renders one rounded full-width box instead of rule rows", () => {
  const el = PromptInput({ state: baseState(), width: 40 });
  const box = flatten(el).find((node) => node?.props?.["data-border-style"] === "round");
  expect(box).toBeTruthy();
  expect(box?.props?.style?.width).toBe(40);
  expect(findTextWhere(el, (s) => s === "â”€".repeat(40))).toBe(false);
});

it("keeps transient chrome outside and input-owned rows inside", () => {
  const status = React.createElement(Text, null, "STATUS");
  const el = PromptInput({
    state: baseState({ text: "hello", isStashed: true, stashNotice: "STASH" }),
    notifications: [{ id: "n", kind: "info", message: "NOTICE" }],
    isProcessing: true,
    queuedItems: ["queued"],
    statusLine: status,
    showStatusLine: false,
    width: 40,
  });
  const rootChildren = children(el);
  const bordered = rootChildren.at(-1);
  expect(findTextWhere(bordered, (s) => s === "STASH")).toBe(true);
  expect(findTextWhere(bordered, (s) => s === "queued")).toBe(true);
  expect(findTextWhere(bordered, (s) => s === "STATUS")).toBe(true);
  expect(findTextWhere(bordered, (s) => s === "NOTICE")).toBe(false);
});

it("leaves a positive viewport at width 40 and clamps tiny widths", () => {
  expect(promptInputViewportWidth(40)).toBe(34);
  expect(promptInputViewportWidth(5)).toBe(0);
  expect(promptInputViewportWidth(Number.NaN)).toBe(0);
});
```

- [ ] **Step 2: Run the focused test and witness RED**

Run:

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts
```

Expected: failures because the component still emits rule rows, has no rounded box or `statusLine`, and does not export `promptInputViewportWidth`.

- [ ] **Step 3: Implement the minimal closed container**

Add:

```ts
import { color, PANEL_BORDER_STYLE } from "./design-system.ts";

const INPUT_BOX_BORDER_COLOR = color("primary", "fg");

export function promptInputViewportWidth(width: number): number {
  if (!Number.isFinite(width)) return 0;
  return Math.max(0, Math.floor(width) - 6);
}
```

Extend props:

```ts
statusLine?: React.ReactNode;
```

Build transient `above` children separately. Build `boxChildren` from stash,
input, queue, overflow, the legacy internal status only when
`showStatusLine === true`, and `statusLine` when supplied. Replace the rule
nodes with:

```ts
const box = React.createElement(
  Box,
  {
    key: "input-box",
    flexDirection: "column",
    borderStyle: PANEL_BORDER_STYLE,
    borderColor: INPUT_BOX_BORDER_COLOR,
    paddingX: 1,
    width: Number.isFinite(width) ? Math.max(0, Math.floor(width)) : 0,
  },
  ...boxChildren,
);

return React.createElement(
  Box,
  { flexDirection: "column", flexShrink: 0 },
  ...above,
  box,
);
```

Use `promptInputViewportWidth(width)` for the cursor-windowed text width.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts
```

Expected: all tests pass with no skipped structural test.

- [ ] **Step 5: Commit the component increment**

```powershell
git add tools/ember-cli/src/components/prompt-input.ts src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts
git commit -m "fix(cli): close the prompt input border"
```

### Task 2: Anchor the real StatusLine inside PromptInput

**Files:**
- Modify: `tools/ember-cli/src/screens/repl.ts`
- Modify: `tools/ember-cli/src/screens/repl-operator-surface.test.ts`

**Interfaces:**
- Consumes: `PromptInputProps.statusLine` from Task 1 and the existing `StatusLine` props/state.
- Produces: exactly one real `StatusLine`, nested inside `PromptInput`, with no permission-only duplicate.

- [ ] **Step 1: Add a production-frame regression**

Extend the existing `ReplScreen` mount at 60x20 and 80x24. After
`parseRenderedIntoFrame`, locate the one row containing
`"bypass permissions on"` and assert it is bounded by the prompt box's vertical
edges:

```ts
const statusRows = lines.filter((line) => line.includes("bypass permissions on"));
expect(statusRows).toHaveLength(1);
const statusRow = statusRows[0]!;
expect(statusRow.indexOf("│")).toBeGreaterThanOrEqual(0);
expect(statusRow.lastIndexOf("│")).toBeGreaterThan(statusRow.indexOf("│"));
```

Also assert the prompt row containing `"❯"` has the same two-edge property.
This uses the real REPL and rendering pipeline; it does not depend on component
names or source-text inspection.

- [ ] **Step 2: Run the REPL regression and witness RED**

Run:

```powershell
bun test tools/ember-cli/src/screens/repl-operator-surface.test.ts
```

Expected: the status component is still a sibling of `PromptInput`.

- [ ] **Step 3: Move only the existing StatusLine element**

In `screens/repl.ts`, construct:

```ts
const statusLine = React.createElement(StatusLine, {
  permissionMode: permModeState,
  interrupt: interruptHandler,
  taskPanel: taskPanelState,
  telemetry,
  modelMetrics: modelMetrics ?? undefined,
  effort: retryStatus,
  degraded: degradedBanner,
  outage: outageBanner,
  roundtripAge,
});
```

Pass `statusLine` to `PromptInput`, retain `showStatusLine: false`, and remove
the former separate sibling element. Do not alter any `StatusLine` prop or
state source.

- [ ] **Step 4: Run focused REPL and PromptInput tests**

Run:

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts tools/ember-cli/src/screens/repl-operator-surface.test.ts
```

Expected: both suites pass and exactly one status component is rendered.

- [ ] **Step 5: Commit status anchoring**

```powershell
git add tools/ember-cli/src/screens/repl.ts tools/ember-cli/src/screens/repl-operator-surface.test.ts
git commit -m "fix(cli): anchor status inside prompt panel"
```

### Task 3: Prove real terminal paint at 80, 40, and restored 80 columns

**Files:**
- Create: `src/ember/infrastructure/tools/ember-cli/src/components/prompt-input-paint.test.ts`

**Interfaces:**
- Consumes: production `PromptInput`, `Text`, `mountInk`, and the real rendering pipeline.
- Produces: a deterministic frame validator used only by this test.

- [ ] **Step 1: Write the failing end-to-end paint test**

For each width in `[80, 40, 80]`, mount:

```ts
const el = React.createElement(PromptInput, {
  state: baseState({ text: "operator input", cursor: 14 }),
  statusLine: React.createElement(Text, null, "STATUS"),
  showStatusLine: false,
  width,
});
```

Capture output through `mountInk`, reconstruct the terminal with
`@xterm/headless`, and assert:

```ts
expect(frame).toContain("â•­");
expect(frame).toContain("â•®");
expect(frame).toContain("â•°");
expect(frame).toContain("â•¯");
expect(frame).toMatch(/â”‚.*â¯.*â”‚/);
expect(frame).toMatch(/â”‚.*STATUS.*â”‚/);
expect(promptInputViewportWidth(40)).toBeGreaterThan(0);
```

The second 80-column mount must be fresh, proving restoration rather than
reusing the first frame.

- [ ] **Step 2: Run and witness RED or the first concrete renderer mismatch**

Run:

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input-paint.test.ts
```

Expected before Tasks 1-2: no closed rounded frame. After those tasks, any
failure identifies a real width/layout defect and must be fixed in
`prompt-input.ts`, not weakened in this test.

- [ ] **Step 3: Make only renderer-required corrections**

If the real pipeline exposes a width mismatch, correct `PromptInput` so the
outer box's painted width equals the supplied width and the prompt/status rows
remain between vertical edges. Do not replace the real-pipeline test with
element inspection.

- [ ] **Step 4: Run the three focused suites**

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts src/ember/infrastructure/tools/ember-cli/src/components/prompt-input-paint.test.ts tools/ember-cli/src/screens/repl-operator-surface.test.ts
```

Expected: all pass, with the 40-column positive-viewport assertion executed.

- [ ] **Step 5: Commit the paint proof**

```powershell
git add src/ember/infrastructure/tools/ember-cli/src/components/prompt-input-paint.test.ts tools/ember-cli/src/components/prompt-input.ts
git commit -m "test(cli): prove prompt border resize paint"
```

### Task 4: Add a bounded compiled-binary ConPTY capture tool

**Files:**
- Create: `src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.ts`
- Create: `src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.test.ts`

**Interfaces:**
- Consumes: exact compiled binary path, output directory, node-pty, `@xterm/headless`, and current Git commit.
- Produces: `findClosedPromptRegion(frame: string[], width: number): { top: number; bottom: number; contentColumns: number }` and a content-addressed receipt.

- [ ] **Step 1: Write RED tests for receipt discrimination**

Test `findClosedPromptRegion` with:

```ts
const valid = [
  "â•­" + "â”€".repeat(38) + "â•®",
  "â”‚ â¯ hello" + " ".repeat(29) + "â”‚",
  "â”‚ STATUS" + " ".repeat(31) + "â”‚",
  "â•°" + "â”€".repeat(38) + "â•¯",
];
expect(findClosedPromptRegion(valid, 40).contentColumns).toBe(38);
expect(() => findClosedPromptRegion(valid.slice(0, -1), 40)).toThrow();
expect(() => findClosedPromptRegion(valid.map((line) => line.replace("â”‚", " ")), 40)).toThrow();
expect(() => findClosedPromptRegion(valid, 80)).toThrow();
```

Also test that receipt construction refuses a missing raw stage, missing frame
stage, zero narrow content width, binary hash mismatch, or stage dimension
other than 80/40/80.

- [ ] **Step 2: Run the capture-tool tests and witness RED**

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.test.ts
```

Expected: module/functions do not exist.

- [ ] **Step 3: Implement the smallest capture utility**

The script must:

1. Require `--binary` and `--out-dir`.
2. Hash the binary before launch and after capture; refuse drift.
3. Resolve `git rev-parse HEAD` and require a clean tracked tree.
4. Create a temporary empty `EMBER_HOME` and set `EMBER_GPU_FREE=1`.
5. Spawn the exact binary with node-pty at 80x24, collect every `onData`
   string as UTF-8 bytes, and feed the same strings into an xterm headless
   terminal.
6. Wait with a bounded timeout for a closed prompt region, save
   `stage-1-80.raw` and `stage-1-80.frame.txt`.
7. Call `pty.resize(40, 24)`, wait for the new closed region, and save
   `stage-2-40.raw` plus its frame.
8. Call `pty.resize(80, 24)`, repeat for stage 3, then terminate the owned PTY.
9. Write `receipt.json` last with source commit, binary hash, exact argv,
   `windows-conpty/node-pty`, dimensions, per-file SHA-256/byte counts, corner
   and edge results, and the narrow `contentColumns`.
10. Re-open and rehash every output before returning success.

No screenshot description, child-reported hash, or JSON boolean substitutes
for the raw stream and independently reconstructed frame.

- [ ] **Step 4: Run capture-tool tests**

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.test.ts
```

Expected: all discriminator tests pass.

- [ ] **Step 5: Commit the capture tool**

```powershell
git add src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.ts src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.test.ts
git commit -m "test(cli): add compiled prompt border capture"
```

### Task 5: Verify, build, capture, publish, and retire

**Files:**
- Create: `receipts/ember-cli/issue-243/live-resize-v1/receipt.json`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-1-80.raw`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-1-80.frame.txt`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-2-40.raw`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-2-40.frame.txt`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-3-80.raw`
- Create: `receipts/ember-cli/issue-243/live-resize-v1/stage-3-80.frame.txt`

**Interfaces:**
- Consumes: all prior commits and the repository build/guard commands.
- Produces: immutable branch head, public PR, public issue evidence, merge result, and lifecycle retirement.

- [ ] **Step 1: Run the focused and adjacent regression suites**

```powershell
bun test src/ember/infrastructure/tools/ember-cli/src/components/prompt-input.test.ts src/ember/infrastructure/tools/ember-cli/src/components/prompt-input-paint.test.ts src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.test.ts tools/ember-cli/src/screens/repl-operator-surface.test.ts tools/ember-cli/src/ink/border-rendering.test.ts tools/ember-cli/src/ink/app-resize.test.ts
```

Expected: all pass.

- [ ] **Step 2: Run repository guards and build from clean tracked bytes**

```powershell
python scripts/repo_guard.py --base origin/master
cd tools/ember-cli/src
bun run build
```

Expected: guard PASS and `ember.exe` produced with the exact commit banner.

- [ ] **Step 3: Capture the real compiled-binary resize receipt**

```powershell
bun run src/ember/infrastructure/tools/ember-cli/src/build-tools/capture-prompt-input-243.ts --binary tools/ember-cli/src/ember.exe --out-dir receipts/ember-cli/issue-243/live-resize-v1
```

Expected: receipt succeeds only after all three raw/frame stages and the
positive 40-column viewport are independently verified.

- [ ] **Step 4: Commit receipt bytes and rerun guards**

```powershell
git add receipts/ember-cli/issue-243/live-resize-v1
git commit -m "test(cli): receipt issue 243 live border resize"
python scripts/repo_guard.py --base origin/master
git diff --check origin/master..HEAD
```

Expected: clean checks and no absolute host path in tracked receipts.

- [ ] **Step 5: Publish through the safe wrappers**

Push the exact branch, open a PR whose body binds the base/head, focused test
counts, build hash, and receipt hashes, then wait for both public guard jobs.
Do not merge a moving head.

- [ ] **Step 6: Obtain independent acceptance and merge**

Route the immutable head and receipt to delegated authority for exact review.
Merge only after PASS, public green guards, and a clean exact-head replay.

- [ ] **Step 7: Attach evidence to issue #243 and close only after merge**

Comment on issue #243 with the merged commit, compiled binary SHA-256, links to
all three raw/frame artifacts, and the verified 80/40/80 dimensions. Close the
issue only when the public merged artifacts match the reviewed receipt.

- [ ] **Step 8: Retire the managed worktree**

Use:

```powershell
python $env:EMBER_REPO\scripts\worktree_lifecycle.py --repo $env:EMBER_REPO retire --path $env:EMBER_ISSUE243_WORKTREE
```

Expected: `RETIRED`, with the reconstructible branch/PR head preserved and no
new stale worktree.

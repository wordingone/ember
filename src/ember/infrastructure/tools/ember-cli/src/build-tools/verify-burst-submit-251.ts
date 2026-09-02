// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Observation-layer verification for #1068 / #251 (burst-safe Enter submission).
//
// The existing regression coverage (screens/repl-input-burst-race.test.ts) drives the real
// usePromptInput hook and ink's useInput/_deliverKeyEvent wiring directly -- it is a strong test,
// but it enters the chain at the diagnosis layer: it already assumes the harness decodes a
// synchronous multi-key burst the way the real terminal does. This driver instead drives the
// COMPILED binary through a real Windows ConPTY and writes the burst exactly as a terminal would,
// so the observation starts at the layer where the original bug was OBSERVED (a silently dropped
// chat turn), not at the layer where it was diagnosed.
//
// Three cases, each a fresh spawn of the same binary:
//   A. the bug's own shape -- one write() of "<text>\r" -- must submit (asserts the fix).
//   B. control -- text and \r as two separate write()s -- must also submit (this always worked;
//      proves the harness itself is not somehow universally blind to submission).
//   C. negative control -- text only, no \r at all -- must NOT submit (proves the assertion can
//      fail-closed: if the harness could never detect "no submission" this case would be a false
//      PASS masking a broken assertion).
//
// RUNTIME NOTE (load-bearing, do not "fix" by switching back to bun run): this script MUST be
// executed with `node --experimental-strip-types`, not `bun run`. Under Bun, node-pty's Windows
// ConPTY input path (a raw named-pipe fd wrapped as a net.Socket in windowsPtyAgent.js) throws an
// async, unhandled "Socket is closed" (ERR_SOCKET_CLOSED) shortly after every child.write() call,
// and the byte(s) never reach the child's stdin -- confirmed by direct comparison: the identical
// spawn+write sequence against the identical binary was run under both runtimes; under Bun all
// three cases showed zero effect (empty input row, no transcript row, in EVERY case including the
// split-write control that has never failed before); under plain Node the burst landed correctly
// (transcript row appeared, `frame.includes("PONG")` true). This is a Bun/node-pty compatibility
// gap in this environment, not a defect in the fix under test -- the existing capture-prompt-
// input-243.ts tool never calls child.write() at all, so this gap was never previously exercised.
// The `bun build --compile` step to produce the binary is unaffected (build-cockpit.ts's own
// build path is used, invoked here via child_process, not via the broken write path) and stays
// Bun-only since Bun is the only builder in this repo.

import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { basename, dirname, join, resolve } from "node:path";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { cockpitCompileArgs, cockpitWindowsMetadataArgs } from "./build-cockpit.ts";
import { headlessCaptureEnv } from "../services/headless-capture.ts";

const { Terminal } = xtermHeadless;

const COLUMNS = 100;
const ROWS = 30;
const MESSAGE = "Reply with exactly the single word: PONG";
const READY_TIMEOUT_MS = 15_000;
const OBSERVE_WINDOW_MS = 5_000;
const POLL_MS = 100;
// Machine-local kill-receipt ledger. Path comes from the environment so no operator-specific
// filesystem layout is baked into a tracked file; unset means receipts are skipped and the
// driver says so rather than silently writing nowhere.
const KILL_RECEIPTS_PATH = process.env.EMBER_KILL_RECEIPTS ?? "";

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function sha256(bytes: Uint8Array | Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function commandText(args: string[], cwd: string): string {
  const result = spawnSync(args[0]!, args.slice(1), { cwd, encoding: "utf8", windowsHide: true, shell: true });
  if (result.status !== 0) {
    throw new Error((result.stderr ?? "").trim() || `${args[0]} failed`);
  }
  return (result.stdout ?? "").trim();
}

// Resolve the REAL bun.exe path rather than relying on `spawnSync("bun", ..., { shell: true })`.
// Root-caused directly (byte-diffed two builds against each other): on Windows, shell:true routes
// through cmd.exe, which strips the literal `"` characters out of the `--banner` argument during
// its own re-quoting -- `globalThis.__EMBER_BUILD_COMMIT__="<sha>";` silently became
// `globalThis.__EMBER_BUILD_COMMIT__=<sha>;` (2 fewer bytes), shifting the entire embedded bundle
// and cascading into a multi-megabyte tail diff plus a PE checksum recompute. That was the ENTIRE
// explanation for the earlier "bun build --compile is not byte-reproducible" finding -- it is
// reproducible; the invocation just wasn't. Confirmed: invoking the resolved bun.exe directly
// (no shell) with an identical banner produced a byte-identical binary to a build done in a plain
// bash shell. `where bun` itself carries no quoted arguments, so shell:true is safe there.
function resolveBunExecutable(): string {
  const located = commandText(["where", "bun"], process.cwd())
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const exe = located.find((line) => line.toLowerCase().endsWith(".exe"));
  if (exe !== undefined) return exe;
  // `where bun` on this host surfaces an extension-less symlink/shim first (not directly
  // spawnable by Windows CreateProcess without a shell) and the .cmd shim second. The .cmd shim
  // (nvm-windows-for-Node style) is a thin wrapper that CALLs "%dp0%\node_modules\bun\bin\bun.exe"
  // -- derive that real .exe path from the shim's own directory rather than trying to spawn the
  // shim itself (which would reintroduce the exact shell/quoting problem this function exists to
  // avoid).
  const cmdShim = located.find((line) => line.toLowerCase().endsWith(".cmd"));
  if (cmdShim !== undefined) {
    const candidate = join(dirname(cmdShim), "node_modules", "bun", "bin", "bun.exe");
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(
    `cannot resolve a directly-spawnable bun.exe from \`where bun\` output: ${JSON.stringify(located)}`,
  );
}

// Copied from capture-prompt-input-243.ts's own region-detection convention (not imported --
// importing that file pulls in a bare `import { Terminal } from "@xterm/headless"`, which Node's
// ESM/CJS interop cannot resolve as a named export; see the default-import workaround above).
export interface ClosedPromptRegion {
  top: number;
  bottom: number;
  contentColumns: number;
}

function findClosedPromptRegion(frame: string[], width: number): ClosedPromptRegion {
  if (!Number.isInteger(width) || width < 2) throw new Error("terminal width is invalid");
  if (frame.length === 0 || frame.some((line) => line.length !== width)) {
    throw new Error("frame does not match terminal width");
  }
  for (let top = 0; top < frame.length; top++) {
    if (!frame[top]!.startsWith("╭")) continue;
    const right = frame[top]!.indexOf("╮", 1);
    if (right <= 1 || right >= width) continue;
    for (let bottom = top + 2; bottom < frame.length; bottom++) {
      if (frame[bottom]![0] !== "╰" || frame[bottom]![right] !== "╯") continue;
      const interior = frame.slice(top + 1, bottom);
      if (!interior.some((line) => line.includes("❯"))) continue;
      if (interior.length < 2) continue;
      if (!interior.every((line) => line[0] === "│" && line[right] === "│")) continue;
      return { top, bottom, contentColumns: right - 1 };
    }
  }
  throw new Error("closed prompt region not found");
}

interface HostPathRedaction {
  sourceSha256: string;
  replacement: string;
  occurrences: number;
}

function redactHostPaths(
  privateBytes: Uint8Array,
  hostPaths: string[],
): { publicBytes: Uint8Array; redactions: HostPathRedaction[] } {
  let text = Buffer.from(privateBytes).toString("utf8");
  const redactions: HostPathRedaction[] = [];
  const replacePath = (source: string): void => {
    const sourceBytes = Buffer.byteLength(source);
    const longToken = `{local-${sha256(Buffer.from(source, "utf8")).slice(0, 12)}}`;
    const base = sourceBytes >= Buffer.byteLength(longToken) ? longToken : "<p>";
    if (sourceBytes < Buffer.byteLength(base)) return;
    const replacement = base.padEnd(sourceBytes, "~");
    const occurrences = text.split(source).length - 1;
    if (occurrences > 0) {
      text = text.split(source).join(replacement);
      redactions.push({ sourceSha256: sha256(Buffer.from(source, "utf8")), replacement, occurrences });
    }
  };
  const uniquePaths = [...new Set(hostPaths)].sort((a, b) => b.length - a.length);
  for (const source of uniquePaths) replacePath(source);
  const residualPaths = [...new Set(text.match(/[A-Za-z]:[\\/][A-Za-z0-9_.~\\/()-]+/g) ?? [])].sort(
    (a, b) => b.length - a.length,
  );
  for (const source of residualPaths) replacePath(source);
  const publicBytes = Buffer.from(text, "utf8");
  return { publicBytes, redactions };
}

function writeKillReceipt(pid: number, matchRule: string, survivorsExpected: string): void {
  const row = {
    ts: new Date().toISOString(),
    script: "src/ember/infrastructure/tools/ember-cli/src/build-tools/verify-burst-submit-251.ts",
    pids: [pid],
    match_rule: matchRule,
    survivors_expected: survivorsExpected,
  };
  if (!KILL_RECEIPTS_PATH) {
    // No ledger configured. Say so loudly rather than appending to "" and losing the row --
    // a kill receipt that silently goes nowhere is worse than having no receipt discipline.
    console.error("[kill-receipt] EMBER_KILL_RECEIPTS unset; receipt NOT persisted:", JSON.stringify(row));
    return;
  }
  appendFileSync(KILL_RECEIPTS_PATH, `${JSON.stringify(row)}\n`, "utf8");
}

interface SpawnedCase {
  child: IPty;
  terminal: InstanceType<typeof Terminal>;
  home: string;
  rawChunks: string[];
}

function frameLines(terminal: InstanceType<typeof Terminal>): string[] {
  const start = terminal.buffer.active.viewportY;
  return Array.from({ length: terminal.rows }, (_, row) =>
    terminal.buffer.active.getLine(start + row)?.translateToString(false) ?? "",
  );
}

function spawnCase(binary: string, repoRoot: string): SpawnedCase {
  const home = mkdtempSync(join(tmpdir(), "ember-verify-251-"));
  const terminal = new Terminal({ cols: COLUMNS, rows: ROWS, allowProposedApi: true });
  const rawChunks: string[] = [];
  const child = spawnPty(binary, [], {
    name: "xterm-256color",
    cols: COLUMNS,
    rows: ROWS,
    cwd: repoRoot,
    env: {
      ...process.env,
      EMBER_HOME: home,
      EMBER_REPO_ROOT: repoRoot,
      EMBER_GPU_FREE: "1",
      EMBER_DISABLE_TERMINAL_TITLE: "1",
      ...headlessCaptureEnv(),
    },
  });
  child.onData((data) => {
    rawChunks.push(data);
    terminal.write(data);
  });
  return { child, terminal, home, rawChunks };
}

async function killCase(spawned: SpawnedCase, matchRule: string): Promise<void> {
  const pid = spawned.child.pid;
  writeKillReceipt(pid, matchRule, "none");
  spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  spawned.terminal.dispose();
  rmSync(spawned.home, { recursive: true, force: true });
}

async function waitForReady(spawned: SpawnedCase): Promise<void> {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  let lastError = "no terminal output";
  while (Date.now() < deadline) {
    if (spawned.rawChunks.length > 0) {
      const current = frameLines(spawned.terminal);
      try {
        findClosedPromptRegion(current, spawned.terminal.cols);
        return;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }
    await sleep(50);
  }
  throw new Error(`timed out waiting for closed prompt region: ${lastError}`);
}

interface PollFrame {
  atMs: number;
  lines: string[];
}

async function observeWindow(spawned: SpawnedCase, windowMs: number): Promise<PollFrame[]> {
  const frames: PollFrame[] = [];
  const start = Date.now();
  const deadline = start + windowMs;
  while (Date.now() < deadline) {
    frames.push({ atMs: Date.now() - start, lines: frameLines(spawned.terminal) });
    await sleep(POLL_MS);
  }
  frames.push({ atMs: Date.now() - start, lines: frameLines(spawned.terminal) });
  return frames;
}

// "Submitted" = a transcript row containing exactly "You" appears (the role label
// components/message-renderers.ts:348 renders before a user turn), AND the message text appears
// on some line that is NOT inside the currently-open input box interior (i.e. it left the input
// row and became a transcript line), in the SAME frame.
function transcriptShowsSubmission(lines: string[], message: string): boolean {
  let region: ClosedPromptRegion | null = null;
  try {
    region = findClosedPromptRegion(lines, lines[0]?.length ?? COLUMNS);
  } catch {
    region = null;
  }
  const insideBox = (index: number): boolean => region !== null && index > region.top && index < region.bottom;
  // The transcript's left pane sits beside a bordered right-hand dashboard panel; a raw terminal
  // row is full-width and carries that panel's "│" border + padding as trailing bytes on the SAME
  // line. Comparing the whole row against "You" always fails once the dashboard is visible -- take
  // only the content before the first "│" (the left-pane segment) before trimming/comparing.
  const leftPaneSegment = (line: string): string => (line.includes("│") ? line.slice(0, line.indexOf("│")) : line);
  const hasYouRow = lines.some((line, index) => !insideBox(index) && leftPaneSegment(line).trim() === "You");
  const hasMessageOutsideBox = lines.some(
    (line, index) => !insideBox(index) && leftPaneSegment(line).includes(message),
  );
  return hasYouRow && hasMessageOutsideBox;
}

// "Still pending in the input row" = the message text is visible ONLY inside the open input box
// interior, and no "You" transcript row exists anywhere.
function inputRowStillHoldsText(lines: string[], message: string): boolean {
  let region: ClosedPromptRegion;
  try {
    region = findClosedPromptRegion(lines, lines[0]?.length ?? COLUMNS);
  } catch {
    return false;
  }
  const interior = lines.slice(region.top + 1, region.bottom);
  const leftPaneSegment = (line: string): string => (line.includes("│") ? line.slice(0, line.indexOf("│")) : line);
  const hasYouRow = lines.some(
    (line, index) => (index <= region.top || index >= region.bottom) && leftPaneSegment(line).trim() === "You",
  );
  return !hasYouRow && interior.some((line) => line.includes(message));
}

interface CaseOutcome {
  name: string;
  expectSubmission: boolean;
  writesPerformed: { bytes: string; note: string }[];
  submissionObservedAtMs: number | null;
  finalFrameText: string;
  pass: boolean;
  detail: string;
}

async function runCase(
  name: string,
  expectSubmission: boolean,
  binary: string,
  repoRoot: string,
  perform: (spawned: SpawnedCase) => Promise<{ bytes: string; note: string }[]>,
): Promise<CaseOutcome> {
  const spawned = spawnCase(binary, repoRoot);
  try {
    await waitForReady(spawned);
    const writesPerformed = await perform(spawned);
    const frames = await observeWindow(spawned, OBSERVE_WINDOW_MS);

    let submissionObservedAtMs: number | null = null;
    for (const frame of frames) {
      if (transcriptShowsSubmission(frame.lines, MESSAGE)) {
        submissionObservedAtMs = frame.atMs;
        break;
      }
    }

    const finalLines = frames[frames.length - 1]!.lines;
    const finalFramePrivateText = `${finalLines.join("\n")}\n`;
    const { publicBytes } = redactHostPaths(Buffer.from(finalFramePrivateText, "utf8"), [binary, repoRoot]);
    const finalFrameText = Buffer.from(publicBytes).toString("utf8");

    let pass: boolean;
    let detail: string;
    if (expectSubmission) {
      pass = submissionObservedAtMs !== null;
      detail = pass
        ? `submission observed at +${submissionObservedAtMs}ms (transcript row "You" + message text outside the input box)`
        : `no submission observed within ${OBSERVE_WINDOW_MS}ms window`;
    } else {
      const stillPending = inputRowStillHoldsText(finalLines, MESSAGE);
      pass = submissionObservedAtMs === null && stillPending;
      if (!pass && submissionObservedAtMs !== null) {
        detail = `FAIL: unexpected submission observed at +${submissionObservedAtMs}ms (no Enter was ever written)`;
      } else if (!pass) {
        detail =
          "FAIL: no submission observed, but the typed text is also not visibly held in the input row -- assertion cannot distinguish this from a crash";
      } else {
        detail = "no submission observed, and the typed text remains visible in the open input row -- assertion fail-closed";
      }
    }

    return { name, expectSubmission, writesPerformed, submissionObservedAtMs, finalFrameText, pass, detail };
  } finally {
    await killCase(
      spawned,
      `ConPTY child spawned by verify-burst-submit-251.ts case "${name}"; sole child of this driver invocation`,
    );
  }
}

async function main(): Promise<void> {
  if (process.platform !== "win32") throw new Error("this verification requires Windows ConPTY");

  const args = new Map<string, string>();
  for (let index = 2; index < process.argv.length; index++) {
    const arg = process.argv[index]!;
    if (arg.startsWith("--")) {
      args.set(arg.slice(2), process.argv[index + 1] ?? "");
      index++;
    }
  }
  const binary = resolve(args.get("binary") ?? "");
  const outDir = resolve(args.get("out-dir") ?? "");
  const receiptPath = resolve(args.get("receipt-path") ?? "");
  if (binary === "" || outDir === "" || receiptPath === "") {
    throw new Error("--binary, --out-dir, and --receipt-path are required");
  }

  const repoRoot = commandText(["git", "rev-parse", "--show-toplevel"], process.cwd());
  const sourceCommit = commandText(["git", "rev-parse", "HEAD"], repoRoot);
  if (commandText(["git", "status", "--porcelain", "--untracked-files=no"], repoRoot) !== "") {
    throw new Error("tracked worktree must be clean before compiled verification");
  }

  const binarySha256Before = sha256(readFileSync(binary));

  // Independent rebuild via the repo's own Bun build path, invoked as a subprocess -- this uses
  // Bun as the BUILDER only (the same role it plays for every other build in this repo); the
  // ConPTY driving above stays entirely under this Node process, which is the part that needed
  // the runtime switch.
  const sourceRoot = join(repoRoot, "tools", "ember-cli", "src");
  const bunExecutable = resolveBunExecutable();
  const rebuildTemp = mkdtempSync(join(tmpdir(), "ember-verify-251-rebuild-"));
  const rebuiltBinary = join(rebuildTemp, "ember.exe");
  const bunResult = spawnSync(
    bunExecutable,
    cockpitCompileArgs(sourceCommit, rebuiltBinary),
    { cwd: sourceRoot, encoding: "utf8", windowsHide: true },
  );
  let rebuildBinarySha256: string;
  try {
    if (bunResult.status !== 0) {
      throw new Error(
        (bunResult.stderr ?? "").trim() ||
          `independent rebuild failed (status=${bunResult.status}, error=${bunResult.error?.message ?? "none"}, bunExecutable=${bunExecutable})`,
      );
    }
    rebuildBinarySha256 = sha256(readFileSync(rebuiltBinary));
  } finally {
    rmSync(rebuildTemp, { recursive: true, force: true });
  }
  const builderVersion = commandText(["bun", "--version"], sourceRoot);
  // `bun build --compile` IS byte-reproducible (same commit + same banner + same --outfile
  // basename => identical bytes, confirmed by three independent back-to-back builds). An earlier
  // version of this driver reported a false "not byte-reproducible" finding here -- that was a
  // bug in THIS driver, not in bun: invoking bun via `spawnSync(..., { shell: true })` routed
  // through cmd.exe, which silently stripped the `"` characters from the --banner argument,
  // shortening the embedded banner by 2 bytes and shifting the rest of the compiled bundle. Fixed
  // by resolving and invoking the real bun.exe directly (resolveBunExecutable(), no shell).
  const rebuildIsByteIdentical = rebuildBinarySha256 === binarySha256Before;
  if (!rebuildIsByteIdentical) {
    throw new Error(
      `independent rebuild sha256 ${rebuildBinarySha256} does not equal the binary under test ${binarySha256Before} -- this now IS a hard gate (see comment above); investigate before trusting the result`,
    );
  }

  mkdirSync(outDir, { recursive: true });
  mkdirSync(dirname(receiptPath), { recursive: true });

  const outcomes: CaseOutcome[] = [];

  outcomes.push(
    await runCase("A_single_burst_write_with_enter", true, binary, repoRoot, async (spawned) => {
      const bytes = `${MESSAGE}\r`;
      spawned.child.write(bytes);
      return [{ bytes: JSON.stringify(bytes), note: "single ptyProcess.write() call containing text + \\r" }];
    }),
  );

  outcomes.push(
    await runCase("B_split_write_text_then_enter", true, binary, repoRoot, async (spawned) => {
      spawned.child.write(MESSAGE);
      await sleep(600);
      spawned.child.write("\r");
      return [
        { bytes: JSON.stringify(MESSAGE), note: "first write() call, no \\r" },
        { bytes: JSON.stringify("\r"), note: "second write() call, 600ms later" },
      ];
    }),
  );

  outcomes.push(
    await runCase("C_text_only_no_enter", false, binary, repoRoot, async (spawned) => {
      spawned.child.write(MESSAGE);
      return [{ bytes: JSON.stringify(MESSAGE), note: "single write() call, no \\r anywhere" }];
    }),
  );

  const binarySha256After = sha256(readFileSync(binary));
  if (binarySha256After !== binarySha256Before) {
    throw new Error("binary changed during verification run");
  }
  const sourceCommitAfter = commandText(["git", "rev-parse", "HEAD"], repoRoot);
  if (sourceCommitAfter !== sourceCommit) {
    throw new Error("source commit changed during verification run");
  }

  for (const outcome of outcomes) {
    writeFileSync(join(outDir, `${outcome.name}.frame.txt`), outcome.finalFrameText, "utf8");
  }

  const receipt = {
    schema_version: "ember-cli-issue-251-burst-submit-verify/v1",
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    issue: 251,
    pr: 1068,
    evidence_class: "LIVE_COMPILED_BINARY_CONPTY",
    driver_runtime: "node --experimental-strip-types (see RUNTIME NOTE at top of driver source)",
    source_commit: sourceCommit,
    binary: {
      artifact: "tools/ember-cli/src/ember.exe (built to a scratch path, not checked in)",
      sha256: binarySha256Before,
      reproducible_rebuild: {
        source_commit: sourceCommit,
        sha256: rebuildBinarySha256,
        equals_captured_binary: rebuildIsByteIdentical,
        note: "byte-identical to the binary under test -- bun build --compile IS byte-reproducible here (same commit + same banner + same --outfile basename => identical bytes); this is a hard gate, not informational (see driver source comment above resolveBunExecutable's call site for the earlier false-negative and its root cause)",
      },
    },
    builder: {
      executable_basename: basename(bunExecutable),
      version: builderVersion,
      invocation: [
        basename(bunExecutable),
        "build",
        "./entrypoints/main.ts",
        "--compile",
        "--outfile",
        "<owned-temp>/ember.exe",
        "--banner",
        "<derived-from-source-commit>",
        ...cockpitWindowsMetadataArgs(),
      ],
    },
    transport: "windows-conpty/node-pty (driven from node, not bun -- see driver_runtime)",
    dimensions: { columns: COLUMNS, rows: ROWS },
    message: MESSAGE,
    cases: outcomes.map((outcome) => ({
      name: outcome.name,
      expect_submission: outcome.expectSubmission,
      writes: outcome.writesPerformed,
      submission_observed_at_ms: outcome.submissionObservedAtMs,
      final_frame_path: `tools/ember-cli/src/build-tools/verify-251-artifacts/${outcome.name}.frame.txt`,
      final_frame_sha256: sha256(Buffer.from(outcome.finalFrameText, "utf8")),
      pass: outcome.pass,
      detail: outcome.detail,
    })),
    claim_boundary: {
      derived: [
        "the compiled binary at source_commit, driven through a real ConPTY, submits a chat turn delivered as text+Enter in a single synchronous write() burst",
        "the same driver's assertion is fail-closed: it correctly reports no-submission when no Enter is ever written",
      ],
      not_proven: [
        "source_commit review acceptance",
        "the model actually replying (this driver never connects a model backend; the assertion is purely input-row-to-transcript-row)",
        "identical behavior under bun run (this driver requires node -- see driver_runtime and the RUNTIME NOTE)",
      ],
    },
    result: outcomes.every((outcome) => outcome.pass) ? "PASS" : "FAIL",
  };

  writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");

  for (const outcome of outcomes) {
    console.log(`[${outcome.pass ? "PASS" : "FAIL"}] ${outcome.name}: ${outcome.detail}`);
  }
  console.log(`receipt written to ${receiptPath}`);

  if (!outcomes.every((outcome) => outcome.pass)) {
    process.exitCode = 1;
  }
}

main()
  .catch((error) => {
    console.error(error instanceof Error ? (error.stack ?? error.message) : String(error));
    process.exitCode = 1;
  })
  .finally(() => {
    // node-pty's Windows agent holds fd-backed net.Socket handles (inSocket/outSocket) whose
    // lifecycle is not fully released by taskkill + terminal.dispose() alone -- observed directly:
    // this driver printed its full result set and the receipt path, then the process stayed alive
    // past a 110s wall-clock budget with zero remaining ember.exe/bun.exe processes (verified via
    // tasklist), i.e. the work was done but the event loop did not drain on its own. Force exit
    // once every case has reported and the receipt is on disk, rather than leaving a caller to
    // discover this by timing out.
    process.exit(process.exitCode ?? 0);
  });

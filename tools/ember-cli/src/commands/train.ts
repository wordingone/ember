// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/train.ts — /train: the phase-gated pre-training spine surface.
//
// HARD PRE-TRAINING GATE (load-bearing): the default command is preflight-only.
// Explicit `--execute` mode is available only with all three certificate paths,
// after the same cond7 launch-packet readiness preflight succeeds, and invokes only
// the fixed certified_train_launch.py consumer. The named run_vertical_slice.py
// command from launch_packet output is never executed as a command string. On any
// preflight, certificate-consumer, or response failure, execution fails closed.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";
import { publishActivityFeedInfrastructureFailure } from "../services/activity-feed.ts";
import { spawn, spawnSync } from "child_process";
import { existsSync, readFileSync } from "fs";
import { join } from "path";

// ---------------------------------------------------------------------------
// Preflight spawn seam (injectable for testing; mirrors model.ts's runner)
// ---------------------------------------------------------------------------

/** Result of running the launch-packet preflight subprocess. */
export interface LaunchPacketRunResult {
  /** Subprocess exit code; null means it never ran / crashed / timed out. */
  status: number | null;
  /** Captured stdout (JSONL preflight rows + a summary object + comment lines). */
  stdout: string;
}

/** A certified consumer that has crossed the only synchronous boundary the cockpit needs:
 * the OS accepted the child spawn.  Its terminal receipt remains owned by the certified
 * consumer and is surfaced by the existing receipt/activity watcher. */
export interface CertifiedLaunchHandle {
  kind: "background";
  pid: number;
  completion: Promise<LaunchPacketRunResult>;
}

export type CertifiedLaunchRunnerResult = LaunchPacketRunResult | CertifiedLaunchHandle;

export interface CertifiedLaunchFailure {
  pid: number;
  status: number | null;
  message: string;
}

export const PREFLIGHT_TIMEOUT_MS = 600_000;
// The certificate permits at most 15 minutes of training. Keep one minute for
// interpreter startup, final receipt emission, and orderly process exit.
export const CERTIFIED_LAUNCH_TIMEOUT_MS = 16 * 60_000;

function _runPythonProcess(
  executable: string,
  args: string[],
  timeout: number,
): LaunchPacketRunResult {
  try {
    const result = spawnSync(executable, args, {
      encoding: "utf8",
      windowsHide: true,
      timeout,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { status: result.status, stdout: result.stdout ?? "" };
  } catch {
    return { status: null, stdout: "" };
  }
}

function _runPythonProcessInBackground(
  executable: string,
  args: string[],
  timeout: number,
): Promise<CertifiedLaunchRunnerResult> {
  return new Promise((resolveStarted) => {
    let stdout = "";
    let settled = false;
    let startSettled = false;
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    let resolveCompletion!: (result: LaunchPacketRunResult) => void;
    const completion = new Promise<LaunchPacketRunResult>((resolve) => {
      resolveCompletion = resolve;
    });

    const finish = (result: LaunchPacketRunResult): void => {
      if (settled) return;
      settled = true;
      if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);
      resolveCompletion(result);
      if (!startSettled) {
        startSettled = true;
        resolveStarted(result);
      }
    };

    try {
      const child = spawn(executable, args, {
        windowsHide: true,
        stdio: ["ignore", "pipe", "ignore"],
      });
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", (chunk: string) => {
        stdout += chunk;
        if (Buffer.byteLength(stdout, "utf8") > 16 * 1024 * 1024) {
          child.kill();
          finish({ status: null, stdout: "" });
        }
      });
      const publishStarted = (): void => {
        if (startSettled) return;
        if (child.pid === undefined) return;
        startSettled = true;
        resolveStarted({
          kind: "background",
          pid: child.pid,
          completion,
        });
      };
      // Node and Bun both expose the owned child PID synchronously once the OS has accepted the
      // spawn. Bun does not consistently emit Node's optional `spawn` event, so publish from the
      // PID first and retain the event only as a compatibility fallback.
      publishStarted();
      child.once("spawn", publishStarted);
      child.once("error", () => finish({ status: null, stdout: "" }));
      child.once("close", (status) => finish({ status, stdout }));
      timeoutHandle = setTimeout(() => {
        child.kill();
        finish({ status: null, stdout: "" });
      }, timeout);
    } catch {
      finish({ status: null, stdout: "" });
    }
  });
}

/**
 * Real launch-packet runner: spawns `python launch_packet.py --config <cfg>`,
 * CPU-only, no GPU allocated (launch_packet.py itself allocates nothing). Any
 * spawn throw (ENOENT/timeout/crash) is caught and reported as status:null so
 * the command fails closed rather than propagating an uncaught rejection.
 *
 * @internal exported (prefixed _) so unit tests inject a mock and NO real
 *           subprocess ever runs.
 */
export function _defaultLaunchPacketRunner(
  executable: string,
  args: string[],
): LaunchPacketRunResult {
  // The clean-genesis + recovery preflights instantiate a tiny CPU model and
  // round-trip a checkpoint, so allow generous headroom; still CPU-only.
  return _runPythonProcess(executable, args, PREFLIGHT_TIMEOUT_MS);
}

/** Fixed certified-consumer runner with headroom above the 15-minute canary. */
export function _defaultCertifiedLaunchRunner(
  executable: string,
  args: string[],
): Promise<CertifiedLaunchRunnerResult> {
  return _runPythonProcessInBackground(executable, args, CERTIFIED_LAUNCH_TIMEOUT_MS);
}

// ---------------------------------------------------------------------------
// Output parsing (fail-closed)
// ---------------------------------------------------------------------------

interface PreflightRow {
  record?: unknown;
  name?: unknown;
  status?: unknown;
  reason?: unknown;
}

interface LaunchPacketSummary {
  record?: unknown;
  overall_ready?: unknown;
  named_ember02_command?: unknown;
}

interface ParsedLaunchPacketOutput {
  /** Every parseable JSON object line (preflight rows + summary). */
  rows: Record<string, unknown>[];
  /** The single `record: "launch-packet-summary"` object, if present. */
  summary: LaunchPacketSummary | null;
}

/**
 * Parse launch_packet.py's stdout. It prints one JSON object per line (each
 * preflight row, then a `launch-packet-summary` object) plus `# ...` comment
 * lines. Non-JSON / comment lines are skipped. Returns whatever parsed, plus
 * the summary object located by its `record` tag. Never throws.
 */
function _parseLaunchPacketOutput(stdout: string): ParsedLaunchPacketOutput {
  const rows: Record<string, unknown>[] = [];
  let summary: LaunchPacketSummary | null = null;
  for (const line of stdout.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("{")) continue;
    let obj: unknown;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (typeof obj !== "object" || obj === null) continue;
    const record = obj as Record<string, unknown>;
    rows.push(record);
    if (record["record"] === "launch-packet-summary") {
      summary = record as LaunchPacketSummary;
    }
  }
  return { rows, summary };
}

/** Collect human-readable reasons from any failing preflight rows. */
function _failureReasons(rows: Record<string, unknown>[]): string[] {
  const reasons: string[] = [];
  for (const row of rows) {
    if (row["record"] === "preflight" && row["status"] === "fail") {
      const name = typeof row["name"] === "string" ? row["name"] : "(unnamed)";
      const reason = typeof row["reason"] === "string" ? row["reason"] : "no reason given";
      reasons.push(`  - ${name}: ${reason}`);
    }
  }
  return reasons;
}

/**
 * Extract the validated launch command string from a summary object, or null.
 * FAIL-CLOSED: only returns a command when overall_ready === true AND
 * named_ember02_command.command is a non-empty string.
 */
function _extractLaunchCommand(
  summary: LaunchPacketSummary | null,
): { command: string; note: string | null; entrypoint: string | null } | null {
  if (summary === null) return null;
  if (summary.overall_ready !== true) return null;
  const named = summary.named_ember02_command;
  if (typeof named !== "object" || named === null) return null;
  const namedRec = named as Record<string, unknown>;
  const command = namedRec["command"];
  if (typeof command !== "string" || command.trim() === "") return null;
  const note = typeof namedRec["note"] === "string" ? namedRec["note"] : null;
  const entrypoint =
    typeof namedRec["library_entrypoint"] === "string" ? namedRec["library_entrypoint"] : null;
  return { command, note, entrypoint };
}

// ---------------------------------------------------------------------------
// Path defaults
// ---------------------------------------------------------------------------

/** Default ember repo root, re-derived read-only the same way sibling commands do. */
function _defaultRepoRoot(cwd: string): string {
  return resolveEmberSourceRootOrCwd({ startDir: cwd }, "[ember] /train");
}

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface TrainCommandDeps {
  /**
   * The launch-packet preflight runner. Tests inject a mock so NO real
   * subprocess (and therefore no torch/CPU work, and never any GPU/training
   * launch) is ever invoked. Defaults to _defaultLaunchPacketRunner.
   */
  runLaunchPacket?: (executable: string, args: string[]) => LaunchPacketRunResult;
  /** Certified B7 consumer with a timeout separate from the CPU preflight. */
  runCertifiedLaunch?: (
    executable: string,
    args: string[],
  ) => CertifiedLaunchRunnerResult | Promise<CertifiedLaunchRunnerResult>;
  /** Existing cockpit monitor-owned surface for receipt-less child failures. */
  reportCertifiedLaunchFailure?: (failure: CertifiedLaunchFailure) => void;
  /** Python executable; defaults to EMBER_PYTHON_BIN env, else "python". */
  pythonBin?: string;
  /** Ember repo root override; defaults to _defaultRepoRoot(ctx.cwd). */
  repoRoot?: string;
  /** Config path override; defaults to <repoRoot>/configs/ember-restart-3b.json. */
  configPath?: string;
  /** launch_packet.py path override; defaults to <repoRoot>/tools/ember-restart-3b/launch_packet.py. */
  scriptPath?: string;
  /** certified_train_launch.py path override. */
  certifiedLaunchScriptPath?: string;
  /** Canonical launch-authority certificate path override; defaults to
   *  <repoRoot>/receipts/ember-02-launch-authority/certificate.json. */
  certificatePath?: string;
  /** Canonical launch-authority declaration-ledger path override; defaults to
   *  <repoRoot>/receipts/ember-02-launch-authority/declaration-ledger.jsonl. */
  declarationLedgerPath?: string;
  /** Canonical launch-authority run-spec path override; defaults to
   *  <repoRoot>/receipts/ember-02-launch-authority/run-spec.json. */
  runSpecPath?: string;
}

// ---------------------------------------------------------------------------
// Canonical launch-authority artifact resolution (offer/confirm default path)
// ---------------------------------------------------------------------------

interface CanonicalArtifactPaths {
  certificate: string;
  declarationLedger: string;
  runSpec: string;
}

function _canonicalArtifactPaths(
  repoRoot: string,
  deps: TrainCommandDeps,
): CanonicalArtifactPaths {
  const base = join(repoRoot, "receipts", "ember-02-launch-authority");
  return {
    certificate: deps.certificatePath ?? join(base, "certificate.json"),
    declarationLedger: deps.declarationLedgerPath ?? join(base, "declaration-ledger.jsonl"),
    runSpec: deps.runSpecPath ?? join(base, "run-spec.json"),
  };
}

interface ResolvedArtifact {
  path: string;
  status: "ok" | "missing" | "invalid";
  reason?: string;
}

/**
 * Existence + parseability check for one launch-authority artifact. This is deliberately
 * shallow -- the certified consumer (certified_train_launch.py) performs the deep schema
 * and scope validation; this check only answers "is there something here worth offering",
 * per SPEC-train-launch-operability-v1.md's acceptance map (S4: existence is not validity,
 * so an empty or unparseable file at a resolved path still fails closed).
 */
function _resolveArtifact(path: string, kind: "json" | "jsonl"): ResolvedArtifact {
  if (!existsSync(path)) {
    return { path, status: "missing" };
  }
  let content: string;
  try {
    content = readFileSync(path, "utf8");
  } catch {
    return { path, status: "missing", reason: "unreadable" };
  }
  if (content.trim() === "") {
    return { path, status: "invalid", reason: "empty file" };
  }
  if (kind === "json") {
    try {
      JSON.parse(content);
    } catch {
      return { path, status: "invalid", reason: "unparseable JSON" };
    }
    return { path, status: "ok" };
  }
  const lines = content.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length === 0) {
    return { path, status: "invalid", reason: "empty file" };
  }
  for (const line of lines) {
    try {
      JSON.parse(line);
    } catch {
      return { path, status: "invalid", reason: "unparseable JSONL line" };
    }
  }
  return { path, status: "ok" };
}

function _artifactFailureLine(label: string, artifact: ResolvedArtifact): string {
  if (artifact.status === "missing") {
    return `  - ${label}: absent at ${artifact.path}`;
  }
  return `  - ${label}: ${artifact.reason ?? "invalid"} at ${artifact.path}`;
}

// ---------------------------------------------------------------------------
// Offer/confirm state (offer/confirm, panel's own idiom -- core/encounter-membrane.ts's
// shape, reused rather than reinvented per SPEC-train-launch-operability-v1.md's kill
// criterion).
//
// MODULE-scoped, deliberately, not per-instance (found fadv-review 2026-07-26, O5/O6):
// command-registry.ts's getCommands(cwd) memoizes createTrainCommand() per cwd, but
// components/spine-panel.ts:695/698 builds `deps.trainCommand ?? createTrainCommand()`
// fresh inside the thunk it calls on every drive(), with no injected dep on that path --
// so an offer minted through one instance was unfindable by a confirm routed through the
// next instance, on the operator panel itself. Hoisting the store here makes offers
// discoverable across those command instances. Every entry is separately bound to the
// CommandContext.sessionId that minted it, so module scope never becomes cross-session
// authority. Offer ids likewise carry a module-level counter PLUS a time+random component
// (not just an instance-local counter) so two instances minting in the same tick can never
// collide.
// ---------------------------------------------------------------------------

interface TrainOffer {
  offerId: string;
  ts: string;
  sessionId: string;
  certificate: string;
  declarationLedger: string;
  runSpec: string;
}

const trainOffers = new Map<string, TrainOffer>();
/** Session ids whose first /train preflight has already been attempted. */
const trainPreflightSessions = new Set<string>();
let trainOfferCounter = 0;

/**
 * The newest outstanding offer minted by `sessionId`, if any (#1475: the cockpit's START control
 * reads this to render its confirm stage and to build the exact `/train confirm <id>` text the
 * offer surfaced). READ-ONLY by construction: the returned id can only be SPENT by dispatching
 * "/train confirm <id>" back through this command, where every membrane check (single-use,
 * session-binding, fail-closed) still runs. Map insertion order is mint order, so the last
 * matching entry is the newest offer.
 */
export function outstandingTrainOfferForSession(
  sessionId: string,
): { offerId: string; ts: string; runSpec: string } | undefined {
  let newest: TrainOffer | undefined;
  for (const offer of trainOffers.values()) {
    if (offer.sessionId === sessionId) newest = offer;
  }
  return newest ? { offerId: newest.offerId, ts: newest.ts, runSpec: newest.runSpec } : undefined;
}

function _mintOfferId(): string {
  trainOfferCounter += 1;
  const entropy = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  return `train-${trainOfferCounter}-${entropy}`;
}

interface TrainArgs {
  execute: boolean;
  certificate?: string;
  declarationLedger?: string;
  runSpec?: string;
}

function _parseTrainArgs(raw: string): TrainArgs {
  const tokens = raw.trim() === "" ? [] : raw.trim().split(/\s+/);
  const parsed: TrainArgs = { execute: false };
  const seen = new Set<string>();
  const valued = new Map<string, "certificate" | "declarationLedger" | "runSpec">([
    ["--certificate", "certificate"],
    ["--declaration-ledger", "declarationLedger"],
    ["--run-spec", "runSpec"],
  ]);
  for (let index = 0; index < tokens.length; index += 1) {
    const option = tokens[index]!;
    if (seen.has(option)) {
      throw new Error(`duplicate train option: ${option}`);
    }
    seen.add(option);
    if (option === "--execute") {
      parsed.execute = true;
      continue;
    }
    const field = valued.get(option);
    if (field === undefined) {
      throw new Error(`unknown train option: ${option}`);
    }
    const value = tokens[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`missing value for ${option}`);
    }
    parsed[field] = value;
    index += 1;
  }
  if (
    !parsed.execute &&
    (parsed.certificate !== undefined ||
      parsed.declarationLedger !== undefined ||
      parsed.runSpec !== undefined)
  ) {
    throw new Error("authority paths require --execute");
  }
  if (
    parsed.execute &&
    (parsed.certificate === undefined ||
      parsed.declarationLedger === undefined ||
      parsed.runSpec === undefined)
  ) {
    throw new Error(
      "usage: /train --execute --certificate <path> --declaration-ledger <path> --run-spec <path>",
    );
  }
  return parsed;
}

// ---------------------------------------------------------------------------
// Certified-consumer result interpretation (shared by --execute and confirm)
// ---------------------------------------------------------------------------

/**
 * Interprets a certified_train_launch.py run result into a CommandResult. Shared by both
 * paths that may invoke the fixed consumer -- explicit `--execute` and `confirm <id>` --
 * so the two paths can never drift into different response handling.
 */
function _interpretCertifiedResult(
  certifiedResult: LaunchPacketRunResult,
): { type: "message"; message: string; exitCode?: number } {
  if (certifiedResult.status !== 0) {
    const detail = certifiedResult.stdout.trim();
    return {
      type: "message" as const,
      message: [
        "error: certified train consumer refused or failed.",
        detail || "No certified execution receipt was produced.",
      ].join("\n"),
      exitCode: certifiedResult.status ?? 1,
    };
  }
  let execution: Record<string, unknown>;
  try {
    // Defense in depth (issue #1408): the consumer redirects its child's
    // stdout away from its own, so this should already be a single pure
    // JSON line -- but parse only the LAST non-empty line rather than the
    // whole stream, so a fixed runner that still leaks noise ahead of the
    // handshake (or a future consumer regression) does not corrupt the
    // cockpit's ability to register a successful certified launch.
    const lines = certifiedResult.stdout.split(/\r?\n/).filter((line) => line.trim() !== "");
    const lastLine = lines.length > 0 ? lines[lines.length - 1] : certifiedResult.stdout;
    const parsedResult: unknown = JSON.parse(lastLine);
    if (typeof parsedResult !== "object" || parsedResult === null) {
      throw new Error("not an object");
    }
    execution = parsedResult as Record<string, unknown>;
  } catch {
    return {
      type: "message" as const,
      message: "error: certified train consumer exited 0 without a valid execution receipt response.",
      exitCode: 1,
    };
  }
  const executionReceipt = execution["execution_receipt"];
  const artifactRoot = execution["artifact_root"];
  if (
    typeof executionReceipt !== "string" ||
    executionReceipt === "" ||
    typeof artifactRoot !== "string" ||
    artifactRoot === ""
  ) {
    return {
      type: "message" as const,
      message: "error: certified train consumer response omitted execution_receipt or artifact_root.",
      exitCode: 1,
    };
  }
  return {
    type: "message" as const,
    message: [
      "certified bounded canary process completed.",
      `execution receipt: ${executionReceipt}`,
      `artifact root: ${artifactRoot}`,
    ].join("\n"),
  };
}

function _isCertifiedLaunchHandle(
  value: CertifiedLaunchRunnerResult,
): value is CertifiedLaunchHandle {
  return "kind" in value && value.kind === "background";
}

/** Return control to the cockpit at spawn, never at child exit.  The certified consumer remains
 * the sole terminal receipt authority; the existing activity watcher renders that receipt when
 * it lands.  Keeping a rejection handler attached prevents a background failure from becoming an
 * unhandled promise without fabricating a second completion surface. */
function _interpretCertifiedDispatch(
  result: CertifiedLaunchRunnerResult,
  reportFailure: (failure: CertifiedLaunchFailure) => void,
): { type: "message"; message: string; exitCode?: number } {
  if (!_isCertifiedLaunchHandle(result)) return _interpretCertifiedResult(result);
  void result.completion.then(
    (terminal) => {
      const interpreted = _interpretCertifiedResult(terminal);
      if (interpreted.exitCode === undefined) return;
      reportFailure({ pid: result.pid, status: terminal.status, message: interpreted.message });
    },
    () => {
      reportFailure({
        pid: result.pid,
        status: null,
        message: "error: certified train consumer completion monitor failed before a terminal execution receipt was observed.",
      });
    },
  );
  return {
    type: "message" as const,
    message: [
      "certified train consumer started in background.",
      `child pid: ${result.pid}`,
      "terminal execution receipt will appear in the activity feed.",
    ].join("\n"),
  };
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Creates the /train command. Registered in command-registry.ts as "train".
 *
 * Behavior (SPEC-train-launch-operability-v1.md):
 *  1. Spawn the cond7 launch-packet preflight FIRST (never training).
 *  2. Without `--execute` and without a `confirm` subcommand: on a green preflight,
 *     resolve the three canonical launch-authority artifacts and, if all three are
 *     present and valid, mint a single-use OFFER through the panel's own confirm-only
 *     idiom (core/encounter-membrane.ts's shape, reused rather than reinvented). No
 *     command string is handed to the operator to paste.
 *  3. `/train confirm <id>` invokes exactly the same fixed certified_train_launch.py consumer
 *     `--execute` invokes, with the paths resolved at offer time -- only for an id
 *     minted by a green preflight earlier in this session.
 *  4. With `--execute` and all three certificate paths, invoke exactly one fixed
 *     certified_train_launch.py consumer with the EXPLICIT paths; canonical resolution
 *     is never consulted on this path. Never execute the named command string.
 *  5. Any malformed input, nonzero exit, or invalid response fails closed.
 */
export function createTrainCommand(deps: TrainCommandDeps = {}): RegistryCommand {
  const runLaunchPacket = deps.runLaunchPacket ?? _defaultLaunchPacketRunner;
  const runCertifiedLaunch =
    deps.runCertifiedLaunch ?? _defaultCertifiedLaunchRunner;
  const reportCertifiedLaunchFailure =
    deps.reportCertifiedLaunchFailure ?? ((failure: CertifiedLaunchFailure) => {
      publishActivityFeedInfrastructureFailure(
        `${failure.message} child pid=${failure.pid}; exit=${failure.status ?? "null"}`,
      );
    });

  // Offer state is module-scoped (trainOffers, above) -- deliberately NOT redeclared
  // here -- so it is single and session-scoped regardless of how many
  // createTrainCommand() instances a caller constructs (registry vs spine-panel; see the
  // comment on trainOffers above).

  return {
    name: "train",
    description: "Preflight EMBER-02 training readiness; execute only through an explicit declared B7 certificate",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, ctx: CommandContext) {
      const trimmed = args.trim();

      // "/train confirm <id>" routes here as the train command's bare-token subcommand, not a
      // --flag invocation -- handled entirely separately, before the flag parser and
      // before any preflight (O3: confirm invokes the consumer only for an id minted by
      // a green preflight already recorded in this session; it never re-runs the
      // preflight itself, since the offer was only minted after one already ran green).
      if (trimmed === "confirm" || trimmed.startsWith("confirm ")) {
        const parts = trimmed.split(/\s+/).filter((p) => p.length > 0);
        const suppliedId = parts.length === 2 ? parts[1] : undefined;
        if (!suppliedId) {
          // S3: malformed or absent id -> no action.
          return {
            type: "message" as const,
            message:
              'error: "/train confirm" requires exactly one offer id -- usage: /train confirm <id>. No action taken.',
            exitCode: 1,
          };
        }
        const offer = trainOffers.get(suppliedId);
        if (!offer) {
          // S1 (no prior /train this session) and S2 (id already spent) both land here:
          // the map has no entry, so no consumer invocation is possible either way.
          return {
            type: "message" as const,
            message: `error: no outstanding train-launch offer for "${suppliedId}" -- nothing to confirm, never auto-acted. Run /train again to mint a fresh offer.`,
            exitCode: 1,
          };
        }
        if (offer.sessionId !== ctx.sessionId) {
          // Do not delete the offer: a foreign session cannot confirm or spend authority
          // that remains valid only for the exact session that minted it.
          return {
            type: "message" as const,
            message: `error: train-launch offer "${suppliedId}" is not valid for this session -- nothing was confirmed or spent.`,
            exitCode: 1,
          };
        }
        // Single-use: remove BEFORE invoking, so a throw/failure in the consumer never
        // leaves a reusable offer behind (C7) and a second confirm for the same id is
        // always the S1/S2 unknown-offer path, regardless of outcome.
        trainOffers.delete(suppliedId);

        const repoRoot = deps.repoRoot ?? _defaultRepoRoot(ctx.cwd);
        const pythonBin = deps.pythonBin ?? process.env["EMBER_PYTHON_BIN"] ?? "python";
        const certifiedLaunchScriptPath =
          deps.certifiedLaunchScriptPath ??
          join(repoRoot, "tools", "ember-restart-3b", "certified_train_launch.py");

        let certifiedResult: CertifiedLaunchRunnerResult;
        try {
          certifiedResult = await runCertifiedLaunch(pythonBin, [
            certifiedLaunchScriptPath,
            "--root",
            repoRoot,
            "--certificate",
            offer.certificate,
            "--declaration-ledger",
            offer.declarationLedger,
            "--run-spec",
            offer.runSpec,
          ]);
        } catch {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer could not be started; no training process was authorized.",
            exitCode: 1,
          };
        }
        return _interpretCertifiedDispatch(certifiedResult, reportCertifiedLaunchFailure);
      }

      let trainArgs: TrainArgs;
      try {
        trainArgs = _parseTrainArgs(trimmed);
      } catch (error) {
        return {
          type: "message" as const,
          message: `error: ${error instanceof Error ? error.message : "invalid /train arguments"}`,
          exitCode: 1,
        };
      }

      const repoRoot = deps.repoRoot ?? _defaultRepoRoot(ctx.cwd);
      const pythonBin = deps.pythonBin ?? process.env["EMBER_PYTHON_BIN"] ?? "python";
      const configPath =
        deps.configPath ?? join(repoRoot, "configs", "ember-restart-3b.json");
      const scriptPath =
        deps.scriptPath ?? join(repoRoot, "tools", "ember-restart-3b", "launch_packet.py");
      const certifiedLaunchScriptPath =
        deps.certifiedLaunchScriptPath ??
        join(
          repoRoot,
          "tools",
          "ember-restart-3b",
          "certified_train_launch.py",
        );

      // (1) Run the preflight first. It is the only subprocess in default mode;
      // certified execute mode may invoke only the fixed consumer below.
      const firstPreflightForSession = !trainPreflightSessions.has(ctx.sessionId);
      const preflightAttempts: Array<number | null> = [];
      let result: LaunchPacketRunResult;
      try {
        result = runLaunchPacket(pythonBin, [scriptPath, "--config", configPath]);
      } catch {
        // A runner that throws (crash/ENOENT/timeout raised as an exception)
        // fails closed rather than crashing the command.
        return {
          type: "message" as const,
          message:
            "error: launch-packet preflight could not be started -- training is BLOCKED (fail-closed). No launch command surfaced.",
          exitCode: 1,
        };
      }

      preflightAttempts.push(result.status);

      // A relaunch can transiently return no process status before the runner is
      // ready. Attribute exactly one retry to the same session and exact argv;
      // every other failure remains fail-closed with no retry.
      let retryNotice: string | null = null;
      if (firstPreflightForSession && !trainArgs.execute && result.status === null) {
        // Consume the per-session retry budget only when this command actually
        // takes the one permitted null-status retry. Green/nonzero/throw paths
        // remain eligible for a later first null observation.
        trainPreflightSessions.add(ctx.sessionId);
        try {
          result = runLaunchPacket(pythonBin, [scriptPath, "--config", configPath]);
        } catch {
          result = { status: null, stdout: "" };
        }
        preflightAttempts.push(result.status);
        retryNotice =
          "launch-packet: first attempt returned status=null; one attributed retry used the identical executable and argv.";
      }

      const parsed = _parseLaunchPacketOutput(result.stdout);

      // (4) Nonzero exit => a preflight failed OR config missing/malformed
      // (launch_packet.py raises on a missing/unreadable config, exiting
      // nonzero). Fail closed with whatever reasons we could parse.
      if (result.status !== 0) {
        const reasons = _failureReasons(parsed.rows);
        const lines = [
          "error: launch-packet preflight FAILED -- EMBER-02 training is BLOCKED (fail-closed).",
        ];
        if (reasons.length > 0) {
          lines.push("failing preflights:");
          lines.push(...reasons);
        } else {
          lines.push(
            `  (no parseable preflight rows; launch_packet exit=${result.status ?? "null"} -- config missing/malformed or the runner never produced output)`,
          );
        }
        if (retryNotice !== null) lines.splice(1, 0, retryNotice);
        if (preflightAttempts.length > 1) {
          lines.push("preflight attempts:");
          preflightAttempts.forEach((status, index) => {
            lines.push(`  attempt ${index + 1}: launch_packet exit=${status ?? "null"}`);
          });
        }
        lines.push("No launch command surfaced.");
        return {
          type: "message" as const,
          message: lines.join("\n"),
          exitCode: 1,
        };
      }

      // (2) Exit 0: parse the summary and extract the VALIDATED launch command.
      // Fail closed if the summary is missing/unparseable, not overall_ready,
      // or carries no command string (defensive -- exit 0 should imply all of
      // these hold, but never surface a command we could not validate).
      const extracted = _extractLaunchCommand(parsed.summary);
      if (extracted === null) {
        const retryLine = retryNotice === null ? "" : `${retryNotice}\n`;
        return {
          type: "message" as const,
          message:
            `${retryLine}error: launch-packet exited 0 but its readiness summary was missing/unparseable or named no launch command -- training is BLOCKED (fail-closed). No launch command surfaced.`,
          exitCode: 1,
        };
      }

      if (trainArgs.execute) {
        // Explicit flags always beat canonical resolution (C8): the canonical
        // launch-authority tree under repoRoot is never consulted on this path.
        let certifiedResult: CertifiedLaunchRunnerResult;
        try {
          certifiedResult = await runCertifiedLaunch(pythonBin, [
            certifiedLaunchScriptPath,
            "--root",
            repoRoot,
            "--certificate",
            trainArgs.certificate!,
            "--declaration-ledger",
            trainArgs.declarationLedger!,
            "--run-spec",
            trainArgs.runSpec!,
          ]);
        } catch {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer could not be started; no training process was authorized.",
            exitCode: 1,
          };
        }
        return _interpretCertifiedDispatch(certifiedResult, reportCertifiedLaunchFailure);
      }

      // Default mode (no --execute, extracted command validated above but no longer
      // surfaced as text -- see extracted.command's non-use below): resolve the
      // canonical launch-authority artifacts and offer the launch through the panel's
      // confirm-only membrane rather than handing the operator a command to paste.
      const canonical = _canonicalArtifactPaths(repoRoot, deps);
      const resolvedCertificate = _resolveArtifact(canonical.certificate, "json");
      const resolvedLedger = _resolveArtifact(canonical.declarationLedger, "jsonl");
      const resolvedRunSpec = _resolveArtifact(canonical.runSpec, "json");

      const failures: string[] = [];
      if (resolvedCertificate.status !== "ok") {
        failures.push(_artifactFailureLine("certificate", resolvedCertificate));
      }
      if (resolvedLedger.status !== "ok") {
        failures.push(_artifactFailureLine("declaration ledger", resolvedLedger));
      }
      if (resolvedRunSpec.status !== "ok") {
        failures.push(_artifactFailureLine("run spec", resolvedRunSpec));
      }
      if (failures.length > 0) {
        return {
          type: "message" as const,
          message: [
            "launch-packet: all preflights GREEN, but the launch-authority artifacts are not all present and valid -- training is BLOCKED (fail-closed).",
            "missing/invalid prerequisites:",
            ...failures,
            "No offer minted.",
          ].join("\n"),
          exitCode: 1,
        };
      }

      const offerId = _mintOfferId();
      trainOffers.set(offerId, {
        offerId,
        ts: new Date().toISOString(),
        sessionId: ctx.sessionId,
        certificate: canonical.certificate,
        declarationLedger: canonical.declarationLedger,
        runSpec: canonical.runSpec,
      });
      return {
        type: "message" as const,
        message: [
          ...(retryNotice === null ? [] : [retryNotice]),
          "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
          "launch-authority artifacts resolved:",
          `  certificate: ${canonical.certificate}`,
          `  declaration ledger: ${canonical.declarationLedger}`,
          `  run spec: ${canonical.runSpec}`,
          "",
          `OFFER ${offerId} action=train-launch -- type "/train confirm ${offerId}" to proceed. Declining, a typo, or anything else takes no action; the confirm-only membrane never silently steers.`,
        ].join("\n"),
      };
    },
  };
}

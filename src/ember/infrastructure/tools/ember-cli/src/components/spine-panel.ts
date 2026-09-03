// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/spine-panel.ts — /spine (alias /b55) operator spine panel (EMBER-01 T2.1,
// ember01plan §B5.5 L1183-1193).
//
// EXTENDS the existing surface -- no new backend logic, no duplicated seat/custody/
// benchmark/launch-packet/claim resolution. Every element reads through an injectable
// dep that DEFAULTS to the SAME production read the sibling command already uses:
//   element 1 authority          -> commands/benchmark.ts's _loadBenchmarkRegistry,
//                                    reading manifests/ember-01-custody/benchmark-
//                                    registry.json's `authority` block.
//   element 2 checkpoint + seat  -> commands/custody.ts's _defaultGetModelSeatDecision
//                                    + renderCustodyStatus (the exact /custody status
//                                    derivation, zero reimplementation).
//   element 3 custody-leg state  -> manifests/ember-01-custody/root-spec.json's
//                                    declared roots, cross-referenced against
//                                    services/custody-bindings.ts's readRootBindingsStore
//                                    (root-bindings.json in the external cockpit
//                                    state root, utils/ember-state-root.ts).
//   element 4 launch-packet      -> the newest receipts/ember-01-launch-packet/<ts>/
//                                    packet.jsonl the real launch_packet.py preflight
//                                    writes (src/ember/infrastructure/tools/ember-restart-3b/launch_packet.py);
//                                    read-only here -- driving re-runs the real /train
//                                    command via driveSpineElement, never a duplicated
//                                    subprocess spawn.
//   element 5 benchmark registry -> the SAME benchmark-registry.json, exact
//                                    execution_status per row (never a guessed count).
//   element 6 failure-class      -> the C0 ledger path T2.2 owns (see C0_LEDGER_REL
//                                    below); absent until T2.2 lands, per spec.
//   element 7 claim scope        -> core/ember-world-state.ts's buildEmberWorldState,
//                                    gated on EMBER_GOALFORGE_ROOT exactly like
//                                    commands/world-state.ts's /cockpit.
//
// Honesty rule (L1653): OFFLINE is shown ONLY for a genuinely-offline element (the
// owned seat pre-birth -- element 2's existing OFFLINE case, inherited unchanged from
// custody.ts). Every other element that cannot currently resolve renders an explicit
// "BLOCKED: <reason>" line instead of a silently-empty or hardcoded-looking value --
// a hardcoded literal here can never react to a mutated/absent real source, which is
// exactly what spine-panel.test.ts's per-element mutation/absence tests assert.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";
import {
  _loadBenchmarkRegistry,
  createBenchmarkCommand,
} from "../commands/benchmark.ts";
import {
  _defaultGetModelSeatDecision,
  createCustodyCommand,
  renderCustodyStatus,
  renderRootBindings,
} from "../commands/custody.ts";
import { createTrainCommand } from "../commands/train.ts";
import { createWorldStateCommand } from "../commands/world-state.ts";
import { selectedModelContract, type ModelSeatDecision } from "../entrypoints/model-seat.ts";
import {
  readRootBindingsStore,
  rootBindingsStorePath,
  type RootBindingsStore,
} from "../services/custody-bindings.ts";
import { GOALFORGE_ROOT, buildEmberWorldState, type EmberWorldState } from "../core/ember-world-state.ts";

// ---------------------------------------------------------------------------
// Path conventions (repo-root-relative)
// ---------------------------------------------------------------------------

const BENCHMARK_REGISTRY_REL = "manifests/ember-01-custody/benchmark-registry.json";
const ROOT_SPEC_REL = "manifests/ember-01-custody/root-spec.json";
const LAUNCH_PACKET_RECEIPTS_DIR_REL = "receipts/ember-01-launch-packet";

// T2.2 dependency (spec L59-61): the C0 failure-class ledger has not landed yet.
// This is the canonical path convention T2.2 is expected to populate -- sibling to
// the benchmark registry + root-spec in the SAME manifests/ember-01-custody/
// directory. Element 6 reads THIS exact path and renders the honest
// "BLOCKED: ledger absent" status until a real file appears there -- never a
// hardcoded/stale failure-class list standing in for it.
const C0_LEDGER_REL = "manifests/ember-01-custody/c0-failure-class-ledger.json";

function _defaultReadFile(path: string): string {
  return readFileSync(path, "utf8");
}

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

export type SpineElementStatus = "BOUND" | "OFFLINE" | "BLOCKED";

export interface SpineElementState {
  /** 1-7, per ember01plan §B5.5 L1183-1193 element numbering. */
  n: number;
  label: string;
  status: SpineElementStatus;
  lines: string[];
}

export interface SpinePanelState {
  ts: string;
  repoRoot: string;
  elements: SpineElementState[];
}

// ---------------------------------------------------------------------------
// Element 1 -- current authority + next executed outcome
// ---------------------------------------------------------------------------

export interface Element1Deps {
  readAuthorityFile?: (path: string) => string;
}

export function assembleAuthorityElement(repoRoot: string, deps: Element1Deps = {}): SpineElementState {
  const path = join(repoRoot, BENCHMARK_REGISTRY_REL);
  const readFile = deps.readAuthorityFile ?? _defaultReadFile;
  const loaded = _loadBenchmarkRegistry(path, readFile);
  if (!loaded.ok) {
    return {
      n: 1,
      label: "current authority + next executed outcome",
      status: "BLOCKED",
      lines: [`BLOCKED: ${loaded.error}`],
    };
  }
  const a = loaded.registry.authority;
  return {
    n: 1,
    label: "current authority + next executed outcome",
    status: "BOUND",
    lines: [
      `goal_id: ${a.goal_id}`,
      `workstream_id: ${a.workstream_id}`,
      `next_executed_outcome: ${a.next_executed_outcome}`,
      `source: ${path}`,
    ],
  };
}

// ---------------------------------------------------------------------------
// Element 2 -- current checkpoint + seat identity
// ---------------------------------------------------------------------------

export interface Element2Deps {
  getModelSeatDecision?: () => ModelSeatDecision;
  selectedModelContractFn?: typeof selectedModelContract;
}

export function assembleSeatElement(deps: Element2Deps = {}): SpineElementState {
  const getDecision = deps.getModelSeatDecision ?? _defaultGetModelSeatDecision;
  const contractFn = deps.selectedModelContractFn ?? selectedModelContract;

  let decision: ModelSeatDecision;
  try {
    decision = getDecision();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      n: 2,
      label: "current checkpoint + seat identity",
      status: "BLOCKED",
      lines: [`BLOCKED: seat resolution failed: ${msg}`],
    };
  }

  const rendered = renderCustodyStatus(decision, contractFn);
  const status: SpineElementStatus =
    !decision.allowed || decision.seat === null
      ? "BLOCKED"
      : decision.seat === "OFFLINE"
        ? "OFFLINE"
        : "BOUND";
  return { n: 2, label: "current checkpoint + seat identity", status, lines: rendered.split("\n") };
}

// ---------------------------------------------------------------------------
// Element 3 -- custody-leg state + persisted logical roots
// ---------------------------------------------------------------------------

interface RootSpecRoot {
  root_id: string;
  binding?: string;
  required?: boolean;
}
interface RootSpecFile {
  roots: RootSpecRoot[];
}

export interface Element3Deps {
  readRootSpecFile?: (path: string) => string;
  readRootBindingsStoreFn?: (repoRoot: string) => RootBindingsStore;
}

export function assembleCustodyLegElement(repoRoot: string, deps: Element3Deps = {}): SpineElementState {
  const specPath = join(repoRoot, ROOT_SPEC_REL);
  const readSpec = deps.readRootSpecFile ?? _defaultReadFile;

  let spec: RootSpecFile;
  try {
    const raw = readSpec(specPath);
    const parsed = JSON.parse(raw) as unknown;
    if (
      !parsed ||
      typeof parsed !== "object" ||
      !Array.isArray((parsed as RootSpecFile).roots)
    ) {
      throw new Error(`root-spec at ${specPath} is missing a "roots" array`);
    }
    spec = parsed as RootSpecFile;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      n: 3,
      label: "custody-leg state + persisted logical roots",
      status: "BLOCKED",
      lines: [`BLOCKED: ${msg}`],
    };
  }

  // Defect (adversarial review, PR #1027): the root-spec read above is wrapped
  // fail-closed, but this bindings-store read was NOT -- readRootBindingsStore's own
  // default implementation is fail-open by design (services/custody-bindings.ts), but
  // an injected readRootBindingsStoreFn (or any future non-fail-open implementation)
  // that throws propagated straight out of assembleCustodyLegElement and crashed the
  // WHOLE /spine command, not just element 3. Wrap it -- per-element isolation.
  const readBindings = deps.readRootBindingsStoreFn ?? ((root: string) => readRootBindingsStore(root));
  try {
    const store = readBindings(repoRoot);
    const boundIds = new Set(Object.keys(store.roots ?? {}));
    const boundCount = spec.roots.filter((r) => boundIds.has(r.root_id)).length;

    const lines = [
      `roots declared: ${spec.roots.length}`,
      `roots bound: ${boundCount}`,
      `store: ${rootBindingsStorePath(repoRoot)}`,
    ];
    const bindingsRendered = renderRootBindings(store);
    if (bindingsRendered) {
      lines.push(...bindingsRendered.split("\n").filter((l) => l !== ""));
    }
    return { n: 3, label: "custody-leg state + persisted logical roots", status: "BOUND", lines };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      n: 3,
      label: "custody-leg state + persisted logical roots",
      status: "BLOCKED",
      lines: [`BLOCKED: root-bindings store read failed: ${msg}`],
    };
  }
}

// ---------------------------------------------------------------------------
// Element 4 -- launch-packet state
// ---------------------------------------------------------------------------

interface LaunchPacketSummaryRow {
  record?: string;
  overall_ready?: boolean;
  implemented_all_pass?: boolean;
  any_deferred?: boolean;
  named_ember02_command?: { command: string } | null;
}

export interface Element4Deps {
  listLaunchPacketReceipts?: (dirPath: string) => string[];
  readLaunchPacketReceipt?: (path: string) => string;
}

// Canonical launch-packet receipt directory name shape: the exact UTC-basic-format
// timestamp launch_packet.py's preflight writes (e.g. "20260201T000000Z").
const CANONICAL_RECEIPT_TS_RE = /^\d{8}T\d{6}Z$/;

// Defect (adversarial review, PR #1027): the prior implementation returned every
// `readdirSync(dirPath)` entry name (files AND directories, canonical-timestamp or not)
// sorted lexicographically, then blindly took the LAST one as "newest". A stray file
// dropped directly in the receipts dir, or a directory whose name doesn't follow the
// canonical timestamp shape, can sort after every real receipt and shadow it -- /spine
// would then try to read a non-existent/malformed packet.jsonl instead of the real
// latest receipt. FAIL-CLOSED here means filtering to real directories matching the
// canonical shape BEFORE selection ever runs.
function _defaultListLaunchPacketReceipts(dirPath: string): string[] {
  try {
    return readdirSync(dirPath, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && CANONICAL_RECEIPT_TS_RE.test(entry.name))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return [];
  }
}

// Defect (re-review, PR #1027 round-2): the newest-to-oldest walk was hardened
// to skip UNREADABLE entries, but its notion of "valid" summary was too weak --
// `obj.record === "launch-packet-summary"` accepted ANY object carrying that tag,
// fields unvalidated. A newest packet.jsonl containing only
// `{"record":"launch-packet-summary"}` (or wrong-typed fields) was accepted as
// valid, rendered BOUND with false-looking defaults (every boolean falling to
// `false` via `=== true`), AND stopped the walk -- silently shadowing a
// genuinely valid OLDER receipt the "newest READABLE VALID receipt" contract
// promises. FAIL-CLOSED here: a summary counts as valid only against this closed
// schema; anything else must be treated exactly like an unreadable entry (skip +
// fall back, never assign-and-stop).
function _isValidLaunchPacketSummary(obj: unknown): obj is LaunchPacketSummaryRow {
  if (typeof obj !== "object" || obj === null) return false;
  const o = obj as Record<string, unknown>;
  if (o.record !== "launch-packet-summary") return false;
  if (typeof o.overall_ready !== "boolean") return false;
  if (typeof o.implemented_all_pass !== "boolean") return false;
  if (typeof o.any_deferred !== "boolean") return false;

  const cmd = o.named_ember02_command;
  if (cmd !== null && cmd !== undefined) {
    if (typeof cmd !== "object") return false;
    const cmdObj = cmd as Record<string, unknown>;
    if (typeof cmdObj.command !== "string" || cmdObj.command.trim().length === 0) return false;
  }

  // Named conditional invariant (re-review, PR #1027 round-2): a claimed-ready summary is unactionable
  // (and therefore invalid) without a real, non-empty named command.
  if (o.overall_ready === true) {
    const cmdObj = cmd as { command?: string } | null | undefined;
    if (!cmdObj || typeof cmdObj.command !== "string" || cmdObj.command.trim().length === 0) return false;
  }

  return true;
}

export function assembleLaunchPacketElement(repoRoot: string, deps: Element4Deps = {}): SpineElementState {
  const dirPath = join(repoRoot, LAUNCH_PACKET_RECEIPTS_DIR_REL);
  const listDirs = deps.listLaunchPacketReceipts ?? _defaultListLaunchPacketReceipts;
  const readFile = deps.readLaunchPacketReceipt ?? _defaultReadFile;

  const dirs = listDirs(dirPath);
  if (dirs.length === 0) {
    return {
      n: 4,
      label: "launch-packet state",
      status: "BLOCKED",
      lines: [
        "BLOCKED: no launch-packet receipt yet",
        `expected under: ${dirPath}`,
        "drive: /spine drive launch-packet runs the real /train preflight",
      ],
    };
  }

  // Select the NEWEST READABLE VALID receipt: walk from newest to oldest and skip
  // (never crash on) any entry that fails to read or lacks a valid summary record --
  // a corrupted/incomplete newest receipt must fall back to the next-newest good one,
  // never silently block on a shadowing entry that a genuinely valid older receipt
  // would have satisfied.
  let lastError: string | null = null;
  for (let i = dirs.length - 1; i >= 0; i--) {
    const candidate = dirs[i]!;
    const receiptPath = join(dirPath, candidate, "packet.jsonl");
    let raw: string;
    try {
      raw = readFile(receiptPath);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      lastError = `could not read ${receiptPath}: ${msg}`;
      continue;
    }

    let summary: LaunchPacketSummaryRow | null = null;
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("{")) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (_isValidLaunchPacketSummary(obj)) summary = obj;
      } catch {
        // skip unparseable line -- mirrors train.ts's _parseLaunchPacketOutput tolerance.
      }
    }
    if (!summary) {
      lastError = `${receiptPath} has no valid launch-packet-summary record`;
      continue;
    }

    const lines = [
      `receipt: ${receiptPath}`,
      `overall_ready: ${summary.overall_ready === true}`,
      `implemented_all_pass: ${summary.implemented_all_pass === true}`,
      `any_deferred: ${summary.any_deferred === true}`,
    ];
    if (summary.overall_ready === true && summary.named_ember02_command?.command) {
      lines.push(`named command: ${summary.named_ember02_command.command}`);
    }
    return { n: 4, label: "launch-packet state", status: "BOUND", lines };
  }

  return {
    n: 4,
    label: "launch-packet state",
    status: "BLOCKED",
    lines: [
      `BLOCKED: no valid launch-packet receipt found under ${dirPath}`,
      ...(lastError ? [lastError] : []),
    ],
  };
}

// ---------------------------------------------------------------------------
// Element 5 -- benchmark registry + exact non-execution/execution state
// ---------------------------------------------------------------------------

export interface Element5Deps {
  readBenchmarkRegistryFile?: (path: string) => string;
}

// _loadBenchmarkRegistry (commands/benchmark.ts) validates benchmark_id/harness_status/
// completion but does NOT constrain execution_status's vocabulary -- it's typed `string`
// with no runtime check. Defect (adversarial review, PR #1027): counting
// `!== "not_executed"` as "executed" silently folds missing/malformed/unsupported/failed/
// novel status strings into the executed bucket. FAIL-CLOSED here: the known vocabulary
// is exactly {"executed", "not_executed"} (the only two values _loadBenchmarkRegistry's
// producer, launch_packet.py / the registry authors, ever write); any row whose
// execution_status is missing, non-string, or outside that set blocks the WHOLE element
// (never a guessed partial count) with the offending benchmark_id named.
const KNOWN_EXECUTION_STATUSES = new Set(["executed", "not_executed"]);

export function assembleBenchmarkElement(repoRoot: string, deps: Element5Deps = {}): SpineElementState {
  const path = join(repoRoot, BENCHMARK_REGISTRY_REL);
  const readFile = deps.readBenchmarkRegistryFile ?? _defaultReadFile;
  const loaded = _loadBenchmarkRegistry(path, readFile);
  if (!loaded.ok) {
    return {
      n: 5,
      label: "benchmark registry + execution state",
      status: "BLOCKED",
      lines: [`BLOCKED: ${loaded.error}`],
    };
  }
  const rows = loaded.registry.benchmarks;
  const badRow = rows.find(
    (r) => typeof r.execution_status !== "string" || !KNOWN_EXECUTION_STATUSES.has(r.execution_status),
  );
  if (badRow) {
    return {
      n: 5,
      label: "benchmark registry + execution state",
      status: "BLOCKED",
      lines: [
        `BLOCKED: benchmark ${badRow.benchmark_id ?? "(unknown)"} has an out-of-vocabulary ` +
          `execution_status ${JSON.stringify(badRow.execution_status)} ` +
          `(known: ${[...KNOWN_EXECUTION_STATUSES].join(", ")})`,
        `source: ${path}`,
      ],
    };
  }
  const executed = rows.filter((r) => r.execution_status === "executed").length;
  const lines = [
    `${rows.length} benchmark(s) -- schema ${loaded.registry.schema}`,
    `executed: ${executed} / ${rows.length}`,
    `source: ${path}`,
  ];
  return { n: 5, label: "benchmark registry + execution state", status: "BOUND", lines };
}

// ---------------------------------------------------------------------------
// Element 6 -- failure-class state (C0 ledger, T2.2 dependency)
// ---------------------------------------------------------------------------

interface C0LedgerRow {
  class_id?: string;
  state?: string;
}
interface C0LedgerFile {
  classes?: C0LedgerRow[];
}

export interface Element6Deps {
  existsC0Ledger?: (path: string) => boolean;
  readC0Ledger?: (path: string) => string;
}

export function assembleFailureClassElement(repoRoot: string, deps: Element6Deps = {}): SpineElementState {
  const path = join(repoRoot, C0_LEDGER_REL);
  const exists = deps.existsC0Ledger ?? existsSync;
  const readFile = deps.readC0Ledger ?? _defaultReadFile;

  if (!exists(path)) {
    return {
      n: 6,
      label: "failure-class state",
      status: "BLOCKED",
      lines: ["BLOCKED: ledger absent", `expected at: ${path}`, "landing: T2.2 (C0 ledger)"],
    };
  }

  let ledger: C0LedgerFile;
  try {
    const raw = readFile(path);
    ledger = JSON.parse(raw) as C0LedgerFile;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      n: 6,
      label: "failure-class state",
      status: "BLOCKED",
      lines: [`BLOCKED: ${path} did not parse: ${msg}`],
    };
  }

  // Defect (adversarial review, PR #1027): `Array.isArray(...) ? ... : []` plus
  // `?? "(unnamed)"` / `?? "unknown"` fallbacks rendered a missing/non-array/empty
  // `classes`, or rows missing class_id/state, as a fake BOUND "0 failure class(es)" or
  // "(unnamed): unknown" line -- structurally invalid ledger bytes must never render as
  // a plausible-looking count. FAIL-CLOSED: `classes` must be a non-empty array and
  // EVERY row must carry non-empty string class_id + state, or the whole element blocks
  // naming the exact violation (never a partial/guessed table).
  if (!Array.isArray(ledger.classes) || ledger.classes.length === 0) {
    return {
      n: 6,
      label: "failure-class state",
      status: "BLOCKED",
      lines: [`BLOCKED: ${path} is missing a non-empty "classes" array`],
    };
  }
  const badIndex = ledger.classes.findIndex(
    (c) =>
      !c ||
      typeof c !== "object" ||
      typeof c.class_id !== "string" ||
      c.class_id.trim() === "" ||
      typeof c.state !== "string" ||
      c.state.trim() === "",
  );
  if (badIndex !== -1) {
    return {
      n: 6,
      label: "failure-class state",
      status: "BLOCKED",
      lines: [`BLOCKED: ${path}: classes[${badIndex}] is missing a non-empty "class_id" or "state"`],
    };
  }

  const classes = ledger.classes;
  const lines = [
    `${classes.length} failure class(es) recorded`,
    ...classes.map((c) => `  ${c.class_id}: ${c.state}`),
    `source: ${path}`,
  ];
  return { n: 6, label: "failure-class state", status: "BOUND", lines };
}

// ---------------------------------------------------------------------------
// Element 7 -- claim scope + blocked reasons
// ---------------------------------------------------------------------------

export interface Element7Deps {
  goalforgeRoot?: string;
  buildWorldState?: (opts: { goalforgeRoot?: string }) => Promise<EmberWorldState>;
}

export async function assembleClaimScopeElement(deps: Element7Deps = {}): Promise<SpineElementState> {
  const root = deps.goalforgeRoot ?? GOALFORGE_ROOT;
  if (!root) {
    return {
      n: 7,
      label: "claim scope + blocked reasons",
      status: "BLOCKED",
      lines: [
        "BLOCKED: world-state source not configured",
        "set EMBER_GOALFORGE_ROOT to enable claim scope (same contract /cockpit uses)",
      ],
    };
  }

  const build = deps.buildWorldState ?? buildEmberWorldState;
  try {
    const state = await build({ goalforgeRoot: root });
    return {
      n: 7,
      label: "claim scope + blocked reasons",
      status: "BOUND",
      lines: [
        `monitor claims: ${state.monitor.conditions.length} (green ${state.monitor.green} / red ${state.monitor.red})`,
        `understand claims: ${state.understand.topology.length}`,
        `interact claims: ${state.interact.ledgerRows.length}`,
        `sources: goal=${state.sources.goal.path} ledger=${state.sources.ledger.path} board=${state.sources.board.path}`,
      ],
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { n: 7, label: "claim scope + blocked reasons", status: "BLOCKED", lines: [`BLOCKED: ${msg}`] };
  }
}

// ---------------------------------------------------------------------------
// Assembly + rendering
// ---------------------------------------------------------------------------

export interface SpinePanelDeps
  extends Element1Deps,
    Element2Deps,
    Element3Deps,
    Element4Deps,
    Element5Deps,
    Element6Deps,
    Element7Deps {
  resolveRepoRoot?: () => string;
}

export async function assembleSpinePanelState(
  cwd: string,
  deps: SpinePanelDeps = {},
): Promise<SpinePanelState> {
  const resolveRepoRoot =
    deps.resolveRepoRoot ?? (() => resolveEmberSourceRootOrCwd({ startDir: cwd }, "[ember] /spine"));
  const repoRoot = resolveRepoRoot();

  const elements: SpineElementState[] = [
    assembleAuthorityElement(repoRoot, deps),
    assembleSeatElement(deps),
    assembleCustodyLegElement(repoRoot, deps),
    assembleLaunchPacketElement(repoRoot, deps),
    assembleBenchmarkElement(repoRoot, deps),
    assembleFailureClassElement(repoRoot, deps),
    await assembleClaimScopeElement(deps),
  ];

  return { ts: new Date().toISOString(), repoRoot, elements };
}

/** Renders every element of the panel. Exported for direct unit testing of the render
 *  shape without going through the command's execute() plumbing. */
export function renderSpinePanel(state: SpinePanelState): string {
  const lines: string[] = [
    "=== B5.5 Operator Spine ===",
    `repoRoot: ${state.repoRoot}`,
    `ts: ${state.ts}`,
    "",
  ];
  for (const el of state.elements) {
    lines.push(`[${el.n}] ${el.label} -- ${el.status}`);
    for (const l of el.lines) lines.push(`    ${l}`);
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

/** Renders a single element in detail (`/spine <n>`). */
export function renderSpineElement(state: SpinePanelState, n: number): string {
  const el = state.elements.find((e) => e.n === n);
  if (!el) return `no such spine element: ${n} (valid: 1-7)`;
  return [`[${el.n}] ${el.label} -- ${el.status}`, ...el.lines].join("\n");
}

// ---------------------------------------------------------------------------
// Drive -- routes to the EXISTING command, no separate console (spec point 4)
// ---------------------------------------------------------------------------

export interface SpineDriveDeps {
  custodyCommand?: RegistryCommand;
  benchmarkCommand?: RegistryCommand;
  trainCommand?: RegistryCommand;
  worldStateCommand?: RegistryCommand;
}

const DRIVE_ALIASES: Record<string, keyof SpineDriveDeps> = {
  "2": "custodyCommand",
  "3": "custodyCommand",
  custody: "custodyCommand",
  seat: "custodyCommand",
  "4": "trainCommand",
  train: "trainCommand",
  "launch-packet": "trainCommand",
  "5": "benchmarkCommand",
  benchmark: "benchmarkCommand",
  "7": "worldStateCommand",
  cockpit: "worldStateCommand",
  claims: "worldStateCommand",
};

export async function driveSpineElement(
  target: string,
  args: string,
  ctx: CommandContext,
  deps: SpineDriveDeps = {},
): Promise<CommandResult> {
  const key = DRIVE_ALIASES[target];
  if (!key) {
    return {
      type: "message",
      message: `no drivable spine element "${target}" (drivable: custody/2/3, launch-packet/4, benchmark/5, cockpit/7)`,
      exitCode: 1,
    };
  }
  const commands: Record<keyof SpineDriveDeps, () => RegistryCommand> = {
    custodyCommand: () => deps.custodyCommand ?? createCustodyCommand(),
    benchmarkCommand: () => deps.benchmarkCommand ?? createBenchmarkCommand(),
    trainCommand: () => deps.trainCommand ?? createTrainCommand(),
    worldStateCommand: () => deps.worldStateCommand ?? createWorldStateCommand(),
  };
  const cmd = commands[key]();
  const result = await cmd.execute(args, ctx);
  return result ?? { type: "message", message: "(no output)" };
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/** Creates the `/spine` (alias `/b55`) command. Registered in command-registry.ts. */
export function createSpinePanelCommand(deps: SpinePanelDeps & SpineDriveDeps = {}): RegistryCommand {
  return {
    name: "spine",
    aliases: ["b55"],
    description:
      "B5.5 operator spine panel: 7 elements (authority, seat, custody, launch-packet, benchmark, failure-class, claim scope) bound to real local state. /spine [n] inspects; /spine drive <target> [args] routes to the existing command.",
    isEnabled(): boolean {
      return true;
    },
    async execute(argsLine: string, ctx: CommandContext): Promise<CommandResult> {
      const trimmed = argsLine.trim();

      if (trimmed === "drive" || trimmed.startsWith("drive ")) {
        const rest = trimmed.slice("drive".length).trim();
        const firstSpace = rest.search(/\s/);
        const target = firstSpace === -1 ? rest : rest.slice(0, firstSpace);
        const driveArgs = firstSpace === -1 ? "" : rest.slice(firstSpace + 1).trim();
        if (!target) {
          return {
            type: "message",
            message: "usage: /spine drive <target> [args] (custody, launch-packet, benchmark, cockpit)",
            exitCode: 1,
          };
        }
        return driveSpineElement(target, driveArgs, ctx, deps);
      }

      const state = await assembleSpinePanelState(ctx.cwd, deps);

      if (trimmed === "") {
        return { type: "message", message: renderSpinePanel(state) };
      }
      const n = Number(trimmed);
      if (Number.isInteger(n)) {
        return { type: "message", message: renderSpineElement(state, n) };
      }
      return {
        type: "message",
        message: "usage: /spine [n] | /spine drive <target> [args]",
      };
    },
  };
}

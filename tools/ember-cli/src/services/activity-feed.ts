// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/activity-feed.ts — issue #485 rung 1: the real-event engine behind the cockpit's
// activity feed. The operator's verbatim complaint (3+ weeks up, zero activity ever seen) and
// the board (C-PROC/C-OBS/C13 all RED) agree this is a genuine gap, not a perception problem —
// GOAL.md's own P-C text: "a keyframed flame is a fabricated receipt in visual form." So every
// line this engine renders traces to one real, observable event:
//
//   - a NEW receipt file landing anywhere under receipts/** (recursive fs watch)
//   - the planned-outage marker appearing/expiring (tools/ember-cli/state/planned-outage.json)
//   - a liveness-watchdog restart-log row or kill-receipt row (server/cockpit up/down)
//   - a new totality board render (scripts/ember_totality/receipts-totality/)
//   - a goal-organ transition/continuation-fire row, tailed from receipts/goal-sessions/*.jsonl
//     (ember issue #211 §7 delta 4, "goal receipts feed the board" -- see the goal-session
//     tail-poll section below; a growing JSONL session log, never a one-shot-parsed file)
//
// Fabricated/synthetic events are constitutionally banned — this engine has no "demo" or
// "sample" event path. Every RENDERED event (including the "(receipt landing…)" placeholder for
// a still-writing file) is appended to state/activity-ledger.jsonl, so "nothing happened" is
// machine-checkable instead of resting on the operator's own eyes.

import { watch, readFileSync, statSync, type FSWatcher } from "node:fs";
import { readFile, stat, writeFile, open } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { isHeadlessCapture } from "./headless-capture.ts";
import { appendLineWithDirs, stripBom } from "../utils/file-operations.ts";
import type { ActivityFeedLine, ActivityFeedSource } from "../components/activity-feed-pane.ts";
import type { GoalReceiptRow } from "./goal-receipts.ts";

export type { ActivityFeedLine, ActivityFeedSource };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Ring-buffer cap on retained lines (bounded scrollback; the visible pane shows far fewer). */
export const RING_BUFFER_CAP = 200;

/** A new receipt/board file that fails to parse on first sight gets exactly one retry, this
 *  many ms later (covers the write-in-progress race — a watcher event can fire before the
 *  writer's fs.writeFile call has flushed all bytes). */
export const RECEIPT_RETRY_DELAY_MS = 500;

/** Poll cadence for the planned-outage marker (no fs-event exists for "time passed", so
 *  expiry is detected by polling) and the two tail-polled JSONL logs. */
export const OUTAGE_POLL_INTERVAL_MS = 1000;
export const TAIL_POLL_INTERVAL_MS = 1000;

/** Hard cap for receipt/board path bookkeeping. Durable watermarks retain a recent replay
 * horizon; the append-only activity ledger remains the complete activity history. */
export const MAX_TRACKED_PATHS = 5000;

/** At most this many goal-session tails are polled concurrently. */
export const MAX_GOAL_TAIL_STATES = 50;

/** FIFO-bounded dedupe set for long-running activity-feed path bookkeeping. */
export class BoundedSet<T> {
  private readonly order: T[] = [];
  private readonly items = new Set<T>();

  constructor(private readonly max: number) {}

  has(value: T): boolean {
    return this.items.has(value);
  }

  add(value: T): void {
    if (this.items.has(value)) return;
    this.items.add(value);
    this.order.push(value);
    while (this.order.length > this.max) {
      const oldest = this.order.shift();
      if (oldest !== undefined) this.items.delete(oldest);
    }
  }

  get size(): number {
    return this.items.size;
  }
}

/** Bound an insertion-ordered string-keyed record without touching newer entries. */
export function boundRecordKeys(record: Record<string, unknown>, max: number): void {
  const excess = Object.keys(record).length - max;
  if (excess <= 0) return;
  for (const key of Object.keys(record).slice(0, excess)) delete record[key];
}

/** Insert/update a map entry and evict oldest entries above its fixed capacity. */
export function setBoundedMapEntry<K, V>(map: Map<K, V>, key: K, value: V, max: number): void {
  map.set(key, value);
  while (map.size > max) {
    const oldest = map.keys().next().value as K | undefined;
    if (oldest === undefined) return;
    map.delete(oldest);
  }
}

/** Return a runner that declines a new asynchronous tick while its prior tick is unsettled. */
export function createSingleFlightRunner(): (work: () => Promise<unknown>) => boolean {
  let inFlight = false;
  return (work) => {
    if (inFlight) return false;
    inFlight = true;
    void work().catch(() => {}).finally(() => { inFlight = false; });
    return true;
  };
}

// ---------------------------------------------------------------------------
// Pure formatters — receipts
// ---------------------------------------------------------------------------

/** "Receipt class" per the spec = the immediate parent directory's basename. */
export function classNameFromPath(filePath: string): string {
  return path.basename(path.dirname(filePath));
}

/** Pulls a `verdict` field out of a parsed receipt JSON, if one exists. Never throws. */
export function extractVerdict(parsed: unknown): string | undefined {
  if (parsed && typeof parsed === "object") {
    const v = (parsed as Record<string, unknown>)["verdict"];
    if (typeof v === "string" && v.length > 0) return v;
  }
  return undefined;
}

export function formatReceiptLine(filePath: string, parsed: unknown): string {
  const cls = classNameFromPath(filePath);
  const name = path.basename(filePath);
  const verdict = extractVerdict(parsed);
  return verdict
    ? `receipt landed [${cls}] ${name} — ${verdict}`
    : `receipt landed [${cls}] ${name}`;
}

export function formatPlaceholderLine(filePath: string): string {
  return `(receipt landing…) ${path.basename(filePath)}`;
}

export function formatUnparsableLine(filePath: string): string {
  return `(receipt unparsable) ${path.basename(filePath)}`;
}

// ---------------------------------------------------------------------------
// P0-B: path exclusion + bulk-materialization coalescing
// ---------------------------------------------------------------------------

/** Path segments that mark a nested fixture/plugin/dependency tree, never an organic receipt
 *  landing -- e.g. a real receipt walk under `.avir/plugins/marketplaces/**` is tooling noise,
 *  not something that happened. Rendering these ever (even correctly labeled) is the wrong
 *  behavior; excluding them is the fix, not relabeling their class name to something friendlier
 *  ("[.claude-plugin]" must never appear in a rendered line, full stop). */
const EXCLUDED_PATH_SEGMENTS = new Set([
  ".avir",
  ".claude-plugin",
  "node_modules",
  "fixture",
  "fixtures",
  "marketplaces",
]);

/** True when any segment of `filePath` matches a known non-organic tree. Checked against the
 *  raw path (not resolved against a specific root) so it works for both absolute paths and the
 *  relative fragments a watcher callback hands back. */
export function isExcludedReceiptPath(filePath: string): boolean {
  const segments = filePath.split(/[\\/]/);
  return segments.some((seg) => EXCLUDED_PATH_SEGMENTS.has(seg));
}

/** One summarized line for a burst of files that all became "new" within the same short window
 *  (e.g. `git checkout` restoring N tracked receipts at once) -- never N individual "receipt
 *  landed" lines for a single bulk operation. */
export function formatBulkMaterializationLine(paths: string[]): string {
  return `${paths.length} receipts materialized at once (bulk restore)`;
}

// ---------------------------------------------------------------------------
// Pure formatters — board runs
// ---------------------------------------------------------------------------

export function formatBoardLine(filePath: string, parsed: unknown): string | null {
  if (!parsed || typeof parsed !== "object") return null;
  const rows = (parsed as Record<string, unknown>)["rows"];
  if (!Array.isArray(rows)) return null;

  let green = 0;
  let red = 0;
  let other = 0;
  for (const row of rows) {
    const status = row && typeof row === "object" ? (row as Record<string, unknown>)["status"] : undefined;
    if (status === "GREEN") green++;
    else if (status === "RED") red++;
    else other++;
  }
  const otherSuffix = other > 0 ? ` / ${other} other` : "";
  return `totality board rendered: ${green} GREEN / ${red} RED${otherSuffix} (${path.basename(filePath)})`;
}

// ---------------------------------------------------------------------------
// Pure formatters — planned-outage marker
// ---------------------------------------------------------------------------

export interface OutageMarker {
  owner: string;
  reason: string;
  target: string;
  started: string;
  expires: string;
  kill_receipt_ref: string;
}

const OUTAGE_MARKER_FIELDS = ["owner", "reason", "target", "started", "expires", "kill_receipt_ref"] as const;

/** Validates the frozen planned-outage.json contract (issue #464 comment 4918207339): all six
 *  fields required and non-blank. Missing/blank field or unparseable JSON -> null (absent),
 *  mirroring the watchdog's own Get-PlannedOutageMarker discipline — never partially honored. */
export function parseOutageMarker(raw: string): OutageMarker | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const obj = parsed as Record<string, unknown>;
  for (const field of OUTAGE_MARKER_FIELDS) {
    const value = obj[field];
    if (typeof value !== "string" || value.trim().length === 0) return null;
  }
  return obj as unknown as OutageMarker;
}

/** Pure: a raw (already-validated) marker is "effective" iff it exists and has not expired.
 *  Shared by classifyOutageTransition (transition detection, activity-feed engine) and issue
 *  #475's cockpit status banner (services/outage-banner-poller.ts) — both need exactly this
 *  same expiry check against the same marker shape, and neither should re-derive it. */
export function computeEffectiveMarker(nextRaw: OutageMarker | null, nowMs: number): OutageMarker | null {
  if (!nextRaw) return null;
  const expired = Date.parse(nextRaw.expires) <= nowMs;
  return expired ? null : nextRaw;
}

export interface OutageTransitionResult {
  transition: "opened" | "closed" | "none";
  text?: string;
  /** The marker the caller should treat as "currently effective" on the next tick. */
  effective: OutageMarker | null;
}

/** Pure state-machine step: given the last EFFECTIVE marker, the freshly-read raw marker (or
 *  null), and now, decides whether an open/close transition happened. An expired marker is
 *  treated exactly like an absent one (closed), matching the watchdog's "does not extend
 *  silently" rule. */
export function classifyOutageTransition(
  prevEffective: OutageMarker | null,
  nextRaw: OutageMarker | null,
  nowMs: number,
): OutageTransitionResult {
  const nextEffective = computeEffectiveMarker(nextRaw, nowMs);

  if (!prevEffective && nextEffective) {
    return {
      transition: "opened",
      text: `server outage window opened: owner=${nextEffective.owner} target=${nextEffective.target} expires=${nextEffective.expires}`,
      effective: nextEffective,
    };
  }
  if (prevEffective && !nextEffective) {
    return {
      transition: "closed",
      text: `server outage window closed: owner=${prevEffective.owner} target=${prevEffective.target}`,
      effective: null,
    };
  }
  return { transition: "none", effective: nextEffective };
}

// ---------------------------------------------------------------------------
// Pure formatters — liveness-watchdog rows (restart-log + kill-receipts)
// ---------------------------------------------------------------------------

export type WatchdogRow = Record<string, unknown>;

/** issue #616 bar 2: a kill-receipt row may render as a SERVER event only when the row's own
 *  cmdline-bearing field (`match_rule` in the kill-discipline receipt format, or a literal
 *  `cmdline` field) names the serving binary. Historical liveness-watchdog kill receipts wrote
 *  "Name=llama-server.exe ..." into match_rule; this reader preserves that append-only evidence
 *  format after the watchdog itself was retired. Classification remains a property the row
 *  itself carries — never an inference from context. */
const SERVER_PROCESS_MARKER = "llama-server";

export function killReceiptNamesServer(row: WatchdogRow): boolean {
  for (const field of ["match_rule", "cmdline"]) {
    const value = row[field];
    if (typeof value === "string" && value.toLowerCase().includes(SERVER_PROCESS_MARKER)) return true;
  }
  return false;
}

/** Handles both row shapes the watchdog logs carry: restart-log rows ({target, event, ...}) and
 *  kill-receipt rows ({ts, script, pids, match_rule, ...}). Returns null for any row it cannot
 *  map CONFIDENTLY — the tail-poll callers render null rows via formatWatchdogFallbackLine
 *  (verbatim passthrough), never a paraphrase.
 *
 *  issue #616 (2026-07-10 incident: two kill receipts for a cockpit PID and a watchdog PID were
 *  rendered as "server killed by watchdog (reason unavailable)" — an invented actor, an invented
 *  target, and an invented admission; none of those words were in the rows). Bars enforced here:
 *  - actor/target come from row fields only (restart rows: `target`; kill rows: `script`) —
 *    a row missing them is unmappable, never defaulted;
 *  - a kill-receipt row renders as a server event ONLY when its own match_rule/cmdline field
 *    names the serving binary (killReceiptNamesServer);
 *  - `reason` renders only when the row carries one — absence renders as nothing, never as an
 *    invented "(reason unavailable)". */
export function formatWatchdogLine(row: WatchdogRow): string | null {
  if (typeof row["event"] === "string") {
    const target = row["target"];
    if (typeof target !== "string" || target.length === 0) return null; // no subject in the row
    switch (row["event"]) {
      case "relaunch":
        return `${target} was down, restarted (pid ${row["relaunchPid"] ?? "?"})`;
      case "crashloop-backoff":
        return `${target} crashlooping — watchdog backing off`;
      case "marker-overrun":
        return `${target} planned-outage window overran (owner=${row["owner"] ?? "?"})`;
      default:
        return `${target} watchdog event: ${row["event"]}`;
    }
  }
  if (Array.isArray(row["pids"])) {
    const script = row["script"];
    if (typeof script !== "string" || script.length === 0) return null; // no actor in the row
    if (!killReceiptNamesServer(row)) return null; // row's own cmdline does not name the server
    const reason =
      typeof row["reason"] === "string" && row["reason"].length > 0 ? ` (${row["reason"]})` : "";
    return `server killed by ${script}${reason}`;
  }
  return null;
}

/** issue #616 bar 3: honest passthrough for a row the summarizer cannot map confidently — the
 *  raw ledger line verbatim, behind a prefix that claims nothing about actor or target. */
export function formatWatchdogFallbackLine(rawLine: string): string {
  return `unmapped watchdog-log row: ${rawLine}`;
}

// ---------------------------------------------------------------------------
// Pure formatters — goal-organ receipt rows (ember issue #211 §7 delta 4:
// "goal receipts feed the board")
// ---------------------------------------------------------------------------

/** True when a path handed back by the recursive receipts-dir watch callback (relative to
 *  receiptsDir) is a goal-organ session log -- services/goal-receipts.ts's
 *  receipts/goal-sessions/session-<UTC>[-sessionId].jsonl. These are APPENDED to repeatedly for
 *  the life of a session (every transition + continuation fire/skip), never written once and
 *  left alone like an ordinary `.json` receipt -- so they need tail-polling (pollTail, same
 *  mechanism as the watchdog's restart-log/kill-receipts logs below), never the one-shot
 *  read-whole-file-as-JSON path `queueForRender` uses for `.json` files. Segment-exact match
 *  (not a substring check) so a coincidentally-similar directory name never misroutes. */
export function isGoalSessionRelativePath(relPath: string): boolean {
  if (!relPath.endsWith(".jsonl")) return false;
  return relPath.split(/[\\/]/).includes("goal-sessions");
}

/** Truncates goal objective text for a one-line activity card -- the full text is always still
 *  available in the goal-sessions receipt file itself (path carried on the rendered line). */
function truncateForActivityLine(value: string, maxLen = 60): string {
  if (value.length <= maxLen) return value;
  return `${value.slice(0, Math.max(maxLen - 1, 0))}…`;
}

/** Maps one goal-organ receipt row (services/goal-receipts.ts's GoalReceiptRow) to an activity
 *  line, or null to exclude it from the feed entirely.
 *
 *  Deliberately excluded:
 *  - `usage_recorded` -- fires on every token tally the store records; pure background noise,
 *    never a human-meaningful "activity".
 *  - `continuation_skipped` -- fires on nearly every ordinary turn once a goal exists (any turn
 *    ending while the user has already typed something skips with `queued_user_input`); the
 *    autonomy-visible signal the current "Operator relationship" section of
 *    docs/goal-mode-mechanism.md cares about
 *    "autonomy must be VISIBLE") is a continuation that FIRED, never the routine skip -- surfacing
 *    skips would flood the feed with exactly the noise issue #485/#576 fought to eliminate.
 *
 *  Everything else is exactly a goal-state transition the operator should see without opening
 *  the receipt file. */
export function formatGoalReceiptLine(row: GoalReceiptRow): string | null {
  const detail = row.detail ?? {};
  switch (row.event) {
    case "created": {
      const objective = typeof detail["objective"] === "string" ? (detail["objective"] as string) : "";
      return `goal created: "${truncateForActivityLine(objective)}"`;
    }
    case "status_changed": {
      const from = typeof detail["from"] === "string" ? (detail["from"] as string) : "?";
      const to = typeof detail["to"] === "string" ? (detail["to"] as string) : "?";
      const reason =
        typeof detail["reason"] === "string" && detail["reason"].length > 0 ? ` (${detail["reason"]})` : "";
      return `goal status: ${from} -> ${to}${reason}`;
    }
    case "objective_edited":
      return "goal objective edited";
    case "cleared":
      return "goal cleared";
    case "continuation_fired": {
      const kind = typeof detail["kind"] === "string" ? (detail["kind"] as string) : "continue";
      return kind === "budget_wrapup"
        ? "goal continuation fired (budget wrap-up)"
        : "goal continuation fired — autonomous turn, zero user input";
    }
    case "continuation_skipped":
    case "usage_recorded":
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Engine state
// ---------------------------------------------------------------------------

export interface ActivityFeedState {
  recentLines: Array<ActivityFeedLine & { sequence: number }>;
}

export interface ActivityFeedDeps {
  repoRoot?: string;
  receiptsDir?: string;
  totalityDir?: string;
  outageMarkerPath?: string;
  restartLogPath?: string;
  watchdogStatePath?: string;
  killReceiptsPath?: string;
  ledgerPath?: string;
  /** P0-B: persistent path->mtime watermark, survives a process restart (see loadWatermark /
   *  persistWatermark below). Defaults to state/activity-feed-watermark.json. */
  watermarkPath?: string;
  /** Overrides process.env -- tests inject a fixed environment. Read only for the
   *  headless-capture check, which decides whether this engine may PUBLISH its watermark. */
  env?: Record<string, string | undefined>;
  /** #576: diagnostic log for the tail-poll path's boot behavior (one row per pollTail() tick +
   *  one row per startActivityFeed()/freshTailState() call). Defaults to
   *  state/activity-feed-tailpoll-debug.jsonl. */
  tailPollDebugLogPath?: string;
  now?: () => number;
}

// ---------------------------------------------------------------------------
// P0-B: persistent watermark (path -> last-rendered mtime, survives a restart)
// ---------------------------------------------------------------------------

/** How long to hold a burst of newly-materialized files open before deciding whether it's one
 *  organic landing (render normally) or a bulk operation (render one summarized line). Kept short
 *  deliberately: files from a single `git checkout`/bulk-restore land across their fs-watch
 *  callbacks within single-digit ms of each other in practice (verified by the coalescing test
 *  below, which writes a burst synchronously in a loop), and this window sits underneath the
 *  existing RECEIPT_RETRY_DELAY_MS-based debounce test's own timing assumptions — it must never
 *  grow large enough to make a single organic receipt's placeholder line visibly late. */
export const BURST_COALESCE_MS = 60;

/** Keyed path+mtime (the cheap, default check — no IO beyond the stat already taken to decide
 *  whether a file is new). `hash` is a sha256 of the file's content, populated at settlement time
 *  and consulted ONLY as a fallback (queueForRender) when mtime disagrees with a KNOWN prior
 *  entry — never on a brand-new path, and never proactively. This exists because mtime alone
 *  misses two real cases: (a) this filesystem's mtimeMs carries sub-millisecond precision that
 *  utimesSync-class rewrites can't round-trip exactly, and (b) `git checkout` re-stamps a file's
 *  mtime to checkout-time even when its bytes are byte-identical to what was already rendered —
 *  both would look like "new" under mtime alone and reflood the pane with content it already
 *  showed once. */
export interface WatermarkEntry {
  mtimeMs: number;
  hash: string;
}

export type Watermark = Record<string, WatermarkEntry>;

/** Synchronous and loaded BEFORE any watcher arms -- this closes the exact race that caused the
 *  operator's replay flood: an async load racing the first watcher callbacks would treat
 *  already-rendered files as new during the gap. Never throws -- an absent/corrupt watermark file
 *  is exactly the same as a fresh install: no prior history, so nothing is dropped as "wrongly
 *  replayed" that was never actually seen. Individual malformed entries are dropped rather than
 *  invalidating the whole map. */
export function loadWatermarkSync(watermarkPath: string): Watermark {
  try {
    const raw = readFileSync(watermarkPath, "utf-8");
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const result: Watermark = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (
        value &&
        typeof value === "object" &&
        typeof (value as Record<string, unknown>)["mtimeMs"] === "number" &&
        typeof (value as Record<string, unknown>)["hash"] === "string"
      ) {
        result[key] = value as WatermarkEntry;
      }
    }
    return result;
  } catch {
    // absent or corrupt -- treated as empty, never a crash.
  }
  return {};
}

export interface ActivityFeedHandle {
  stop: () => void;
}

let _state: ActivityFeedState = { recentLines: [] };
let _stopFns: Array<() => void> = [];

let _nextSequence = 0;
/** Returns a shallow copy safe to read at any time; last-polled snapshot. */
export function getActivityFeedState(): ActivityFeedState {
  return _state;
}

interface TailState {
  byteOffset: number;
  lineBuffer: string;
}

function freshTailState(): TailState {
  return { byteOffset: 0, lineBuffer: "" };
}

/** Watchdog logs are historical event streams. On a fresh cockpit boot, begin at the current
 *  byte length so completed rows are not replayed into the new process's live activity feed.
 *  If the file does not exist yet, offset zero correctly observes its future creation. */
function tailStateAtCurrentEnd(filePath: string): TailState {
  try {
    return { byteOffset: statSync(filePath).size, lineBuffer: "" };
  } catch {
    return freshTailState();
  }
}

/** #576: The historical incident saw one `kill-receipts` row explode to ~65,000 duplicate
 *  renders in one tick. Boot baselining prevents completed-row replay; this cap remains a
 *  defense-in-depth backstop for any anomalous live append. If a single tick emits more than
 *  MAX_TAIL_LINES_PER_TICK lines, render ONE collapsed summary line instead of N individual
 *  ones (mirrors the receipts-side burst-coalescing in P0-B/#574). */
export const MAX_TAIL_LINES_PER_TICK = 20;

export interface PollTailResult {
  bytesRead: number;
  byteOffsetBefore: number;
  byteOffsetAfter: number;
  lineCount: number;
  capped: boolean;
}

/**
 * issue #1045 (operator report, 2026-07-24: 4.9GB cockpit working set correlated with the
 * 871-row watchdog restart log): the tail poller used to `readFile(filePath)` -- the WHOLE
 * file, every tick, forever -- then slice off the already-seen prefix. Bytes 0..byteOffset
 * were re-read from disk and re-allocated into a fresh Buffer on every single tick for the
 * life of the process, even though only the tail past byteOffset was ever new. On a
 * long-lived cockpit against a log that only grows (never rotated), that per-tick
 * allocation scales with the CURRENT file size, not with the tick's actual delta -- the
 * exact "tail-poll re-reads re-parsing the whole log each tick" defect class the issue
 * names as its prime suspect. Fixed: stat for the current size, then open+read ONLY the
 * `size - byteOffset` new bytes via a positional fd read -- the per-tick allocation is now
 * bounded by the tick's real delta, never by total file size.
 */
async function pollTail(
  filePath: string,
  state: TailState,
  onLine: (line: string) => void,
  onOverflow: (count: number) => void,
): Promise<PollTailResult | null> {
  let size: number;
  try {
    size = (await stat(filePath)).size;
  } catch {
    return null;
  }

  // File shrank beneath us (rotated/truncated/cleared) -- resync from the new start rather
  // than reading a negative-length range or silently missing the file's new content.
  if (size < state.byteOffset) {
    state.byteOffset = 0;
    state.lineBuffer = "";
  }
  if (size <= state.byteOffset) return null;

  const byteOffsetBefore = state.byteOffset;
  const readLength = size - state.byteOffset;
  let newBytes: Buffer;
  const handle = await open(filePath, "r").catch(() => null);
  if (handle === null) return null;
  try {
    const buf = Buffer.alloc(readLength);
    const { bytesRead } = await handle.read(buf, 0, readLength, state.byteOffset);
    newBytes = buf.subarray(0, bytesRead);
  } catch {
    return null;
  } finally {
    await handle.close().catch(() => {});
  }
  state.byteOffset += newBytes.length;

  const text = state.lineBuffer + newBytes.toString("utf-8");
  const rawLines = text.split("\n");
  state.lineBuffer = rawLines.pop() ?? "";
  const trimmedLines = rawLines.map((l) => l.trim()).filter((l) => l.length > 0);

  const capped = trimmedLines.length > MAX_TAIL_LINES_PER_TICK;
  if (capped) {
    onOverflow(trimmedLines.length);
  } else {
    for (const line of trimmedLines) onLine(line);
  }

  return {
    bytesRead: newBytes.length,
    byteOffsetBefore,
    byteOffsetAfter: state.byteOffset,
    lineCount: trimmedLines.length,
    capped,
  };
}

/**
 * Starts the activity-feed engine: a recursive receipts watcher, a flat totality-board watcher,
 * a planned-outage poll, and two tail-polled watchdog logs. If a previous engine is running it
 * is stopped and replaced (mirrors services/telemetry-watch.ts's own restart contract).
 */
export function startActivityFeed(deps: ActivityFeedDeps = {}): ActivityFeedHandle {
  for (const fn of _stopFns) fn();
  _stopFns = [];
  _state = { recentLines: [] };

  const repoRoot = deps.repoRoot ?? resolveEmberRepoRootOrCwd({}, "[activity-feed]");
  const receiptsDir =
    deps.receiptsDir ?? process.env["EMBER_ACTIVITY_RECEIPTS_DIR"] ?? path.join(repoRoot, "receipts");
  const totalityDir =
    deps.totalityDir ?? path.join(repoRoot, "scripts", "ember_totality", "receipts-totality");
  const cliStateDir = path.join(repoRoot, "tools", "ember-cli", "state");
  const outageMarkerPath = deps.outageMarkerPath ?? path.join(cliStateDir, "planned-outage.json");
  const restartLogPath =
    deps.restartLogPath ?? path.join(cliStateDir, "liveness-watchdog-restart-log.jsonl");
  const watchdogStatePath =
    deps.watchdogStatePath ?? path.join(cliStateDir, "liveness-watchdog-state.json");
  const ledgerPath = deps.ledgerPath ?? path.join(cliStateDir, "activity-ledger.jsonl");
  const watermarkPath = deps.watermarkPath ?? path.join(cliStateDir, "activity-feed-watermark.json");
  const tailPollDebugLogPath =
    deps.tailPollDebugLogPath ?? path.join(cliStateDir, "activity-feed-tailpoll-debug.jsonl");
  const clock = deps.now ?? Date.now.bind(Date);

  // #576: one row per pollTail() tick (not per emitted line) plus one row per
  // startActivityFeed()/freshTailState() call -- cheap under normal operation, and the only way
  // to directly observe the byte-offset/line-count pattern live on the next occurrence instead
  // of inferring it from ledger output after the fact. Best-effort, same discipline as the
  // ledger itself: a logging failure must never take the feed down.
  function logTailPollDiagnostic(entry: Record<string, unknown>): void {
    void appendLineWithDirs(
      tailPollDebugLogPath,
      JSON.stringify({ ts: new Date(clock()).toISOString(), pid: process.pid, ...entry }),
    ).catch(() => {});
  }
  logTailPollDiagnostic({ event: "startActivityFeed" });

  const seen = new BoundedSet<string>(MAX_TRACKED_PATHS);
  const rendered = new BoundedSet<string>(MAX_TRACKED_PATHS);

  // P0-B: loaded synchronously BEFORE either watcher arms (see loadWatermarkSync's comment) --
  // a file whose current mtime already matches this map was rendered in a PRIOR run and must
  // never replay just because the process restarted.
  const watermark: Watermark = loadWatermarkSync(watermarkPath);
  // A capture harness drives the real binary, and repl.ts mounts this engine unconditionally with
  // default deps -- so the harness advances the watermark at the MAIN repo root (the resolver
  // converges every worktree onto it) and the operator's NEXT cockpit boot reads that map and
  // suppresses replay. The receipts were "rendered" to a PTY nobody was reading. This is the
  // mirror of the heartbeat defect: there a dead cockpit looked alive, here unseen events look
  // seen. Reading the watermark is left alone -- only PUBLISHING it is the harm, and reading
  // keeps the instrument's behaviour faithful to the cockpit's.
  const suppressWatermarkWrites = isHeadlessCapture(deps.env);
  let watermarkDirty = false;
  function persistWatermark(): void {
    boundRecordKeys(watermark, MAX_TRACKED_PATHS);
    // Checked before the dirty flag and before the timer is armed, so a capture run schedules no
    // write at all rather than arming one that later no-ops.
    if (suppressWatermarkWrites) return;
    if (watermarkDirty) return; // a write is already scheduled; it will pick up the latest map
    watermarkDirty = true;
    setTimeout(() => {
      watermarkDirty = false;
      void writeFile(watermarkPath, JSON.stringify(watermark)).catch(() => {});
    }, 0).unref?.();
  }

  function renderEvent(event: { source: ActivityFeedSource; text: string; path?: string }): void {
    const line: ActivityFeedLine = {
      ts: new Date(clock()).toISOString(),
      source: event.source,
      text: event.text,
      path: event.path,
    };
    _state.recentLines.push({ ...line, sequence: ++_nextSequence });
    if (_state.recentLines.length > RING_BUFFER_CAP) _state.recentLines.shift();

    // The ledger is the machine-checkable half — append-only, written ONLY for a line that was
    // actually rendered (never speculative). A ledger-write failure must never take the feed
    // down with it.
    void appendLineWithDirs(
      ledgerPath,
      JSON.stringify({ ts: line.ts, source: line.source, path: line.path ?? null, line: line.text }),
    ).catch(() => {});
  }

  /** P0-B: writes the watermark using a FRESH stat at the moment a file's processing is fully
   *  settled (success or terminally-unparsable) — never at first sight. A receipt is commonly
   *  written partial-then-final (temp write, rename, or truncate-then-append); watermarking at
   *  first sight would freeze on a mid-write mtime, and a later restart would see the file's true
   *  final mtime as "different" and wrongly replay it. Watermarking at settlement time means the
   *  stored mtime always reflects the on-disk state we actually finished processing.
   *  `knownContent`, when the caller already has the bytes in hand (the success path in
   *  debouncedRenderFromFile), avoids a second read purely for hashing. */
  function settleWatermark(absPath: string, knownContent?: string): void {
    void (async () => {
      try {
        const info = await stat(absPath);
        const content = knownContent ?? (await readFile(absPath, "utf-8").catch(() => null));
        const hash = content != null ? createHash("sha256").update(content).digest("hex") : "";
        watermark[absPath] = { mtimeMs: info.mtimeMs, hash };
        persistWatermark();
      } catch {
        // file vanished before the re-stat -- nothing durable to persist for it.
      }
    })();
  }

  /** Shared "a new JSON file landed" handler for both receipts and board runs: render a
   *  placeholder immediately if the file can't be parsed yet, retry once after
   *  RECEIPT_RETRY_DELAY_MS, then render the final line either way. */
  function debouncedRenderFromFile(
    absPath: string,
    source: ActivityFeedSource,
    formatSuccess: (parsed: unknown) => string,
  ): void {
    if (rendered.has(absPath) || seen.has(absPath)) return;
    seen.add(absPath);

    const attempt = async (isRetry: boolean): Promise<void> => {
      let raw: string | undefined;
      try {
        raw = await readFile(absPath, "utf-8");
        const parsed = JSON.parse(raw);
        renderEvent({ source, text: formatSuccess(parsed), path: absPath });
        rendered.add(absPath);
        settleWatermark(absPath, raw);
      } catch {
        if (!isRetry) {
          renderEvent({ source, text: formatPlaceholderLine(absPath), path: absPath });
          const timer = setTimeout(() => {
            void attempt(true);
          }, RECEIPT_RETRY_DELAY_MS);
          timer.unref?.();
        } else {
          renderEvent({ source, text: formatUnparsableLine(absPath), path: absPath });
          rendered.add(absPath);
          settleWatermark(absPath, raw);
        }
      }
    };
    void attempt(false);
  }

  // -- P0-B: watermark gate + burst-coalescing buffer ----------------------
  // A raw watcher callback firing for a JSON file never renders directly anymore -- it first
  // passes through here, which (a) drops anything under an excluded/fixture/plugin tree, (b)
  // drops anything whose mtime already matches the persisted watermark (a restart re-arming the
  // watcher, or the OS re-firing a recursive watch on startup, must never replay old receipts as
  // new), then (c) buffers genuinely-new files for BURST_COALESCE_MS before deciding whether this
  // is one organic landing (render normally, with the existing placeholder/retry path) or a bulk
  // operation like a `git checkout` of many tracked receipts at once (render ONE summarized line).
  const pendingBurst = new Map<string, { source: ActivityFeedSource; formatSuccess: (parsed: unknown) => string }>();
  let burstTimer: ReturnType<typeof setTimeout> | null = null;

  function flushBurst(): void {
    burstTimer = null;
    const entries = [...pendingBurst.entries()];
    pendingBurst.clear();
    if (entries.length === 0) return;

    // Grouped by source: a receipts-flood burst and a (rare) coincident board render in the same
    // window must never merge into one mislabeled "receipts materialized" line — each source's
    // entries are flushed independently, single files via the normal placeholder/retry path,
    // multi-file groups via one coalesced summary per source.
    const bySource = new Map<ActivityFeedSource, Array<[string, (parsed: unknown) => string]>>();
    for (const [absPath, { source, formatSuccess }] of entries) {
      const group = bySource.get(source) ?? [];
      group.push([absPath, formatSuccess]);
      bySource.set(source, group);
    }

    for (const [source, group] of bySource) {
      if (group.length === 1) {
        const [absPath, formatSuccess] = group[0]!;
        debouncedRenderFromFile(absPath, source, formatSuccess);
        continue;
      }
      renderEvent({ source, text: formatBulkMaterializationLine(group.map(([p]) => p)) });
      for (const [absPath] of group) {
        rendered.add(absPath); // never individually re-rendered later by a delayed retry path
        settleWatermark(absPath); // this IS these files' settlement point — watermark now, not before
      }
    }
  }

  function queueForRender(
    absPath: string,
    source: ActivityFeedSource,
    formatSuccess: (parsed: unknown) => string,
  ): void {
    if (isExcludedReceiptPath(absPath)) return;
    if (rendered.has(absPath) || seen.has(absPath) || pendingBurst.has(absPath)) return;

    // The watermark is only ever WRITTEN at settlement time (settleWatermark, above), never here.
    // Writing it at first sight would let a partial-then-final write freeze the wrong (mid-write)
    // mtime; see settleWatermark's comment.
    void stat(absPath)
      .then(async (info) => {
        const prior = watermark[absPath];
        if (prior && prior.mtimeMs === info.mtimeMs) return; // cheap match -- settled in a PRIOR run

        if (prior) {
          // mtime disagrees with a KNOWN prior settlement -- fall back to a content hash before
          // treating this as new (the ONLY place this engine pays hashing IO, and only for a path
          // it has already rendered once before): a mtime-granularity miss or a `git checkout`
          // re-stamping an unchanged receipt's timestamp must not replay it.
          const content = await readFile(absPath, "utf-8").catch(() => null);
          if (content != null) {
            const hash = createHash("sha256").update(content).digest("hex");
            if (hash === prior.hash) {
              watermark[absPath] = { mtimeMs: info.mtimeMs, hash }; // refresh mtime only
              persistWatermark();
              return;
            }
          }
        }

        pendingBurst.set(absPath, { source, formatSuccess });
        if (burstTimer) clearTimeout(burstTimer);
        burstTimer = setTimeout(flushBurst, BURST_COALESCE_MS);
        burstTimer.unref?.();
      })
      .catch(() => {
        // stat race (file already gone) -- nothing to render.
      });
  }

  // -- Goal-organ session logs (ember issue #211 §7 delta 4) --------------
  // Discovered dynamically (one file per session, created lazily on first goal use) via the
  // SAME recursive receiptsWatcher below -- never a separate directory watcher, which would
  // have to handle the goal-sessions dir not existing yet at boot (the common case: most
  // sessions never touch /goal). Each discovered path gets its own TailState and is polled
  // every tick alongside the watchdog logs (see tailInterval below).
  const goalTailStates = new Map<string, TailState>();

  // -- Receipts watcher (recursive) ----------------------------------------
  let receiptsWatcher: FSWatcher | null = null;
  try {
    receiptsWatcher = watch(receiptsDir, { recursive: true }, (_eventType, filename) => {
      if (!filename) return;
      const name = filename.toString();
      if (isGoalSessionRelativePath(name)) {
        const abs = path.join(receiptsDir, name);
        if (!goalTailStates.has(abs)) {
          setBoundedMapEntry(goalTailStates, abs, freshTailState(), MAX_GOAL_TAIL_STATES);
        }
        return;
      }
      if (!name.endsWith(".json")) return;
      const abs = path.join(receiptsDir, name);
      queueForRender(abs, "receipt", (parsed) => formatReceiptLine(abs, parsed));
    });
  } catch {
    receiptsWatcher = null; // recursive watch unsupported/unavailable here — fail open, no crash
  }
  if (receiptsWatcher) {
    const w = receiptsWatcher;
    _stopFns.push(() => w.close());
  }

  // -- Totality board watcher (flat dir) -----------------------------------
  let boardWatcher: FSWatcher | null = null;
  try {
    boardWatcher = watch(totalityDir, (_eventType, filename) => {
      if (!filename) return;
      const name = filename.toString();
      if (!name.endsWith(".json")) return;
      const abs = path.join(totalityDir, name);
      queueForRender(
        abs,
        "board",
        (parsed) => formatBoardLine(abs, parsed) ?? `totality board rendered: ${path.basename(abs)}`,
      );
    });
  } catch {
    boardWatcher = null;
  }
  if (boardWatcher) {
    const w = boardWatcher;
    _stopFns.push(() => w.close());
  }

  // -- Planned-outage marker poll -------------------------------------------
  let lastEffectiveMarker: OutageMarker | null = null;
  const outageInterval = setInterval(() => {
    void (async () => {
      let raw: string | null = null;
      try {
        raw = await readFile(outageMarkerPath, "utf-8");
      } catch {
        raw = null;
      }
      // #475: PS-written marker files can carry a UTF-8 BOM (Windows PowerShell 5.1's
      // `-Encoding utf8` default) -- stripped here so a BOM never silently degrades an
      // active marker into "unparsable JSON" -> treated as absent.
      const parsed = raw ? parseOutageMarker(stripBom(raw)) : null;
      const result = classifyOutageTransition(lastEffectiveMarker, parsed, clock());
      if (result.transition !== "none" && result.text) {
        renderEvent({ source: "outage", text: result.text, path: outageMarkerPath });
      }
      lastEffectiveMarker = result.effective;
    })();
  }, OUTAGE_POLL_INTERVAL_MS);
  _stopFns.push(() => clearInterval(outageInterval));

  // -- Watchdog: restart-log + kill-receipts (tail-polled JSONL) -----------
  const restartTail = tailStateAtCurrentEnd(restartLogPath);
  logTailPollDiagnostic({ event: "freshTailState", file: "restart-log" });
  let resolvedKillReceiptsPath = deps.killReceiptsPath;
  let killTail = resolvedKillReceiptsPath ? tailStateAtCurrentEnd(resolvedKillReceiptsPath) : null;
  if (killTail) logTailPollDiagnostic({ event: "freshTailState", file: "kill-receipts" });

  const resolveKillReceiptsPath = (async (): Promise<void> => {
    if (resolvedKillReceiptsPath) return;
    try {
      const raw = await readFile(watchdogStatePath, "utf-8");
      const parsed = JSON.parse(raw);
      const candidate =
        parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>)["kill_receipts_path"] : undefined;
      if (typeof candidate === "string" && candidate.length > 0) {
        resolvedKillReceiptsPath = candidate;
      }
    } catch {
      // watchdog-state.json absent/unreadable — treated as "no kill_receipts_path", never a crash.
    }
    if (!resolvedKillReceiptsPath) {
      resolvedKillReceiptsPath = process.env["EMBER_KILL_RECEIPTS_PATH"] || undefined;
    }
    if (resolvedKillReceiptsPath && killTail === null) {
      killTail = tailStateAtCurrentEnd(resolvedKillReceiptsPath);
      logTailPollDiagnostic({ event: "freshTailState", file: "kill-receipts" });
    }
  })();

  /** #576 containment: a tick whose line count exceeds MAX_TAIL_LINES_PER_TICK renders ONE
   *  collapsed summary line instead of N individual ones -- independent of root-causing why the
   *  tick ballooned (see MAX_TAIL_LINES_PER_TICK's comment). The diagnostic log entry ALWAYS
   *  fires (capped or not), so a below-threshold anomaly is still visible in the debug log even
   *  when it doesn't trip the visible-pane cap. `source` defaults to "watchdog" (the original two
   *  tail-polled logs); goal-session tail-polling below passes "goal" so an overflow on THAT log
   *  reads as a goal-organ anomaly, not a watchdog one -- text stays `${count} ${source} events
   *  collapsed...`, so the pre-existing "watchdog events collapsed" wording is unchanged. */
  function makeTailOverflowHandler(sourcePath: string, source: ActivityFeedSource = "watchdog") {
    return (count: number): void => {
      renderEvent({
        source,
        text: `${count} ${source} events collapsed (tail-poll anomaly)`,
        path: sourcePath,
      });
    };
  }

  /** issue #616 bar 3: a watchdog-log line the pure formatter cannot map confidently (null),
   *  or that isn't parseable JSON at all, renders VERBATIM — honest passthrough beats confident
   *  paraphrase, and beats silent dropping (a dropped kill receipt is invisible to the operator's
   *  audit channel). Never crashes the feed. */
  function renderWatchdogLogLine(line: string, sourcePath: string): void {
    let text: string | null = null;
    try {
      const row = JSON.parse(line) as WatchdogRow;
      text = formatWatchdogLine(row);
    } catch {
      text = null; // unparseable — falls through to the verbatim path below
    }
    renderEvent({
      source: "watchdog",
      text: text ?? formatWatchdogFallbackLine(line),
      path: sourcePath,
    });
  }

  const runTailTick = createSingleFlightRunner();
  const tailInterval = setInterval(() => {
    runTailTick(async () => {
      const pending: Array<Promise<unknown>> = [];
      pending.push(
        pollTail(
          restartLogPath,
          restartTail,
          (line) => renderWatchdogLogLine(line, restartLogPath),
          makeTailOverflowHandler(restartLogPath),
        ).then((result) => {
          if (result) logTailPollDiagnostic({ event: "pollTail", file: "restart-log", ...result });
        }),
      );

    if (resolvedKillReceiptsPath && killTail) {
      const killPath = resolvedKillReceiptsPath;
      pending.push(
        pollTail(
          killPath,
          killTail,
          (line) => renderWatchdogLogLine(line, killPath),
          makeTailOverflowHandler(killPath),
        ).then((result) => {
          if (result) logTailPollDiagnostic({ event: "pollTail", file: "kill-receipts", ...result });
        }),
      );
    }

    // -- Goal-organ session logs (ember issue #211 §7 delta 4) -------------
    // One TailState per discovered receipts/goal-sessions/*.jsonl path (registered by the
    // receiptsWatcher callback above the moment the file is created). A file discovered THIS
    // tick starts at byte offset 0, so its very first poll already sees whatever was written
    // between creation and now -- same "boot replay is correct, not a bug" contract the
    // watchdog logs rely on (see freshTailState's callers).
    for (const [absPath, state] of goalTailStates) {
      pending.push(
        pollTail(
          absPath,
          state,
          (line) => {
          try {
            const row = JSON.parse(line) as GoalReceiptRow;
            const text = formatGoalReceiptLine(row);
            if (text) renderEvent({ source: "goal", text, path: absPath });
          } catch {
            // malformed row — skip, never crash the feed
          }
          },
          makeTailOverflowHandler(absPath, "goal"),
        ).then((result) => {
          if (result) logTailPollDiagnostic({ event: "pollTail", file: "goal-session", path: absPath, ...result });
        }),
      );
    }
    await Promise.allSettled(pending);
    });
  }, TAIL_POLL_INTERVAL_MS);
  _stopFns.push(() => clearInterval(tailInterval));
  void resolveKillReceiptsPath;

  return {
    stop: () => {
      for (const fn of _stopFns) fn();
      _stopFns = [];
    },
  };
}

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
//
// Fabricated/synthetic events are constitutionally banned — this engine has no "demo" or
// "sample" event path. Every RENDERED event (including the "(receipt landing…)" placeholder for
// a still-writing file) is appended to state/activity-ledger.jsonl, so "nothing happened" is
// machine-checkable instead of resting on the operator's own eyes.

import { watch, type FSWatcher } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { appendLineWithDirs } from "../utils/file-operations.ts";
import type { ActivityFeedLine, ActivityFeedSource } from "../components/activity-feed-pane.ts";

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
  const nextExpired = nextRaw ? Date.parse(nextRaw.expires) <= nowMs : true;
  const nextEffective = nextRaw && !nextExpired ? nextRaw : null;

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

/** Handles both row shapes the watchdog emits: restart-log rows ({target, event, ...}) and
 *  kill-receipt rows ({script, pids, reason, ...}). Returns null for a row it can't map to a
 *  sensible line (never a crash, never a blank/garbled line). */
export function formatWatchdogLine(row: WatchdogRow): string | null {
  if (typeof row["event"] === "string") {
    const target = typeof row["target"] === "string" ? row["target"] : "target";
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
  if (Array.isArray(row["pids"]) || typeof row["reason"] === "string") {
    return `server killed by watchdog (${row["reason"] ?? "reason unavailable"})`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Engine state
// ---------------------------------------------------------------------------

export interface ActivityFeedState {
  recentLines: ActivityFeedLine[];
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
  now?: () => number;
}

export interface ActivityFeedHandle {
  stop: () => void;
}

let _state: ActivityFeedState = { recentLines: [] };
let _stopFns: Array<() => void> = [];

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

async function pollTail(
  filePath: string,
  state: TailState,
  onLine: (line: string) => void,
): Promise<void> {
  let buf: Buffer;
  try {
    buf = await readFile(filePath);
  } catch {
    return;
  }
  if (buf.length <= state.byteOffset) return;

  const newBytes = buf.slice(state.byteOffset);
  state.byteOffset = buf.length;

  const text = state.lineBuffer + newBytes.toString("utf-8");
  const lines = text.split("\n");
  state.lineBuffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed) onLine(trimmed);
  }
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
  const clock = deps.now ?? Date.now.bind(Date);

  const seen = new Set<string>();
  const rendered = new Set<string>();

  function renderEvent(event: { source: ActivityFeedSource; text: string; path?: string }): void {
    const line: ActivityFeedLine = {
      ts: new Date(clock()).toISOString(),
      source: event.source,
      text: event.text,
      path: event.path,
    };
    _state.recentLines.push(line);
    if (_state.recentLines.length > RING_BUFFER_CAP) _state.recentLines.shift();

    // The ledger is the machine-checkable half — append-only, written ONLY for a line that was
    // actually rendered (never speculative). A ledger-write failure must never take the feed
    // down with it.
    void appendLineWithDirs(
      ledgerPath,
      JSON.stringify({ ts: line.ts, source: line.source, path: line.path ?? null, line: line.text }),
    ).catch(() => {});
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
      try {
        const raw = await readFile(absPath, "utf-8");
        const parsed = JSON.parse(raw);
        renderEvent({ source, text: formatSuccess(parsed), path: absPath });
        rendered.add(absPath);
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
        }
      }
    };
    void attempt(false);
  }

  // -- Receipts watcher (recursive) ----------------------------------------
  let receiptsWatcher: FSWatcher | null = null;
  try {
    receiptsWatcher = watch(receiptsDir, { recursive: true }, (_eventType, filename) => {
      if (!filename) return;
      const name = filename.toString();
      if (!name.endsWith(".json")) return;
      const abs = path.join(receiptsDir, name);
      debouncedRenderFromFile(abs, "receipt", (parsed) => formatReceiptLine(abs, parsed));
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
      debouncedRenderFromFile(
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
      const parsed = raw ? parseOutageMarker(raw) : null;
      const result = classifyOutageTransition(lastEffectiveMarker, parsed, clock());
      if (result.transition !== "none" && result.text) {
        renderEvent({ source: "outage", text: result.text, path: outageMarkerPath });
      }
      lastEffectiveMarker = result.effective;
    })();
  }, OUTAGE_POLL_INTERVAL_MS);
  _stopFns.push(() => clearInterval(outageInterval));

  // -- Watchdog: restart-log + kill-receipts (tail-polled JSONL) -----------
  const restartTail = freshTailState();
  const killTail = freshTailState();
  let resolvedKillReceiptsPath = deps.killReceiptsPath;

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
  })();

  const tailInterval = setInterval(() => {
    void pollTail(restartLogPath, restartTail, (line) => {
      try {
        const row = JSON.parse(line) as WatchdogRow;
        const text = formatWatchdogLine(row);
        if (text) renderEvent({ source: "watchdog", text, path: restartLogPath });
      } catch {
        // malformed row — skip, never crash the feed
      }
    });
    if (resolvedKillReceiptsPath) {
      const killPath = resolvedKillReceiptsPath;
      void pollTail(killPath, killTail, (line) => {
        try {
          const row = JSON.parse(line) as WatchdogRow;
          const text = formatWatchdogLine(row);
          if (text) renderEvent({ source: "watchdog", text, path: killPath });
        } catch {
          // malformed row — skip
        }
      });
    }
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

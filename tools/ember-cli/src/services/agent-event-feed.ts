// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Journal-bound agent event custody for the C4 operator surface (#485 rung 2).
// This module renders only rows that were read from the configured JSONL journal; it has no
// heartbeat, demo, timer, or synthetic-event path.
import { readFile } from "node:fs/promises";

export const AGENT_EVENT_KINDS = ["choose", "act", "tool", "verify", "reply", "reasoning-status"] as const;
export type AgentEventKind = (typeof AGENT_EVENT_KINDS)[number];
export const AGENT_EVENT_SCHEMA_VERSION = "ember-agent-event-v1" as const;
export const AGENT_EVENT_RING_CAP = 200;
export const AGENT_EVENT_POLL_INTERVAL_MS = 500;

export interface AgentJournalEvent {
  schemaVersion: typeof AGENT_EVENT_SCHEMA_VERSION;
  ts: string;
  runId: string;
  seq: number;
  kind: AgentEventKind;
  payload: { summary: string; [key: string]: unknown };
}

export type AgentEventChannelStatus = "UNKNOWN" | "ONLINE" | "OFFLINE";

export interface AgentEventFeedState {
  events: AgentJournalEvent[];
  channelStatus: AgentEventChannelStatus;
}

function isAgentEventKind(value: unknown): value is AgentEventKind {
  return typeof value === "string" && (AGENT_EVENT_KINDS as readonly string[]).includes(value);
}

/** Parse one journal row; malformed or untrusted rows are rejected without defaults. */
export function parseAgentJournalLine(line: string): AgentJournalEvent | undefined {
  let parsed: unknown;
  try { parsed = JSON.parse(line); } catch { return undefined; }
  if (!parsed || typeof parsed !== "object") return undefined;
  const row = parsed as Record<string, unknown>;
  if (row["schema_version"] !== AGENT_EVENT_SCHEMA_VERSION) return undefined;
  const ts = row["ts"];
  const runId = row["run_id"];
  const seq = row["seq"];
  const kind = row["kind"];
  const payload = row["payload"];
  if (typeof ts !== "string" || !Number.isFinite(Date.parse(ts))) return undefined;
  if (typeof runId !== "string" || runId.length === 0) return undefined;
  if (typeof seq !== "number" || !Number.isInteger(seq) || seq < 1) return undefined;
  if (!isAgentEventKind(kind) || !payload || typeof payload !== "object" || Array.isArray(payload)) return undefined;
  const summary = (payload as Record<string, unknown>)["summary"];
  if (typeof summary !== "string" || summary.trim().length === 0) return undefined;
  return { schemaVersion: AGENT_EVENT_SCHEMA_VERSION, ts, runId, seq, kind, payload: payload as { summary: string; [key: string]: unknown } };
}

export function parseAgentJournal(text: string): AgentJournalEvent[] {
  const events: AgentJournalEvent[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const event = parseAgentJournalLine(line);
    if (!event) continue;
    const key = `${event.runId}:${event.seq}`;
    if (seen.has(key)) continue;
    seen.add(key);
    events.push(event);
  }
  return events.sort((left, right) => left.seq - right.seq || Date.parse(left.ts) - Date.parse(right.ts));
}

/** Select one latest journal run; never merges rows across run IDs. */
export function selectAgentEventRun(events: AgentJournalEvent[], maxEvents: number = 12): AgentJournalEvent[] {
  if (maxEvents <= 0 || events.length === 0) return [];
  const latest = events.reduce((chosen, event) => {
    if (!chosen) return event;
    const chosenTime = Date.parse(chosen.ts);
    const eventTime = Date.parse(event.ts);
    return eventTime > chosenTime || (eventTime === chosenTime && event.seq > chosen.seq) ? event : chosen;
  }, undefined as AgentJournalEvent | undefined);
  if (!latest) return [];
  return events.filter((event) => event.runId === latest.runId).sort((left, right) => left.seq - right.seq).slice(-maxEvents);
}

export function formatAgentEventLine(event: AgentJournalEvent): string {
  return `[${event.kind}] ${event.runId}#${event.seq} ${event.payload.summary}`;
}

export async function readAgentJournal(path: string): Promise<AgentJournalEvent[]> {
  try { return parseAgentJournal(await readFile(path, "utf8")); } catch { return []; }
}

export interface AgentEventWatchHandle { stop: () => void; }
export interface AgentEventWatchDeps { journalPath: string; pollIntervalMs?: number; maxEvents?: number; }

let state: AgentEventFeedState = { events: [], channelStatus: "UNKNOWN" };
let timer: ReturnType<typeof setInterval> | undefined;

export function getAgentEventFeedState(): AgentEventFeedState { return state; }

export function startAgentEventWatch(deps: AgentEventWatchDeps): AgentEventWatchHandle {
  if (timer) clearInterval(timer);
  state = { events: [], channelStatus: "UNKNOWN" };
  const poll = async (): Promise<void> => {
    try {
      const events = parseAgentJournal(await readFile(deps.journalPath, "utf8"));
      state = { events: events.slice(-Math.max(1, deps.maxEvents ?? AGENT_EVENT_RING_CAP)), channelStatus: "ONLINE" };
    } catch { state = { ...state, channelStatus: "OFFLINE" }; }
  };
  void poll();
  timer = setInterval(() => { void poll(); }, deps.pollIntervalMs ?? AGENT_EVENT_POLL_INTERVAL_MS);
  return { stop: () => { if (timer) clearInterval(timer); timer = undefined; } };
}

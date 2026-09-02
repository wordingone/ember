// telemetry.ts — OTel event logging, Perfetto trace writing, and session tracing.

import { createHash } from 'crypto';
import { AsyncLocalStorage } from 'async_hooks';
import { join } from 'path';
import { getEmberConfigHomeDir } from './utils/env-detection.ts';

// ---- Constants ----

export const TRACER_NAME = 'com.ember.ember.tracing';
export const TRACER_VERSION = '1.0.0';
export const MAX_PERFETTO_EVENTS = 100_000;
export const BETA_TRACING_CONTENT_MAX_BYTES = 60_000;

// ---- Types ----

export interface OTelEventRecord {
  name: string;
  eventSequence: number;
  promptContent?: string;
  redacted?: boolean;
  hasPromptContent?: boolean;
  attributes?: Record<string, unknown>;
}

export interface PerfettoEvent {
  ph: string;
  name: string;
  ts: number;
  id?: string;
}

// ---- Perfetto trace file path ----

export function getPerfettoTraceFilePath(sessionId: string): string {
  return join(getEmberConfigHomeDir(), 'traces', `trace-${sessionId}.json`);
}

// ---- OTel event logging ----

type OTelEventSink = (record: OTelEventRecord) => void;

let _otelSink: OTelEventSink = () => undefined;
let _otelSequence = 0;

export function setOTelEventSink(sink: OTelEventSink): void {
  _otelSink = sink;
}

export function resetOTelSequence(): void {
  _otelSequence = 0;
}

interface LogOTelEventOpts {
  name: string;
  promptContent?: string;
  hasPromptContent?: boolean;
  attributes?: Record<string, unknown>;
}

/**
 * Logs an OTel event through the current sink.
 * Prompt content is redacted unless OTEL_LOG_USER_PROMPTS is set.
 */
export function logOTelEvent(opts: LogOTelEventOpts): void {
  _otelSequence += 1;

  const record: OTelEventRecord = {
    name: opts.name,
    eventSequence: _otelSequence,
  };

  if (opts.hasPromptContent === true && opts.promptContent !== undefined) {
    if (process.env['OTEL_LOG_USER_PROMPTS']) {
      record.promptContent = opts.promptContent;
    } else {
      record.promptContent = '[REDACTED]';
      record.redacted = true;
    }
  }

  if (opts.hasPromptContent !== undefined) {
    record.hasPromptContent = opts.hasPromptContent;
  }

  if (opts.attributes !== undefined) {
    record.attributes = opts.attributes;
  }

  _otelSink(record);
}

// ---- PerfettoTraceWriter ----

const EVICT_FRACTION = 0.5; // evict oldest 50% when cap exceeded
const STALE_SPAN_THRESHOLD_US = 30 * 60 * 1_000_000; // 30 minutes in microseconds

interface OpenSpan {
  name: string;
  ts: number; // microseconds
  id?: string;
}

/**
 * Writes Perfetto-format trace events for a session.
 * Evicts the oldest 50% of events when MAX_PERFETTO_EVENTS + 1 events are added.
 * Tracks B/E duration spans and can clean up stale open spans.
 */
export class PerfettoTraceWriter {
  private readonly sessionId: string;
  private _events: PerfettoEvent[] = [];
  private readonly _openSpans = new Map<string, OpenSpan>();

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  get eventCount(): number {
    return this._events.length;
  }

  get openSpanCount(): number {
    return this._openSpans.size;
  }

  addEvent(event: PerfettoEvent): void {
    this._events.push(event);

    // Track B/E spans
    if (event.ph === 'B') {
      const key = event.id ?? event.name;
      this._openSpans.set(key, { name: event.name, ts: event.ts, id: event.id });
    } else if (event.ph === 'E') {
      const key = event.id ?? event.name;
      this._openSpans.delete(key);
    }

    // Evict when over capacity: keep newest 50%, drop oldest 50%
    if (this._events.length > MAX_PERFETTO_EVENTS) {
      const keepCount = Math.floor(MAX_PERFETTO_EVENTS * EVICT_FRACTION);
      this._events = this._events.slice(this._events.length - keepCount);
    }
  }

  /** Removes B-phase spans whose start timestamp is older than 30 minutes. */
  cleanupStaleSpans(nowMs: number): void {
    const nowUs = nowMs * 1000;
    for (const [key, span] of this._openSpans) {
      if (nowUs - span.ts > STALE_SPAN_THRESHOLD_US) {
        this._openSpans.delete(key);
      }
    }
  }

  /** Returns a shallow copy of the internal event list. */
  getEvents(): readonly PerfettoEvent[] {
    return [...this._events];
  }

  // Suppress unused-private-field lint; sessionId is used for future file-write integration
  private _unused(): string { return this.sessionId; }
}

// ---- BetaSessionTracer ----

interface BetaSessionTracerOpts {
  isAntUser: boolean;
  httpPost?: (url: string, body: string) => Promise<void>;
}

interface RecordOpts {
  name: string;
  content: string;
  isThinkingBlock?: boolean;
}

/**
 * Traces detailed session events and sends them to a remote endpoint.
 *
 * - Always active for internal (ant) users
 * - External users need ENABLE_BETA_TRACING_DETAILED + BETA_TRACING_ENDPOINT
 * - Deduplicates events by content hash; each unique (name, content) pair sent once
 * - External users: thinking blocks are excluded
 */
export class BetaSessionTracer {
  private readonly isAntUser: boolean;
  private readonly httpPost: ((url: string, body: string) => Promise<void>) | undefined;
  private readonly _seenHashes = new Set<string>();

  constructor(opts: BetaSessionTracerOpts) {
    this.isAntUser = opts.isAntUser;
    this.httpPost = opts.httpPost;
  }

  isActive(): boolean {
    if (this.isAntUser) return true;
    return (
      !!process.env['ENABLE_BETA_TRACING_DETAILED'] &&
      !!process.env['BETA_TRACING_ENDPOINT']
    );
  }

  get seenHashCount(): number {
    return this._seenHashes.size;
  }

  async record(opts: RecordOpts): Promise<void> {
    if (!this.isActive()) return;

    // External users: skip thinking blocks
    if (!this.isAntUser && opts.isThinkingBlock) return;

    // Deduplicate by content hash
    const hash = createHash('sha256')
      .update(opts.name + '\x00' + opts.content)
      .digest('hex');

    if (this._seenHashes.has(hash)) return;
    this._seenHashes.add(hash);

    const endpoint = process.env['BETA_TRACING_ENDPOINT'];
    if (!endpoint || !this.httpPost) return;

    const body = JSON.stringify({ name: opts.name, content: opts.content });
    try {
      await this.httpPost(endpoint, body);
    } catch {
      // Tracing failures must never propagate to callers
    }
  }
}

// ---- Plugin telemetry ----

/**
 * Returns a 16-character lowercase hex hash of `pluginId`.
 * Deterministic: the same input always yields the same output.
 */
export function hashPluginId(pluginId: string): string {
  return createHash('sha256').update(pluginId).digest('hex').slice(0, 16);
}

/**
 * Classifies a plugin as 'ember' (first-party) or 'third-party'.
 * First-party: ends with @builtin or @ember-plugins-official.
 */
export function getTelemetryPluginScope(pluginId: string): 'ember' | 'third-party' {
  if (pluginId.endsWith('@builtin') || pluginId.endsWith('@ember-plugins-official')) {
    return 'ember';
  }
  return 'third-party';
}

/**
 * Records a plugin telemetry event via the current OTel sink.
 * Third-party plugins are reported as 'third-party'; ember plugins get a hashed ID.
 */
export function recordPluginTelemetryEvent(opts: {
  type: string;
  pluginId: string;
}): void {
  const scope = getTelemetryPluginScope(opts.pluginId);
  const reportedId = scope === 'third-party' ? 'third-party' : hashPluginId(opts.pluginId);

  logOTelEvent({
    name: `plugin.${opts.type}`,
    attributes: { pluginId: reportedId, scope },
  });
}

// ---- AsyncLocalStorage contexts ----

interface InteractionContext {
  promptId: string;
  agentId: string;
  querySource: string;
}

interface ToolContext {
  toolName: string;
  toolCallId: string;
}

export const interactionStorage = new AsyncLocalStorage<InteractionContext>();
export const toolStorage = new AsyncLocalStorage<ToolContext>();

/** Runs `fn` with the given interaction context accessible via interactionStorage.getStore(). */
export function runWithInteractionContext<T>(
  ctx: InteractionContext,
  fn: () => Promise<T>,
): Promise<T> {
  return interactionStorage.run(ctx, fn);
}

/** Runs `fn` with the given tool context accessible via toolStorage.getStore(). */
export function runWithToolContext<T>(
  ctx: ToolContext,
  fn: () => Promise<T>,
): Promise<T> {
  return toolStorage.run(ctx, fn);
}

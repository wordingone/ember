// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// cli/headless-repl.ts — headless agent loop for non-interactive sessions.
// Drives the query engine from an IO surface without a TUI. Used by the
// -p / --print flag path in process-entry.ts.
// Bundle: cli/headless-repl.ts (lines 308342–308540)

import { QueryEngine, type QueryEvent } from "../core/query-engine.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { LoopDepsOverrides } from "../query/query-loop-support.ts";

// ---------------------------------------------------------------------------
// Public option type — exported; test + process-entry import it
// ---------------------------------------------------------------------------

export interface HeadlessReplOptions {
  systemPrompt?:       string;
  appendSystemPrompt?: string;
  userSpecifiedModel?: string;
  fallbackModel?:      string;
  thinkingConfig?:     unknown;
  maxTurns?:           number;
  maxBudgetUsd?:       number;
  taskBudget?:         unknown;
  jsonSchema?:         unknown;
  verbose?:            boolean;
  replayUserMessages?: boolean;
}

// ---------------------------------------------------------------------------
// IOSurface — structural shape of the surface passed to headlessRepl
// ---------------------------------------------------------------------------

interface IOSurface {
  write(event: QueryEvent): void;
  prependUserMessage(content: string): void;
  [Symbol.asyncIterator](): AsyncIterator<unknown>;
}

// ---------------------------------------------------------------------------
// Wire message (minimal structural type consumed from the IO surface)
// ---------------------------------------------------------------------------

interface WireMessage {
  type:       string;
  uuid?:      string;
  content?:   unknown;
  workload?:  string;
  isMeta?:    boolean;
}

// ---------------------------------------------------------------------------
// Module constants
// ---------------------------------------------------------------------------

const MAX_UUID_CACHE = 10_000;

// Events that are never forwarded to the output surface or to callers.
const FILTERED_EVENT_TYPES = new Set<string>([
  "control_response",
  "control_request",
  "system_state_change",
  "stream_event",
  "keep_alive",
  "prompt_suggestion",
]);

// ---------------------------------------------------------------------------
// shouldEmit — returns false for events filtered from output
// ---------------------------------------------------------------------------

function shouldEmit(event: QueryEvent): boolean {
  const outerType: string = event.type;
  if (FILTERED_EVENT_TYPES.has(outerType)) return false;
  const sub: string | undefined = (event as unknown as { subtype?: string }).subtype;
  if (sub && FILTERED_EVENT_TYPES.has(sub)) return false;
  return true;
}

// ---------------------------------------------------------------------------
// UuidDedup — LRU ring buffer; deduplicates wire messages by UUID
// ---------------------------------------------------------------------------

class UuidDedup {
  private readonly _seen: Set<string> = new Set();
  private readonly _ring: string[]    = [];

  has(uuid: string): boolean {
    return this._seen.has(uuid);
  }

  add(uuid: string): void {
    if (this._seen.has(uuid)) return;
    if (this._ring.length >= MAX_UUID_CACHE) {
      const evict = this._ring.shift();
      if (evict !== undefined) this._seen.delete(evict);
    }
    this._ring.push(uuid);
    this._seen.add(uuid);
  }
}

// ---------------------------------------------------------------------------
// Batching helpers — coalesce consecutive batchable user messages
// ---------------------------------------------------------------------------

function isBatchable(msg: WireMessage): boolean {
  return msg.type === "user";
}

function canBatch(a: WireMessage, b: WireMessage): boolean {
  return a.workload === b.workload && Boolean(a.isMeta) === Boolean(b.isMeta);
}

function mergeBatch(messages: WireMessage[]): WireMessage {
  if (messages.length === 1) return messages[0]!;
  const mergedContent: unknown[] = ([] as unknown[]).concat(
    ...messages.map((m) =>
      Array.isArray(m.content) ? (m.content as unknown[]) : [],
    ),
  );
  return { ...messages[0]!, content: mergedContent };
}

// ---------------------------------------------------------------------------
// headlessRepl — main async generator
// ---------------------------------------------------------------------------

export async function* headlessRepl(
  ioSurface:              IOSurface,
  mcpServers:             unknown[],
  commands:               unknown[],
  tools:                  Tool[],
  initialMessages:        unknown[],
  canUseTool:             (tool: Tool, input: unknown) => Promise<boolean>,
  sdkMcpConfigs:          unknown[],
  getAppState:            () => unknown,
  setAppState:            (updater: (prev: unknown) => unknown) => void | Promise<void>,
  agents:                 unknown[],
  options:                HeadlessReplOptions,
  _turnInterruptionState?: unknown,
  _testDeps?:             LoopDepsOverrides,
): AsyncGenerator<QueryEvent> {
  const sessionAbort  = new AbortController();
  const sigintHandler = (): void => { sessionAbort.abort(); };
  process.on("SIGINT", sigintHandler);

  const resumeInterrupted  = !!process.env["EMBER_RESUME_INTERRUPTED_TURN"];
  const messagesForEngine  = [...initialMessages];
  const readFileCache      = new Map<string, unknown>();

  const engineConfig = {
    cwd:               process.cwd(),
    tools,
    commands,
    mcpClients:        null as unknown,
    agents:            null as unknown,
    canUseTool,
    getAppState,
    setAppState,
    initialMessages:   messagesForEngine,
    readFileCache,
    customSystemPrompt:  options.systemPrompt,
    appendSystemPrompt:  options.appendSystemPrompt,
    userSpecifiedModel:  options.userSpecifiedModel,
    fallbackModel:       options.fallbackModel,
    thinkingConfig:      options.thinkingConfig,
    maxTurns:            options.maxTurns,
    maxBudgetUsd:        options.maxBudgetUsd,
    taskBudget:          options.taskBudget,
    jsonSchema:          options.jsonSchema,
    verbose:             options.verbose,
    replayUserMessages:  options.replayUserMessages ?? resumeInterrupted,
  };

  const engine = new QueryEngine(engineConfig, _testDeps);
  const dedup  = new UuidDedup();

  // Proactive mode: emit events on a trigger without blocking on ioSurface.
  // When EMBER_PROACTIVE is set, submit a single proactive-tick message to the
  // engine and yield all emittable events before returning. This bypasses the
  // normal ioSurface iteration entirely so the generator does not block.
  if (process.env["EMBER_PROACTIVE"]) {
    const proactiveText =
      typeof process.env["EMBER_PROACTIVE"] === "string" &&
      process.env["EMBER_PROACTIVE"] !== "1"
        ? process.env["EMBER_PROACTIVE"]
        : "proactive-tick";
    try {
      for await (const event of engine.submitMessage(proactiveText)) {
        if (sessionAbort.signal.aborted) break;
        if (shouldEmit(event)) {
          ioSurface.write(event);
          yield event;
        }
      }
    } finally {
      process.off("SIGINT", sigintHandler);
    }
    return;
  }

  let pendingBatch: WireMessage[] = [];

  const flushBatch = async function* (): AsyncGenerator<QueryEvent> {
    if (pendingBatch.length === 0) return;
    const merged  = mergeBatch(pendingBatch);
    pendingBatch  = [];
    const textParts = (Array.isArray(merged.content) ? (merged.content as unknown[]) : [])
      .filter((b): b is { type: string; text: string } =>
        (b as { type?: string }).type === "text" &&
        typeof (b as { text?: unknown }).text === "string",
      )
      .map((b) => b.text);
    const userText = textParts.join("\n");
    for await (const event of engine.submitMessage(userText)) {
      if (sessionAbort.signal.aborted) break;
      if (shouldEmit(event)) {
        ioSurface.write(event);
        yield event;
      }
    }
  };

  try {
    for await (const raw of ioSurface) {
      if (sessionAbort.signal.aborted) break;
      const wireMsg = raw as WireMessage;
      if (wireMsg.type !== "user") continue;

      const uuid = wireMsg.uuid;
      if (uuid) {
        if (dedup.has(uuid)) continue;
        dedup.add(uuid);
      }

      if (isBatchable(wireMsg)) {
        if (pendingBatch.length > 0 && canBatch(pendingBatch[0]!, wireMsg)) {
          pendingBatch.push(wireMsg);
        } else {
          yield* flushBatch();
          pendingBatch = [wireMsg];
        }
      } else {
        yield* flushBatch();
        const text = String(wireMsg.content ?? "");
        for await (const event of engine.submitMessage(text)) {
          if (sessionAbort.signal.aborted) break;
          if (shouldEmit(event)) {
            ioSurface.write(event);
            yield event;
          }
        }
      }
    }
    yield* flushBatch();
  } finally {
    process.off("SIGINT", sigintHandler);
  }
}

// ---------------------------------------------------------------------------
// runHeadlessPrompt — one-shot wrapper (single prompt → collect events)
// ---------------------------------------------------------------------------

export async function runHeadlessPrompt(
  prompt:     string,
  ioSurface:  IOSurface,
  tools:      Tool[],
  options:    HeadlessReplOptions,
  _testDeps?: LoopDepsOverrides,
): Promise<{ events: QueryEvent[]; exitCode: number }> {
  ioSurface.prependUserMessage(prompt);

  const appState: Record<string, unknown> = {};
  const emittedEvents: QueryEvent[]        = [];

  const gen = headlessRepl(
    ioSurface,
    [],
    [],
    tools,
    [],
    async () => true,
    [],
    () => appState,
    async (updater) => { Object.assign(appState, updater(appState)); },
    [],
    options,
    undefined,
    _testDeps,
  );

  for await (const event of gen) {
    emittedEvents.push(event);
  }

  const lastResult = [...emittedEvents]
    .reverse()
    .find((e) => e.type === "result");
  const exitCode =
    (lastResult as unknown as { subtype?: string } | undefined)?.subtype === "success"
      ? 0
      : 1;

  return { events: emittedEvents, exitCode };
}

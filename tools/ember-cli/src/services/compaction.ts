// services/compaction.ts — real context-compaction for the agent query loop.
//
// Replaces the production no-op micro/autocompact stubs (entrypoints/session-init.ts)
// with real implementations:
//   - createMicrocompact: a deterministic, in-loop trimmer that minimally shrinks the
//     message list when it nears the context budget (truncates large bodies; never
//     drops messages; preserves a leading system message + the most recent turns).
//   - createAutocompact: a model-summary rebuild that condenses the older portion of
//     the conversation into a single summary message via callModel.
//
// Both are factory-built so session-init wires production dependencies while tests
// inject controlled behavior. The micro path is pure (no model call); the auto path
// fails safe (any model error leaves the conversation unchanged — never corrupts it).

import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

// ---------------------------------------------------------------------------
// Token estimation (cheap, deterministic — no tokenizer dependency)
// ---------------------------------------------------------------------------

/** Approximate token count for one message: ~4 chars per token over its serialization. */
export function estimateMessageTokens(message: unknown): number {
  let serialized: string;
  if (typeof message === "string") {
    serialized = message;
  } else {
    try {
      serialized = JSON.stringify(message) ?? "";
    } catch {
      serialized = String(message);
    }
  }
  return Math.ceil(serialized.length / 4);
}

function totalTokens(messages: unknown[], estimate: (m: unknown) => number): number {
  let sum = 0;
  for (const m of messages) sum += estimate(m);
  return sum;
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Default context budget (tokens) when EMBER_CONTEXT_TOKENS is unset/invalid. */
const DEFAULT_MAX_TOKENS = 24000;

function envMaxTokens(): number | null {
  const raw = process.env["EMBER_CONTEXT_TOKENS"];
  if (raw === undefined) return null;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function roleOf(message: unknown): string | undefined {
  if (message !== null && typeof message === "object" && "role" in message) {
    const r = (message as { role: unknown }).role;
    return typeof r === "string" ? r : undefined;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Micro-compaction — minimal in-loop body truncation
// ---------------------------------------------------------------------------

/** Chars retained from each end of a large body before the elision marker. */
const TRUNCATE_KEEP = 200;

function truncateText(text: string): string {
  if (text.length <= TRUNCATE_KEEP * 2 + 40) return text;
  const head = text.slice(0, TRUNCATE_KEEP);
  const tail = text.slice(-TRUNCATE_KEEP);
  const elided = text.length - head.length - tail.length;
  return `${head}[…truncated ${elided} chars…]${tail}`;
}

/**
 * Returns a structurally-identical copy of `message` with large textual bodies
 * truncated. Never throws; a message it cannot interpret is returned unchanged.
 */
function trimMessageBody(message: unknown): unknown {
  if (message === null || typeof message !== "object") return message;
  const obj = message as Record<string, unknown>;
  const content = obj["content"];

  if (typeof content === "string") {
    const trimmed = truncateText(content);
    return trimmed === content ? message : { ...obj, content: trimmed };
  }

  if (Array.isArray(content)) {
    let changed = false;
    const trimmedBlocks = content.map((block) => {
      if (block !== null && typeof block === "object" && "text" in block) {
        const t = (block as { text: unknown }).text;
        if (typeof t === "string") {
          const tt = truncateText(t);
          if (tt !== t) {
            changed = true;
            return { ...(block as Record<string, unknown>), text: tt };
          }
        }
      }
      return block;
    });
    return changed ? { ...obj, content: trimmedBlocks } : message;
  }

  return message;
}

export interface MicrocompactOpts {
  /** Token budget that triggers trimming. Falls back to EMBER_CONTEXT_TOKENS, then 24000. */
  maxTokens?: number;
  /** Most-recent messages preserved verbatim. Default 6. */
  keepRecent?: number;
  /** Override the token estimator (testing). */
  estimateTokens?: (message: unknown) => number;
}

/**
 * Builds the production microcompact: when the message list exceeds the token
 * budget, it preserves a leading system message and the most recent `keepRecent`
 * messages verbatim, and minimally truncates the bodies of the middle messages.
 * Length is always preserved (no message is dropped) and the input is never mutated.
 */
export function createMicrocompact(
  opts: MicrocompactOpts = {},
): (messages: unknown[]) => Promise<unknown[]> {
  const keepRecent = opts.keepRecent ?? 6;
  const estimate = opts.estimateTokens ?? estimateMessageTokens;

  return async (messages: unknown[]): Promise<unknown[]> => {
    if (!Array.isArray(messages) || messages.length === 0) return messages;

    const maxTokens = opts.maxTokens ?? envMaxTokens() ?? DEFAULT_MAX_TOKENS;
    if (totalTokens(messages, estimate) <= maxTokens) return messages;

    const n = messages.length;
    const protectedStart = roleOf(messages[0]) === "system" ? 1 : 0;
    const recentStart = Math.max(protectedStart, n - keepRecent);

    const out: unknown[] = new Array(n);
    for (let i = 0; i < n; i++) {
      out[i] = i < protectedStart || i >= recentStart ? messages[i] : trimMessageBody(messages[i]);
    }
    return out;
  };
}

// ---------------------------------------------------------------------------
// Auto-compaction — model-summary conversation rebuild
// ---------------------------------------------------------------------------

const SUMMARY_SYSTEM_PROMPT =
  "Summarize the prior conversation into a compact set of durable facts, decisions, and " +
  "open state. Preserve task-critical details, identifiers, file paths, and unresolved " +
  "threads. Output only the summary.";

/** Concatenate text from a ModelResponse content array (text blocks or bare strings). */
function extractResponseText(content: unknown[]): string {
  const parts: string[] = [];
  for (const block of content) {
    if (typeof block === "string") {
      parts.push(block);
    } else if (block !== null && typeof block === "object" && "text" in block) {
      const t = (block as { text: unknown }).text;
      if (typeof t === "string") parts.push(t);
    }
  }
  return parts.join("\n").trim();
}

export interface AutocompactDeps {
  /** The model sampling function (production: the wired callModel; tests: a spy). */
  callModel: (params: CallModelParams) => Promise<ModelResponse>;
  /** Reads the current persisted conversation. */
  getMessages: () => unknown[];
  /** Replaces the persisted conversation with the compacted form. */
  setMessages: (messages: unknown[]) => void;
  /** One-shot post-compaction hook (session-state.markPostCompaction). Receives
   *  the elapsed seconds of the compaction so the REPL can show "Crunched for Xs". */
  markPostCompaction?: (elapsedSecs: number) => void;
  /** Most-recent messages preserved verbatim after the summary. Default 6. */
  keepRecent?: number;
  /** Below this length the conversation is left as-is. Default keepRecent + 2. */
  minMessagesToCompact?: number;
  /** Model id for the summary request. Falls back to EMBER_MODEL, then "default". */
  model?: string;
  /** Override the summary-message constructor (testing / shape control). */
  buildSummaryMessage?: (summaryText: string) => unknown;
}

/**
 * Builds the production autocompact: condenses the older portion of the conversation
 * (everything except a leading system message and the most recent `keepRecent`
 * messages) into a single summary message produced by callModel, then rewrites the
 * conversation as [system?, summary, ...recent]. Fails safe: a model error or an
 * empty summary leaves the conversation untouched.
 */
export function createAutocompact(deps: AutocompactDeps): () => Promise<void> {
  const keepRecent = deps.keepRecent ?? 6;
  const minMessages = deps.minMessagesToCompact ?? keepRecent + 2;
  const buildSummary =
    deps.buildSummaryMessage ??
    ((text: string): unknown => ({
      role: "user",
      content: [{ type: "text", text: `[compacted conversation summary]\n${text}` }],
    }));

  return async (): Promise<void> => {
    const startedAt = Date.now();
    const messages = deps.getMessages();
    if (!Array.isArray(messages) || messages.length <= minMessages) return;

    const headLen = roleOf(messages[0]) === "system" ? 1 : 0;
    const head = messages.slice(0, headLen);
    const cutoff = messages.length - keepRecent;
    if (cutoff <= headLen) return; // nothing old enough to compact
    const older = messages.slice(headLen, cutoff);
    const recent = messages.slice(cutoff);

    let response: ModelResponse;
    try {
      response = await deps.callModel({
        messages: older,
        systemPrompt: SUMMARY_SYSTEM_PROMPT,
        tools: [],
        model: deps.model ?? process.env["EMBER_MODEL"] ?? "default",
        maxTokens: 1024,
        skipCacheWrite: true,
      });
    } catch {
      return; // model failure → leave the conversation unchanged (no corruption)
    }

    const summaryText = Array.isArray(response.content) ? extractResponseText(response.content) : "";
    if (summaryText.length === 0) return; // empty summary → no change

    deps.setMessages([...head, buildSummary(summaryText), ...recent]);
    deps.markPostCompaction?.(Math.max(0, Math.round((Date.now() - startedAt) / 1000)));
  };
}

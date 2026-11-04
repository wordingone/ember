// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

/**
 * Microcompact budget for a server context of `nCtx` tokens: 90% of it, never below the
 * 24,000-token default. Auto-compaction runs first, at 85%; microcompact is the in-turn
 * backstop for a turn that grows past that, so it must not fire earlier on a large window.
 */
export function microcompactBudgetForContext(nCtx: number): number {
  return Math.max(DEFAULT_MAX_TOKENS, Math.floor(nCtx * 0.9));
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

/** Share of the context window the prompt may reach before auto-compaction runs. */
export const DEFAULT_AUTO_COMPACT_FRACTION = 0.85;

/** Vision tokens charged per attached image. */
const IMAGE_TOKENS_ESTIMATE = 1500;

export const SUMMARY_SYSTEM_PROMPT =
  "Summarize the prior conversation into a compact set of durable facts, decisions, and " +
  "open state. Preserve task-critical details, identifiers, file paths, and unresolved " +
  "threads. Keep, in order: what the user asked for and any constraints they set (exact " +
  "wording where it matters); what was done so far (files read or changed, commands run, " +
  "results, errors); decisions and the reason for each; the current state and the next " +
  "step. Output only the summary.";

const SUMMARY_REQUEST_TEXT =
  "Write the summary of the conversation above now, following the system instructions.";

/** Marker that opens every summary message the default constructor builds. */
export const SUMMARY_MARKER = "[compacted conversation summary]";

/** Heading of the deterministic file-work section appended to every summary. */
export const FILES_SECTION_HEADING = "Files changed this session:";

const FILE_TOOLS: Record<string, string> = { Write: "file_path", Edit: "file_path", NotebookEdit: "notebook_path" };

const PREVIOUS_SUMMARY_REQUEST_TEXT =
  "The conversation above begins with a summary from an earlier compaction. Carry EVERY fact " +
  "from that previous summary forward (requests, constraints, files created or changed, " +
  "decisions, state), then add the work done after it. Do not drop anything the previous " +
  "summary recorded. Write the new summary now, following the system instructions.";

function messageText(message: unknown): string {
  if (message === null || typeof message !== "object") return "";
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const b of content) {
    if (typeof b === "string") parts.push(b);
    else if (b !== null && typeof b === "object" && typeof (b as { text?: unknown }).text === "string") {
      parts.push((b as { text: string }).text);
    }
  }
  return parts.join("\n");
}

function isPreviousSummary(message: unknown): boolean {
  return roleOf(message) === "user" && messageText(message).trimStart().startsWith(SUMMARY_MARKER);
}

/** Split a summary into its prose and the paths listed in its trailing files section. */
export function splitFilesSection(text: string): { body: string; files: string[] } {
  const idx = text.lastIndexOf(FILES_SECTION_HEADING);
  if (idx < 0) return { body: text, files: [] };
  const files: string[] = [];
  for (const line of text.slice(idx + FILES_SECTION_HEADING.length).split("\n")) {
    const m = /^\s*-\s+(.+?)\s*$/.exec(line);
    if (m?.[1]) files.push(m[1]);
  }
  return { body: text.slice(0, idx).trimEnd(), files };
}

/** Paths from successful Write/Edit/NotebookEdit calls in `messages`, in first-seen order. */
export function collectChangedFiles(messages: unknown[]): string[] {
  const failed = new Set<string>();
  const ok = new Set<string>();
  for (const m of messages) {
    const content = m !== null && typeof m === "object" ? (m as { content?: unknown }).content : undefined;
    if (!Array.isArray(content)) continue;
    for (const b of content) {
      if (b === null || typeof b !== "object") continue;
      const blk = b as Record<string, unknown>;
      if (blk["type"] === "tool_result" && typeof blk["tool_use_id"] === "string") {
        (blk["is_error"] === true ? failed : ok).add(blk["tool_use_id"]);
      }
    }
  }
  const out: string[] = [];
  for (const m of messages) {
    const content = m !== null && typeof m === "object" ? (m as { content?: unknown }).content : undefined;
    if (!Array.isArray(content)) continue;
    for (const b of content) {
      if (b === null || typeof b !== "object") continue;
      const blk = b as Record<string, unknown>;
      if (blk["type"] !== "tool_use" || typeof blk["name"] !== "string") continue;
      const key = FILE_TOOLS[blk["name"]];
      if (key === undefined) continue;
      const id = blk["id"];
      if (typeof id !== "string" || failed.has(id) || !ok.has(id)) continue;
      const input = blk["input"];
      const path = input !== null && typeof input === "object" ? (input as Record<string, unknown>)[key] : undefined;
      if (typeof path === "string" && path !== "" && !out.includes(path)) out.push(path);
    }
  }
  return out;
}

/** The model's summary with a deterministic files section: prior summary's files + this fold's. */
export function appendFilesSection(summaryText: string, older: unknown[]): string {
  const files: string[] = [];
  const add = (p: string): void => {
    if (!files.includes(p)) files.push(p);
  };
  for (const m of older) if (isPreviousSummary(m)) splitFilesSection(messageText(m)).files.forEach(add);
  collectChangedFiles(older).forEach(add);
  const { body, files: echoed } = splitFilesSection(summaryText);
  echoed.forEach(add);
  if (files.length === 0) return summaryText;
  return `${body}\n\n${FILES_SECTION_HEADING}\n${files.map((f) => `- ${f}`).join("\n")}`;
}

function parsePositiveInt(raw: string | undefined): number | null {
  if (raw === undefined) return null;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Fraction of the window that triggers auto-compaction: EMBER_AUTO_COMPACT_FRACTION, else 0.85. */
export function resolveAutoCompactFraction(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env["EMBER_AUTO_COMPACT_FRACTION"];
  if (raw === undefined) return DEFAULT_AUTO_COMPACT_FRACTION;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 && n <= 1 ? n : DEFAULT_AUTO_COMPACT_FRACTION;
}

/**
 * Prompt size (tokens) at which auto-compaction runs for a server context of `nCtx` tokens.
 * EMBER_AUTO_COMPACT_WINDOW (models.json `autoCompactWindow`) caps the window the fraction
 * applies to, so an operator can compact earlier than the server's full context allows.
 */
export function resolveAutoCompactThresholdTokens(nCtx: number, env: NodeJS.ProcessEnv = process.env): number {
  const cap = parsePositiveInt(env["EMBER_AUTO_COMPACT_WINDOW"]);
  const window = cap !== null ? Math.min(cap, nCtx) : nCtx;
  return Math.max(1, Math.floor(window * resolveAutoCompactFraction(env)));
}

/** Output budget for a summary: nCtx/64 (4096 at 262144), within [1024, 8192] and at most nCtx/4. */
export function summaryBudgetTokens(nCtx: number): number {
  const scaled = Math.min(8192, Math.max(1024, Math.floor(nCtx / 64)));
  return Math.max(256, Math.min(scaled, Math.floor(nCtx / 4)));
}

/** The summary system prompt with any non-empty extra instructions appended. */
export function buildSummarySystemPrompt(...extra: Array<string | undefined>): string {
  const lines = extra.map((e) => e?.trim() ?? "").filter((e) => e !== "");
  if (lines.length === 0) return SUMMARY_SYSTEM_PROMPT;
  return `${SUMMARY_SYSTEM_PROMPT}\n\nAdditional instructions for this summary:\n${lines.join("\n\n")}`;
}

function safeJsonLength(value: unknown): number {
  try {
    return JSON.stringify(value)?.length ?? 0;
  } catch {
    return String(value).length;
  }
}

/**
 * Tokens one conversation message adds to the prompt: its content blocks as the server sees
 * them. Unlike estimateMessageTokens this ignores the engine's bookkeeping fields (the raw
 * `message` response and the `toolUseResult` mirror), which would otherwise count each
 * assistant reply and tool result twice.
 */
export function estimatePromptMessageTokens(message: unknown): number {
  if (message === null || typeof message !== "object") return estimateMessageTokens(message);
  const obj = message as Record<string, unknown>;
  let chars = 16; // role + template framing
  const content = obj["content"];
  if (typeof content === "string") {
    chars += content.length;
  } else if (Array.isArray(content)) {
    for (const block of content) {
      if (typeof block === "string") {
        chars += block.length;
      } else if (block !== null && typeof block === "object") {
        const b = block as Record<string, unknown>;
        if (b["type"] === "text" && typeof b["text"] === "string") chars += b["text"].length;
        else if (b["type"] === "tool_use") chars += String(b["name"] ?? "").length + safeJsonLength(b["input"]);
        else if (b["type"] === "tool_result") {
          chars += typeof b["content"] === "string" ? b["content"].length : safeJsonLength(b["content"]);
        } else if (b["type"] === "thinking" && typeof b["thinking"] === "string") chars += b["thinking"].length;
        else chars += safeJsonLength(block);
      }
    }
  }
  const images = obj["images"];
  if (Array.isArray(images)) chars += images.length * IMAGE_TOKENS_ESTIMATE * 4;
  return Math.ceil(chars / 4);
}

/** A user message that carries tool results (it must stay next to the assistant call that produced them). */
function isToolResultMessage(message: unknown): boolean {
  if (roleOf(message) !== "user") return false;
  const content = (message as { content?: unknown }).content;
  return (
    Array.isArray(content) &&
    content.some((b) => b !== null && typeof b === "object" && (b as { type?: unknown }).type === "tool_result")
  );
}

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

export type CompactionOutcome =
  | {
      status: "compacted";
      trigger: "auto" | "manual";
      tokensBefore: number;
      tokensAfter: number;
      elapsedSecs: number;
    }
  | {
      status: "skipped";
      reason: "below-threshold" | "too-short" | "no-conversation" | "model-error" | "empty-summary";
      detail?: string;
    };

export interface CompactRunOptions {
  /** Compact now even below the threshold, folding the whole conversation into the summary. */
  force?: boolean;
  /** Extra instructions for this one summary (the `/compact <text>` argument). */
  instructions?: string;
}

export type Autocompact = (opts?: CompactRunOptions) => Promise<CompactionOutcome>;

const formatTokens = (n: number): string => `~${Math.round(n).toLocaleString("en-US")}`;

/** One line for the user: what a compaction attempt did. */
export function describeCompactionOutcome(outcome: CompactionOutcome): string {
  if (outcome.status === "compacted") {
    return `Conversation compacted: ${formatTokens(outcome.tokensBefore)} → ${formatTokens(outcome.tokensAfter)} tokens.`;
  }
  switch (outcome.reason) {
    case "no-conversation":
    case "too-short":
      return "Nothing to compact yet.";
    case "below-threshold":
      return "The conversation is below the compaction threshold.";
    case "model-error":
      return `Compaction failed (${outcome.detail ?? "model error"}); the conversation is unchanged.`;
    case "empty-summary":
      return "Compaction failed: the model returned an empty summary; the conversation is unchanged.";
  }
}

export interface AutocompactDeps {
  /** The model sampling function (production: the wired callModel; tests: a spy). */
  callModel: (params: CallModelParams) => Promise<ModelResponse>;
  /** Reads the current persisted conversation. */
  getMessages: () => unknown[];
  /** Replaces the persisted conversation with the compacted form. */
  setMessages: (messages: unknown[]) => void;
  /** One-shot post-compaction hook (session-state.markPostCompaction). Receives the elapsed
   *  seconds and the before/after token estimates for the transcript notice row. Only an
   *  automatic compaction calls it; a manual one returns its outcome to the command. */
  markPostCompaction?: (elapsedSecs: number, info?: { tokensBefore: number; tokensAfter: number }) => void;
  /** Most-recent messages preserved verbatim after the summary. Default 6. */
  keepRecent?: number;
  /** At or below this length an automatic compaction leaves the log as-is. Default keepRecent + 2. */
  minMessagesToCompact?: number;
  /** Model id for the summary request. Falls back to EMBER_MODEL, then "default". */
  model?: string;
  /** Override the summary-message constructor (testing / shape control). */
  buildSummaryMessage?: (summaryText: string) => unknown;
  /**
   * The model server's context size in tokens. When it resolves to a positive number,
   * auto-compaction runs only once the estimated prompt reaches the threshold
   * (resolveAutoCompactThresholdTokens). When absent or null the size is unknown and the
   * legacy rule applies: compact whenever the log is longer than `minMessagesToCompact`.
   */
  nCtx?: number | (() => number | null | undefined);
  /** Standing instructions (settings / EMBER.md) appended to every summary prompt. */
  getStandingInstructions?: () => string | undefined | Promise<string | undefined>;
  /** Tokens the prompt carries besides the messages (system prompt, tool schemas). Default 0. */
  overheadTokens?: () => number;
  /** Per-message token estimator. Defaults to estimatePromptMessageTokens. */
  estimateTokens?: (message: unknown) => number;
  /** Environment for the threshold overrides. Defaults to process.env. */
  env?: NodeJS.ProcessEnv;
}

/**
 * Builds the production autocompact: condenses the older portion of the conversation
 * (everything except a leading system message and the most recent `keepRecent`
 * messages) into a single summary message produced by callModel, then rewrites the
 * conversation as [system?, summary, ...recent]. A forced (manual) run folds in everything
 * but the system head. Fails safe: a model error or an empty summary leaves the
 * conversation untouched and is reported in the returned outcome.
 */
export function createAutocompact(deps: AutocompactDeps): Autocompact {
  const keepRecent = deps.keepRecent ?? 6;
  const minMessages = deps.minMessagesToCompact ?? keepRecent + 2;
  const estimate = deps.estimateTokens ?? estimatePromptMessageTokens;
  const env = deps.env ?? process.env;
  const buildSummary =
    deps.buildSummaryMessage ??
    ((text: string): unknown => ({
      role: "user",
      content: [{ type: "text", text: `${SUMMARY_MARKER}\n${text}` }],
    }));

  const skipped = (
    reason: Extract<CompactionOutcome, { status: "skipped" }>["reason"],
    detail?: string,
  ): CompactionOutcome =>
    detail === undefined ? { status: "skipped", reason } : { status: "skipped", reason, detail };

  return async (run: CompactRunOptions = {}): Promise<CompactionOutcome> => {
    const startedAt = Date.now();
    const force = run.force === true;
    const messages = deps.getMessages();
    if (!Array.isArray(messages) || messages.length === 0) return skipped("no-conversation");

    const rawNCtx = typeof deps.nCtx === "function" ? deps.nCtx() : deps.nCtx;
    const nCtx = typeof rawNCtx === "number" && rawNCtx > 0 ? rawNCtx : null;
    const overhead = deps.overheadTokens?.() ?? 0;
    const tokensBefore = overhead + totalTokens(messages, estimate);

    if (!force && nCtx !== null && tokensBefore < resolveAutoCompactThresholdTokens(nCtx, env)) {
      return skipped("below-threshold");
    }
    if (!force && messages.length <= minMessages) return skipped("too-short");

    const headLen = roleOf(messages[0]) === "system" ? 1 : 0;
    const head = messages.slice(0, headLen);
    let cutoff = force ? messages.length : messages.length - keepRecent;
    // A tool result must stay beside the assistant call that produced it: never start the
    // preserved tail on one.
    while (!force && cutoff > headLen && isToolResultMessage(messages[cutoff])) cutoff--;
    if (cutoff <= headLen) return skipped("too-short"); // nothing old enough to compact
    const older = messages.slice(headLen, cutoff);
    if (force && older.length < 2) return skipped("too-short");
    const recent = messages.slice(cutoff);

    let standing: string | undefined;
    try {
      standing = await deps.getStandingInstructions?.();
    } catch {
      standing = undefined; // unreadable instructions never block a compaction
    }

    let response: ModelResponse;
    try {
      response = await deps.callModel({
        messages: [
          ...older,
          {
            role: "user",
            content: [
              { type: "text", text: older.some(isPreviousSummary) ? PREVIOUS_SUMMARY_REQUEST_TEXT : SUMMARY_REQUEST_TEXT },
            ],
          },
        ],
        systemPrompt: buildSummarySystemPrompt(standing, run.instructions),
        tools: [],
        model: deps.model ?? process.env["EMBER_MODEL"] ?? "default",
        maxTokens: summaryBudgetTokens(nCtx ?? DEFAULT_MAX_TOKENS),
        skipCacheWrite: true,
      });
    } catch (err) {
      // model failure → leave the conversation unchanged (no corruption)
      return skipped("model-error", err instanceof Error ? err.message : String(err));
    }

    const modelText = Array.isArray(response.content) ? extractResponseText(response.content) : "";
    if (modelText.length === 0) return skipped("empty-summary"); // empty summary → no change
    const summaryText = appendFilesSection(modelText, older);

    const next = [...head, buildSummary(summaryText), ...recent];
    deps.setMessages(next);
    const tokensAfter = overhead + totalTokens(next, estimate);
    const elapsedSecs = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    if (!force) deps.markPostCompaction?.(elapsedSecs, { tokensBefore, tokensAfter });
    return { status: "compacted", trigger: force ? "manual" : "auto", tokensBefore, tokensAfter, elapsedSecs };
  };
}

// services/speculation.ts — speculative execution overlay for tool calls.
// Pre-runs predicted tool sequences in an isolated filesystem overlay, then
// merges the result into the working tree on acceptance.

import { rm, mkdir, copyFile } from "fs/promises";
import { join, dirname } from "path";
import { tmpdir } from "os";

import type { EmberMessage } from "../types/message-types.ts";
import { globalConfig } from "./prompt-suggestion.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SpeculationBoundary =
  | { type: "complete" }
  | { type: "bash"; command?: string }
  | { type: "edit"; path?: string }
  | { type: "tool"; toolName: string };

export type ActiveSpeculationState = {
  status: "active";
  id: string;
  overlayPath: string;
  writtenPaths: Set<string>;
  abortController: AbortController;
  messages: EmberMessage[];
  boundary: SpeculationBoundary | null;
  sessionTimeSavedMs: number;
  pipelinedSuggestion?: string;
  startTime: number;
};

export type RichSpeculationState =
  | { status: "idle" }
  | ActiveSpeculationState;

export interface SpeculationResult {
  messages: EmberMessage[];
  boundary: SpeculationBoundary | null;
  timeSavedMs: number;
}

// ---------------------------------------------------------------------------
// Interrupt message sentinels
// ---------------------------------------------------------------------------

const INTERRUPT_MESSAGE = "\n[Request interrupted by user]";
const INTERRUPT_MESSAGE_FOR_TOOL_USE =
  "\n[Request interrupted by user for tool use]";

// ---------------------------------------------------------------------------
// Overlay filesystem helpers
// ---------------------------------------------------------------------------

/**
 * Removes an overlay directory tree, tolerating races and retrying on EPERM.
 */
export function safeRemoveOverlay(overlayPath: string): void {
  rm(overlayPath, {
    recursive: true,
    force: true,
    maxRetries: 3,
    retryDelay: 100,
  }).catch(() => {
    // Removal errors are non-fatal; log but continue.
    console.debug("[speculation] safeRemoveOverlay: removal failed silently", overlayPath);
  });
}

/**
 * Returns the absolute path for a per-session, per-speculation overlay directory.
 * Path: <tmpdir>/ember-speculation/<pid>/<id>
 */
export function getOverlayPath(id: string): string {
  return join(tmpdir(), "ember-speculation", String(process.pid), id);
}

// ---------------------------------------------------------------------------
// Decision helpers
// ---------------------------------------------------------------------------

/**
 * Builds a deny decision with a structured reason.
 */
export function denySpeculation(
  message: string,
  reason: string,
): { behavior: "deny"; message: string; decisionReason: string } {
  return { behavior: "deny", message, decisionReason: reason };
}

// ---------------------------------------------------------------------------
// Overlay merge
// ---------------------------------------------------------------------------

/**
 * Copies every written overlay file to the corresponding path in `cwd`.
 * Returns true when all copies succeeded, false if any copy failed.
 */
export async function copyOverlayToMain(
  overlayPath: string,
  writtenPaths: Set<string>,
  cwd: string,
): Promise<boolean> {
  let allOk = true;
  for (const relPath of writtenPaths) {
    const source = join(overlayPath, relPath);
    const dest = join(cwd, relPath);
    try {
      await mkdir(dirname(dest), { recursive: true });
      await copyFile(source, dest);
    } catch (err) {
      console.error("[speculation] copyOverlayToMain: copy failed", {
        source,
        dest,
        err,
      });
      allOk = false;
    }
  }
  return allOk;
}

// ---------------------------------------------------------------------------
// Analytics logging
// ---------------------------------------------------------------------------

/**
 * Logs a structured speculation outcome record for analytics.
 */
export function logSpeculation(
  id: string,
  outcome: "accepted" | "aborted" | "error",
  startTime: number,
  suggestionLength: number,
  messages: EmberMessage[],
  boundary: SpeculationBoundary | null,
  extras?: object,
): void {
  console.debug("[speculation] outcome", {
    id,
    outcome,
    durationMs: Date.now() - startTime,
    suggestionLength,
    messageCount: messages.length,
    boundaryType: boundary?.type ?? null,
    ...extras,
  });
}

// ---------------------------------------------------------------------------
// Message inspection helpers
// ---------------------------------------------------------------------------

/**
 * Counts tool_result blocks across all messages that are NOT errors.
 */
export function countToolsInMessages(messages: EmberMessage[]): number {
  let count = 0;
  for (const m of messages) {
    if (typeof m.content === "string") continue;
    for (const block of m.content as Array<Record<string, unknown>>) {
      if (block["type"] === "tool_result" && !block["is_error"]) {
        count++;
      }
    }
  }
  return count;
}

/**
 * Returns the tool name from a "tool" boundary, or null for other boundary types.
 */
export function getBoundaryTool(boundary: SpeculationBoundary): string | null {
  if (boundary.type === "tool") {
    return boundary.toolName;
  }
  return null;
}

/**
 * Returns the payload detail from a bash or edit boundary, or null otherwise.
 */
export function getBoundaryDetail(boundary: SpeculationBoundary): string | null {
  if (boundary.type === "bash") return boundary.command ?? null;
  if (boundary.type === "edit") return boundary.path ?? null;
  return null;
}

/**
 * Returns true when the message is a user message with array content.
 */
export function isUserMessageWithArrayContent(m: EmberMessage): boolean {
  return m.role === "user" && Array.isArray(m.content);
}

// ---------------------------------------------------------------------------
// Feature gate
// ---------------------------------------------------------------------------

/**
 * Returns true when speculative execution is enabled for internal users.
 */
export function isSpeculationEnabled(): boolean {
  return (
    process.env["USER_TYPE"] === "ant" && globalConfig.speculationEnabled
  );
}

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------

/**
 * Resets speculation state to idle.
 */
export function resetSpeculationState(
  setRichState: (s: RichSpeculationState) => void,
): void {
  setRichState({ status: "idle" });
}

/**
 * Applies an updater to an active speculation state.
 * Returns the current state unchanged when not active or when no plain fields
 * differ.
 */
export function updateActiveSpeculationState(
  currentState: RichSpeculationState,
  updater: (s: ActiveSpeculationState) => ActiveSpeculationState,
): RichSpeculationState {
  if (currentState.status !== "active") return currentState;
  const next = updater(currentState);
  // Compare plain scalar fields for a cheap change-detection short-circuit.
  if (
    next.id === currentState.id &&
    next.overlayPath === currentState.overlayPath &&
    next.sessionTimeSavedMs === currentState.sessionTimeSavedMs &&
    next.pipelinedSuggestion === currentState.pipelinedSuggestion &&
    next.startTime === currentState.startTime &&
    next.boundary === currentState.boundary &&
    next.messages === currentState.messages
  ) {
    return currentState;
  }
  return next;
}

// ---------------------------------------------------------------------------
// Message preparation
// ---------------------------------------------------------------------------

/**
 * Cleans a message array for injection into a speculated context.
 *
 * Filtering rules applied in order:
 * 1. Remove thinking / redacted_thinking blocks.
 * 2. Remove orphan tool_use blocks (no matching tool_result of any kind).
 * 3. Remove tool_result blocks whose tool_use was removed in step 2.
 * 4. Remove messages that are exactly the interrupt sentinel strings.
 * 5. Drop messages that are empty or whitespace-only after prior filtering.
 */
export function prepareMessagesForInjection(
  messages: EmberMessage[],
): EmberMessage[] {
  // Step 1 & 2: collect all tool_use IDs that have at least one result.
  const resolvedToolUseIds = new Set<string>();
  for (const m of messages) {
    if (typeof m.content === "string") continue;
    for (const block of m.content as Array<Record<string, unknown>>) {
      if (block["type"] === "tool_result") {
        const id = block["tool_use_id"] as string | undefined;
        if (id !== undefined) resolvedToolUseIds.add(id);
      }
    }
  }

  const result: EmberMessage[] = [];

  for (const m of messages) {
    // Step 4: remove interrupt sentinel messages
    if (
      m.content === INTERRUPT_MESSAGE ||
      m.content === INTERRUPT_MESSAGE_FOR_TOOL_USE
    ) {
      continue;
    }

    if (typeof m.content === "string") {
      // Step 5: drop empty or whitespace-only string messages
      if (m.content.trim().length === 0) continue;
      result.push(m);
      continue;
    }

    // Content is an array of blocks
    const rawBlocks = m.content as Array<Record<string, unknown>>;

    const filteredBlocks = rawBlocks.filter((block) => {
      const t = block["type"] as string;

      // Step 1: remove thinking blocks
      if (t === "thinking" || t === "redacted_thinking") return false;

      // Step 2: remove orphan tool_use (no matching result at all)
      if (t === "tool_use") {
        const id = block["id"] as string | undefined;
        if (id !== undefined && !resolvedToolUseIds.has(id)) return false;
      }

      // Step 3: remove tool_result whose tool_use_id was removed in step 2
      if (t === "tool_result") {
        const id = block["tool_use_id"] as string | undefined;
        if (id !== undefined && !resolvedToolUseIds.has(id)) return false;
      }

      return true;
    });

    // Step 5: drop messages that are now empty
    if (filteredBlocks.length === 0) continue;

    // Rebuild the message with the cleaned content
    result.push({
      ...m,
      content: filteredBlocks as EmberMessage["content"],
    });
  }

  return result;
}

// ---------------------------------------------------------------------------
// Feedback / analytics
// ---------------------------------------------------------------------------

/**
 * Builds a system message summarising speculation savings.
 * Returns null for non-internal users or when there are no speculated messages.
 */
export function createSpeculationFeedbackMessage(
  messages: EmberMessage[],
  boundary: SpeculationBoundary | null,
  timeSavedMs: number,
  sessionTotalMs: number,
): EmberMessage | null {
  if (process.env["USER_TYPE"] !== "ant") return null;
  if (messages.length === 0) return null;

  const text = `Speculated ${messages.length} tool uses · ${timeSavedMs}ms saved (+${sessionTotalMs}ms this session)`;
  void boundary; // boundary context is logged separately

  return { role: "system", content: text };
}

// ---------------------------------------------------------------------------
// Speculation lifecycle stubs
// ---------------------------------------------------------------------------

/**
 * STUB — pipelined suggestion generation is out of scope for this task.
 */
export async function generatePipelinedSuggestion(
  ...args: unknown[]
): Promise<void> {
  void args;
}

/**
 * STUB — full overlay filesystem integration is out of scope for this task.
 */
export async function startSpeculation(...args: unknown[]): Promise<void> {
  void args;
}

/**
 * Accepts a completed speculation: merges the overlay, removes it, and returns
 * the accumulated result.
 */
export async function acceptSpeculation(
  state: RichSpeculationState,
  cleanMessageCount: number,
  cwd: string,
): Promise<SpeculationResult | null> {
  if (state.status !== "active") return null;

  state.abortController.abort();

  if (cleanMessageCount > 0) {
    await copyOverlayToMain(state.overlayPath, state.writtenPaths, cwd);
  }

  safeRemoveOverlay(state.overlayPath);

  const timeSavedMs = Date.now() - state.startTime;

  logSpeculation(
    state.id,
    "accepted",
    state.startTime,
    state.pipelinedSuggestion?.length ?? 0,
    state.messages,
    state.boundary,
  );

  return {
    messages: state.messages,
    boundary: state.boundary,
    timeSavedMs,
  };
}

/**
 * Aborts an active speculation and removes its overlay.
 */
export function abortSpeculation(state: RichSpeculationState): void {
  if (state.status !== "active") return;
  state.abortController.abort();
  safeRemoveOverlay(state.overlayPath);
  logSpeculation(
    state.id,
    "aborted",
    state.startTime,
    state.pipelinedSuggestion?.length ?? 0,
    state.messages,
    state.boundary,
  );
}

/**
 * STUB — accept-with-query integration is out of scope for this task.
 */
export async function handleSpeculationAccept(
  state: RichSpeculationState,
  timeSavedMs: number,
  input: string,
): Promise<{ queryRequired: boolean }> {
  void state;
  void timeSavedMs;
  void input;
  return { queryRequired: true };
}

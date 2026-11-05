// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-transcript.ts -- the on-screen transcript of a restored session (#2373).
//
// The REPL draws SessionMessage rows (user / assistant / tool_call / tool_result); the engine
// stores API-shaped messages. This rebuilds the rows from the messages, so a resumed session
// shows what the model will be sent on the next turn.

import type { SessionMessage } from "../components/app-shell.ts";
import { summarizeToolInput } from "../components/message-renderers.ts";
import { userPromptText } from "./session-store.ts";

export const COMPACTION_SUMMARY_PREFIX = "[compacted conversation summary]";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function resultText(content: unknown): string {
  if (typeof content === "string") return content;
  try {
    return JSON.stringify(content) ?? "";
  } catch {
    return String(content);
  }
}

export function engineMessagesToTranscript(
  messages: unknown[],
  newId: () => string = () => crypto.randomUUID(),
): SessionMessage[] {
  // is_error by tool_use id, so a call row can show how it ended
  const failed = new Map<string, boolean>();
  for (const m of messages) {
    const rec = asRecord(m);
    if (rec === null || rec["role"] !== "user" || !Array.isArray(rec["content"])) continue;
    for (const block of rec["content"] as unknown[]) {
      const b = asRecord(block);
      if (b !== null && b["type"] === "tool_result") failed.set(String(b["tool_use_id"]), b["is_error"] === true);
    }
  }

  const rows: SessionMessage[] = [];
  for (const m of messages) {
    const rec = asRecord(m);
    if (rec === null) continue;
    const content = rec["content"];
    if (rec["role"] === "user") {
      if (Array.isArray(content) && content.some((b) => asRecord(b)?.["type"] === "tool_result")) {
        for (const block of content as unknown[]) {
          const b = asRecord(block);
          if (b === null || b["type"] !== "tool_result") continue;
          rows.push({
            id: newId(),
            type: "tool_result",
            tool_use_id: String(b["tool_use_id"] ?? ""),
            content: resultText(b["content"]),
            is_error: b["is_error"] === true,
          });
        }
        continue;
      }
      const text = userPromptText(m);
      if (text.startsWith(COMPACTION_SUMMARY_PREFIX)) {
        rows.push({
          id: newId(),
          type: "assistant",
          content: `Earlier conversation, summarized:\n${text.slice(COMPACTION_SUMMARY_PREFIX.length).trim()}`,
        });
      } else if (text.trim() !== "") {
        rows.push({ id: newId(), type: "user", content: text });
      }
    } else if (rec["role"] === "assistant" && Array.isArray(content)) {
      const text = (content as unknown[])
        .map((block) => (asRecord(block)?.["type"] === "text" ? String(asRecord(block)!["text"] ?? "") : ""))
        .join("");
      if (text.trim() !== "") rows.push({ id: newId(), type: "assistant", content: text });
      for (const block of content as unknown[]) {
        const b = asRecord(block);
        if (b === null || b["type"] !== "tool_use") continue;
        const id = String(b["id"] ?? "");
        rows.push({
          id: newId(),
          type: "tool_call",
          toolUseId: id,
          toolName: String(b["name"] ?? "tool"),
          summary: summarizeToolInput(b["input"]),
          status: failed.get(id) === true ? "error" : "done",
        });
      }
    }
  }
  return rows;
}

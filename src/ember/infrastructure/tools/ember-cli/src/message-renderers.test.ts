// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// message-renderers.test.ts — AC1–AC14.
import { test, expect, describe } from "bun:test";
import React from "react";
import {
  MAX_API_ERROR_CHARS,
  MIN_HINT_DISPLAY_MS,
  BLACK_CIRCLE,
  COMPACT_BOUNDARY_TEXT,
  COMPACTION_IN_PROGRESS_TEXT,
  COMPACTION_COMPLETE_PREFIX,
  FILTERED_ATTACHMENT_TYPES,
  buildMessageLookups,
  classifyAssistantText,
  resolveToolUseState,
  extractTurnOrder,
  isSlashCommand,
  AssistantThinkingMessage,
  AssistantTextMessage,
  AssistantToolUseMessage,
  AttachmentMessage,
  SystemAPIErrorMessage,
  CompactBoundaryMessage,
  CompactionProgressMessage,
} from "./components/message-renderers.ts";
import type { Message, AssistantMessage } from "../types/message-types.ts";

function props(el: React.ReactElement): Record<string, unknown> {
  return el.props as Record<string, unknown>;
}

function childText(el: React.ReactElement): string {
  return JSON.stringify(el);
}

// ---------------------------------------------------------------------------
// AC1: Assistant turn produces thinking block first, then text/tool_use.
// ---------------------------------------------------------------------------
describe("AC1: thinking block precedes text/tool_use", () => {
  test("extractTurnOrder: thinking comes before text", () => {
    const msg: AssistantMessage = {
      role: "assistant",
      uuid: "u1",
      timestamp: "2026",
      content: [
        { type: "text",     text: "Hello" },
        { type: "thinking", thinking: "reasoning here" },
      ],
    };
    const turns = extractTurnOrder(msg);
    expect(turns[0]?.kind).toBe("thinking");
    expect(turns[1]?.kind).toBe("text");
  });

  test("extractTurnOrder: thinking before tool_use", () => {
    const msg: AssistantMessage = {
      role: "assistant",
      uuid: "u2",
      timestamp: "2026",
      content: [
        { type: "tool_use", name: "Bash", id: "t1" },
        { type: "thinking", thinking: "thinking" },
      ],
    };
    const turns = extractTurnOrder(msg);
    expect(turns[0]?.kind).toBe("thinking");
    expect(turns[1]?.kind).toBe("tool_use");
  });

  test("extractTurnOrder: order cannot be reversed", () => {
    const msg: AssistantMessage = {
      role: "assistant",
      uuid: "u3",
      timestamp: "2026",
      content: [
        { type: "thinking", thinking: "T" },
        { type: "text",     text: "X"     },
      ],
    };
    const turns = extractTurnOrder(msg);
    expect(turns.findIndex(t => t.kind === "thinking"))
      .toBeLessThan(turns.findIndex(t => t.kind === "text"));
  });
});

// ---------------------------------------------------------------------------
// AC2: Empty trimmed text → no rendered output.
// ---------------------------------------------------------------------------
describe("AC2: empty text message produces null", () => {
  test("AssistantTextMessage('') returns null", () => {
    expect(AssistantTextMessage({ text: "" })).toBeNull();
  });
  test("AssistantTextMessage('   ') returns null", () => {
    expect(AssistantTextMessage({ text: "   " })).toBeNull();
  });
  test("AssistantTextMessage('hi') is non-null", () => {
    expect(AssistantTextMessage({ text: "hi" })).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC3: credit-balance routes to specialized renderer (not plain text).
// ---------------------------------------------------------------------------
describe("AC3: credit-balance routes to specialized renderer", () => {
  test("classifyAssistantText detects credit-balance", () => {
    expect(classifyAssistantText("__credit_balance__")).toBe("credit-balance");
  });
  test("classifyAssistantText returns null for normal text", () => {
    expect(classifyAssistantText("Hello world")).toBeNull();
  });
  test("AssistantTextMessage credit-balance renders yellow border box", () => {
    const el = AssistantTextMessage({ text: "__credit_balance__" });
    expect(el).not.toBeNull();
    if (el) {
      const p = props(el);
      expect(p["borderColor"]).toBe("yellow");
    }
  });
  test("AssistantTextMessage credit-balance NOT a plain text renderer", () => {
    const plain = AssistantTextMessage({ text: "hello" });
    const credit = AssistantTextMessage({ text: "__credit_balance__" });
    // They should be different elements
    expect(JSON.stringify(plain)).not.toBe(JSON.stringify(credit));
  });
});

// ---------------------------------------------------------------------------
// AC4: isWaitingForPermission → tool name + permission-pending indicator.
// ---------------------------------------------------------------------------
describe("AC4: waiting-for-permission state", () => {
  test("AssistantToolUseMessage shows permission label when waiting", () => {
    const lookups = buildMessageLookups([]);
    lookups.permissionPendingToolUseIDs.add("tid1");
    const el = AssistantToolUseMessage({
      toolUseId: "tid1",
      toolName: "Write",
      toolFacingName: "Write",
      lookups,
    });
    const text = childText(el);
    expect(text).toContain("permission");
    expect(text).toContain("Write");
  });
});

// ---------------------------------------------------------------------------
// AC5: isResolved state shows outcome summary, not loader glyph.
// ---------------------------------------------------------------------------
describe("AC5: resolved state shows outcome, not BLACK_CIRCLE", () => {
  test("AssistantToolUseMessage resolved shows ✓, not BLACK_CIRCLE", () => {
    const msgs: Message[] = [
      {
        role: "assistant" as const,
        uuid: "a1",
        timestamp: "t",
        content: [{ type: "tool_use", id: "tid2", name: "Read" }],
      },
      {
        role: "user" as const,
        uuid: "u1",
        timestamp: "t",
        content: [{ type: "tool_result", tool_use_id: "tid2", content: "ok" }],
        toolUseResult: undefined,
      },
    ];
    const lookups = buildMessageLookups(msgs);
    const el = AssistantToolUseMessage({
      toolUseId: "tid2",
      toolName: "Read",
      lookups,
    });
    const text = childText(el);
    expect(text).toContain("✓");
    expect(text).not.toContain(BLACK_CIRCLE);
  });

  test("In-progress tool shows BLACK_CIRCLE", () => {
    const msgs: Message[] = [
      {
        role: "assistant" as const,
        uuid: "a2",
        timestamp: "t",
        content: [{ type: "tool_use", id: "tid3", name: "Bash" }],
      },
    ];
    const lookups = buildMessageLookups(msgs);
    const el = AssistantToolUseMessage({
      toolUseId: "tid3",
      toolName: "Bash",
      lookups,
    });
    expect(childText(el)).toContain(BLACK_CIRCLE);
  });
});

// ---------------------------------------------------------------------------
// AC6: Error text > 1000 chars → truncated with Ctrl+O expand control.
// ---------------------------------------------------------------------------
describe("AC6: long error text truncation", () => {
  test("MAX_API_ERROR_CHARS is 1000", () => {
    expect(MAX_API_ERROR_CHARS).toBe(1000);
  });

  test("AssistantTextMessage truncates text over 1000 chars", () => {
    const longText = "x".repeat(1001);
    const el = AssistantTextMessage({ text: longText, isExpanded: false });
    expect(el).not.toBeNull();
    const serialized = childText(el!);
    expect(serialized).toContain("Ctrl+O");
    // The actual text in the element should be ≤ 1000 chars content + ellipsis
    expect(serialized).not.toContain("x".repeat(1001));
  });

  test("AssistantTextMessage does NOT truncate when isExpanded=true", () => {
    const longText = "y".repeat(1001);
    const el = AssistantTextMessage({ text: longText, isExpanded: true });
    expect(el).not.toBeNull();
    expect(childText(el!)).not.toContain("Ctrl+O");
  });
});

// ---------------------------------------------------------------------------
// AC7: Thinking block with hideInTranscript=true renders nothing.
// ---------------------------------------------------------------------------
describe("AC7: hideInTranscript suppresses thinking", () => {
  test("AssistantThinkingMessage hideInTranscript=true → null", () => {
    expect(AssistantThinkingMessage({ thinking: "text", hideInTranscript: true })).toBeNull();
  });
  test("AssistantThinkingMessage hideInTranscript=false → non-null", () => {
    expect(AssistantThinkingMessage({ thinking: "text", hideInTranscript: false })).not.toBeNull();
  });
  test("AssistantThinkingMessage hideInTranscript absent → renders", () => {
    expect(AssistantThinkingMessage({ thinking: "think" })).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC8: CompactBoundaryMessage shows literal text.
// ---------------------------------------------------------------------------
describe("AC8: CompactBoundaryMessage literal text", () => {
  test("COMPACT_BOUNDARY_TEXT is exact spec string", () => {
    expect(COMPACT_BOUNDARY_TEXT).toBe("Conversation compacted (Ctrl+O for history)");
  });
  test("CompactBoundaryMessage renders COMPACT_BOUNDARY_TEXT", () => {
    const el = CompactBoundaryMessage();
    expect(props(el)["children"]).toBe(COMPACT_BOUNDARY_TEXT);
  });
});

// ---------------------------------------------------------------------------
// issue #197 leg 4: SystemAPIErrorMessage always renders a terminal error,
// regardless of retryCount. Supersedes the old "AC9: hidden for retries ≤ 3"
// spec -- that threshold assumed every terminal error had already retried
// past 3 attempts, which a deterministic 4xx (retryCount=0, no retry ever
// attempted) never does; hiding on retryCount<=3 made every such error
// invisible, a strictly worse regression than the "Retrying…" zombie text
// it was meant to guard against. A message only reaches this component once
// the turn has definitively ended (repl.ts's applyResultEvent), so there is
// no "still retrying, don't alarm the user yet" case left to hide.
// ---------------------------------------------------------------------------
describe("issue #197: API error always renders, any retryCount", () => {
  test("retryCount=0 (deterministic 4xx, never retried) → non-null", () => {
    expect(SystemAPIErrorMessage({ errorText: "err", retryCount: 0 })).not.toBeNull();
  });
  test("retryCount=1 → non-null", () => {
    expect(SystemAPIErrorMessage({ errorText: "err", retryCount: 1 })).not.toBeNull();
  });
  test("retryCount=3 → non-null", () => {
    expect(SystemAPIErrorMessage({ errorText: "err", retryCount: 3 })).not.toBeNull();
  });
  test("retryCount=4 → non-null", () => {
    expect(SystemAPIErrorMessage({ errorText: "err", retryCount: 4 })).not.toBeNull();
  });
  test("retryCount=0 never claims an in-progress retry (no 'Retrying…' text)", () => {
    const el = SystemAPIErrorMessage({ errorText: "err", retryCount: 0 })!;
    const rendered = JSON.stringify(el);
    expect(rendered).not.toContain("Retrying");
  });
  test("retryCount>0 surfaces a completed attempt count, not a live retry claim", () => {
    const el = SystemAPIErrorMessage({ errorText: "err", retryCount: 2 })!;
    const rendered = JSON.stringify(el);
    expect(rendered).toContain("Gave up after 2 retry attempts");
    expect(rendered).not.toContain("Retrying");
  });
});

// ---------------------------------------------------------------------------
// AC10: buildMessageLookups populates inProgressToolUseIDs.
// ---------------------------------------------------------------------------
describe("AC10: inProgressToolUseIDs for unresolved tool calls", () => {
  test("tool_use with no result → inProgress", () => {
    const msgs: Message[] = [
      {
        role: "assistant" as const,
        uuid: "a1",
        timestamp: "t",
        content: [{ type: "tool_use", id: "tool_123", name: "Read" }],
      },
    ];
    const lookups = buildMessageLookups(msgs);
    expect(lookups.inProgressToolUseIDs.has("tool_123")).toBe(true);
  });

  test("tool_use with result → resolved, not inProgress", () => {
    const msgs: Message[] = [
      {
        role: "assistant" as const,
        uuid: "a1",
        timestamp: "t",
        content: [{ type: "tool_use", id: "tool_456", name: "Read" }],
      },
      {
        role: "user" as const,
        uuid: "u1",
        timestamp: "t",
        content: [{ type: "tool_result", tool_use_id: "tool_456", content: "ok" }],
      },
    ];
    const lookups = buildMessageLookups(msgs);
    expect(lookups.inProgressToolUseIDs.has("tool_456")).toBe(false);
    expect(lookups.resolvedToolUseIDs.has("tool_456")).toBe(true);
  });

  test("multiple tools: some resolved, some in-progress", () => {
    const msgs: Message[] = [
      {
        role: "assistant" as const,
        uuid: "a1",
        timestamp: "t",
        content: [
          { type: "tool_use", id: "t1", name: "A" },
          { type: "tool_use", id: "t2", name: "B" },
        ],
      },
      {
        role: "user" as const,
        uuid: "u1",
        timestamp: "t",
        content: [{ type: "tool_result", tool_use_id: "t1", content: "ok" }],
      },
    ];
    const lookups = buildMessageLookups(msgs);
    expect(lookups.resolvedToolUseIDs.has("t1")).toBe(true);
    expect(lookups.inProgressToolUseIDs.has("t2")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC12: AttachmentMessage does not render idle_notification / teammate_terminated.
// ---------------------------------------------------------------------------
describe("AC12: AttachmentMessage filters silent types", () => {
  test("FILTERED_ATTACHMENT_TYPES contains idle_notification", () => {
    expect(FILTERED_ATTACHMENT_TYPES.has("idle_notification")).toBe(true);
  });
  test("FILTERED_ATTACHMENT_TYPES contains teammate_terminated", () => {
    expect(FILTERED_ATTACHMENT_TYPES.has("teammate_terminated")).toBe(true);
  });
  test("AttachmentMessage idle_notification → null", () => {
    expect(AttachmentMessage({ attachment: { type: "idle_notification" } })).toBeNull();
  });
  test("AttachmentMessage teammate_terminated → null", () => {
    expect(AttachmentMessage({ attachment: { type: "teammate_terminated" } })).toBeNull();
  });
  test("AttachmentMessage task_assignment → non-null", () => {
    expect(AttachmentMessage({ attachment: { type: "task_assignment", content: "x" } })).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC13: Auto-compaction text: "Razzle-dazzling…" / "⌁ Crunched for Xs".
// ---------------------------------------------------------------------------
describe("AC13: compaction display text", () => {
  test("COMPACTION_IN_PROGRESS_TEXT is 'Razzle-dazzling…'", () => {
    expect(COMPACTION_IN_PROGRESS_TEXT).toBe("Razzle-dazzling…");
  });
  test("COMPACTION_COMPLETE_PREFIX is '⌁ Crunched for '", () => {
    expect(COMPACTION_COMPLETE_PREFIX).toBe("⌁ Crunched for ");
  });
  test("CompactionProgressMessage during compaction shows Razzle-dazzling…", () => {
    const el = CompactionProgressMessage({ isComplete: false });
    expect(props(el)["children"]).toBe("Razzle-dazzling…");
  });
  test("CompactionProgressMessage complete shows '⌁ Crunched for Xs'", () => {
    const el = CompactionProgressMessage({ isComplete: true, elapsedSecs: 7 });
    expect(props(el)["children"]).toBe("⌁ Crunched for 7s");
  });
});

// ---------------------------------------------------------------------------
// AC14: Slash commands do not produce user or assistant message entries.
// ---------------------------------------------------------------------------
describe("AC14: slash commands are TUI-level", () => {
  test("isSlashCommand('/help') = true", () => {
    expect(isSlashCommand("/help")).toBe(true);
  });
  test("isSlashCommand('/model gpt-4') = true", () => {
    expect(isSlashCommand("/model gpt-4")).toBe(true);
  });
  test("isSlashCommand('hello world') = false", () => {
    expect(isSlashCommand("hello world")).toBe(false);
  });
  test("isSlashCommand('  /clear') = true (leading whitespace)", () => {
    expect(isSlashCommand("  /clear")).toBe(true);
  });
  test("MIN_HINT_DISPLAY_MS is 700", () => {
    expect(MIN_HINT_DISPLAY_MS).toBe(700);
  });
  test("BLACK_CIRCLE is ●", () => {
    expect(BLACK_CIRCLE).toBe("●");
  });
});

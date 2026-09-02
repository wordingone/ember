// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for message-adapter.ts — AC1–AC12

import { describe, it, expect } from "bun:test";
import {
  convertSDKMessage,
  isSessionEndMessage,
  isSuccessResult,
  getResultText,
  fromSDKCompactMetadata,
  type SDKMessage,
  type SDKResultMessage,
  type RemoteAssistantSDKMsg,
  type RemoteResultSDKMsg,
  type RemoteCompactBoundarySDKMsg,
} from "./message-adapter.ts";
import type { EmberMessage } from "../types/message-types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEmberMsg(): EmberMessage {
  return {
    id: "msg_001",
    type: "message",
    role: "assistant",
    content: [{ type: "text", text: "hello" }],
    model: "qwen-3.6",
    stop_reason: "end_turn",
    stop_sequence: null,
    usage: {
      input_tokens: 10,
      output_tokens: 5,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      cache_creation: { ephemeral_1h_input_tokens: 0, ephemeral_5m_input_tokens: 0 },
    },
  };
}

function assistantMsg(overrides?: Partial<RemoteAssistantSDKMsg>): SDKMessage {
  return {
    type: "assistant",
    uuid: "uuid-001",
    message: makeEmberMsg(),
    timestamp: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function streamEventMsg(): SDKMessage {
  return {
    type: "stream_event",
    event: { type: "message_start", message: { id: "msg_x", role: "assistant", model: "m", usage: { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, cache_creation: { ephemeral_1h_input_tokens: 0, ephemeral_5m_input_tokens: 0 } } } },
  };
}

function userToolResultMsg(): SDKMessage {
  return {
    type: "user",
    message: {
      content: [
        { type: "tool_result", tool_use_id: "tu_1", content: "ok" },
      ],
    },
  };
}

function userTextMsg(): SDKMessage {
  return {
    type: "user",
    message: {
      content: [{ type: "text", text: "hello" }],
    },
  };
}

function resultMsg(subtype: string, extra?: Partial<RemoteResultSDKMsg>): SDKMessage {
  return { type: "result", subtype, result: "done", ...extra } as SDKMessage;
}

// ---------------------------------------------------------------------------
// AC1: assistant → AssistantMessage
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC1 (assistant)", () => {
  it("AC1: produces type='message' with AssistantMessage", () => {
    const out = convertSDKMessage(assistantMsg());
    expect(out.type).toBe("message");
    if (out.type === "message") {
      expect(out.message.role).toBe("assistant");
    }
  });

  it("AC1: preserves uuid from SDK message", () => {
    const out = convertSDKMessage(assistantMsg({ uuid: "my-uuid" }));
    if (out.type === "message") {
      const am = out.message as { uuid?: string };
      expect(am.uuid).toBe("my-uuid");
    }
  });

  it("AC1: preserves timestamp from SDK message", () => {
    const ts = "2026-06-01T12:00:00.000Z";
    const out = convertSDKMessage(assistantMsg({ timestamp: ts }));
    if (out.type === "message") {
      const am = out.message as { timestamp?: string };
      expect(am.timestamp).toBe(ts);
    }
  });

  it("AC1: attaches raw message to AssistantMessage.message", () => {
    const raw = makeEmberMsg();
    const out = convertSDKMessage(assistantMsg({ message: raw }));
    if (out.type === "message") {
      const am = out.message as { message?: unknown };
      expect(am.message).toBe(raw);
    }
  });
});

// ---------------------------------------------------------------------------
// AC2: stream_event → stream_event event
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC2 (stream_event)", () => {
  it("AC2: produces type='stream_event'", () => {
    const out = convertSDKMessage(streamEventMsg());
    expect(out.type).toBe("stream_event");
  });

  it("AC2: event field is the raw streaming event (reference equality)", () => {
    const msg = streamEventMsg();
    const rawEvent = (msg as unknown as { event: unknown }).event;
    const out = convertSDKMessage(msg);
    if (out.type === "stream_event") {
      expect(out.event as unknown).toBe(rawEvent);
    }
  });
});

// ---------------------------------------------------------------------------
// AC3: user + tool_result
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC3 (user tool_result)", () => {
  it("AC3: with convertToolResults=true → UserMessage", () => {
    const out = convertSDKMessage(userToolResultMsg(), { convertToolResults: true });
    expect(out.type).toBe("message");
    if (out.type === "message") {
      expect(out.message.role).toBe("user");
    }
  });

  it("AC3: with convertToolResults=false → ignored", () => {
    const out = convertSDKMessage(userToolResultMsg(), { convertToolResults: false });
    expect(out.type).toBe("ignored");
  });

  it("AC3: default (no opts) → ignored", () => {
    const out = convertSDKMessage(userToolResultMsg());
    expect(out.type).toBe("ignored");
  });

  it("AC3: type detection uses type=tool_result, not parent_tool_use_id", () => {
    const msg: SDKMessage = {
      type: "user",
      message: {
        content: [
          // No parent_tool_use_id field, but type is tool_result
          { type: "tool_result", tool_use_id: "tu_x" },
        ],
      },
    };
    const out = convertSDKMessage(msg, { convertToolResults: true });
    expect(out.type).toBe("message");
  });
});

// ---------------------------------------------------------------------------
// AC4: user + text message
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC4 (user text)", () => {
  it("AC4: with convertUserTextMessages=true → UserMessage", () => {
    const out = convertSDKMessage(userTextMsg(), { convertUserTextMessages: true });
    expect(out.type).toBe("message");
    if (out.type === "message") {
      expect(out.message.role).toBe("user");
    }
  });

  it("AC4: with convertUserTextMessages=false → ignored", () => {
    const out = convertSDKMessage(userTextMsg(), { convertUserTextMessages: false });
    expect(out.type).toBe("ignored");
  });

  it("AC4: default (no opts) → ignored", () => {
    const out = convertSDKMessage(userTextMsg());
    expect(out.type).toBe("ignored");
  });
});

// ---------------------------------------------------------------------------
// AC5: system status=compacting
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC5 (system compacting)", () => {
  it("AC5: status=compacting → SystemMessage with 'Compacting conversation…'", () => {
    const msg: SDKMessage = { type: "system", status: "compacting" };
    const out = convertSDKMessage(msg);
    expect(out.type).toBe("message");
    if (out.type === "message") {
      const sm = out.message as { content?: string; role?: string };
      expect(sm.content).toBe("Compacting conversation…");
      expect(sm.role).toBe("system");
    }
  });

  it("other status values → 'Status: {status}'", () => {
    const msg: SDKMessage = { type: "system", status: "idle" };
    const out = convertSDKMessage(msg);
    if (out.type === "message") {
      const sm = out.message as { content?: string };
      expect(sm.content).toBe("Status: idle");
    }
  });
});

// ---------------------------------------------------------------------------
// AC6: system with no status → ignored
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC6 (system no status)", () => {
  it("AC6: system with no status field → ignored", () => {
    const msg: SDKMessage = { type: "system" };
    const out = convertSDKMessage(msg);
    expect(out.type).toBe("ignored");
  });

  it("AC6: system with subtype but no status → ignored (unless init)", () => {
    const msg: SDKMessage = { type: "system", subtype: "something_else" };
    const out = convertSDKMessage(msg);
    expect(out.type).toBe("ignored");
  });

  it("system subtype=init with model → produces info SystemMessage", () => {
    const msg: SDKMessage = { type: "system", subtype: "init", model: "qwen-3.6" };
    const out = convertSDKMessage(msg);
    expect(out.type).toBe("message");
    if (out.type === "message") {
      const sm = out.message as { content?: string };
      expect(sm.content).toBe("qwen-3.6");
    }
  });
});

// ---------------------------------------------------------------------------
// AC7: result subtype=success
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC7 (result success)", () => {
  it("AC7: success → SystemMessage level info", () => {
    const out = convertSDKMessage(resultMsg("success", { result: "Task done" }));
    expect(out.type).toBe("message");
    if (out.type === "message") {
      const sm = out.message as { type?: string; content?: string };
      expect(sm.type).toBe("info");
      expect(sm.content).toBe("Task done");
    }
  });
});

// ---------------------------------------------------------------------------
// AC8: result subtype=error
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC8 (result error)", () => {
  it("AC8: error subtype → SystemMessage level warning (api_error)", () => {
    const out = convertSDKMessage(resultMsg("error", { error: "something broke" }));
    expect(out.type).toBe("message");
    if (out.type === "message") {
      const sm = out.message as { type?: string };
      expect(sm.type).toBe("api_error");
    }
  });

  it("AC8: error message has error content", () => {
    const out = convertSDKMessage(resultMsg("error", { error: "timeout" }));
    if (out.type === "message") {
      const sm = out.message as { content?: string };
      expect(sm.content).toContain("timeout");
    }
  });
});

// ---------------------------------------------------------------------------
// AC9 + AC10: isSessionEndMessage
// ---------------------------------------------------------------------------

describe("isSessionEndMessage", () => {
  it("AC9: result message → true", () => {
    const msg: SDKMessage = { type: "result", subtype: "success", result: "ok" };
    expect(isSessionEndMessage(msg)).toBe(true);
  });

  it("AC9: result with error subtype → true", () => {
    const msg: SDKMessage = { type: "result", subtype: "error" };
    expect(isSessionEndMessage(msg)).toBe(true);
  });

  it("AC10: assistant message → false", () => {
    const msg: SDKMessage = assistantMsg();
    expect(isSessionEndMessage(msg)).toBe(false);
  });

  it("AC10: system message → false", () => {
    const msg: SDKMessage = { type: "system", status: "idle" };
    expect(isSessionEndMessage(msg)).toBe(false);
  });

  it("AC10: user message → false", () => {
    const msg: SDKMessage = { type: "user" };
    expect(isSessionEndMessage(msg)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC11: filtered types → ignored
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC11 (filtered types)", () => {
  it("AC11: tool_use_summary → ignored", () => {
    const msg: SDKMessage = { type: "tool_use_summary", summary: "...", precedingToolUseIds: [] };
    expect(convertSDKMessage(msg).type).toBe("ignored");
  });

  it("AC11: auth_status → ignored", () => {
    const msg: SDKMessage = { type: "auth_status" };
    expect(convertSDKMessage(msg).type).toBe("ignored");
  });

  it("AC11: rate_limit_event → ignored", () => {
    const msg: SDKMessage = { type: "rate_limit_event" };
    expect(convertSDKMessage(msg).type).toBe("ignored");
  });

  it("AC11: unknown type → ignored", () => {
    const msg: SDKMessage = { type: "totally_unknown_future_type" };
    expect(convertSDKMessage(msg).type).toBe("ignored");
  });
});

// ---------------------------------------------------------------------------
// AC12: compact_boundary → SystemMessage with compactMetadata
// ---------------------------------------------------------------------------

describe("convertSDKMessage — AC12 (compact_boundary)", () => {
  it("AC12: produces SystemMessage with subtype=compact_boundary", () => {
    const msg: RemoteCompactBoundarySDKMsg = {
      type: "compact_boundary",
      summary: "Compacted 5 turns",
      tokens_saved: 1200,
    };
    const out = convertSDKMessage(msg as SDKMessage);
    expect(out.type).toBe("message");
    if (out.type === "message") {
      const sm = out.message as { type?: string; content?: string };
      expect(sm.type).toBe("compact_boundary");
      expect(sm.content).toBe("Conversation compacted");
    }
  });

  it("AC12: compactMetadata is attached", () => {
    const msg: RemoteCompactBoundarySDKMsg = {
      type: "compact_boundary",
      summary: "summary text",
      tokens_saved: 500,
    };
    const out = convertSDKMessage(msg as SDKMessage);
    if (out.type === "message") {
      const sm = out.message as { compactMetadata?: { summary: string; tokensSaved: number } };
      expect(sm.compactMetadata?.summary).toBe("summary text");
      expect(sm.compactMetadata?.tokensSaved).toBe(500);
    }
  });
});

// ---------------------------------------------------------------------------
// isSuccessResult + getResultText
// ---------------------------------------------------------------------------

describe("isSuccessResult", () => {
  it("returns true for success subtype", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "success", result: "ok" };
    expect(isSuccessResult(msg)).toBe(true);
  });

  it("returns false for error subtype", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "error" };
    expect(isSuccessResult(msg)).toBe(false);
  });

  it("returns false for max_turns subtype", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "max_turns" };
    expect(isSuccessResult(msg)).toBe(false);
  });
});

describe("getResultText", () => {
  it("returns msg.result on success", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "success", result: "done" };
    expect(getResultText(msg)).toBe("done");
  });

  it("returns null on error", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "error" };
    expect(getResultText(msg)).toBeNull();
  });

  it("returns null if result is undefined on success", () => {
    const msg: SDKResultMessage = { type: "result", subtype: "success" };
    expect(getResultText(msg)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// fromSDKCompactMetadata
// ---------------------------------------------------------------------------

describe("fromSDKCompactMetadata", () => {
  it("maps summary and tokens_saved", () => {
    const meta = fromSDKCompactMetadata({
      type: "compact_boundary",
      summary: "5 turns compacted",
      tokens_saved: 800,
    });
    expect(meta.summary).toBe("5 turns compacted");
    expect(meta.tokensSaved).toBe(800);
  });

  it("defaults to empty string + 0 when fields are absent", () => {
    const meta = fromSDKCompactMetadata({ type: "compact_boundary" });
    expect(meta.summary).toBe("");
    expect(meta.tokensSaved).toBe(0);
  });
});

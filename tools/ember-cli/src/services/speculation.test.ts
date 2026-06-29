// services/speculation.test.ts
// Covers AC5–AC7 from the speculation surface spec.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, readFile, rm } from "fs/promises";
import type { EmberMessage } from "../types/message-types.ts";
import {
  prepareMessagesForInjection,
  copyOverlayToMain,
} from "./speculation.ts";
import { shouldFilterSuggestion } from "./prompt-suggestion.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function textMsg(role: "user" | "assistant" | "system", text: string): EmberMessage {
  return { role, content: text };
}

function blockMsg(
  role: "user" | "assistant",
  blocks: Array<Record<string, unknown>>,
): EmberMessage {
  return { role, content: blocks as EmberMessage["content"] };
}

// ---------------------------------------------------------------------------
// AC5 — prepareMessagesForInjection
// ---------------------------------------------------------------------------

describe("AC5: prepareMessagesForInjection", () => {
  it("removes thinking blocks from content arrays", () => {
    const messages: EmberMessage[] = [
      blockMsg("assistant", [
        { type: "thinking", thinking: "internal monologue" },
        { type: "text", text: "visible response" },
      ]),
    ];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(1);
    const content = result[0]!.content as Array<Record<string, unknown>>;
    expect(content.some((b) => b["type"] === "thinking")).toBe(false);
    expect(content.some((b) => b["type"] === "text")).toBe(true);
  });

  it("removes redacted_thinking blocks from content arrays", () => {
    const messages: EmberMessage[] = [
      blockMsg("assistant", [
        { type: "redacted_thinking", data: "encrypted" },
        { type: "text", text: "visible response" },
      ]),
    ];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(1);
    const content = result[0]!.content as Array<Record<string, unknown>>;
    expect(content.some((b) => b["type"] === "redacted_thinking")).toBe(false);
  });

  it("removes orphan tool_use blocks (no matching tool_result)", () => {
    const messages: EmberMessage[] = [
      blockMsg("assistant", [
        { type: "tool_use", id: "orphan-id", name: "read_file", input: {} },
        { type: "text", text: "calling tool" },
      ]),
      // No tool_result for 'orphan-id'
    ];
    const result = prepareMessagesForInjection(messages);
    // The assistant message should have only the text block
    const content = result[0]!.content as Array<Record<string, unknown>>;
    expect(content.some((b) => b["type"] === "tool_use")).toBe(false);
    expect(content.some((b) => b["type"] === "text")).toBe(true);
  });

  it("keeps tool_use that has a matching errored tool_result (not orphaned)", () => {
    const toolId = "errored-tool-id";
    const messages: EmberMessage[] = [
      blockMsg("assistant", [
        { type: "tool_use", id: toolId, name: "bash", input: { command: "ls" } },
      ]),
      blockMsg("user", [
        {
          type: "tool_result",
          tool_use_id: toolId,
          content: "permission denied",
          is_error: true,
        },
      ]),
    ];
    const result = prepareMessagesForInjection(messages);
    // Both messages should survive: tool_use has a result (even errored)
    expect(result).toHaveLength(2);
    const assistantContent = result[0]!.content as Array<Record<string, unknown>>;
    expect(assistantContent.some((b) => b["type"] === "tool_use")).toBe(true);
    const userContent = result[1]!.content as Array<Record<string, unknown>>;
    expect(userContent.some((b) => b["type"] === "tool_result")).toBe(true);
  });

  it("removes messages matching the user-interrupt sentinel", () => {
    const interruptMsg: EmberMessage = {
      role: "user",
      content: "\n[Request interrupted by user]",
    };
    const messages: EmberMessage[] = [
      textMsg("user", "hello"),
      interruptMsg,
      textMsg("assistant", "hi"),
    ];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(2);
    expect(result.some((m) => m.content === "\n[Request interrupted by user]")).toBe(false);
  });

  it("removes messages matching the tool-use interrupt sentinel", () => {
    const interruptMsg: EmberMessage = {
      role: "user",
      content: "\n[Request interrupted by user for tool use]",
    };
    const messages: EmberMessage[] = [interruptMsg, textMsg("assistant", "ok")];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(1);
    expect(result[0]!.role).toBe("assistant");
  });

  it("drops messages that are empty or whitespace-only after filtering", () => {
    const messages: EmberMessage[] = [
      textMsg("user", "   "),
      textMsg("assistant", ""),
      blockMsg("assistant", [
        // Only a thinking block — will be removed, leaving an empty array
        { type: "thinking", thinking: "hmm" },
      ]),
      textMsg("user", "real message"),
    ];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(1);
    expect(result[0]!.content).toBe("real message");
  });

  it("preserves valid messages untouched", () => {
    const messages: EmberMessage[] = [
      textMsg("user", "what is 2+2"),
      textMsg("assistant", "it is 4"),
    ];
    const result = prepareMessagesForInjection(messages);
    expect(result).toHaveLength(2);
    expect(result[0]!.content).toBe("what is 2+2");
    expect(result[1]!.content).toBe("it is 4");
  });

  it("handles empty input array", () => {
    const result = prepareMessagesForInjection([]);
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// AC6 — copyOverlayToMain
// ---------------------------------------------------------------------------

describe("AC6: copyOverlayToMain", () => {
  const testId = `speculation-test-${Date.now()}`;
  const overlayDir = join(tmpdir(), "ember-overlay-test", testId, "overlay");
  const mainDir = join(tmpdir(), "ember-overlay-test", testId, "main");

  beforeEach(async () => {
    await mkdir(overlayDir, { recursive: true });
    await mkdir(mainDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(join(tmpdir(), "ember-overlay-test", testId), {
      recursive: true,
      force: true,
    });
  });

  it("copies a flat file from overlay to main dir", async () => {
    const filename = "output.txt";
    const content = "speculated content";
    await writeFile(join(overlayDir, filename), content, "utf-8");

    const ok = await copyOverlayToMain(overlayDir, new Set([filename]), mainDir);
    expect(ok).toBe(true);

    const dest = join(mainDir, filename);
    const read = await readFile(dest, "utf-8");
    expect(read).toBe(content);
  });

  it("copies a nested file and creates parent dirs", async () => {
    const relPath = join("subdir", "nested.txt");
    const content = "nested file content";
    await mkdir(join(overlayDir, "subdir"), { recursive: true });
    await writeFile(join(overlayDir, relPath), content, "utf-8");

    const ok = await copyOverlayToMain(
      overlayDir,
      new Set([relPath]),
      mainDir,
    );
    expect(ok).toBe(true);

    const read = await readFile(join(mainDir, relPath), "utf-8");
    expect(read).toBe(content);
  });

  it("returns false when source file does not exist", async () => {
    const ok = await copyOverlayToMain(
      overlayDir,
      new Set(["nonexistent.txt"]),
      mainDir,
    );
    expect(ok).toBe(false);
  });

  it("copies multiple files and returns true when all succeed", async () => {
    const files = ["a.txt", "b.txt", "c.txt"];
    for (const f of files) {
      await writeFile(join(overlayDir, f), `content of ${f}`, "utf-8");
    }

    const ok = await copyOverlayToMain(overlayDir, new Set(files), mainDir);
    expect(ok).toBe(true);

    for (const f of files) {
      const content = await readFile(join(mainDir, f), "utf-8");
      expect(content).toBe(`content of ${f}`);
    }
  });
});

// ---------------------------------------------------------------------------
// AC7 — shouldFilterSuggestion on speculation-like outputs
// ---------------------------------------------------------------------------

describe("AC7: shouldFilterSuggestion on speculation outputs", () => {
  it("filters assistant-voice prefix \"I'll\"", () => {
    expect(
      shouldFilterSuggestion("I'll complete that for you", "user_intent"),
    ).toBe(true);
  });

  it("filters evaluative opener 'great'", () => {
    expect(
      shouldFilterSuggestion("great, let's do that", "user_intent"),
    ).toBe(true);
  });

  it("keeps a direct action phrase", () => {
    expect(shouldFilterSuggestion("fix the bug", "user_intent")).toBe(false);
  });

  it("keeps a short command phrase", () => {
    expect(shouldFilterSuggestion("run the tests", "user_intent")).toBe(false);
  });

  it("keeps a two-word instruction", () => {
    expect(shouldFilterSuggestion("build project", "user_intent")).toBe(false);
  });

  it("filters 'Of course' voice prefix", () => {
    expect(
      shouldFilterSuggestion("Of course I can help", "stated_intent"),
    ).toBe(true);
  });
});

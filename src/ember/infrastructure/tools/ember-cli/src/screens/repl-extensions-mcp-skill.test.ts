// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-extensions-mcp-skill.test.ts — issue #2375 through the REAL ReplScreen, the real
// QueryEngine and the real keyboard path (only callModel is scripted):
//   * the model calls a stdio MCP server's tool, and the result comes back to it
//   * a server that fails to start shows a notice row and the session still works
//   * a skill runs as a /<skill> slash command (its text is what the model receives)
// One real mount per file (see repl-suggestion-boundary-real-scheduling-success.test.ts).

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { _resetExtensionsForTests, awaitExtensionsReady, startExtensions, stopExtensions } from "../extensions/runtime.ts";
import { ReplScreen } from "../screens/repl.ts";

const FIXTURE = join(import.meta.dir, "..", "extensions", "__fixtures__", "tiny-mcp-server.ts");

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function until(pred: () => boolean, maxMs = 8000): Promise<void> {
  const start = Date.now();
  while (!pred() && Date.now() - start < maxMs) await wait(20);
}

function renderedText(raw: string, columns: number, rows: number): string {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join("")).join("\n");
}

async function typeLine(text: string): Promise<void> {
  for (const ch of text) _deliverKeyEvent(ch, {});
  await wait(200);
  _deliverKeyEvent("return", {});
}

describe("issue #2375 — MCP tool + skill command through the real REPL", () => {
  afterEach(async () => {
    mock.restore();
    await stopExtensions();
    _resetExtensionsForTests();
    resetCommandRegistryForTests();
  });

  test("the model calls an MCP tool; a broken server is a notice; a skill runs as /<skill>", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-repl-ext-"));
    const home = join(root, "home");
    const proj = join(root, "proj");
    mkdirSync(home, { recursive: true });
    mkdirSync(join(proj, ".ember", "skills", "shout"), { recursive: true });
    writeFileSync(
      join(home, "mcp.json"),
      JSON.stringify({
        mcpServers: {
          tiny: { command: process.execPath, args: ["run", FIXTURE] },
          broken: { command: "ember-no-such-binary-xyz" },
        },
      }),
    );
    writeFileSync(
      join(proj, ".ember", "skills", "shout", "SKILL.md"),
      "---\nname: shout\ndescription: Shout it\n---\nReply with the text in capitals: $ARGUMENTS\n",
    );

    // The prompt-suggestion side call would otherwise reach the scripted model too.
    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async () => {},
      makeSuggestionExecutor: () => async () => ({}),
    }));

    // What the model is asked, and what it is shown, on each call.
    const modelCalls: Array<{ toolNames: string[]; lastUser: string }> = [];
    let script = 0;
    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async (p: { messages: Array<{ role: string; content: unknown }>; tools?: Array<{ name: string }> }): Promise<ModelResponse> => {
          const last = p.messages[p.messages.length - 1]!;
          const blocks = Array.isArray(last.content) ? (last.content as Array<Record<string, unknown>>) : [];
          const lastUser = blocks
            .map((b) => (b["type"] === "tool_result" ? `[tool_result] ${String(b["content"])}` : String(b["text"] ?? "")))
            .join("\n");
          modelCalls.push({ toolNames: (p.tools ?? []).map((t) => t.name), lastUser });
          script++;
          if (script === 1) {
            return { role: "assistant", content: [{ type: "tool_use", id: "c1", name: "mcp__tiny__echo", input: { text: "from the TUI" } }], stop_reason: "tool_use" };
          }
          return { role: "assistant", content: [{ type: "text", text: `scripted reply ${script}` }], stop_reason: "end_turn" };
        },
        microcompact: async (m: unknown[]) => m,
        autocompact: async () => {},
        generateUuid: () => crypto.randomUUID(),
        sleep: async () => {},
      }),
      getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
      getCircuitBreakerState: () => null,
    }));

    startExtensions({ cwd: proj, home, connectTimeoutMs: 15_000 });
    await awaitExtensionsReady(30_000);

    let raw = "";
    const columns = 120, rows = 40;
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const handle = mountInk(
      React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, { config, cwd: proj, env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" }, onExit: () => {} }),
      ),
      { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } },
    );

    try {
      await wait(300);
      // Turn 1: an ordinary prompt; the scripted model answers with an MCP tool call.
      await typeLine("please echo something");
      await until(() => modelCalls.length >= 2);
      expect(modelCalls.length).toBe(2);
      expect(modelCalls[0]!.toolNames).toContain("mcp__tiny__echo");
      expect(modelCalls[1]!.lastUser).toBe("[tool_result] echo: from the TUI");

      // The failed server is visible as a notice, in the transcript.
      await until(() => renderedText(raw, columns, rows).includes("scripted reply 2"));
      const screen = renderedText(raw, columns, rows);
      expect(screen).toContain('MCP server "broken" failed to start');

      // Turn 2: the skill, typed as a slash command, reaches the model with its text.
      await typeLine("/shout hello world");
      await until(() => modelCalls.length >= 3);
      expect(modelCalls.length).toBe(3);
      expect(modelCalls[2]!.lastUser).toContain("Reply with the text in capitals: hello world");
    } finally {
      handle.unmount();
      await stopExtensions(); // stops the MCP server processes this test started
      await wait(800);
      try {
        rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      } catch {
        // a temp dir still held by an exiting child is not a test failure
      }
    }
  }, 60_000);
});

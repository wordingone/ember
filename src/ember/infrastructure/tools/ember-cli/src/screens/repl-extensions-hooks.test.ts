// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-extensions-hooks.test.ts — issue #2376 through the REAL ReplScreen, QueryEngine,
// the real Bash tool and the real keyboard path (only callModel is scripted):
//   * a PreToolUse hook (exit 2) blocks a Bash call; the command never runs and the model is
//     shown the hook's stderr as the reason
//   * a UserPromptSubmit hook (exit 2) blocks a prompt before any model call

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
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

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const fwd = (p: string): string => p.replace(/\\/g, "/");

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

describe("issue #2376 — hooks through the real REPL", () => {
  afterEach(async () => {
    mock.restore();
    await stopExtensions();
    _resetExtensionsForTests();
    resetCommandRegistryForTests();
  });

  test("a PreToolUse hook blocks a Bash call; a UserPromptSubmit hook blocks a prompt", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-repl-hooks-"));
    const home = join(root, "home");
    const proj = join(root, "proj");
    mkdirSync(home, { recursive: true });
    mkdirSync(join(proj, ".ember"), { recursive: true });
    const marker = join(root, "marker-file.txt");
    const bun = fwd(process.execPath);
    const preHook = fwd(join(root, "pre.ts"));
    writeFileSync(
      preHook,
      'const i = JSON.parse(await Bun.stdin.text());\n' +
        'if (String(i.tool_input.command).includes("marker")) { console.error("Bash writes to marker files are not allowed here"); process.exit(2); }\n',
    );
    const promptHook = fwd(join(root, "prompt.ts"));
    writeFileSync(
      promptHook,
      'const i = JSON.parse(await Bun.stdin.text());\n' +
        'if (i.prompt.includes("forbidden")) { console.error("that topic is off limits"); process.exit(2); }\n',
    );
    writeFileSync(
      join(proj, ".ember", "settings.json"),
      JSON.stringify({
        hooks: {
          PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: `"${bun}" run "${preHook}"`, timeout: 20 }] }],
          UserPromptSubmit: [{ hooks: [{ type: "command", command: `"${bun}" run "${promptHook}"`, timeout: 20 }] }],
        },
      }),
    );

    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async () => {},
      makeSuggestionExecutor: () => async () => ({}),
    }));
    const markerPath = fwd(marker);
    const seen: string[] = [];
    let n = 0;
    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async (p: { messages: Array<{ role: string; content: unknown }> }): Promise<ModelResponse> => {
          const last = p.messages[p.messages.length - 1]!;
          const blocks = Array.isArray(last.content) ? (last.content as Array<Record<string, unknown>>) : [];
          seen.push(blocks.map((b) => (b["type"] === "tool_result" ? `[tool_result] ${String(b["content"])}` : String(b["text"] ?? ""))).join("\n"));
          n++;
          if (n === 1) {
            return {
              role: "assistant",
              content: [{ type: "tool_use", id: "b1", name: "Bash", input: { command: `echo hi > "${markerPath}"` } }],
              stop_reason: "tool_use",
            };
          }
          return { role: "assistant", content: [{ type: "text", text: `scripted reply ${n}` }], stop_reason: "end_turn" };
        },
        microcompact: async (m: unknown[]) => m,
        autocompact: async () => {},
        generateUuid: () => crypto.randomUUID(),
        sleep: async () => {},
      }),
      getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
      getCircuitBreakerState: () => null,
    }));

    startExtensions({ cwd: proj, home });
    await awaitExtensionsReady(15_000);

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
      await typeLine("write the marker file");
      await until(() => seen.length >= 2);
      expect(seen.length).toBe(2);
      expect(seen[1]).toBe("[tool_result] PreToolUse hook blocked Bash: Bash writes to marker files are not allowed here");
      expect(existsSync(marker)).toBe(false); // the command never ran

      // A prompt the UserPromptSubmit hook refuses never reaches the model.
      await until(() => renderedText(raw, columns, rows).includes("scripted reply 2"));
      await typeLine("tell me something forbidden");
      await until(() => renderedText(raw, columns, rows).includes("that topic is off limits"), 8000);
      expect(renderedText(raw, columns, rows)).toContain("Prompt blocked by a UserPromptSubmit hook: that topic is off limits");
      expect(seen.length).toBe(2);
    } finally {
      handle.unmount();
      await stopExtensions();
      await wait(500);
      try {
        rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      } catch {
        // ignore
      }
    }
  }, 60_000);
});

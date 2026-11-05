// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/project-context.test.ts -- #2374: instruction files and the memory index reach the
// system prompt, capped and listed, and the model can add memory with its file tools.

import { afterEach, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  appendProjectContext,
  contextNoticeLine,
  describeLoadedContext,
  listMemoryFiles,
  loadProjectContext,
  memoryDirFor,
  systemPromptWithContext,
} from "./project-context.ts";
import { writeTool } from "../tools/file-write.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";
import { QueryEngine } from "../core/query-engine.ts";
import type { CallModelParams, LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";

const made: string[] = [];
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

/** A fake EMBER_HOME and a fake repository (marked by a .git directory) with a nested cwd. */
function world(): { home: string; root: string; sub: string } {
  const base = mkdtempSync(join(tmpdir(), "ember-ctx-"));
  made.push(base);
  const home = join(base, "home");
  const root = join(base, "repo");
  const sub = join(root, "pkg", "inner");
  mkdirSync(home, { recursive: true });
  mkdirSync(join(root, ".git"), { recursive: true });
  mkdirSync(sub, { recursive: true });
  return { home, root, sub };
}
const put = (path: string, text: string) => writeFileSync(path, text, "utf-8");

describe("loadProjectContext: instruction files", () => {
  it("orders user, then repo root down to the cwd (EMBER, AGENTS, CLAUDE), then the memory index", () => {
    const { home, root, sub } = world();
    put(join(home, "EMBER.md"), "USER-RULE");
    put(join(root, "EMBER.md"), "ROOT-EMBER");
    put(join(root, "CLAUDE.md"), "ROOT-CLAUDE");
    put(join(root, "pkg", "AGENTS.md"), "PKG-AGENTS");
    put(join(sub, "CLAUDE.md"), "INNER-CLAUDE");
    const mem = memoryDirFor(sub, home);
    mkdirSync(mem, { recursive: true });
    put(join(mem, "MEMORY.md"), "- [Plum](plum.md) - the secret word\n");

    const ctx = loadProjectContext({ cwd: sub, home });
    const at = (s: string) => ctx.prompt.indexOf(s);
    const order = ["USER-RULE", "ROOT-EMBER", "ROOT-CLAUDE", "PKG-AGENTS", "INNER-CLAUDE", "the secret word"].map(at);
    expect(order.every((n) => n >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(ctx.files.map((f) => f.label)).toEqual([
      "EMBER.md (user)", "EMBER.md", "CLAUDE.md", "pkg/AGENTS.md", "pkg/inner/CLAUDE.md", "MEMORY.md",
    ]);
    expect(ctx.files.map((f) => f.kind)).toEqual(["user", "project", "project", "project", "project", "memory"]);
    expect(ctx.files.at(-1)?.entries).toBe(1);
  });

  it("skips blank files and strips a BOM; nothing found means an empty prompt", () => {
    const { home, root } = world();
    put(join(root, "CLAUDE.md"), "   \n\n");
    put(join(root, "AGENTS.md"), "﻿be brief");
    const ctx = loadProjectContext({ cwd: root, home, memoryGuidance: false });
    expect(ctx.files.map((f) => f.label)).toEqual(["AGENTS.md"]);
    expect(ctx.prompt).toContain("be brief");
    expect(ctx.prompt).not.toContain("﻿");

    const none = world();
    const empty = loadProjectContext({ cwd: none.root, home: none.home, memoryGuidance: false });
    expect(empty.prompt).toBe("");
    expect(empty.files).toEqual([]);
    expect(contextNoticeLine(empty)).toBeNull();
  });

  it("cuts an over-long file on a line boundary, says so in the prompt, and lists it as cut", () => {
    const { home, root } = world();
    const body = Array.from({ length: 400 }, (_, i) => `rule number ${i}`).join("\n");
    put(join(root, "CLAUDE.md"), body);
    const ctx = loadProjectContext({ cwd: root, home, memoryGuidance: false, limits: { fileChars: 1000 } });
    const f = ctx.files[0]!;
    expect(f.status).toBe("truncated");
    expect(f.chars).toBe(body.length);
    expect(f.included).toBeLessThanOrEqual(1000);
    expect(ctx.prompt).toContain("rule number 0");
    expect(ctx.prompt).not.toContain("rule number 399");
    expect(ctx.prompt).toMatch(/\[truncated: \d+ more characters; read .*CLAUDE\.md for the rest\]/);
    expect(describeLoadedContext(ctx)).toContain("cut to");
    expect(contextNoticeLine(ctx)).toContain("[cut]");
  });

  it("over the total cap the files nearest the cwd are kept and the rest are listed as left out", () => {
    const { home, root, sub } = world();
    put(join(home, "EMBER.md"), "U".repeat(600));
    put(join(root, "CLAUDE.md"), "R".repeat(600));
    put(join(sub, "CLAUDE.md"), "I".repeat(600));
    const ctx = loadProjectContext({ cwd: sub, home, memoryGuidance: false, limits: { totalChars: 1300 } });
    const byLabel = Object.fromEntries(ctx.files.map((f) => [f.label, f.status]));
    expect(byLabel).toEqual({ "EMBER.md (user)": "omitted", "CLAUDE.md": "full", "pkg/inner/CLAUDE.md": "full" });
    expect(ctx.prompt).toContain("I".repeat(600));
    expect(ctx.prompt).not.toContain("U".repeat(10));
    expect(describeLoadedContext(ctx)).toContain("LEFT OUT");
    expect(contextNoticeLine(ctx)).toContain("left out");
  });
});

describe("loadProjectContext: memory", () => {
  it("keys the memory directory by repository root, so subdirectories share it", () => {
    const { home, root, sub } = world();
    expect(memoryDirFor(sub, home)).toBe(memoryDirFor(root, home));
    expect(memoryDirFor(root, home).startsWith(join(home, "memory"))).toBe(true);
    expect(memoryDirFor(join(home, "elsewhere"), home)).not.toBe(memoryDirFor(root, home));
  });

  it("caps the index by lines and by characters and says what was cut", () => {
    const { home, root } = world();
    const mem = memoryDirFor(root, home);
    mkdirSync(mem, { recursive: true });
    const index = Array.from({ length: 300 }, (_, i) => `- [F${i}](f${i}.md) - h`).join("\n");
    put(join(mem, "MEMORY.md"), index);
    const ctx = loadProjectContext({ cwd: root, home, memoryGuidance: false });
    const f = ctx.files[0]!;
    expect(f.status).toBe("truncated");
    expect(f.entries).toBe(300);
    expect(ctx.prompt).toContain("[F199]");
    expect(ctx.prompt).not.toContain("[F200]");
    expect(ctx.prompt).toContain("[truncated:");

    const wide = loadProjectContext({ cwd: root, home, memoryGuidance: false, limits: { memoryIndexLines: 1000, memoryIndexChars: 500 } });
    expect(wide.files[0]!.included).toBeLessThanOrEqual(500);
    expect(wide.files[0]!.status).toBe("truncated");
  });

  it("guidance tells the model where memory lives and how to write it; it can be switched off", () => {
    const { home, root } = world();
    const on = loadProjectContext({ cwd: root, home });
    expect(on.prompt).toContain(memoryDirFor(root, home));
    expect(on.prompt).toContain("MEMORY.md");
    expect(on.prompt).toContain("(empty: nothing saved yet)");
    expect(on.files).toEqual([]); // guidance alone is not a loaded file

    const off = loadProjectContext({ cwd: root, home, memoryGuidance: false });
    expect(off.prompt).toBe("");
  });

  it("a memory the model writes with its Write tool is in the next session's prompt", async () => {
    const { home, root } = world();
    const first = loadProjectContext({ cwd: root, home });
    expect(first.files).toEqual([]);

    // what the model does when told "remember that the secret word is PLUM-42": two file writes
    const ctx = {
      options: {}, abortController: new AbortController(), getAppState: () => ({}), setAppState: async () => {},
      setAppStateForTasks: () => {}, readFileState: new Map(), messages: [], appendSystemMessage: () => {},
      nestedMemoryAttachmentTriggers: new Set(), loadedNestedMemoryPaths: new Set(), dynamicSkillDirTriggers: new Set(),
      discoveredSkillNames: new Set(), fileReadingLimits: { maxTokens: 25_000, maxSizeBytes: 256 * 1024 },
      globLimits: { maxResults: 100 }, toolUseId: "t", cwd: root,
    } as unknown as ToolUseContext;
    await writeTool.call(
      { file_path: join(first.memoryDir, "secret-word.md"), content: "---\nname: secret-word\ndescription: the secret word\ntype: user\n---\nThe secret word is PLUM-42.\n" },
      ctx, async () => true, undefined,
    );
    await writeTool.call(
      { file_path: first.memoryIndexPath, content: "- [Secret word](secret-word.md) - the secret word\n" },
      ctx, async () => true, undefined,
    );

    const next = loadProjectContext({ cwd: root, home });
    expect(next.files.map((f) => f.kind)).toEqual(["memory"]);
    expect(next.prompt).toContain("[Secret word](secret-word.md)");
    expect(next.prompt).not.toContain("nothing saved yet");
    expect(listMemoryFiles(next.memoryDir)).toEqual([{ name: "secret-word.md", description: "the secret word" }]);
    expect(describeLoadedContext(next)).toContain("secret-word.md - the secret word");
  });
});

describe("systemPromptWithContext: what the engine is actually sent", () => {
  it("the model's first request carries the base prompt, the instruction files and the memory index", async () => {
    const { home, root } = world();
    put(join(root, "CLAUDE.md"), "Always answer in French.");
    const mem = memoryDirFor(root, home);
    mkdirSync(mem, { recursive: true });
    put(join(mem, "MEMORY.md"), "- [Deploy](deploy.md) - deploys go through the staging branch\n");

    const { prompt } = systemPromptWithContext("You are ember.", { cwd: root, home });
    const seen: string[] = [];
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, customSystemPrompt: prompt },
      {
        callModel: async (p: CallModelParams) => {
          seen.push(p.systemPrompt);
          return { role: "assistant", content: [{ type: "text", text: "ok" }], stop_reason: "end_turn" } as ModelResponse;
        },
        generateUuid: () => "u",
      } as LoopDepsOverrides,
    );
    for await (const _ev of engine.submitMessage("hi")) {
      // drain
    }
    expect(seen.length).toBe(1);
    expect(seen[0]!.startsWith("You are ember.")).toBe(true);
    expect(seen[0]).toContain("Always answer in French.");
    expect(seen[0]).toContain("deploys go through the staging branch");
    expect(seen[0]).toContain(mem);
  });

  it("a seat with no system prompt gets its files and index but no memory guidance", () => {
    const { home, root } = world();
    put(join(root, "EMBER.md"), "terse");
    const noPrompt = systemPromptWithContext("", { cwd: root, home });
    expect(noPrompt.prompt).toContain("terse");
    expect(noPrompt.prompt).not.toContain("Persistent memory for this project");

    const withPrompt = systemPromptWithContext("base", { cwd: root, home });
    expect(withPrompt.prompt).toContain("Persistent memory for this project");

    const bare = world();
    expect(systemPromptWithContext("", { cwd: bare.root, home: bare.home }).prompt).toBe("");
  });
});

describe("prompt helpers", () => {
  it("appendProjectContext joins with a blank line, and leaves the prompt alone when there is nothing", () => {
    expect(appendProjectContext("base", { prompt: "" })).toBe("base");
    expect(appendProjectContext("base", { prompt: "ctx" })).toBe("base\n\nctx");
    expect(appendProjectContext("", { prompt: "ctx" })).toBe("ctx");
  });

  it("the notice line names what loaded; /memory text names paths, the memory directory and the caps", () => {
    const { home, root } = world();
    put(join(root, "CLAUDE.md"), "x");
    const mem = memoryDirFor(root, home);
    mkdirSync(mem, { recursive: true });
    put(join(mem, "MEMORY.md"), "- [A](a.md) - a\n- [B](b.md) - b\n");
    const ctx = loadProjectContext({ cwd: root, home });
    expect(contextNoticeLine(ctx)).toBe("Loaded CLAUDE.md, memory index (2 entries). /memory shows details.");
    const text = describeLoadedContext(ctx);
    expect(text).toContain(join(root, "CLAUDE.md"));
    expect(text).toContain(`Memory directory: ${mem}`);
    expect(text).toContain("Size caps:");
    expect(describeLoadedContext(loadProjectContext({ cwd: world().root, home }))).toContain("Nothing loaded");
  });
});

// tools/file-read.test.ts — issue #192: the Read tool's "File unchanged since last
// read" cross-turn stub blinded models whose context never actually received the
// content (a turn can be abandoned or compacted away between reads). The stub
// predicate is now: there is none -- Read always returns real content. This test
// pins that predicate so it can't silently regress back in.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdir, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { readTool } from "./file-read.ts";
import type { ReadOutput } from "./file-read.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

function makeTmpDir(): string {
  return join(tmpdir(), `ember-read-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
}

function makeContext(overrides: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 25_000, maxSizeBytes: 256 * 1024 },
    globLimits: { maxResults: 100 },
    toolUseId: "test-tool-use-id",
    ...overrides,
  } as unknown as ToolUseContext;
}

let tmpDir: string;
let filePath: string;

beforeEach(async () => {
  tmpDir = makeTmpDir();
  await mkdir(tmpDir, { recursive: true });
  filePath = join(tmpDir, "example.txt");
  await writeFile(filePath, "line one\nline two\nline three", "utf-8");
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
});

describe("issue #192: Read never returns the cross-turn 'unchanged' stub", () => {
  test("re-reading the same unchanged file returns full content again, not a stub", async () => {
    const ctx = makeContext();

    const first = (await readTool.call({ file_path: filePath, limit: 2000, offset: 0 }, ctx, async () => true, undefined)) as {
      data: ReadOutput;
    };
    expect(first.data.type).toBe("text");

    // Same ctx (same readFileState Map, same mtime) -- simulates a second Read call
    // in a later turn whose context never actually carried turn 1's content.
    const second = (await readTool.call({ file_path: filePath, limit: 2000, offset: 0 }, ctx, async () => true, undefined)) as {
      data: ReadOutput;
    };
    expect(second.data.type).toBe("text");
    if (second.data.type === "text") {
      expect(second.data.content).toContain("line one");
      expect(second.data.content).toContain("line two");
    }
  });

  test("mapToolResultToToolResultBlockParam never emits an 'unchanged' stub string", async () => {
    const ctx = makeContext();
    await readTool.call({ file_path: filePath, limit: 2000, offset: 0 }, ctx, async () => true, undefined);
    const second = (await readTool.call({ file_path: filePath, limit: 2000, offset: 0 }, ctx, async () => true, undefined)) as {
      data: ReadOutput;
    };
    const block = readTool.mapToolResultToToolResultBlockParam(second.data, "tu-1");
    expect(String(block.content)).not.toContain("File unchanged since last read");
    expect(String(block.content)).toContain("line one");
  });

  test("populates readFileState (still consumed by file-edit.ts's external-modification check)", async () => {
    const ctx = makeContext();
    await readTool.call({ file_path: filePath, limit: 2000, offset: 0 }, ctx, async () => true, undefined);
    const cached = ctx.readFileState?.get(filePath) as { mtime: number; content: string } | undefined;
    expect(cached).toBeDefined();
    expect(cached?.content).toContain("line one");
  });
});

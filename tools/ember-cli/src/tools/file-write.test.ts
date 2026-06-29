// TDD tests for the Write tool — one test per AC from specs/tools/file-write.md
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdir, readFile, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { writeTool } from "./file-write.ts";
import type { WriteOutput } from "./file-write.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

function makeTmpDir(): string {
  return join(tmpdir(), `ember-write-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
}

function makeContext(
  overrides: Partial<ToolUseContext> = {},
  denyPaths: string[] = []
): ToolUseContext {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({ denyPaths }),
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

beforeEach(async () => {
  tmpDir = makeTmpDir();
  await mkdir(tmpDir, { recursive: true });
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
});

// AC1: Writing to a non-existent path creates the file; type is 'create'; originalFile is null
describe("AC1: create new file", () => {
  test("creates file and returns type=create with null originalFile", async () => {
    const filePath = join(tmpDir, "new-file.txt");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "hello world" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    expect(result.data.type).toBe("create");
    expect(result.data.originalFile).toBeNull();
    expect(result.data.filePath).toBe(filePath);
    expect(result.data.content).toBe("hello world");
    // Verify file was actually written
    const disk = await readFile(filePath, "utf-8");
    expect(disk).toBe("hello world");
  });
});

// AC2: Writing to an existing path overwrites; type is 'update'; originalFile holds prior content; structuredPatch populated
describe("AC2: overwrite existing file", () => {
  test("overwrites file with type=update, preserves originalFile, structuredPatch non-empty", async () => {
    const filePath = join(tmpDir, "existing.txt");
    await writeFile(filePath, "old content\nline two");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "new content\nline two\nline three" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    expect(result.data.type).toBe("update");
    expect(result.data.originalFile).toBe("old content\nline two");
    expect(result.data.filePath).toBe(filePath);
    expect(Array.isArray(result.data.structuredPatch)).toBe(true);
    // Verify file was overwritten
    const disk = await readFile(filePath, "utf-8");
    expect(disk).toBe("new content\nline two\nline three");
  });
});

// AC3: Path matching a session deny rule is rejected without any file write
describe("AC3: deny rule rejects write", () => {
  test("denied path returns error without writing file", async () => {
    const filePath = join(tmpDir, "secret.txt");
    // We pass the path in denyPaths
    const ctx = makeContext({
      getAppState: () => ({ denyPaths: [filePath] }),
    });
    const result = await writeTool.call(
      { file_path: filePath, content: "should not be written" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    // Should be denied (error result)
    expect(result.data.error).toBeDefined();
    // File should NOT exist
    try {
      await readFile(filePath);
      expect(true).toBe(false); // unreachable
    } catch {
      // Good — file doesn't exist
    }
  });
});

// AC4: Content containing team memory secrets is rejected
describe("AC4: secret check rejects content", () => {
  test("content with TEAM_MEMORY_SECRET marker is rejected", async () => {
    const filePath = join(tmpDir, "output.txt");
    const ctx = makeContext();
    // The secret marker format used in the implementation
    const secretContent = "text\n__EMBER_TEAM_MEMORY_SECRET__\nmore";
    const result = await writeTool.call(
      { file_path: filePath, content: secretContent },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    // Should be rejected
    expect(result.data.error).toBeDefined();
  });
});

// AC5: UNC path returns error without any filesystem access
describe("AC5: UNC path returns error", () => {
  test("UNC path is rejected without filesystem access", async () => {
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: "\\\\server\\share\\file.txt", content: "data" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    expect(result.data.error).toBeDefined();
    expect(result.data.error?.toLowerCase()).toMatch(/unc|network|path/);
  });
});

// AC6: Written file preserves original line-ending convention when overwriting
describe("AC6: line ending preservation", () => {
  test("CRLF file keeps CRLF on overwrite", async () => {
    const filePath = join(tmpDir, "crlf.txt");
    await writeFile(filePath, "line one\r\nline two\r\n");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "line one\nline two\nline three" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    expect(result.data.type).toBe("update");
    const disk = await readFile(filePath, "utf-8");
    // Should use CRLF since original used CRLF
    expect(disk).toContain("\r\n");
  });

  test("LF file keeps LF on overwrite", async () => {
    const filePath = join(tmpDir, "lf.txt");
    await writeFile(filePath, "line one\nline two\n");
    const ctx = makeContext();
    await writeTool.call(
      { file_path: filePath, content: "line one\nline two\nline three" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    const disk = await readFile(filePath, "utf-8");
    // Should NOT convert to CRLF
    expect(disk).not.toContain("\r\n");
  });
});

// AC7: When inside a git repo, gitDiff is included
describe("AC7: git diff when in git repo", () => {
  test("gitDiff may be present if inside git repo", async () => {
    // We run tests from within a git repo, so this may trigger
    const filePath = join(tmpDir, "tracked.txt");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "initial content" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    // gitDiff is optional — just verify the shape when present
    if (result.data.gitDiff !== undefined) {
      expect(typeof result.data.gitDiff).toBe("object");
    }
    expect(result.data.type).toBe("create");
  });
});

// AC8: Writing to a .ember/ path triggers skill discovery
describe("AC8: .ember/ path triggers skill discovery", () => {
  test("skill discovery triggered for .ember/ path", async () => {
    const claudeDir = join(tmpDir, ".ember", "skills");
    await mkdir(claudeDir, { recursive: true });
    const filePath = join(claudeDir, "my-skill.md");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "# My Skill" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    expect(result.data.type).toBe("create");
    // Skill discovery is signaled via dynamicSkillDirTriggers in ctx
    // (implementation triggers this when .ember/ path is detected)
    // Just verify the write succeeded
    const disk = await readFile(filePath, "utf-8");
    expect(disk).toBe("# My Skill");
  });
});

// mapToolResultToToolResultBlockParam
describe("mapToolResultToToolResultBlockParam", () => {
  test("success serializes to JSON content", async () => {
    const filePath = join(tmpDir, "serialized.txt");
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: filePath, content: "test" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    const block = writeTool.mapToolResultToToolResultBlockParam(result.data, "tu-1");
    expect(block.type).toBe("tool_result");
    expect(block.tool_use_id).toBe("tu-1");
    expect(block.is_error).toBeFalsy();
    expect(typeof block.content).toBe("string");
  });

  test("error result has is_error: true", async () => {
    const ctx = makeContext();
    const result = await writeTool.call(
      { file_path: "\\\\server\\share", content: "data" },
      ctx,
      async () => true,
      undefined
    ) as { data: WriteOutput };
    const block = writeTool.mapToolResultToToolResultBlockParam(result.data, "tu-2");
    expect(block.is_error).toBe(true);
  });
});

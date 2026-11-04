// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Regressions from the fileops blind test: FO-15 (multi-line Edit on a CRLF file),
// FO-22 (Grep with a relative directory path doubled the prefix), FO-23 (Grep count
// on a single file reported zero).
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdir, readFile, rm, stat, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { editTool } from "./file-edit.ts";
import { grepTool } from "./search-tools.ts";
import { fileStateKey } from "./file-text.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

let dir = "";

function ctx(cwd: string): ToolUseContext {
  return {
    options: {},
    cwd,
    abortController: new AbortController(),
    getAppState: () => ({ denyPaths: [] }),
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
    toolUseId: "t",
  } as unknown as ToolUseContext;
}

/** Records a Read of the file, as the Read tool does: Edit refuses an unread file (FO-21). */
async function markRead(c: ToolUseContext, f: string): Promise<void> {
  const st = await stat(f);
  c.readFileState?.set(fileStateKey(f), { mtime: st.mtimeMs, content: "" });
}

/** A context in which `f` has been Read. */
async function readCtx(f: string): Promise<ToolUseContext> {
  const c = ctx(dir);
  await markRead(c, f);
  return c;
}

async function call(tool: any, input: unknown, c: ToolUseContext): Promise<any> {
  const r = await tool.call(input, c, async () => true, undefined);
  return r.data;
}

beforeEach(async () => {
  dir = join(tmpdir(), `ember-fo-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(join(dir, "src"), { recursive: true });
});
afterEach(async () => { await rm(dir, { recursive: true, force: true }); });

describe("Edit on CRLF files (FO-15)", () => {
  test("a multi-line LF old_string matches a CRLF file and CRLF is kept", async () => {
    const f = join(dir, "crlf.txt");
    await writeFile(f, "one\r\ntwo\r\nthree\r\n");
    const out = await call(editTool, { file_path: f, old_string: "one\ntwo", new_string: "ONE\nTWO" }, await readCtx(f));
    expect(out.error).toBeUndefined();
    expect(await readFile(f, "utf-8")).toBe("ONE\r\nTWO\r\nthree\r\n");
  });

  test("replace_all across lines on CRLF", async () => {
    const f = join(dir, "dup.txt");
    await writeFile(f, "foo\r\nbar\r\nfoo\r\nbar\r\n");
    const out = await call(editTool, { file_path: f, old_string: "foo\nbar", new_string: "x", replace_all: true }, await readCtx(f));
    expect(out.error).toBeUndefined();
    expect(await readFile(f, "utf-8")).toBe("x\r\nx\r\n");
  });

  test("a whitespace-only near miss is an error, never a silent no-op success", async () => {
    const f = join(dir, "ws.txt");
    await writeFile(f, "a  b\n");
    const out = await call(editTool, { file_path: f, old_string: "a b", new_string: "c" }, await readCtx(f));
    expect(String(out.error)).toContain("not found");
    expect(await readFile(f, "utf-8")).toBe("a  b\n");
  });
});

describe("Grep paths and counts (FO-22, FO-23)", () => {
  test("relative directory path gives real paths", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle\n");
    const out = await call(grepTool, { pattern: "needle", path: "src" }, ctx(dir));
    expect(out.filenames).toEqual([join("src", "a.py")]);
  });

  test("count mode on a single file counts", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle\nneedle\nother\n");
    const out = await call(grepTool, { pattern: "needle", path: "src/a.py", output_mode: "count" }, ctx(dir));
    expect(out.numMatches).toBe(2);
    expect(out.numFiles).toBe(1);
  });

  test("content mode lists the file for an absolute path", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle\n");
    const out = await call(grepTool, { pattern: "needle", path: join(dir, "src"), output_mode: "content" }, ctx(dir));
    expect(out.numFiles).toBe(1);
    expect(out.filenames).toEqual([join("src", "a.py")]);
  });
});

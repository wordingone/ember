// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Regressions for the second fileops blind test (issue #2379): FO-7, FO-15, FO-21, FO-22, FO-31,
// FO-32, FO-34, FO-43, FO-49, FO-51.
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdir, readFile, rm, writeFile } from "fs/promises";
import { join, resolve } from "path";
import { tmpdir } from "os";
import { editTool } from "./file-edit.ts";
import { writeTool, computeUnifiedDiff } from "./file-write.ts";
import { readTool } from "./file-read.ts";
import { grepTool } from "./search-tools.ts";
import {
  decodeTextBuffer,
  detectUtf16,
  encodeText,
  invalidFileNameReason,
  isOutsideCwd,
} from "./file-text.ts";
import { buildApprovalDetail } from "../screens/approval-preview.ts";
import { formatToolResultForDisplay } from "../components/tool-result-renderers.ts";
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

async function call(tool: any, input: unknown, c: ToolUseContext): Promise<any> {
  const r = await tool.call(input, c, async () => true, undefined);
  return r.data;
}

/** What the model is told after the call (the tool's own mapping to a tool_result). */
function modelText(tool: any, data: unknown): string {
  return String(tool.mapToolResultToToolResultBlockParam(data, "id").content);
}

beforeEach(async () => {
  dir = join(tmpdir(), `ember-2379-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(join(dir, "src"), { recursive: true });
});
afterEach(async () => { await rm(dir, { recursive: true, force: true }); });

describe("FO-32: Edit of a big file returns a small result around the change", () => {
  test("one line in a 5000-line file: result is small and shows the changed line", async () => {
    const f = join(dir, "big.txt");
    const lines = Array.from({ length: 5000 }, (_, i) => `line number ${i + 1} of the big file`);
    await writeFile(f, lines.join("\n") + "\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f, limit: 5000 }, c);
    const out = await call(editTool, { file_path: f, old_string: "line number 3000 of", new_string: "LINE NUMBER 3000 of" }, c);
    expect(out.error).toBeUndefined();
    const text = modelText(editTool, out);
    expect(text.length).toBeLessThan(800);
    expect(text).toContain("-line number 3000 of the big file");
    expect(text).toContain("+LINE NUMBER 3000 of the big file");
    expect(text).toContain("@@ -2997,7 +2997,7 @@");
    expect(text).not.toContain("line number 1 of");
    expect(text).not.toContain("line number 4000 of");
  });

  test("the diff of two big texts that differ in one line is one small hunk", () => {
    const a = Array.from({ length: 5000 }, (_, i) => `l${i}`);
    const b = [...a];
    b[10] = "changed";
    const hunks = computeUnifiedDiff(a.join("\n"), b.join("\n"));
    expect(hunks).toHaveLength(1);
    expect(hunks[0]!.lines.length).toBeLessThanOrEqual(8);
    expect(hunks[0]!.oldStart).toBe(8);
  });

  test("a pure insertion and a pure deletion at the ends keep correct line numbers", () => {
    const base = ["a", "b", "c", "d", "e", "f", "g", "h"];
    const ins = computeUnifiedDiff(base.join("\n"), [...base, "i"].join("\n"));
    expect(ins).toHaveLength(1);
    expect(ins[0]!.lines.filter((l) => l.startsWith("+"))).toEqual(["+i"]);
    const del = computeUnifiedDiff(base.join("\n"), base.slice(1).join("\n"));
    expect(del).toHaveLength(1);
    expect(del[0]!.oldStart).toBe(1);
    expect(del[0]!.lines.filter((l) => l.startsWith("-"))).toEqual(["-a"]);
    expect(computeUnifiedDiff("same\n", "same\n")).toEqual([]);
  });

  test("a rewrite of every line still produces a (capped) result, not the whole file", async () => {
    const f = join(dir, "all.txt");
    await writeFile(f, Array.from({ length: 3000 }, (_, i) => `old ${i}`).join("\n") + "\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f, limit: 3000 }, c);
    const out = await call(writeTool, { file_path: f, content: Array.from({ length: 3000 }, (_, i) => `new ${i}`).join("\n") + "\n" }, c);
    expect(modelText(writeTool, out).length).toBeLessThan(4000);
  });
});

describe("FO-21: Edit needs a prior Read", () => {
  test("an unread file is refused and left alone", async () => {
    const f = join(dir, "u.txt");
    await writeFile(f, "alpha\nbeta\n");
    const out = await call(editTool, { file_path: f, old_string: "alpha", new_string: "ALPHA" }, ctx(dir));
    expect(String(out.error)).toContain("has not been read");
    expect(await readFile(f, "utf-8")).toBe("alpha\nbeta\n");
  });

  test("after Read the edit works, and a second edit needs no new Read", async () => {
    const f = join(dir, "r.txt");
    await writeFile(f, "alpha\nbeta\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f }, c);
    expect((await call(editTool, { file_path: f, old_string: "alpha", new_string: "ALPHA" }, c)).error).toBeUndefined();
    expect((await call(editTool, { file_path: f, old_string: "beta", new_string: "BETA" }, c)).error).toBeUndefined();
    expect(await readFile(f, "utf-8")).toBe("ALPHA\nBETA\n");
  });

  test("a file changed after the Read is refused", async () => {
    const f = join(dir, "c.txt");
    await writeFile(f, "alpha\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f }, c);
    await new Promise((r) => setTimeout(r, 20));
    await writeFile(f, "alpha changed elsewhere\n");
    const out = await call(editTool, { file_path: f, old_string: "alpha", new_string: "A" }, c);
    expect(String(out.error)).toContain("changed on disk");
  });

  test("Read with a forward-slash path counts for an Edit with the same file in backslash form", async () => {
    const f = join(dir, "s.txt");
    await writeFile(f, "one\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f.replace(/\\/g, "/") }, c);
    expect((await call(editTool, { file_path: f, old_string: "one", new_string: "two" }, c)).error).toBeUndefined();
  });

  test("an empty old_string says to use Write", async () => {
    const f = join(dir, "e.txt");
    await writeFile(f, "x\n");
    const c = ctx(dir);
    await call(readTool, { file_path: f }, c);
    expect(String((await call(editTool, { file_path: f, old_string: "", new_string: "y" }, c)).error)).toContain("use Write");
  });
});

describe("FO-22: a write outside the working directory asks", () => {
  test("isOutsideCwd", () => {
    expect(isOutsideCwd(join(dir, "a.txt"), dir)).toBe(false);
    expect(isOutsideCwd(join(dir, "sub", "a.txt"), dir)).toBe(false);
    expect(isOutsideCwd(join(dir, "..", "a.txt"), dir)).toBe(true);
    expect(isOutsideCwd(join(dir, "..x", "a.txt"), dir)).toBe(false);
  });

  test("Write and Edit return ask with 'outside the working directory'", async () => {
    const c = ctx(dir);
    const w = await (writeTool as any).checkPermissions({ file_path: "../outside-w.txt", content: "x" }, c);
    expect(w.behavior).toBe("ask");
    expect(w.message).toContain("outside the working directory");
    const e = await (editTool as any).checkPermissions({ file_path: join(dir, "..", "o.txt"), old_string: "a", new_string: "b" }, c);
    expect(e.behavior).toBe("ask");
    expect(e.message).toContain("outside the working directory");
  });

  test("inside the working directory (relative or absolute) is allowed", async () => {
    const c = ctx(dir);
    expect((await (writeTool as any).checkPermissions({ file_path: "src/a.txt", content: "x" }, c)).behavior).toBe("allow");
    expect((await (editTool as any).checkPermissions({ file_path: join(dir, "src", "a.txt"), old_string: "a", new_string: "b" }, c)).behavior).toBe("allow");
  });

  test("a denied path stays denied", async () => {
    const c = ctx(dir);
    (c as any).getAppState = () => ({ denyPaths: [join(dir, "src")] });
    expect((await (writeTool as any).checkPermissions({ file_path: "src/a.txt", content: "x" }, c)).behavior).toBe("deny");
  });
});

describe("FO-31: Read says so when there is nothing to show", () => {
  test("offset past the end of the file", async () => {
    const f = join(dir, "five.txt");
    await writeFile(f, "1\n2\n3\n4\n5\n");
    const out = await call(readTool, { file_path: f, offset: 6000 }, ctx(dir));
    expect(out.type).toBe("text");
    expect(out.content).toContain("past the end of the file");
    expect(out.content).toContain("5 lines");
  });

  test("limit 0 is an error that says why", async () => {
    const f = join(dir, "five.txt");
    await writeFile(f, "1\n2\n3\n");
    const out = await call(readTool, { file_path: f, limit: 0 }, ctx(dir));
    expect(out.type).toBe("error");
    expect(out.error).toContain("limit must be at least 1");
  });

  test("a negative offset is an error", async () => {
    const f = join(dir, "five.txt");
    await writeFile(f, "1\n2\n3\n");
    const out = await call(readTool, { file_path: f, offset: -2 }, ctx(dir));
    expect(out.type).toBe("error");
    expect(out.error).toContain("offset must be 0 or more");
  });

  test("a large (streamed) file past its end", async () => {
    const f = join(dir, "large.txt");
    await writeFile(f, Array.from({ length: 20000 }, (_, i) => `line ${i} padding padding padding`).join("\n") + "\n");
    const out = await call(readTool, { file_path: f, offset: 30000 }, ctx(dir));
    expect(out.content).toContain("past the end of the file");
    expect(out.content).toContain("20000 lines");
  });
});

describe("FO-34: UTF-16 text is text", () => {
  const text = "first line\r\nsecond line\r\n";

  test("detectUtf16 by BOM and by NUL pattern; not for UTF-8 or binary", () => {
    expect(detectUtf16(encodeText(text, "utf-16le", true))).toEqual({ encoding: "utf-16le", bom: true });
    expect(detectUtf16(encodeText(text, "utf-16be", true))).toEqual({ encoding: "utf-16be", bom: true });
    expect(detectUtf16(encodeText(text, "utf-16le", false))).toEqual({ encoding: "utf-16le", bom: false });
    expect(detectUtf16(encodeText(text, "utf-16be", false))).toEqual({ encoding: "utf-16be", bom: false });
    expect(detectUtf16(Buffer.from(text, "utf-8"))).toBeNull();
    expect(detectUtf16(Buffer.alloc(4096))).toBeNull(); // all zero: NULs in both positions
    expect(detectUtf16(Buffer.from([0xff, 0xfe, 0x00, 0x00, 0x00, 0x01, 0x80, 0x90, 0x01, 0x02, 0x03, 0x04]))).toBeNull(); // BOM-like, but junk
  });

  test("round trip keeps encoding and BOM", () => {
    for (const [enc, bom] of [["utf-16le", true], ["utf-16le", false], ["utf-16be", true], ["utf-16be", false]] as const) {
      const bytes = encodeText(text, enc, bom);
      const d = decodeTextBuffer(bytes);
      expect(d.text).toBe(text);
      expect(d.encoding).toBe(enc);
      expect(d.bom).toBe(bom);
      expect(encodeText(d.text, d.encoding, d.bom).equals(bytes)).toBe(true);
    }
  });

  test("Read shows a PowerShell-style UTF-16LE file as text", async () => {
    const f = join(dir, "ps.txt");
    await writeFile(f, encodeText("Name  Value\r\nalpha 1\r\n", "utf-16le", true));
    const out = await call(readTool, { file_path: f }, ctx(dir));
    expect(out.type).toBe("text");
    expect(out.content).toContain("Name  Value");
    expect(out.content).toContain("alpha 1");
    expect(out.totalLines).toBe(2);
  });

  test("a real binary file is still refused", async () => {
    const f = join(dir, "x.bin");
    await writeFile(f, Buffer.from([0x4d, 0x5a, 0x90, 0x00, 0x03, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0xff, 0xff, 0x00, 0x00]));
    const out = await call(readTool, { file_path: f }, ctx(dir));
    expect(out.type).toBe("error");
    expect(out.error).toContain("binary");
  });

  test("Edit changes a UTF-16LE file and writes UTF-16LE back", async () => {
    const f = join(dir, "e16.txt");
    await writeFile(f, encodeText("hello world\r\nbye\r\n", "utf-16le", true));
    const c = ctx(dir);
    await call(readTool, { file_path: f }, c);
    const out = await call(editTool, { file_path: f, old_string: "hello world", new_string: "HELLO" }, c);
    expect(out.error).toBeUndefined();
    const bytes = await readFile(f);
    expect(bytes[0]).toBe(0xff);
    expect(bytes[1]).toBe(0xfe);
    expect(decodeTextBuffer(bytes).text).toBe("HELLO\r\nbye\r\n");
  });

  test("Write over a UTF-16LE file keeps it UTF-16LE", async () => {
    const f = join(dir, "w16.txt");
    await writeFile(f, encodeText("old\r\n", "utf-16le", true));
    const c = ctx(dir);
    await call(readTool, { file_path: f }, c);
    const out = await call(writeTool, { file_path: f, content: "new\n" }, c);
    expect(out.type).toBe("update");
    const d = decodeTextBuffer(await readFile(f));
    expect(d.encoding).toBe("utf-16le");
    expect(d.bom).toBe(true);
    expect(d.text).toBe("new\r\n");
  });
});

describe("FO-43: an invalid file name is called one", () => {
  test("invalidFileNameReason on Windows rules", () => {
    expect(invalidFileNameReason("C:\\proj\\bad<name>.txt", "win32")).toContain('Windows does not allow the character <');
    expect(invalidFileNameReason("C:/proj/a?b.txt", "win32")).toContain("?");
    expect(invalidFileNameReason("C:/proj/sub:dir/f.txt", "win32")).toContain(":");
    expect(invalidFileNameReason("C:/proj/NUL.txt", "win32")).toContain("reserved");
    expect(invalidFileNameReason("C:/proj/name.", "win32")).toContain("ends with a dot");
    expect(invalidFileNameReason("C:/proj/fine-name_1.txt", "win32")).toBeNull();
    expect(invalidFileNameReason("C:\\proj\\sub\\ok.txt", "win32")).toBeNull();
    expect(invalidFileNameReason("/home/u/a<b>.txt", "linux")).toBeNull();
    expect(invalidFileNameReason("/home/u/a\u0001b.txt", "linux")).toContain("control character");
  });

  test.skipIf(process.platform !== "win32")("Write to bad<name>.txt says invalid file name, not ENOENT", async () => {
    const out = await call(writeTool, { file_path: join(dir, "bad<name>.txt"), content: "x" }, ctx(dir));
    expect(out.type).toBe("error");
    expect(out.error).toContain("Invalid file name");
    expect(out.error).not.toContain("ENOENT");
  });

  test("writing onto a directory is a plain message", async () => {
    const c = ctx(dir);
    const out = await call(writeTool, { file_path: join(dir, "src"), content: "x" }, c);
    expect(out.type).toBe("error");
    expect(out.error).not.toContain("ENOENT:");
  });
});

describe("FO-15 / FO-51: Grep paths and counts", () => {
  test("content mode lines start with a path relative to the working directory", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle one\nother\nneedle two\n");
    const out = await call(grepTool, { pattern: "needle", output_mode: "content" }, ctx(dir));
    const first = String(out.content).split("\n")[0]!;
    expect(first.startsWith(join("src", "a.py") + ":")).toBe(true);
    expect(String(out.content)).not.toContain(resolve(dir));
  });

  test("context lines are relative too", async () => {
    await writeFile(join(dir, "src", "a.py"), "before\nneedle\nafter\n");
    const out = await call(grepTool, { pattern: "needle", output_mode: "content", "-C": 1 }, ctx(dir));
    for (const l of String(out.content).split("\n").filter((x) => x.length > 0)) {
      expect(l.startsWith(join("src", "a.py"))).toBe(true);
    }
  });

  test("a search outside the working directory keeps absolute paths", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle\n");
    const out = await call(grepTool, { pattern: "needle", path: join(dir, "src"), output_mode: "content" }, ctx(join(dir, "src", "..", "..")));
    expect(String(out.content)).toContain("a.py");
  });

  test("count mode keeps the per-file counts, and the screen shows them", async () => {
    await writeFile(join(dir, "src", "a.py"), "needle\nneedle\nother\n");
    await writeFile(join(dir, "src", "b.py"), "needle\n");
    const out = await call(grepTool, { pattern: "needle", output_mode: "count" }, ctx(dir));
    expect(out.numMatches).toBe(3);
    expect(String(out.content)).toContain(`${join("src", "a.py")}:2`);
    expect(String(out.content)).toContain(`${join("src", "b.py")}:1`);
    const shown = formatToolResultForDisplay(JSON.stringify(out));
    expect(shown).toContain("3 matches in 2 files");
    expect(shown).toContain(`${join("src", "a.py")}:2`);
  });

  test("count mode with nothing found", async () => {
    const out = await call(grepTool, { pattern: "zzzznotthere", output_mode: "count" }, ctx(dir));
    expect(formatToolResultForDisplay(JSON.stringify(out))).toBe("No matches found.");
  });
});

describe("FO-49: Read results are not shown as raw JSON", () => {
  test("text, image, notebook and pdf shapes", () => {
    expect(formatToolResultForDisplay(JSON.stringify({ type: "text", content: "     1\thello", lineNumberStart: 1, totalLines: 1 }))).toBe("     1\thello");
    expect(formatToolResultForDisplay(JSON.stringify({ type: "image", content: "AAAA", dimensions: { width: 1, height: 1 }, format: "png", metadata: "PNG image, 70 bytes" }))).toBe("PNG image, 70 bytes");
    expect(formatToolResultForDisplay(JSON.stringify({ type: "notebook", cells: [{}, {}], metadata: {} }))).toBe("Notebook with 2 cells");
    expect(formatToolResultForDisplay(JSON.stringify({ type: "pdf", content: "x", pageCount: 3, extractedPages: "1-2", format: "text" }))).toBe("PDF, 3 pages (pages 1-2)");
  });

  test("Grep content mode shows the matches, not only file names", () => {
    const shown = formatToolResultForDisplay(JSON.stringify({ mode: "content", numFiles: 1, filenames: ["a.py"], content: "a.py:1:needle", appliedOffset: 0 }));
    expect(shown).toBe("a.py:1:needle");
  });
});

describe("FO-7: the approval prompt previews the change", () => {
  test("Write to a new file says it creates one and shows the first lines", async () => {
    const detail = await buildApprovalDetail("Write", { file_path: "n.txt", content: "l1\nl2\nl3\nl4\nl5\n" }, dir);
    expect(detail[0]).toBe("creates a new file (5 lines)");
    expect(detail).toContain("+ l1");
    expect(detail.join("\n")).toContain("2 more lines");
  });

  test("Write over an existing file says it OVERWRITES and shows the changed lines", async () => {
    await writeFile(join(dir, "o.txt"), "keep\nold line\nkeep too\n");
    const detail = await buildApprovalDetail("Write", { file_path: join(dir, "o.txt"), content: "keep\nnew line\nkeep too\n" }, dir);
    expect(detail[0]).toContain("OVERWRITES an existing file");
    expect(detail[0]).toContain("+1 -1");
    expect(detail).toContain("- old line");
    expect(detail).toContain("+ new line");
  });

  test("Edit shows what is replaced and by what", async () => {
    const detail = await buildApprovalDetail("Edit", { file_path: "x", old_string: "a\nb", new_string: "c", replace_all: true }, dir);
    expect(detail[0]).toContain("ALL occurrences");
    expect(detail).toContain("- a");
    expect(detail).toContain("- b");
    expect(detail).toContain("+ c");
  });

  test("other tools and unreadable files give no detail and no error", async () => {
    expect(await buildApprovalDetail("Bash", { command: "ls" }, dir)).toEqual([]);
    expect(await buildApprovalDetail("Write", { file_path: "Z:\\nonexistent\\\\x", content: "x" }, dir)).toHaveLength(2);
  });
});

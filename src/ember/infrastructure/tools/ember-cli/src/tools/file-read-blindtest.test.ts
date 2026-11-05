// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Regressions from the fileops blind test: FO-01 phantom line, FO-32 line range of a large file,
// FO-35 binary dumped as text, FO-36 empty file, FO-37 directory.
import { test, expect, beforeAll, afterAll } from "bun:test";
import { mkdir, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { readTool } from "./file-read.ts";

const dir = join(tmpdir(), `ember-read-${Date.now()}`);
const ctx = (maxSizeBytes = 256 * 1024) => ({
  cwd: dir,
  abortController: new AbortController(),
  readFileState: new Map(),
  fileReadingLimits: { maxTokens: 25_000, maxSizeBytes },
  getAppState: () => ({}),
}) as any;
const read = async (input: object, c = ctx()) =>
  (await readTool.call(input as any, c, async () => true, undefined as any)).data as any;

beforeAll(async () => { await mkdir(join(dir, "sub"), { recursive: true }); });
afterAll(async () => { await rm(dir, { recursive: true, force: true }); });

test("a 3-line file with a final newline has 3 lines", async () => {
  await writeFile(join(dir, "n.txt"), "a\nb\nc\n");
  const out = await read({ file_path: join(dir, "n.txt") });
  expect(out.totalLines).toBe(3);
});

test("empty file says so", async () => {
  await writeFile(join(dir, "e.txt"), "");
  const out = await read({ file_path: join(dir, "e.txt") });
  expect(out.content).toContain("empty");
});

test("binary file is refused with a clear message", async () => {
  await writeFile(join(dir, "b.dat"), Buffer.from([0, 1, 2, 255, 0, 10]));
  const out = await read({ file_path: join(dir, "b.dat") });
  expect(out.error).toContain("binary");
});

test("directory gets a clear message", async () => {
  const out = await read({ file_path: join(dir, "sub") });
  expect(out.error).toContain("is a directory");
});

test("a line range of a file over the size cap is readable", async () => {
  const lines = Array.from({ length: 5000 }, (_, i) => `line ${i + 1}`).join("\n");
  await writeFile(join(dir, "big.txt"), lines);
  const out = await read({ file_path: join(dir, "big.txt"), offset: 4000, limit: 3 }, ctx(1024));
  expect(out.content).toContain("line 4001");
  expect(out.content).toContain("line 4003");
  expect(out.content).not.toContain("line 4004");
  expect(out.totalLines).toBe(5000);
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/file-read-image.test.ts -- #2381 CV-9: Read of an image reaches the model as an image block
// (the same shape Computer screenshots use), or says plainly that it was not shown.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, rm, writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";
import { readTool } from "./file-read.ts";
import type { ReadOutput } from "./file-read.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

const ctx = {
  options: {}, abortController: new AbortController(), getAppState: () => ({}), setAppState: async () => {},
  readFileState: new Map(), messages: [],
  fileReadingLimits: { maxTokens: 25_000, maxSizeBytes: 256 * 1024 },
} as unknown as ToolUseContext;

const png = (extra = 0) => {
  const b = Buffer.alloc(33 + extra);
  Buffer.from("89504e470d0a1a0a", "hex").copy(b);
  b.writeUInt32BE(13, 8); b.write("IHDR", 12, "latin1"); b.writeUInt32BE(64, 16); b.writeUInt32BE(32, 20);
  return b;
};

let dir: string;
let savedVision: string | undefined;
beforeEach(async () => {
  dir = join(tmpdir(), `ember-readimg-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await mkdir(dir, { recursive: true });
  savedVision = process.env["EMBER_VISION"];
});
afterEach(async () => {
  if (savedVision === undefined) delete process.env["EMBER_VISION"]; else process.env["EMBER_VISION"] = savedVision;
  await rm(dir, { recursive: true, force: true });
});

async function readMapped(file: string) {
  const out = (await readTool.call({ file_path: file } as never, ctx)).data as ReadOutput;
  return { out, block: readTool.mapToolResultToToolResultBlockParam(out, "t1") };
}

describe("Read of an image file", () => {
  test("with a vision projector the model gets an image content block (like Computer screenshots)", async () => {
    process.env["EMBER_VISION"] = "1";
    const f = join(dir, "a.png");
    const bytes = png();
    await writeFile(f, bytes);
    const { block } = await readMapped(f);
    expect(Array.isArray(block.content)).toBe(true);
    const parts = block.content as Array<{ type: string; text?: string; source?: { data: string; media_type: string } }>;
    expect(parts[0]!.type).toBe("text");
    expect(parts[0]!.text).toContain("PNG image");
    expect(parts[1]!.type).toBe("image");
    expect(parts[1]!.source!.media_type).toBe("image/png");
    expect(parts[1]!.source!.data).toBe(bytes.toString("base64"));
  });

  test("without a vision projector the result says plainly the image was not shown, with no base64 in it", async () => {
    delete process.env["EMBER_VISION"];
    const f = join(dir, "a.png");
    await writeFile(f, png());
    const { block } = await readMapped(f);
    expect(typeof block.content).toBe("string");
    const t = block.content as string;
    expect(t).toContain("NOT shown to the model");
    expect(t).toContain("no vision projector");
    expect(t).not.toContain("iVBOR");
  });

  test.each([
    ["a.jpg", Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0x10, 0x4a, 0x46]), "image/jpeg"],
    ["a.gif", Buffer.from("GIF89a\x01\x00\x01\x00", "latin1"), "image/gif"],
    ["a.webp", Buffer.concat([Buffer.from("RIFF"), Buffer.from([4, 0, 0, 0]), Buffer.from("WEBPVP8 ")]), "image/webp"],
  ])("%s is recognised and sent with media type %s", async (name, bytes, mt) => {
    process.env["EMBER_VISION"] = "1";
    const f = join(dir, name);
    await writeFile(f, bytes);
    const { block } = await readMapped(f);
    const parts = block.content as Array<{ type: string; source?: { media_type: string } }>;
    expect(parts[1]!.source!.media_type).toBe(mt);
  });

  test("a bmp is recognised; a text file that merely starts with BM is not an image", async () => {
    process.env["EMBER_VISION"] = "1";
    const bmp = Buffer.alloc(54); bmp.write("BM", 0); bmp.writeUInt32LE(40, 14);
    await writeFile(join(dir, "a.bmp"), bmp);
    const { block } = await readMapped(join(dir, "a.bmp"));
    expect((block.content as Array<{ type: string }>)[1]!.type).toBe("image");
    await writeFile(join(dir, "BM.txt"), "BM is a text file with enough bytes in it to pass the length check ok");
    const { out } = await readMapped(join(dir, "BM.txt"));
    expect(out.type).toBe("text");
  });

  test("an image above the text size cap but under the image cap is still sent", async () => {
    process.env["EMBER_VISION"] = "1";
    const f = join(dir, "big.png");
    await writeFile(f, png(300 * 1024));
    const { out, block } = await readMapped(f);
    expect(out.type).toBe("image");
    expect(Array.isArray(block.content)).toBe(true);
  });

  test("an image above the image cap is refused with a plain 'not shown' message", async () => {
    process.env["EMBER_VISION"] = "1";
    const f = join(dir, "huge.png");
    await writeFile(f, png(9 * 1024 * 1024));
    const { out, block } = await readMapped(f);
    expect(out.type).toBe("error");
    expect(String((block as { content: unknown }).content)).toContain("NOT shown to the model");
  });
});

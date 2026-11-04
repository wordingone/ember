// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/file-read.ts — Read tool: read files from the filesystem.
// De-transpiled from bundle (lines 304672–304882). Handles text, images, PDF,
// Jupyter notebooks, with line-number formatting and token-cap truncation.
// bundle=Y

import { stat, readFile, readdir, open } from "fs/promises";
import { createReadStream } from "fs";
import { createInterface } from "readline";
import { join, dirname, basename, isAbsolute } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import { decodeTextBuffer, detectUtf16, fileStateKey } from "./file-text.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_MAX_SIZE_BYTES = 256 * 1024;
const DEFAULT_MAX_TOKENS = 25_000;
const CHARS_PER_TOKEN = 4;

const BLOCKED_DEVICE_PATHS = new Set([
  "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full",
  "/dev/stdin", "/dev/tty", "/dev/console",
  "/dev/stdout", "/dev/stderr",
  "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
]);

// ---------------------------------------------------------------------------
// Path guards
// ---------------------------------------------------------------------------

function isBlockedDevicePath(p: string): boolean {
  if (BLOCKED_DEVICE_PATHS.has(p)) return true;
  return /^\/proc\/\d+\/fd\/[012]$/.test(p);
}

function isUncPath(p: string): boolean {
  return p.startsWith("\\\\") || p.startsWith("//");
}

export function resolveFilePath(p: string, cwd: string): string {
  if (p === "~" || p.startsWith("~/") || p.startsWith("~\\")) {
    const home = process.env["HOME"] ?? process.env["USERPROFILE"] ?? "";
    p = home + p.slice(1);
  }
  p = p.replace(/\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)/g, (_, braced: string, bare: string) => {
    return process.env[braced ?? bare] ?? "";
  });
  // issue #182: the Read tool's contract says "always use absolute paths", but
  // a relative path here previously fell through to Node's implicit
  // resolution against the real process.cwd() (the launch cwd) instead of
  // the agent's resolved repo root — join it against the resolved cwd
  // defensively rather than trusting every caller to comply.
  if (!isAbsolute(p)) {
    p = join(cwd, p);
  }
  return p;
}

// ---------------------------------------------------------------------------
// Image format detection
// ---------------------------------------------------------------------------

type ImageFormat = "png" | "jpeg" | "gif" | "webp" | "bmp";
const IMAGE_MEDIA_TYPES: Record<ImageFormat, string> = {
  png: "image/png",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
};
/** Largest image file (bytes) handed to the model; bigger ones are reported, not sent. */
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

function detectImageFormat(buf: Buffer): ImageFormat | null {
  if (buf.length >= 8 && buf[0] === 137 && buf[1] === 80 && buf[2] === 78 && buf[3] === 71) {
    return "png";
  }
  if (buf.length >= 3 && buf[0] === 255 && buf[1] === 216 && buf[2] === 255) {
    return "jpeg";
  }
  if (buf.length >= 6 && buf.toString("latin1", 0, 4) === "GIF8" && (buf[4] === 0x37 || buf[4] === 0x39) && buf[5] === 0x61) {
    return "gif";
  }
  if (buf.length >= 12 && buf.toString("latin1", 0, 4) === "RIFF" && buf.toString("latin1", 8, 12) === "WEBP") {
    return "webp";
  }
  // BMP: "BM", reserved words zero, a known DIB header size (so a text file starting "BM" is not an image).
  if (buf.length >= 26 && buf[0] === 0x42 && buf[1] === 0x4d && buf.readUInt32LE(6) === 0 && [12, 40, 52, 56, 64, 108, 124].includes(buf.readUInt32LE(14))) {
    return "bmp";
  }
  return null;
}

function extractPngDimensions(buf: Buffer): { width: number; height: number } | null {
  if (buf.length < 24) return null;
  try {
    const width = buf.readUInt32BE(16);
    const height = buf.readUInt32BE(20);
    return { width, height };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Notebook parsing
// ---------------------------------------------------------------------------

interface NotebookCell {
  type: string;
  source: string;
  output: unknown;
}

interface ParsedNotebook {
  cells: NotebookCell[];
  metadata: Record<string, unknown>;
}

function parseNotebook(content: string): ParsedNotebook | null {
  try {
    const nb = JSON.parse(content) as Record<string, unknown>;
    if (!nb["cells"] || !Array.isArray(nb["cells"])) return null;
    const cells = (nb["cells"] as Record<string, unknown>[]).map((c) => ({
      type: c["cell_type"] as string,
      source: Array.isArray(c["source"])
        ? (c["source"] as string[]).join("")
        : (c["source"] as string) ?? "",
      output: c["outputs"],
    }));
    return { cells, metadata: (nb["metadata"] as Record<string, unknown>) ?? {} };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// cat -n formatting
// ---------------------------------------------------------------------------

function formatCatN(lines: string[], startLine: number): string {
  return lines
    .map((line, i) => {
      const lineNum = startLine + i;
      const padded = String(lineNum).padStart(6, " ");
      return `${padded}\t${line}`;
    })
    .join("\n");
}

// ---------------------------------------------------------------------------
// Similar file suggestion
// ---------------------------------------------------------------------------

async function findSimilarFiles(missingPath: string): Promise<string[]> {
  try {
    const dir = dirname(missingPath);
    const name = basename(missingPath).toLowerCase();
    const entries = await readdir(dir, { encoding: "utf-8" });
    return entries
      .filter(
        (e) =>
          e.toLowerCase().includes(name.slice(0, 4)) ||
          name.includes(e.toLowerCase().slice(0, 4)),
      )
      .slice(0, 5)
      .map((e) => join(dir, e));
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Token cap helpers
// ---------------------------------------------------------------------------

function getMaxTokens(ctx: ToolUseContext): number {
  const envOverride = process.env["EMBER_FILE_READ_MAX_OUTPUT_TOKENS"];
  if (envOverride) {
    const parsed = parseInt(envOverride, 10);
    if (!isNaN(parsed) && parsed > 0) return parsed;
  }
  return ctx.fileReadingLimits?.maxTokens ?? DEFAULT_MAX_TOKENS;
}

function truncateToTokenCap(content: string, maxTokens: number): string {
  const maxChars = maxTokens * CHARS_PER_TOKEN;
  if (content.length <= maxChars) return content;
  return content.slice(0, maxChars) + "\n\n... [output truncated due to token cap] ...";
}

// ---------------------------------------------------------------------------
// Public output type
// ---------------------------------------------------------------------------

export type ReadOutput =
  | { type: "error"; error: string }
  | {
      type: "image";
      content: string;
      dimensions: { width: number; height: number };
      format: ImageFormat;
      metadata: string;
    }
  | { type: "notebook"; cells: NotebookCell[]; metadata: Record<string, unknown> }
  | {
      type: "pdf";
      content: string;
      pageCount: number;
      extractedPages: string;
      format: "text";
    }
  | { type: "text"; content: string; lineNumberStart: number; totalLines: number };

// ---------------------------------------------------------------------------
// Core read implementation
// ---------------------------------------------------------------------------

/** Files larger than this are refused even for a line range. */
const STREAM_READ_MAX_BYTES = 1024 * 1024 * 1024;

/** A NUL byte in the first 8 KB: the usual "this is not text" test (git, grep). */
function bufLooksBinary(buf: Buffer): boolean {
  return buf.subarray(0, 8192).includes(0);
}

/** What a file looks like from its first 8 KB: UTF-16 text is text, not binary (blind test FO-34). */
async function sniffFile(path: string): Promise<"binary" | "utf16" | "text"> {
  const fh = await open(path, "r");
  try {
    const head = Buffer.alloc(8192);
    const { bytesRead } = await fh.read(head, 0, head.length, 0);
    const bytes = head.subarray(0, bytesRead);
    if (detectUtf16(bytes)) return "utf16";
    return bufLooksBinary(bytes) ? "binary" : "text";
  } finally {
    await fh.close();
  }
}

/** UTF-16 files above this size are not read (they are decoded whole, unlike streamed UTF-8). */
const UTF16_MAX_BYTES = 64 * 1024 * 1024;

function binaryMessage(path: string, size: number): string {
  return `${path} is a binary file (${size} bytes), not shown as text. Inspect it with a tool made for it (for example a python script).`;
}

/** Lines of a decoded text, a trailing newline ending the last line rather than starting another. */
function splitLines(text: string): string[] {
  const lines = text.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines.map((l) => (l.endsWith("\r") ? l.slice(0, -1) : l));
}

/** What to show when a range starts after the last line (blind test FO-31: it used to return nothing). */
function pastEndNotice(offset: number, total: number): string {
  return `(no lines to show: offset ${offset} is past the end of the file, which has ${total} line${total === 1 ? "" : "s"}. Offsets start at 0.)`;
}

/** Lines [offset, offset+limit) of a large text file, read as a stream, plus the total line count. */
async function readLineRange(path: string, offset: number, limit: number): Promise<{ lines: string[]; total: number }> {
  const rl = createInterface({ input: createReadStream(path, { encoding: "utf-8" }), crlfDelay: Infinity });
  const lines: string[] = [];
  let i = 0;
  for await (const line of rl) {
    if (i >= offset && i < offset + limit) lines.push(line);
    i++;
  }
  return { lines, total: i };
}

/** A line range the tool cannot honour, in plain words (blind test FO-31: limit 0 returned an empty string). */
function rangeError(offset: number, limit: number): string | null {
  if (limit < 1) return `limit must be at least 1 (limit ${limit} would read no lines). Omit limit to read up to 2000 lines.`;
  if (offset < 0) return `offset must be 0 or more (offset ${offset}). Offsets start at 0, the first line of the file.`;
  return null;
}

async function readFile_(
  input: { file_path: string; limit?: number; offset?: number; pages?: string },
  ctx: ToolUseContext,
): Promise<ReadOutput> {
  const resolvedPath = resolveFilePath(input.file_path, ctx.cwd ?? process.cwd());

  if (isUncPath(resolvedPath)) {
    return {
      type: "error",
      error: `UNC network paths are not supported for security reasons: ${resolvedPath}`,
    };
  }
  if (isBlockedDevicePath(resolvedPath)) {
    return {
      type: "error",
      error: `Blocked device path: ${resolvedPath}. Reading from this path could cause hangs or infinite output.`,
    };
  }

  let fileStat: Awaited<ReturnType<typeof stat>>;
  try {
    fileStat = await stat(resolvedPath);
  } catch {
    const similar = await findSimilarFiles(resolvedPath);
    const suggestions =
      similar.length > 0 ? `\nSimilar files: ${similar.join(", ")}` : "";
    return { type: "error", error: `File not found: ${resolvedPath}${suggestions}` };
  }

  if (fileStat.isDirectory()) {
    return {
      type: "error",
      error: `${resolvedPath} is a directory, not a file. List it with Glob (pattern "*") or Bash "dir".`,
    };
  }

  const maxSizeBytes = ctx.fileReadingLimits?.maxSizeBytes ?? DEFAULT_MAX_SIZE_BYTES;
  // #2381 CV-9: a real picture is usually bigger than the text cap; images have their own cap.
  let isImageFile = false;
  if (fileStat.size > maxSizeBytes && /\.(png|jpe?g|gif|webp|bmp)$/i.test(resolvedPath)) {
    try {
      const fh = await open(resolvedPath, "r");
      try {
        const head = Buffer.alloc(32);
        const { bytesRead } = await fh.read(head, 0, 32, 0);
        isImageFile = detectImageFormat(head.subarray(0, bytesRead)) !== null;
      } finally {
        await fh.close();
      }
    } catch { /* fall through to the generic size handling */ }
    if (isImageFile && fileStat.size > MAX_IMAGE_BYTES) {
      return {
        type: "error",
        error: `Image is ${fileStat.size} bytes, larger than the ${MAX_IMAGE_BYTES / (1024 * 1024)} MB limit. It was NOT shown to the model; do not describe it.`,
      };
    }
  }
  if (fileStat.size > maxSizeBytes && !isImageFile) {
    // Too big to load whole, but a line range is still readable: stream it (blind test FO-32).
    if (fileStat.size > STREAM_READ_MAX_BYTES) {
      return {
        type: "error",
        error: `File is ${fileStat.size} bytes, too large to read. Search it with Grep instead.`,
      };
    }
    const kind = await sniffFile(resolvedPath);
    if (kind === "binary") {
      return { type: "error", error: binaryMessage(resolvedPath, fileStat.size) };
    }
    const offset = input.offset ?? 0;
    const limit = input.limit ?? 2000;
    const badRange = rangeError(offset, limit);
    if (badRange) return { type: "error", error: badRange };
    let lines: string[];
    let total: number;
    if (kind === "utf16") {
      if (fileStat.size > UTF16_MAX_BYTES) {
        return {
          type: "error",
          error: `${resolvedPath} is a UTF-16 text file of ${fileStat.size} bytes, too large to read (the limit is ${UTF16_MAX_BYTES} bytes). Search it with Grep or convert it to UTF-8 first.`,
        };
      }
      const all = splitLines(decodeTextBuffer(await readFile(resolvedPath)).text);
      total = all.length;
      lines = all.slice(offset, offset + limit);
    } else {
      ({ lines, total } = await readLineRange(resolvedPath, offset, limit));
    }
    // A range read counts as a read for the Write/Edit guards (content is not kept: too large).
    ctx.readFileState?.set(fileStateKey(resolvedPath), { mtime: fileStat.mtimeMs, content: "" });
    const startLine = offset + 1;
    if (lines.length === 0) {
      return { type: "text", content: pastEndNotice(offset, total), lineNumberStart: startLine, totalLines: total };
    }
    const note = `\n[large file: ${fileStat.size} bytes, ${total} lines; showing lines ${startLine}-${offset + lines.length}. Use offset/limit for other ranges, or Grep to find text.]`;
    return {
      type: "text",
      content: truncateToTokenCap(formatCatN(lines, startLine), getMaxTokens(ctx)) + note,
      lineNumberStart: startLine,
      totalLines: total,
    };
  }

  const mtimeMs = fileStat.mtimeMs;

  // issue #192: this used to short-circuit here and return a lightweight
  // "unchanged since last read" stub when ctx.readFileState (a session-wide,
  // cross-turn cache) had a matching mtime -- but that cache tracks nothing
  // about whether the CURRENT model context actually still carries the
  // content (a turn can be abandoned, compacted away, or simply never
  // started). The stub then blinds the model to a file it's asking about,
  // with no way to recover other than a doomed retry loop (live repro:
  // receipts/operator-sessions/session-20260705T234943Z.jsonl). The
  // read-state cache below is still populated/consulted by file-edit.ts and
  // file-write.ts for external-modification detection -- that use is
  // unaffected. Read itself now always returns real content.
  const buf = await readFile(resolvedPath);
  const decoded = decodeTextBuffer(buf);
  const rawContent = decoded.text;
  const isUtf16 = decoded.encoding !== "utf-8";
  ctx.readFileState?.set(fileStateKey(resolvedPath), { mtime: mtimeMs, content: rawContent });

  // Image detection
  const imageFormat = isUtf16 ? null : detectImageFormat(buf);
  if (imageFormat !== null) {
    const dims =
      imageFormat === "png"
        ? extractPngDimensions(buf) ?? { width: 0, height: 0 }
        : { width: 0, height: 0 };
    return {
      type: "image",
      content: buf.toString("base64"),
      dimensions: dims,
      format: imageFormat,
      metadata: `${imageFormat.toUpperCase()} image, ${fileStat.size} bytes`,
    };
  }

  // Jupyter notebook
  if (resolvedPath.endsWith(".ipynb")) {
    const nb = parseNotebook(rawContent);
    if (nb) {
      return { type: "notebook", cells: nb.cells, metadata: nb.metadata };
    }
  }

  // PDF
  if (resolvedPath.endsWith(".pdf") || rawContent.startsWith("%PDF")) {
    const pageMatches = rawContent.match(/\/Type\s*\/Page\b/g);
    const pageCount = pageMatches ? pageMatches.length : 1;
    if (pageCount > 10 && !input.pages) {
      return {
        type: "error",
        error: `PDF has ${pageCount} pages. Please provide the \`pages\` parameter to specify which pages to read (e.g., "1-5" or "3").`,
      };
    }
    const extractedPages = input.pages ?? "1";
    return {
      type: "pdf",
      content: rawContent.slice(0, 2000),
      pageCount,
      extractedPages,
      format: "text",
    };
  }

  if (!isUtf16 && bufLooksBinary(buf)) {
    return { type: "error", error: binaryMessage(resolvedPath, fileStat.size) };
  }

  if (rawContent.length === 0) {
    return { type: "text", content: "(the file is empty)", lineNumberStart: 1, totalLines: 0 };
  }

  // Plain text with line-range slicing. A trailing newline ends the last line; it does not
  // start another one (blind test FO-01 saw a phantom extra line).
  const allLines = isUtf16 ? splitLines(rawContent) : rawContent.split("\n");
  if (!isUtf16 && allLines.length > 1 && allLines[allLines.length - 1] === "") allLines.pop();
  const offset = input.offset ?? 0;
  const limit = input.limit ?? 2000;
  const badRange = rangeError(offset, limit);
  if (badRange) return { type: "error", error: badRange };
  const slicedLines = allLines.slice(offset, offset + limit);
  const startLine = offset + 1;
  if (slicedLines.length === 0) {
    return { type: "text", content: pastEndNotice(offset, allLines.length), lineNumberStart: startLine, totalLines: allLines.length };
  }
  const formatted = formatCatN(slicedLines, startLine);
  const maxTokens = getMaxTokens(ctx);
  const truncated = truncateToTokenCap(formatted, maxTokens);

  return {
    type: "text",
    content: truncated,
    lineNumberStart: startLine,
    totalLines: allLines.length,
  };
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const ReadInputSchema = z.object({
  file_path: z.string(),
  limit: z.number().int().optional().default(2000),
  offset: z.number().int().optional().default(0),
  pages: z.string().optional(),
});

export type ReadInput = z.infer<typeof ReadInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const readTool = Object.assign(
  buildTool<ReadInput, ReadOutput>({
    name: "Read",

    inputSchema: ReadInputSchema,

    isReadOnly: () => true,
    isConcurrencySafe: () => false,
    isDestructive: () => false,

    maxResultSizeChars: Infinity,

    description: (_input?: ReadInput, _opts?) =>
      "Read a file from the local filesystem. Returns file contents with line numbers.",

    prompt: (_opts?) => `## Read tool
Use the Read tool to read files from the filesystem. Always use absolute paths.
- Text files: returned with line numbers in cat -n format.
- Image files (.png, .jpg, .jpeg, .gif, .webp, .bmp): shown to you as an image when the model has a vision projector; otherwise the result says the image was not shown, and you must not describe it.
- PDF files (.pdf): requires \`pages\` parameter for files with >10 pages.
- Jupyter notebooks (.ipynb): cells returned as structured list.
- The \`limit\` (default 2000) and \`offset\` (default 0) parameters control line range.`,

    call: async (args: ReadInput, ctx: ToolUseContext) => {
      const data = await readFile_(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: ReadOutput, toolUseId: string) => {
      if (content.type === "error") {
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: content.error,
          is_error: true,
        };
      }
      if (content.type === "image") {
        // #2381 CV-9: an image reaches the model as an image block, the same shape Computer
        // screenshots use (query-engine splitToolContent -> adapter image_url, only with EMBER_VISION=1).
        // Never stringify the base64 into text, and never let the model believe it saw the image.
        const dims = content.dimensions.width > 0 ? `${content.dimensions.width}x${content.dimensions.height}, ` : "";
        const label = `${content.metadata} (${dims}${content.format})`;
        const bytes = Math.floor((content.content.length * 3) / 4);
        if (bytes > MAX_IMAGE_BYTES) {
          return {
            type: "tool_result" as const,
            tool_use_id: toolUseId,
            content: `${label}. The image was NOT shown to the model: it is larger than the ${MAX_IMAGE_BYTES / (1024 * 1024)} MB image limit. Do not describe its contents.`,
          };
        }
        if (process.env["EMBER_VISION"] !== "1") {
          return {
            type: "tool_result" as const,
            tool_use_id: toolUseId,
            content: `${label}. The image was NOT shown to the model: the loaded model has no vision projector, so you cannot see it. Say so plainly; do not guess or describe its contents.`,
          };
        }
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: [
            { type: "text", text: label },
            { type: "image", source: { type: "base64", media_type: IMAGE_MEDIA_TYPES[content.format], data: content.content } },
          ],
        };
      }
      return {
        type: "tool_result" as const,
        tool_use_id: toolUseId,
        content: JSON.stringify(content),
      };
    },

    toAutoClassifierInput: (input?: ReadInput) => input?.file_path ?? "",
  }),
  {
    searchHint: "read file contents from the filesystem",
    alwaysLoad: true,
    getPath: (i: ReadInput) => i.file_path,
  } as const,
);

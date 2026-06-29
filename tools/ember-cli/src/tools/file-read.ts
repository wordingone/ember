// tools/file-read.ts — Read tool: read files from the filesystem.
// De-transpiled from bundle (lines 304672–304882). Handles text, images, PDF,
// Jupyter notebooks, with line-number formatting and token-cap truncation.
// bundle=Y

import { stat, readFile, readdir } from "fs/promises";
import { join, dirname, basename } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_MAX_SIZE_BYTES = 256 * 1024;
const DEFAULT_MAX_TOKENS = 25_000;
const CHARS_PER_TOKEN = 4;
const FILE_UNCHANGED_STUB_TYPE = "unchanged";

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

function resolveFilePath(p: string): string {
  if (p === "~" || p.startsWith("~/") || p.startsWith("~\\")) {
    const home = process.env["HOME"] ?? process.env["USERPROFILE"] ?? "";
    p = home + p.slice(1);
  }
  p = p.replace(/\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)/g, (_, braced: string, bare: string) => {
    return process.env[braced ?? bare] ?? "";
  });
  return p;
}

// ---------------------------------------------------------------------------
// Image format detection
// ---------------------------------------------------------------------------

function detectImageFormat(buf: Buffer): "png" | "jpeg" | null {
  if (buf.length >= 8 && buf[0] === 137 && buf[1] === 80 && buf[2] === 78 && buf[3] === 71) {
    return "png";
  }
  if (buf.length >= 3 && buf[0] === 255 && buf[1] === 216 && buf[2] === 255) {
    return "jpeg";
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
  | { type: typeof FILE_UNCHANGED_STUB_TYPE; filePath: string }
  | {
      type: "image";
      content: string;
      dimensions: { width: number; height: number };
      format: "png" | "jpeg";
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

async function readFile_(
  input: { file_path: string; limit?: number; offset?: number; pages?: string },
  ctx: ToolUseContext,
): Promise<ReadOutput> {
  const resolvedPath = resolveFilePath(input.file_path);

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

  const maxSizeBytes = ctx.fileReadingLimits?.maxSizeBytes ?? DEFAULT_MAX_SIZE_BYTES;
  if (fileStat.size > maxSizeBytes) {
    return {
      type: "error",
      error: `File exceeds size limit (${fileStat.size} bytes > ${maxSizeBytes} bytes). Reading this file would use too much memory.`,
    };
  }

  const mtimeMs = fileStat.mtimeMs;
  const cached = ctx.readFileState?.get(resolvedPath) as
    | { mtime: number; content: string }
    | undefined;
  if (cached && cached.mtime === mtimeMs) {
    return { type: FILE_UNCHANGED_STUB_TYPE, filePath: resolvedPath };
  }

  const buf = await readFile(resolvedPath);
  const rawContent = buf.toString("utf-8");
  ctx.readFileState?.set(resolvedPath, { mtime: mtimeMs, content: rawContent });

  // Image detection
  const imageFormat = detectImageFormat(buf);
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

  // Plain text with line-range slicing
  const allLines = rawContent.split("\n");
  const offset = input.offset ?? 0;
  const limit = input.limit ?? 2000;
  const slicedLines = allLines.slice(offset, offset + limit);
  const startLine = offset + 1;
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
- Image files (.png, .jpg, .jpeg): returned as base64-encoded content with dimensions.
- PDF files (.pdf): requires \`pages\` parameter for files with >10 pages.
- Jupyter notebooks (.ipynb): cells returned as structured list.
- Files read once are cached; re-reading an unchanged file returns a lightweight stub.
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
      if (content.type === FILE_UNCHANGED_STUB_TYPE) {
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: `File unchanged since last read: ${content.filePath}`,
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

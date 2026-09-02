// tools/search-tools.ts — Glob and Grep tools backed by Bun.Glob and ripgrep.
//
// Glob: fast file-pattern matching sorted by mtime.
// Grep: ripgrep-powered content search with three output modes.
// Both tools are read-only and concurrency-safe.

import { spawn } from "child_process";
import { stat } from "fs/promises";
import { join, relative, isAbsolute } from "path";
import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// UNC / path helpers
// ---------------------------------------------------------------------------

function isUncPath(p: string): boolean {
  return /^\\\\[^\\]/.test(p) || /^\/\/[^/]/.test(p);
}

function expandPath(p: string): string {
  if (p.startsWith("~/") || p === "~") {
    return p.replace("~", process.env["HOME"] ?? process.env["USERPROFILE"] ?? "~");
  }
  return p.replace(
    /\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g,
    (_, a: string | undefined, b: string | undefined) => {
      const varName = a ?? b;
      return (varName ? process.env[varName] : undefined) ?? _;
    },
  );
}

function toRelativePath(absPath: string, base: string): string {
  if (!isAbsolute(absPath)) return absPath;
  const rel = relative(base, absPath);
  if (rel.startsWith("..")) return absPath;
  return rel;
}

// ---------------------------------------------------------------------------
// Glob implementation (Bun.Glob)
// ---------------------------------------------------------------------------

interface GlobResult {
  filenames: string[];
  durationMs: number;
  numFiles: number;
  truncated: boolean;
  error?: string;
}

async function runGlob(input: GlobInput, ctx: ToolUseContext): Promise<GlobResult> {
  const startMs = Date.now();
  const limit = ctx.globLimits?.maxResults ?? 100;
  const rawPath = input.path;
  const searchPath = rawPath ? expandPath(rawPath) : (ctx.cwd ?? process.cwd());

  if (isUncPath(searchPath)) {
    return {
      filenames: [],
      durationMs: 0,
      numFiles: 0,
      truncated: false,
      error: "UNC paths are blocked to prevent NTLM credential leaks",
    };
  }

  try {
    const s = await stat(searchPath);
    if (!s.isDirectory()) {
      return {
        filenames: [],
        durationMs: 0,
        numFiles: 0,
        truncated: false,
        error: `Not a directory: ${searchPath}`,
      };
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      filenames: [],
      durationMs: 0,
      numFiles: 0,
      truncated: false,
      error: `Directory does not exist or is not accessible: ${msg}`,
    };
  }

  const allFiles: string[] = [];
  // issue #156: `globalThis.Glob` is undefined in the Bun runtime (verified:
  // `typeof globalThis.Glob === "undefined"` while `typeof Bun.Glob ===
  // "function"`) — the prior interop cast constructed off the wrong global
  // and threw "undefined is not a constructor". Bun.Glob is the real ctor.
  const glob = new Bun.Glob(input.pattern);
  for await (const file of glob.scan({ cwd: searchPath, absolute: true, onlyFiles: true })) {
    allFiles.push(file);
  }

  const numFiles = allFiles.length;
  const mtimes = await Promise.all(
    allFiles.map(async (f) => {
      try {
        const s = await stat(f);
        return { file: f, mtime: s.mtimeMs };
      } catch {
        return { file: f, mtime: 0 };
      }
    }),
  );
  mtimes.sort((a, b) => b.mtime - a.mtime);
  const sorted = mtimes.map((x) => x.file);

  const truncated = sorted.length > limit;
  const selected = truncated ? sorted.slice(0, limit) : sorted;

  const cwd = ctx.cwd ?? process.cwd();
  const relativized = selected.map((f) => toRelativePath(f, cwd));
  const durationMs = Date.now() - startMs;

  return { filenames: relativized, durationMs, numFiles, truncated };
}

// ---------------------------------------------------------------------------
// ripgrep runner
// ---------------------------------------------------------------------------

interface RipgrepResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

function runRipgrep(
  args: string[],
  cwd: string,
  abortSignal: AbortSignal,
): Promise<RipgrepResult> {
  return new Promise((resolve) => {
    const stdoutChunks: string[] = [];
    const stderrChunks: string[] = [];
    let finished = false;

    const proc = spawn("rg", args, { cwd, env: process.env, shell: false });

    const abort = () => {
      if (!finished) {
        proc.kill();
        finished = true;
        resolve({
          stdout: stdoutChunks.join(""),
          stderr: stderrChunks.join(""),
          exitCode: -1,
        });
      }
    };
    abortSignal.addEventListener("abort", abort, { once: true });

    proc.stdout?.on("data", (d: Buffer) => stdoutChunks.push(d.toString("utf-8")));
    proc.stderr?.on("data", (d: Buffer) => stderrChunks.push(d.toString("utf-8")));

    proc.on("close", (code: number | null) => {
      if (!finished) {
        finished = true;
        abortSignal.removeEventListener("abort", abort);
        resolve({
          stdout: stdoutChunks.join(""),
          stderr: stderrChunks.join(""),
          exitCode: code ?? 0,
        });
      }
    });

    proc.on("error", (err: Error) => {
      if (!finished) {
        finished = true;
        abortSignal.removeEventListener("abort", abort);
        resolve({ stdout: "", stderr: String(err), exitCode: 1 });
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Grep implementation
// ---------------------------------------------------------------------------

interface GrepResult {
  mode: string;
  numFiles: number;
  filenames: string[];
  appliedOffset: number;
  error?: string;
  appliedLimit?: number;
  numMatches?: number;
  numLines?: number;
  content?: string;
}

async function runGrep(input: GrepInput, ctx: ToolUseContext): Promise<GrepResult> {
  const outputMode = input.output_mode ?? "files_with_matches";
  const rawPath = input.path;
  const headLimit = input.head_limit ?? 250;
  const offset = input.offset ?? 0;
  const searchPath = rawPath ? expandPath(rawPath) : (ctx.cwd ?? process.cwd());

  if (isUncPath(searchPath)) {
    return {
      mode: outputMode,
      numFiles: 0,
      filenames: [],
      appliedOffset: offset,
      error: "UNC paths are blocked to prevent NTLM credential leaks",
    };
  }

  const cwd = ctx.cwd ?? process.cwd();
  const args: string[] = [];
  const pattern = input.pattern;

  if (pattern.startsWith("-")) {
    args.push("-e", pattern);
  } else {
    args.push(pattern);
  }

  for (const excl of VCS_EXCLUSION_GLOBS) {
    args.push("--glob", excl);
  }
  args.push("--max-columns", "500");

  if (input["-i"]) args.push("-i");
  if (input["-o"]) args.push("-o");
  if (input.type) args.push("--type", input.type);

  if (input.glob) {
    const globs = input.glob.split(/[\s,]+/).filter((g) => g.length > 0);
    for (const g of globs) {
      args.push("--glob", g);
    }
  }

  if (input.multiline) {
    args.push("-U", "--multiline-dotall");
  }

  if (outputMode === "files_with_matches") {
    args.push("--files-with-matches");
  } else if (outputMode === "count") {
    args.push("--count");
  } else {
    const contextBefore = input["-B"];
    const contextAfter = input["-A"];
    const contextBoth = input["-C"] ?? input.context;
    if (contextBoth != null) {
      args.push("-C", String(contextBoth));
    } else {
      if (contextBefore != null) args.push("-B", String(contextBefore));
      if (contextAfter != null) args.push("-A", String(contextAfter));
    }
    if (input["-n"] !== false) args.push("-n");
  }

  args.push(searchPath);

  const result = await runRipgrep(args, cwd, ctx.abortController.signal);

  // Exit codes: 0=match, 1=no match, 2=error; -1=aborted
  if (result.exitCode !== 0 && result.exitCode !== 1 && result.exitCode !== -1) {
    const stderr = result.stderr.trim();
    if (
      stderr.includes("No such file") ||
      stderr.includes("not found") ||
      stderr.toLowerCase().includes("does not exist")
    ) {
      return {
        mode: outputMode,
        numFiles: 0,
        filenames: [],
        appliedOffset: offset,
        error: `File not found: ${searchPath}`,
      };
    }
    if (
      stderr.includes("ENOENT") ||
      stderr.toLowerCase().includes("not found") ||
      stderr.includes("spawn")
    ) {
      return {
        mode: outputMode,
        numFiles: 0,
        filenames: [],
        appliedOffset: offset,
        error: `ripgrep (rg) not available: ${stderr}`,
      };
    }
    return {
      mode: outputMode,
      numFiles: 0,
      filenames: [],
      appliedOffset: offset,
      error: `Error searching files: ${stderr}`,
    };
  }

  const stdout = result.stdout;

  if (outputMode === "files_with_matches") {
    const rawFiles = stdout
      .split("\n")
      .filter((f) => f.trim().length > 0);

    const withMtime = await Promise.all(
      rawFiles.map(async (f) => {
        const absPath = isAbsolute(f) ? f : join(searchPath, f);
        try {
          const s = await stat(absPath);
          return { file: f, mtime: s.mtimeMs };
        } catch {
          return { file: f, mtime: 0 };
        }
      }),
    );
    withMtime.sort((a, b) => {
      if (b.mtime !== a.mtime) return b.mtime - a.mtime;
      return a.file.localeCompare(b.file);
    });
    const sorted = withMtime.map((x) => x.file);
    const sliced = headLimit > 0
      ? sorted.slice(offset, offset + headLimit)
      : sorted.slice(offset);
    const appliedLimit =
      headLimit > 0 && sliced.length < sorted.slice(offset).length ? headLimit : undefined;
    const relativized = sliced.map((f) => {
      const absPath = isAbsolute(f) ? f : join(searchPath, f);
      return toRelativePath(absPath, cwd);
    });
    return {
      mode: outputMode,
      numFiles: rawFiles.length,
      filenames: relativized,
      appliedLimit,
      appliedOffset: offset,
    };
  }

  if (outputMode === "count") {
    const lines = stdout.split("\n").filter((l) => l.trim().length > 0);
    let totalMatches = 0;
    const fileMatches: string[] = [];
    for (const line of lines) {
      const colonIdx = line.lastIndexOf(":");
      if (colonIdx < 0) continue;
      const countStr = line.slice(colonIdx + 1).trim();
      const filePart = line.slice(0, colonIdx);
      const count = parseInt(countStr, 10);
      if (!isNaN(count)) {
        totalMatches += count;
        fileMatches.push(filePart);
      }
    }
    const sliced = headLimit > 0
      ? fileMatches.slice(offset, offset + headLimit)
      : fileMatches.slice(offset);
    const relativized = sliced.map((f) => {
      const absPath = isAbsolute(f) ? f : join(searchPath, f);
      return toRelativePath(absPath, cwd);
    });
    return {
      mode: outputMode,
      numFiles: fileMatches.length,
      filenames: relativized,
      numMatches: totalMatches,
      appliedOffset: offset,
    };
  }

  // content mode
  const contentLines = stdout.split("\n");
  const sliced = headLimit > 0
    ? contentLines.slice(offset, offset + headLimit)
    : contentLines.slice(offset);
  const appliedLimit =
    headLimit > 0 && sliced.length < contentLines.slice(offset).length ? headLimit : undefined;

  const fileSet = new Set<string>();
  for (const line of contentLines) {
    const m = /^([^:]+):\d+:/.exec(line);
    if (m) {
      const absPath = isAbsolute(m[1]) ? m[1] : join(searchPath, m[1]);
      fileSet.add(toRelativePath(absPath, cwd));
    }
  }

  const content = sliced.join("\n");
  return {
    mode: outputMode,
    numFiles: fileSet.size,
    filenames: [...fileSet],
    content,
    numLines: sliced.filter((l) => l.trim().length > 0).length,
    appliedLimit,
    appliedOffset: offset,
  };
}

// ---------------------------------------------------------------------------
// VCS exclusion globs (ripgrep negation globs)
// ---------------------------------------------------------------------------

export const VCS_EXCLUSION_GLOBS: string[] = [
  "!.git/**",
  "!.svn/**",
  "!.hg/**",
  "!.bzr/**",
  "!.jj/**",
  "!.sl/**",
];

// ---------------------------------------------------------------------------
// Glob tool
// ---------------------------------------------------------------------------

const GlobInputSchema = z.object({
  pattern: z.string(),
  path: z.string().optional(),
});

type GlobInput = z.infer<typeof GlobInputSchema>;

export const globTool = buildTool<GlobInput, GlobResult>({
  name: "Glob",
  inputSchema: GlobInputSchema,

  isReadOnly: () => true,
  isDestructive: () => false,
  isConcurrencySafe: () => true,
  userFacingName: (_input?: GlobInput) => "Search",

  description: (_input?: GlobInput, _opts?) =>
    "Fast file-pattern matching. Returns file paths sorted by modification time.",

  prompt: (_opts?) => `## Glob tool
Find files by glob patterns.
- Pattern syntax: **/*.ts, src/**/*.{js,ts}
- path: directory to search (defaults to cwd).
- Returns up to 100 matches sorted by modification time (most recent first).
- When truncated, use more specific patterns.`,

  checkPermissions: async (input, _ctx) => {
    const rawPath = input.path ?? "";
    if (rawPath && isUncPath(expandPath(rawPath))) {
      return { behavior: "deny", updatedInput: input, message: "UNC paths are blocked" };
    }
    return { behavior: "allow", updatedInput: input };
  },

  async call(input, ctx, _canUseTool, _parentMsg) {
    const data = await runGlob(input, ctx);
    return { data };
  },

  mapToolResultToToolResultBlockParam(content, toolUseId) {
    return {
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
      is_error: content.error !== undefined ? true : undefined,
    };
  },

  toAutoClassifierInput: (input?: GlobInput) => input?.pattern ?? "",
});

// ---------------------------------------------------------------------------
// Grep tool
// ---------------------------------------------------------------------------

const GrepInputSchema = z.object({
  pattern: z.string(),
  path: z.string().optional(),
  glob: z.string().optional(),
  output_mode: z
    .enum(["content", "files_with_matches", "count"])
    .optional()
    .default("files_with_matches"),
  "-B": z.number().optional(),
  "-A": z.number().optional(),
  "-C": z.number().optional(),
  context: z.number().optional(),
  "-n": z.boolean().optional().default(true),
  "-i": z.boolean().optional(),
  "-o": z.boolean().optional(),
  type: z.string().optional(),
  head_limit: z.number().optional().default(250),
  offset: z.number().optional().default(0),
  multiline: z.boolean().optional().default(false),
});

type GrepInput = z.infer<typeof GrepInputSchema>;

export const grepTool = buildTool<GrepInput, GrepResult>({
  name: "Grep",
  inputSchema: GrepInputSchema,

  isReadOnly: () => true,
  isDestructive: () => false,
  isConcurrencySafe: () => true,
  userFacingName: (_input?: GrepInput) => "Search",

  description: (_input?: GrepInput, _opts?) =>
    "Content search powered by ripgrep. Supports regex, file-type filters, and three output modes.",

  prompt: (_opts?) => `## Grep tool
Search file contents with ripgrep.
- output_mode: 'files_with_matches' (default), 'content', 'count'
- glob: filter by file extension (e.g. "*.ts")
- type: ripgrep type filter (e.g. "ts", "py")
- -C: context lines around each match (content mode)
- head_limit: limit results (default 250); offset: skip first N
- multiline: enable cross-line matching
- VCS directories (.git, .svn, etc.) are excluded automatically.`,

  checkPermissions: async (input, _ctx) => {
    const rawPath = input.path ?? "";
    if (rawPath && isUncPath(expandPath(rawPath))) {
      return { behavior: "deny", updatedInput: input, message: "UNC paths are blocked" };
    }
    return { behavior: "allow", updatedInput: input };
  },

  async call(input, ctx, _canUseTool, _parentMsg) {
    const data = await runGrep(input, ctx);
    return { data };
  },

  mapToolResultToToolResultBlockParam(content, toolUseId) {
    return {
      type: "tool_result" as const,
      tool_use_id: toolUseId,
      content: JSON.stringify(content),
      is_error: content.error !== undefined ? true : undefined,
    };
  },

  toAutoClassifierInput: (input?: GrepInput) => input?.pattern ?? "",
});

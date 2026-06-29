// tools/file-write.ts — Write tool: create or overwrite files.
// De-transpiled from bundle (lines 304860–305245). Also contains utilities
// (computeUnifiedDiff, detectLineEndings, resolveGitDir) inlined from
// utils/file-operations.ts and utils/git.ts in the bundle, since those
// reconstructed stubs don't yet export these functions.
// bundle=Y

import { readFile, writeFile, stat, mkdir } from "fs/promises";
import { dirname } from "path";
import { exec } from "child_process";
import { promisify } from "util";
import { readFile as readFileGit, stat as statGit } from "fs/promises";
import { join as pathJoin, dirname as pathDirname } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";

const execAsync = promisify(exec);

// ---------------------------------------------------------------------------
// Team memory secret guard
// ---------------------------------------------------------------------------

const TEAM_MEMORY_SECRET_MARKERS = [
  "__EMBER_TEAM_MEMORY_SECRET__",
  "TEAM_MEMORY_SECRET",
];

function containsTeamMemorySecrets(content: string): boolean {
  return TEAM_MEMORY_SECRET_MARKERS.some((m) => content.includes(m));
}

// ---------------------------------------------------------------------------
// Path guards
// ---------------------------------------------------------------------------

function isUncPath(p: string): boolean {
  return p.startsWith("\\\\") || p.startsWith("//");
}

function isDenied(filePath: string, ctx: ToolUseContext): boolean {
  const state = ctx.getAppState() as Record<string, unknown>;
  const denyPaths = (state["denyPaths"] as string[] | undefined) ?? [];
  return denyPaths.some(
    (d) => filePath === d || filePath.startsWith(d + "/") || filePath.startsWith(d + "\\"),
  );
}

// ---------------------------------------------------------------------------
// Line ending detection (mirrors utils/file-operations.ts bundle code)
// ---------------------------------------------------------------------------

type LineEnding = "crlf" | "cr" | "lf" | "mixed" | "none";

export function detectLineEndings(content: string): LineEnding {
  let crlf = 0, cr = 0, lf = 0;
  for (let i = 0; i < content.length; i++) {
    if (content[i] === "\r") {
      if (i + 1 < content.length && content[i + 1] === "\n") {
        crlf++; i++;
      } else {
        cr++;
      }
    } else if (content[i] === "\n") {
      lf++;
    }
  }
  const total = crlf + cr + lf;
  if (total === 0) return "none";
  const max = Math.max(crlf, cr, lf);
  const winners: LineEnding[] = [];
  if (crlf === max) winners.push("crlf");
  if (cr === max) winners.push("cr");
  if (lf === max) winners.push("lf");
  return winners.length === 1 ? winners[0] : "mixed";
}

function applyLineEnding(content: string, targetEnding: LineEnding): string {
  if (targetEnding === "crlf") {
    const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    return normalized.replace(/\n/g, "\r\n");
  }
  if (targetEnding === "cr") {
    return content.replace(/\r\n/g, "\r").replace(/\n/g, "\r");
  }
  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

// ---------------------------------------------------------------------------
// Git dir resolution (mirrors utils/git.ts bundle code)
// ---------------------------------------------------------------------------

const _resolvedGitDirCache = new Map<string, string | null>();

export async function resolveGitDir(startDir: string): Promise<string | null> {
  const cached = _resolvedGitDirCache.get(startDir);
  if (cached !== undefined) return cached;
  let dir = startDir;
  while (true) {
    const gitPath = pathJoin(dir, ".git");
    try {
      const info = await statGit(gitPath);
      if (info.isDirectory()) {
        _resolvedGitDirCache.set(startDir, gitPath);
        return gitPath;
      } else if (info.isFile()) {
        const content = await readFileGit(gitPath, "utf-8");
        const match = content.match(/^gitdir:\s*(.+)$/m);
        if (match) {
          const commonDir = match[1]!.trim();
          _resolvedGitDirCache.set(startDir, commonDir);
          return commonDir;
        }
        _resolvedGitDirCache.set(startDir, null);
        return null;
      }
    } catch {}
    const parent = pathDirname(dir);
    if (parent === dir) {
      _resolvedGitDirCache.set(startDir, null);
      return null;
    }
    dir = parent;
  }
}

// ---------------------------------------------------------------------------
// Unified diff computation (exported for file-edit.ts)
// ---------------------------------------------------------------------------

export interface HunkPatch {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];
}

export function computeUnifiedDiff(
  oldText: string,
  newText: string,
  contextLines = 3,
): HunkPatch[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const m = oldLines.length;
  const n = newLines.length;

  // Fast path: if files are large, produce a single hunk with all changes
  if (m * n > 1e5) {
    const lines: string[] = [];
    for (const l of oldLines) lines.push(`-${l}`);
    for (const l of newLines) lines.push(`+${l}`);
    return [{ oldStart: 1, oldLines: m, newStart: 1, newLines: n, lines }];
  }

  // LCS-based diff via DP
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (oldLines[i] === newLines[j]) {
        dp[i]![j] = (dp[i + 1]?.[j + 1] ?? 0) + 1;
      } else {
        dp[i]![j] = Math.max(dp[i + 1]?.[j] ?? 0, dp[i]?.[j + 1] ?? 0);
      }
    }
  }

  type Op = { op: "eq" | "ins" | "del"; oldLine: number; newLine: number; text: string };
  const ops: Op[] = [];
  let i = 0, j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && oldLines[i] === newLines[j]) {
      ops.push({ op: "eq", oldLine: i, newLine: j, text: oldLines[i]! });
      i++; j++;
    } else if (j < n && (i >= m || (dp[i]?.[j + 1] ?? 0) >= (dp[i + 1]?.[j] ?? 0))) {
      ops.push({ op: "ins", oldLine: i, newLine: j, text: newLines[j]! });
      j++;
    } else {
      ops.push({ op: "del", oldLine: i, newLine: j, text: oldLines[i]! });
      i++;
    }
  }

  const hunks: HunkPatch[] = [];
  let k = 0;
  while (k < ops.length) {
    if (ops[k]!.op === "eq") { k++; continue; }
    const start = Math.max(0, k - contextLines);
    let end = k;
    while (end < ops.length) {
      if (ops[end]!.op !== "eq") {
        end++;
      } else {
        let eq = 0, e2 = end;
        while (e2 < ops.length && ops[e2]!.op === "eq") { eq++; e2++; }
        if (eq > contextLines * 2) break;
        end = e2;
      }
    }
    const hunkEnd = Math.min(ops.length, end + contextLines);
    const hunkOps = ops.slice(start, hunkEnd);
    const lines: string[] = [];
    let delCount = 0, insCount = 0;
    let oldStartLine = -1, newStartLine = -1;
    for (const op of hunkOps) {
      if (oldStartLine < 0 && (op.op === "eq" || op.op === "del")) oldStartLine = op.oldLine + 1;
      if (newStartLine < 0 && (op.op === "eq" || op.op === "ins")) newStartLine = op.newLine + 1;
      if (op.op === "eq") {
        lines.push(` ${op.text}`);
        delCount++; insCount++;
      } else if (op.op === "del") {
        lines.push(`-${op.text}`);
        delCount++;
      } else {
        lines.push(`+${op.text}`);
        insCount++;
      }
    }
    if (delCount > 0 || insCount > 0) {
      hunks.push({
        oldStart: oldStartLine > 0 ? oldStartLine : 1,
        oldLines: delCount,
        newStart: newStartLine > 0 ? newStartLine : 1,
        newLines: insCount,
        lines,
      });
    }
    k = hunkEnd;
  }
  return hunks;
}

// ---------------------------------------------------------------------------
// Git diff helper
// ---------------------------------------------------------------------------

export interface GitDiff {
  filename: string;
  status: "modified";
  additions: number;
  deletions: number;
  changes: number;
  patch: string;
}

async function computeGitDiff(filePath: string): Promise<GitDiff | undefined> {
  try {
    const gitDir = await resolveGitDir(dirname(filePath));
    if (!gitDir) return undefined;
    const { stdout } = await execAsync(`git diff --no-color -- "${filePath}"`, {
      cwd: dirname(filePath),
      timeout: 5000,
    });
    if (!stdout.trim()) return undefined;
    const additions = (stdout.match(/^\+[^+]/gm) ?? []).length;
    const deletions = (stdout.match(/^-[^-]/gm) ?? []).length;
    return {
      filename: filePath,
      status: "modified",
      additions,
      deletions,
      changes: additions + deletions,
      patch: stdout,
    };
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Public output type (used by test: import type { WriteOutput })
// ---------------------------------------------------------------------------

// Flat interface (not a discriminated union) so test code can access all properties
// without narrowing. Runtime shape is still discriminated by `type`.
export interface WriteOutput {
  type: "create" | "update" | "error";
  filePath?: string;
  content?: string;
  /** null for create, string for update, undefined for error */
  originalFile?: string | null;
  structuredPatch?: HunkPatch[];
  gitDiff?: GitDiff;
  /** Defined when type === "error" */
  error?: string;
}

// ---------------------------------------------------------------------------
// Core write implementation
// ---------------------------------------------------------------------------

async function writeFile_(
  input: { file_path: string; content: string },
  ctx: ToolUseContext,
): Promise<WriteOutput> {
  const { file_path: filePath, content } = input;

  if (containsTeamMemorySecrets(content)) {
    return { type: "error", error: "Write rejected: content contains team memory secrets." };
  }
  if (isUncPath(filePath)) {
    return { type: "error", error: `UNC network paths are not supported: ${filePath}` };
  }
  if (isDenied(filePath, ctx)) {
    return { type: "error", error: `Write denied by session rules: ${filePath}` };
  }

  let originalFile: string | null = null;
  let originalEnding: LineEnding = "none";
  let isCreate = true;
  try {
    originalFile = await readFile(filePath, "utf-8");
    isCreate = false;
    originalEnding = detectLineEndings(originalFile);
  } catch {
    isCreate = true;
  }

  const finalContent = isCreate ? content : applyLineEnding(content, originalEnding);
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, finalContent, "utf-8");

  try {
    const newStat = await stat(filePath);
    ctx.readFileState?.set(filePath, { mtime: newStat.mtimeMs, content: finalContent });
  } catch {}

  if (filePath.includes("/.ember/") || filePath.includes("\\.ember\\")) {
    ctx.dynamicSkillDirTriggers?.add(dirname(filePath));
  }

  if (!isCreate && originalFile !== null) {
    const patch = computeUnifiedDiff(originalFile, finalContent);
    const gitDiff = await computeGitDiff(filePath);
    return {
      type: "update" as const,
      filePath,
      content: finalContent,
      structuredPatch: patch,
      originalFile,
      ...(gitDiff ? { gitDiff } : {}),
    };
  }
  return { type: "create" as const, filePath, content: finalContent, originalFile: null };
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const WriteInputSchema = z.object({
  file_path: z.string(),
  content: z.string(),
});

export type WriteInput = z.infer<typeof WriteInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const writeTool = Object.assign(
  buildTool<WriteInput, WriteOutput>({
    name: "Write",

    inputSchema: WriteInputSchema,

    isReadOnly: () => false,
    isDestructive: () => true,
    isConcurrencySafe: () => false,

    description: (_input?: WriteInput, _opts?) =>
      "Write content to a file, creating or overwriting it. Prefer Edit for partial modifications.",

    prompt: (_opts?) => `## Write tool
Write complete content to a file. Creates the file if it does not exist, or replaces it entirely.
- Prefer the Edit tool for modifying specific sections of an existing file.
- For new files or complete rewrites, use Write.
- Always read an existing file before writing to it.
- Absolute paths only.`,

    call: async (args: WriteInput, ctx: ToolUseContext) => {
      const data = await writeFile_(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: WriteOutput, toolUseId: string) => {
      if (content.type === "error") {
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: content.error ?? "Write error",
          is_error: true,
        };
      }
      return {
        type: "tool_result" as const,
        tool_use_id: toolUseId,
        content: JSON.stringify(content),
      };
    },

    toAutoClassifierInput: (input?: WriteInput) => input?.file_path ?? "",
  }),
  { searchHint: "write complete file content to disk", getPath: (i: WriteInput) => i.file_path } as const,
);

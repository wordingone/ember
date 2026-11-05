// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// tools/file-write.ts — Write tool: create or overwrite files.
// De-transpiled from bundle (lines 304860–305245). Also contains utilities
// (computeUnifiedDiff, detectLineEndings, resolveGitDir) inlined from
// utils/file-operations.ts and utils/git.ts in the bundle, since those
// reconstructed stubs don't yet export these functions.
// bundle=Y

import { readFile, writeFile, stat, mkdir } from "fs/promises";
import { dirname } from "path";
import { isUnderEmberState } from "../utils/ember-state-root.ts";
import { exec } from "child_process";
import { promisify } from "util";
import { readFile as readFileGit, stat as statGit } from "fs/promises";
import { join as pathJoin, dirname as pathDirname } from "path";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import { resolveFilePath } from "./file-read.ts";
import {
  decodeTextBuffer,
  describeWriteError,
  encodeText,
  fileStateKey,
  invalidFileNameReason,
  isOutsideCwd,
  outsideCwdMessage,
  type TextEncoding,
} from "./file-text.ts";

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

  // Lines the two texts share at the start and at the end are not diffed. Without this, a one-line
  // edit of a 5000-line file fell into the "large file" fallback below and was reported as every
  // old line deleted and every new line added (blind test FO-32).
  let prefix = 0;
  while (prefix < m && prefix < n && oldLines[prefix] === newLines[prefix]) prefix++;
  let suffix = 0;
  while (suffix < m - prefix && suffix < n - prefix && oldLines[m - 1 - suffix] === newLines[n - 1 - suffix]) suffix++;
  const midOld = oldLines.slice(prefix, m - suffix);
  const midNew = newLines.slice(prefix, n - suffix);
  const mm = midOld.length;
  const nn = midNew.length;

  type Op = { op: "eq" | "ins" | "del"; oldLine: number; newLine: number; text: string };
  const ops: Op[] = [];

  // Only `contextLines` of the shared head and tail can ever appear in a hunk.
  for (let k = Math.max(0, prefix - contextLines); k < prefix; k++) {
    ops.push({ op: "eq", oldLine: k, newLine: k, text: oldLines[k]! });
  }

  if (mm * nn > 1e5) {
    // A very large changed region: one hunk, all old lines out and all new lines in.
    for (let k = 0; k < mm; k++) ops.push({ op: "del", oldLine: prefix + k, newLine: prefix, text: midOld[k]! });
    for (let k = 0; k < nn; k++) ops.push({ op: "ins", oldLine: prefix + mm, newLine: prefix + k, text: midNew[k]! });
  } else {
    // LCS-based diff via DP on the changed region only
    const dp: number[][] = Array.from({ length: mm + 1 }, () => new Array(nn + 1).fill(0));
    for (let i = mm - 1; i >= 0; i--) {
      for (let j = nn - 1; j >= 0; j--) {
        if (midOld[i] === midNew[j]) {
          dp[i]![j] = (dp[i + 1]?.[j + 1] ?? 0) + 1;
        } else {
          dp[i]![j] = Math.max(dp[i + 1]?.[j] ?? 0, dp[i]?.[j + 1] ?? 0);
        }
      }
    }
    let i = 0, j = 0;
    while (i < mm || j < nn) {
      if (i < mm && j < nn && midOld[i] === midNew[j]) {
        ops.push({ op: "eq", oldLine: prefix + i, newLine: prefix + j, text: midOld[i]! });
        i++; j++;
      } else if (i < mm && (j >= nn || (dp[i + 1]?.[j] ?? 0) >= (dp[i]?.[j + 1] ?? 0))) {
        // removed lines come before the lines that replace them, as in every diff a reader has seen
        ops.push({ op: "del", oldLine: prefix + i, newLine: prefix + j, text: midOld[i]! });
        i++;
      } else {
        ops.push({ op: "ins", oldLine: prefix + i, newLine: prefix + j, text: midNew[j]! });
        j++;
      }
    }
  }

  for (let k = 0; k < Math.min(contextLines, suffix); k++) {
    ops.push({ op: "eq", oldLine: m - suffix + k, newLine: n - suffix + k, text: oldLines[m - suffix + k]! });
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
  const { content } = input;
  // Relative paths resolve against the agent cwd, exactly as Read does (a bare
  // "x.py" used to reach mkdir(".") which Bun on Windows rejects with EEXIST).
  const filePath = resolveFilePath(input.file_path, ctx.cwd ?? process.cwd());

  if (containsTeamMemorySecrets(content)) {
    return { type: "error", error: "Write rejected: content contains team memory secrets." };
  }
  if (isUncPath(filePath)) {
    return { type: "error", error: `UNC network paths are not supported: ${filePath}` };
  }
  if (isDenied(filePath, ctx)) {
    return { type: "error", error: `Write denied by session rules: ${filePath}` };
  }

  // Windows rejects some names (< > : " | ? *, CON, NUL ...); Bun reports that as a bare ENOENT (blind test FO-43).
  const badName = invalidFileNameReason(filePath);
  if (badName) {
    return { type: "error", error: badName };
  }

  let originalFile: string | null = null;
  let originalEnding: LineEnding = "none";
  let originalEncoding: TextEncoding = "utf-8";
  let originalBom = false;
  let isCreate = true;
  try {
    // A UTF-16 file (PowerShell output) is rewritten as UTF-16, as its line endings are kept (FO-34).
    const decoded = decodeTextBuffer(await readFile(filePath));
    originalFile = decoded.text;
    originalEncoding = decoded.encoding;
    originalBom = decoded.bom;
    isCreate = false;
    originalEnding = detectLineEndings(originalFile);
  } catch {
    isCreate = true;
  }

  // Overwriting a file the model has never read (or that changed since it read it) silently
  // destroys content it never saw (blind test FO-09). Same guard as Claude Code's Write.
  if (!isCreate && ctx.readFileState) {
    const seen = ctx.readFileState.get(fileStateKey(filePath)) as { mtime: number } | undefined;
    if (!seen) {
      return {
        type: "error",
        error: `${filePath} already exists and has not been read in this session. Read it first, then Write (or use Edit for a change).`,
      };
    }
    try {
      const current = await stat(filePath);
      if (current.mtimeMs !== seen.mtime) {
        return {
          type: "error",
          error: `${filePath} changed on disk since it was last read. Read it again before writing.`,
        };
      }
    } catch {}
  }

  const finalContent = isCreate ? content : applyLineEnding(content, originalEnding);
  try {
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, encodeText(finalContent, originalEncoding, originalBom));
  } catch (e) {
    return { type: "error", error: describeWriteError(e, filePath) };
  }

  try {
    const newStat = await stat(filePath);
    ctx.readFileState?.set(fileStateKey(filePath), { mtime: newStat.mtimeMs, content: finalContent });
  } catch {}

  if (isUnderEmberState(filePath)) {
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
- An existing file must be Read first: writing over a file you have not read (or that changed since) is refused.
- A path outside the working directory needs the operator's approval every time.
- Absolute paths only.`,

    // A write that leaves the working directory asks every time, even after "always allow Write" (FO-22).
    checkPermissions: async (input: WriteInput, ctx: ToolUseContext) => {
      const cwd = ctx.cwd ?? process.cwd();
      const filePath = resolveFilePath(input.file_path, cwd);
      if (isDenied(filePath, ctx)) {
        return { behavior: "deny" as const, updatedInput: input, message: `Write denied by session rules: ${filePath}` };
      }
      if (isOutsideCwd(filePath, cwd)) {
        return { behavior: "ask" as const, updatedInput: input, message: outsideCwdMessage(filePath, cwd) };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

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
        content: content.type === "create"
          ? `Created ${content.filePath} (${(content.content ?? "").split("\n").length} lines).`
          : summarizeFileChange("Updated", content.filePath ?? "", content.structuredPatch),
      };
    },

    toAutoClassifierInput: (input?: WriteInput) => input?.file_path ?? "",
  }),
  { searchHint: "write complete file content to disk", getPath: (i: WriteInput) => i.file_path } as const,
);

/** What the model gets back after a successful write: a short confirmation and the changed lines,
 *  never the whole file (blind test: one Edit of a 5000-line file sent the full 80 KB back). */
export function summarizeFileChange(verb: string, filePath: string, patch: HunkPatch[] | undefined): string {
  const head = `${verb} ${filePath}.`;
  if (!patch || patch.length === 0) return head;
  const out: string[] = [];
  let budget = 40;
  for (const h of patch) {
    if (budget <= 0) break;
    out.push(`@@ -${h.oldStart},${h.oldLines} +${h.newStart},${h.newLines} @@`);
    for (const line of h.lines) {
      if (budget-- <= 0) { out.push("..."); break; }
      out.push(line.length > 300 ? line.slice(0, 300) + "..." : line);
    }
  }
  return `${head}\n${out.join("\n")}`;
}

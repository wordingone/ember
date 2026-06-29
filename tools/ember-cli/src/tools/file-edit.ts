// tools/file-edit.ts — Edit tool: exact-string-replacement edits on existing files.
// De-transpiled from bundle (lines 305245–305510). Requires prior Read; uses
// computeUnifiedDiff and detectLineEndings from file-write.ts.
// bundle=Y

import { readFile, writeFile, stat, mkdir } from "fs/promises";
import { dirname } from "path";
import { exec } from "child_process";
import { promisify } from "util";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import {
  computeUnifiedDiff,
  detectLineEndings,
  resolveGitDir,
  type HunkPatch,
  type GitDiff,
} from "./file-write.ts";

const execAsync2 = promisify(exec);

const MAX_FILE_SIZE_GIB = 1 * 1024 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Path and content guards
// ---------------------------------------------------------------------------

function isUncPath3(p: string): boolean {
  return p.startsWith("\\\\") || p.startsWith("//");
}

function isDenied2(filePath: string, ctx: ToolUseContext): boolean {
  const state = ctx.getAppState() as Record<string, unknown>;
  const denyPaths = (state["denyPaths"] as string[] | undefined) ?? [];
  return denyPaths.some(
    (d) => filePath === d || filePath.startsWith(d + "/") || filePath.startsWith(d + "\\"),
  );
}

function containsTeamMemorySecrets2(s: string): boolean {
  return s.includes("__EMBER_TEAM_MEMORY_SECRET__") || s.includes("TEAM_MEMORY_SECRET");
}

function applyLineEnding2(
  content: string,
  ending: "crlf" | "cr" | "lf" | "mixed" | "none",
): string {
  if (ending === "crlf") {
    const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    return normalized.replace(/\n/g, "\r\n");
  }
  if (ending === "cr") {
    return content.replace(/\r\n/g, "\r").replace(/\n/g, "\r");
  }
  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

// ---------------------------------------------------------------------------
// String search helpers
// ---------------------------------------------------------------------------

function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) return 0;
  let count = 0, start = 0;
  while (true) {
    const idx = haystack.indexOf(needle, start);
    if (idx < 0) break;
    count++;
    start = idx + needle.length;
  }
  return count;
}

function replaceAll2(haystack: string, needle: string, replacement: string): string {
  if (needle.length === 0) return haystack;
  return haystack.split(needle).join(replacement);
}

function findWithNormalization(haystack: string, needle: string): number {
  const normalizeWS = (s: string) => s.replace(/[ \t]+/g, " ").trim();
  const normHaystack = normalizeWS(haystack);
  const normNeedle = normalizeWS(needle);
  return normHaystack.indexOf(normNeedle);
}

// ---------------------------------------------------------------------------
// Git diff helper
// ---------------------------------------------------------------------------

async function computeGitDiff2(filePath: string): Promise<GitDiff | undefined> {
  try {
    const gitDir = await resolveGitDir(dirname(filePath));
    if (!gitDir) return undefined;
    const { stdout } = await execAsync2(`git diff --no-color -- "${filePath}"`, {
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
// Public output type
// ---------------------------------------------------------------------------

export type EditOutput =
  | { error: string }
  | {
      filePath: string;
      oldString: string;
      newString: string;
      originalFile: string;
      structuredPatch: HunkPatch[];
      userModified: boolean;
      replaceAll: boolean;
      gitDiff?: GitDiff;
    };

// ---------------------------------------------------------------------------
// Core edit implementation
// ---------------------------------------------------------------------------

async function editFile_(
  input: {
    file_path: string;
    old_string: string;
    new_string: string;
    replace_all?: boolean;
  },
  ctx: ToolUseContext,
): Promise<EditOutput> {
  const { file_path: filePath, old_string: oldString, new_string: newString } = input;
  const replaceAllFlag = input.replace_all ?? false;

  if (containsTeamMemorySecrets2(newString)) {
    return { error: "Edit rejected: new_string contains team memory secrets." };
  }
  if (oldString === newString) {
    return {
      error: "Edit rejected: old_string and new_string are identical. No change would be made.",
    };
  }
  if (isDenied2(filePath, ctx)) {
    return { error: `Edit denied by session rules: ${filePath}` };
  }
  if (isUncPath3(filePath)) {
    return { error: `UNC network paths are not supported: ${filePath}` };
  }

  let fileStat: Awaited<ReturnType<typeof stat>>;
  try {
    fileStat = await stat(filePath);
  } catch {
    return { error: `File not found: ${filePath}` };
  }

  if (fileStat.size > MAX_FILE_SIZE_GIB) {
    return {
      error: `File exceeds 1 GiB limit (${fileStat.size} bytes). Edit rejected to prevent OOM.`,
    };
  }

  let originalFile: string;
  try {
    originalFile = await readFile(filePath, "utf-8");
  } catch (e) {
    return { error: `Failed to read file: ${filePath}: ${String(e)}` };
  }

  const cachedEntry = ctx.readFileState?.get(filePath) as
    | { mtime: number; content: string }
    | undefined;
  const externallyModified = cachedEntry !== undefined && cachedEntry.mtime !== fileStat.mtimeMs;

  if (replaceAllFlag) {
    const occurrences = countOccurrences(originalFile, oldString);
    if (occurrences === 0) {
      const normIdx = findWithNormalization(originalFile, oldString);
      if (normIdx < 0) {
        return {
          error: `old_string not found in file: ${filePath}. Verify the exact text to replace.`,
        };
      }
    }
    const newContent = replaceAll2(originalFile, oldString, newString);
    const ending = detectLineEndings(originalFile);
    const finalContent = applyLineEnding2(newContent, ending);
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, finalContent, "utf-8");
    try {
      const newStat = await stat(filePath);
      ctx.readFileState?.set(filePath, { mtime: newStat.mtimeMs, content: finalContent });
    } catch {}
    if (filePath.includes("/.ember/") || filePath.includes("\\.ember\\")) {
      ctx.dynamicSkillDirTriggers?.add(dirname(filePath));
    }
    const patch = computeUnifiedDiff(originalFile, finalContent);
    const gitDiff = await computeGitDiff2(filePath);
    return {
      filePath,
      oldString,
      newString,
      originalFile,
      structuredPatch: patch,
      userModified: false,
      replaceAll: true,
      ...(gitDiff ? { gitDiff } : {}),
    };
  } else {
    const occurrences = countOccurrences(originalFile, oldString);
    if (occurrences === 0) {
      const normIdx = findWithNormalization(originalFile, oldString);
      if (normIdx < 0) {
        return {
          error: `old_string not found in file: ${filePath}. Verify the exact text to replace.`,
        };
      }
    } else if (occurrences > 1) {
      return {
        error:
          `old_string is not unique in the file (${occurrences} matches found). ` +
          `Provide more context to make the match unique, or use replace_all: true.`,
      };
    }
    const newContent = originalFile.replace(oldString, newString);
    const ending = detectLineEndings(originalFile);
    const finalContent = applyLineEnding2(newContent, ending);
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, finalContent, "utf-8");
    try {
      const newStat = await stat(filePath);
      ctx.readFileState?.set(filePath, { mtime: newStat.mtimeMs, content: finalContent });
    } catch {}
    if (filePath.includes("/.ember/") || filePath.includes("\\.ember\\")) {
      ctx.dynamicSkillDirTriggers?.add(dirname(filePath));
    }
    const patch = computeUnifiedDiff(originalFile, finalContent);
    const gitDiff = await computeGitDiff2(filePath);
    // externallyModified is tracked but output shape is unchanged (matches bundle)
    void externallyModified;
    return {
      filePath,
      oldString,
      newString,
      originalFile,
      structuredPatch: patch,
      userModified: false,
      replaceAll: false,
      ...(gitDiff ? { gitDiff } : {}),
    };
  }
}

// ---------------------------------------------------------------------------
// Schema and input type
// ---------------------------------------------------------------------------

const EditInputSchema = z.object({
  file_path: z.string(),
  old_string: z.string(),
  new_string: z.string(),
  replace_all: z.boolean().optional().default(false),
});

export type EditInput = z.infer<typeof EditInputSchema>;

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const editTool = Object.assign(
  buildTool<EditInput, EditOutput>({
    name: "Edit",

    inputSchema: EditInputSchema,

    isReadOnly: () => false,
    isDestructive: () => true,
    isConcurrencySafe: () => false,

    description: (_input?: EditInput, _opts?) =>
      "Apply exact-string-replacement edits to an existing file. Requires prior Read of the file.",

    prompt: (_opts?) => `## Edit tool
Perform exact-string replacements on files. The model provides the exact text to find (old_string) and
replacement text (new_string). Use Read before editing to get the current content.
- old_string must be unique in the file unless replace_all is true.
- Empty old_string creates the file (equivalent to Write for a new file).
- replace_all: true replaces every occurrence.
- Absolute paths only.`,

    checkPermissions: async (input: EditInput, ctx: ToolUseContext) => {
      if (isDenied2(input.file_path, ctx)) {
        return { behavior: "deny" as const, updatedInput: input, message: "Denied by session rules" };
      }
      return { behavior: "allow" as const, updatedInput: input };
    },

    call: async (args: EditInput, ctx: ToolUseContext) => {
      const data = await editFile_(args, ctx);
      return { data };
    },

    mapToolResultToToolResultBlockParam: (content: EditOutput, toolUseId: string) => {
      if ("error" in content && content.error !== undefined) {
        return {
          type: "tool_result" as const,
          tool_use_id: toolUseId,
          content: content.error,
          is_error: true,
        };
      }
      return {
        type: "tool_result" as const,
        tool_use_id: toolUseId,
        content: JSON.stringify(content),
      };
    },

    toAutoClassifierInput: (input?: EditInput) => input?.file_path ?? "",
  }),
  { searchHint: "edit a file by replacing exact text", getPath: (i: EditInput) => i.file_path } as const,
);

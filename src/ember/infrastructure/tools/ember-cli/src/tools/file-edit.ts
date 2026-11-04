// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// tools/file-edit.ts — Edit tool: exact-string-replacement edits on existing files.
// De-transpiled from bundle (lines 305245–305510). Requires prior Read; uses
// computeUnifiedDiff and detectLineEndings from file-write.ts.
// bundle=Y

import { readFile, writeFile, stat } from "fs/promises";
import { dirname } from "path";
import { isUnderEmberState } from "../utils/ember-state-root.ts";
import { exec } from "child_process";
import { promisify } from "util";
import { z } from "zod";
import { buildTool, type ToolUseContext } from "../core/tool-interface.ts";
import { resolveFilePath } from "./file-read.ts";
import {
  decodeTextBuffer,
  describeWriteError,
  encodeText,
  fileStateKey,
  isOutsideCwd,
  outsideCwdMessage,
  type TextEncoding,
} from "./file-text.ts";
import {
  computeUnifiedDiff,
  summarizeFileChange,
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
  let { old_string: oldString, new_string: newString } = input;
  const filePath = resolveFilePath(input.file_path, ctx.cwd ?? process.cwd());
  const replaceAllFlag = input.replace_all ?? false;

  if (containsTeamMemorySecrets2(newString)) {
    return { error: "Edit rejected: new_string contains team memory secrets." };
  }
  if (oldString === "") {
    return {
      error: "Edit rejected: old_string is empty. To create a file or replace all of its content, use Write.",
    };
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

  // Editing a file the model never read (or that changed since it read it) replaces text it has
  // not seen. Same guard as Write (blind test FO-21; Write's is FO-09).
  if (ctx.readFileState) {
    const seen = ctx.readFileState.get(fileStateKey(filePath)) as { mtime: number } | undefined;
    if (!seen) {
      return {
        error: `${filePath} has not been read in this session. Read it first, then Edit.`,
      };
    }
    if (seen.mtime !== fileStat.mtimeMs) {
      return {
        error: `${filePath} changed on disk since it was last read. Read it again before editing.`,
      };
    }
  }

  let originalFile: string;
  let encoding: TextEncoding;
  let bom: boolean;
  try {
    // A UTF-16 file (PowerShell output) is edited as text and written back as UTF-16 (FO-34).
    const decoded = decodeTextBuffer(await readFile(filePath));
    originalFile = decoded.text;
    encoding = decoded.encoding;
    bom = decoded.bom;
  } catch (e) {
    return { error: `Failed to read file: ${filePath}: ${String(e)}` };
  }

  // Models send old_string with LF line breaks. A CRLF file would never match a
  // multi-line old_string, so match on LF-normalised text; the original line
  // ending is restored on write.
  const originalEnding = detectLineEndings(originalFile);
  const normalizeEol = originalEnding === "crlf" || originalEnding === "lf";
  const toLf = (s: string) => (normalizeEol ? s.replace(/\r\n/g, "\n") : s);
  const workFile = toLf(originalFile);
  oldString = toLf(oldString);
  newString = toLf(newString);
  const notFound = () => {
    const near = findWithNormalization(workFile, oldString) >= 0
      ? " A match exists if spaces/tabs are ignored: copy the exact whitespace from a fresh Read."
      : "";
    return { error: `old_string not found in file: ${filePath}. Verify the exact text to replace.${near}` };
  };

  if (replaceAllFlag) {
    const occurrences = countOccurrences(workFile, oldString);
    if (occurrences === 0) return notFound();
    const newContent = replaceAll2(workFile, oldString, newString);
    const ending = originalEnding;
    const finalContent = applyLineEnding2(newContent, ending);
    try {
      await writeFile(filePath, encodeText(finalContent, encoding, bom));
    } catch (e) {
      return { error: describeWriteError(e, filePath) };
    }
    try {
      const newStat = await stat(filePath);
      ctx.readFileState?.set(fileStateKey(filePath), { mtime: newStat.mtimeMs, content: finalContent });
    } catch {}
    if (isUnderEmberState(filePath)) {
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
    const occurrences = countOccurrences(workFile, oldString);
    if (occurrences === 0) {
      return notFound();
    } else if (occurrences > 1) {
      return {
        error:
          `old_string is not unique in the file (${occurrences} matches found). ` +
          `Provide more context to make the match unique, or use replace_all: true.`,
      };
    }
    const idx = workFile.indexOf(oldString);
    const newContent = workFile.slice(0, idx) + newString + workFile.slice(idx + oldString.length);
    const ending = originalEnding;
    const finalContent = applyLineEnding2(newContent, ending);
    try {
      await writeFile(filePath, encodeText(finalContent, encoding, bom));
    } catch (e) {
      return { error: describeWriteError(e, filePath) };
    }
    try {
      const newStat = await stat(filePath);
      ctx.readFileState?.set(fileStateKey(filePath), { mtime: newStat.mtimeMs, content: finalContent });
    } catch {}
    if (isUnderEmberState(filePath)) {
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
- The file must have been Read in this session (and not changed since): editing an unread file is refused.
- To create a file or replace all of it, use Write.
- replace_all: true replaces every occurrence.
- A path outside the working directory needs the operator's approval every time.
- Absolute paths only.`,

    checkPermissions: async (input: EditInput, ctx: ToolUseContext) => {
      const cwd = ctx.cwd ?? process.cwd();
      const filePath = resolveFilePath(input.file_path, cwd);
      if (isDenied2(filePath, ctx)) {
        return { behavior: "deny" as const, updatedInput: input, message: "Denied by session rules" };
      }
      // Leaving the working directory asks every time, even after "always allow Edit" (FO-22).
      if (isOutsideCwd(filePath, cwd)) {
        return { behavior: "ask" as const, updatedInput: input, message: outsideCwdMessage(filePath, cwd) };
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
        content: "filePath" in content ? summarizeFileChange("Edited", content.filePath, content.structuredPatch) : JSON.stringify(content),
      };
    },

    toAutoClassifierInput: (input?: EditInput) => input?.file_path ?? "",
  }),
  { searchHint: "edit a file by replacing exact text", getPath: (i: EditInput) => i.file_path } as const,
);

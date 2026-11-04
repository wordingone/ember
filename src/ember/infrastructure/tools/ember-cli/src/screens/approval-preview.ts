// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// screens/approval-preview.ts — what the approval prompt shows under "Allow Write: file_path=...".
// Blind test FO-7: the prompt showed only the path, no content, no diff, and nothing said that a
// Write would overwrite an existing file. This builds a few plain lines from the call's input and,
// for Write, the file as it is on disk now. Pure read-only filesystem access.

import { readFile, stat } from "fs/promises";
import { resolveFilePath } from "../tools/file-read.ts";
import { decodeTextBuffer } from "../tools/file-text.ts";
import { computeUnifiedDiff } from "../tools/file-write.ts";

/** Most lines the preview adds to the approval box. */
export const APPROVAL_DETAIL_MAX_LINES = 8;
const LINE_MAX_CHARS = 100;
const SNIPPET_LINES = 3;

function clip(line: string): string {
  const flat = line.replace(/\r/g, "").replace(/\t/g, "  ");
  return flat.length > LINE_MAX_CHARS ? flat.slice(0, LINE_MAX_CHARS - 3) + "..." : flat;
}

function lineCount(text: string): number {
  if (text.length === 0) return 0;
  const n = text.split("\n").length;
  return text.endsWith("\n") ? n - 1 : n;
}

/** First `max` lines of `text`, prefixed, with a "+K more lines" tail when it is longer. */
function snippet(text: string, prefix: string, max: number): string[] {
  const lines = text.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const shown = lines.slice(0, max).map((l) => `${prefix} ${clip(l)}`);
  if (lines.length > max) shown.push(`  ... ${lines.length - max} more line${lines.length - max === 1 ? "" : "s"}`);
  return shown;
}

/** Changed lines only (no context), at most `max`, from the unified diff of old -> new. */
function changedLines(oldText: string, newText: string, max: number): { lines: string[]; added: number; removed: number } {
  const hunks = computeUnifiedDiff(oldText, newText, 0);
  const lines: string[] = [];
  let added = 0;
  let removed = 0;
  for (const h of hunks) {
    for (const l of h.lines) {
      if (l.startsWith("+")) added++;
      else if (l.startsWith("-")) removed++;
      else continue;
      if (lines.length < max) lines.push(`${l[0]} ${clip(l.slice(1))}`);
    }
  }
  if (added + removed > max) lines.push(`  ... ${added + removed - max} more changed line${added + removed - max === 1 ? "" : "s"}`);
  return { lines, added, removed };
}

/**
 * Detail lines for an approval prompt. Empty for tools with nothing worth previewing.
 * Never throws: a file that cannot be read just gets a shorter preview.
 */
export async function buildApprovalDetail(toolName: string, input: unknown, cwd: string): Promise<string[]> {
  const o = (input && typeof input === "object" ? input : {}) as Record<string, unknown>;
  try {
    if (toolName === "Write" && typeof o["file_path"] === "string" && typeof o["content"] === "string") {
      const path = resolveFilePath(o["file_path"], cwd);
      const content = o["content"];
      let existing: string | null = null;
      try {
        if ((await stat(path)).isFile()) existing = decodeTextBuffer(await readFile(path)).text;
      } catch { /* does not exist: a new file */ }
      if (existing === null) {
        return [`creates a new file (${lineCount(content)} lines)`, ...snippet(content, "+", SNIPPET_LINES)].slice(0, APPROVAL_DETAIL_MAX_LINES);
      }
      const diff = changedLines(existing.replace(/\r\n/g, "\n"), content.replace(/\r\n/g, "\n"), APPROVAL_DETAIL_MAX_LINES - 1);
      const head = `OVERWRITES an existing file (${lineCount(existing)} lines -> ${lineCount(content)} lines; +${diff.added} -${diff.removed})`;
      return diff.lines.length === 0 ? [head, "  (the new content is identical)"] : [head, ...diff.lines];
    }
    if (toolName === "Edit" && typeof o["old_string"] === "string" && typeof o["new_string"] === "string") {
      const all = o["replace_all"] === true ? "replaces ALL occurrences of:" : "replaces:";
      return [
        all,
        ...snippet(o["old_string"], "-", SNIPPET_LINES),
        "with:",
        ...snippet(o["new_string"], "+", SNIPPET_LINES),
      ].slice(0, APPROVAL_DETAIL_MAX_LINES + 2);
    }
  } catch {
    return [];
  }
  return [];
}

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/project-context.ts -- the standing context a session starts with (#2374): the user's
// $EMBER_HOME/EMBER.md, the project's EMBER.md / AGENTS.md / CLAUDE.md from the repository root
// down to the cwd, and the project's memory index ($EMBER_HOME/memory/<project>/MEMORY.md).
//
// Memory uses the Claude Code layout: MEMORY.md is only an index (one line per fact) and every
// fact lives in its own file beside it. The model reads the index from its system prompt and
// writes memory with its ordinary file tools, so there is no memory-specific tool to maintain.
//
// Every file is capped, the total is capped, and what was loaded (or cut, or left out) is
// reported by `describeLoadedContext` -- nothing is silently dropped from the prompt.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { discoverInstructionFiles, findProjectRoot, readInstructionText } from "./instruction-files.ts";
import { projectKey } from "./project-key.ts";

export interface ContextLimits {
  /** Characters kept from any one instruction file. */
  fileChars: number;
  /** Characters across all instruction files; the files nearest the cwd are kept first. */
  totalChars: number;
  /** Lines kept from MEMORY.md. */
  memoryIndexLines: number;
  /** Characters kept from MEMORY.md. */
  memoryIndexChars: number;
}

export const DEFAULT_CONTEXT_LIMITS: ContextLimits = {
  fileChars: 8_000,
  totalChars: 24_000,
  memoryIndexLines: 200,
  memoryIndexChars: 6_000,
};

export interface LoadedContextFile {
  kind: "user" | "project" | "memory";
  /** Short name for lists: `EMBER.md`, `sub/AGENTS.md`, `MEMORY.md`. */
  label: string;
  path: string;
  /** Characters in the file. */
  chars: number;
  /** Characters placed in the prompt (0 when left out). */
  included: number;
  status: "full" | "truncated" | "omitted";
  /** Index lines that name a memory file (memory only). */
  entries?: number;
}

export interface ProjectContext {
  /** Text to append to the system prompt; "" when there is nothing to add. */
  prompt: string;
  files: LoadedContextFile[];
  memoryDir: string;
  memoryIndexPath: string;
}

export interface LoadContextOpts {
  cwd: string;
  /** Defaults to the memoized EMBER_HOME / ~/.ember directory. */
  home?: string;
  limits?: Partial<ContextLimits>;
  /**
   * Tell the model where memory lives and how to write it. Off for a seat that runs with no system
   * prompt at all (the reference Ember seat); the instruction files and the index still load.
   */
  memoryGuidance?: boolean;
}

export const MEMORY_INDEX_NAME = "MEMORY.md";

/** `$EMBER_HOME/memory/<project>/`, keyed by the repository root so subdirectories share it. */
export function memoryDirFor(cwd: string, home: string = getEmberConfigHomeDir()): string {
  return join(home, "memory", projectKey(findProjectRoot(cwd)));
}

function clipChars(text: string, max: number): { text: string; cut: number } {
  if (text.length <= max) return { text, cut: 0 };
  let end = text.lastIndexOf("\n", max);
  if (end < max / 2) end = max;
  return { text: text.slice(0, end).trimEnd(), cut: text.length - end };
}

function clipIndex(text: string, limits: ContextLimits): { text: string; cut: number } {
  const lines = text.split(/\r?\n/);
  let kept = lines.slice(0, limits.memoryIndexLines).join("\n");
  let cut = 0;
  if (lines.length > limits.memoryIndexLines) {
    cut += lines.slice(limits.memoryIndexLines).join("\n").length;
  }
  const byChars = clipChars(kept, limits.memoryIndexChars);
  kept = byChars.text;
  cut += byChars.cut;
  return { text: kept, cut };
}

function countEntries(index: string): number {
  return index.split(/\r?\n/).filter((l) => /^\s*[-*]\s*\[[^\]]+\]\([^)]+\)/.test(l)).length;
}

function readIndex(path: string): string {
  try {
    return readFileSync(path, "utf-8").replace(/^﻿/, "");
  } catch {
    return "";
  }
}

function memoryGuidanceText(dir: string): string {
  return [
    `Persistent memory for this project lives in ${dir}.`,
    `- Save a fact worth keeping across sessions as its own file there, <short-name>.md, starting with "---", "name: <short-name>", "description: <one line>", "type: user|feedback|project|reference", "---", then the fact.`,
    `- Then add one line to ${MEMORY_INDEX_NAME} in that directory: "- [Title](file.md) - one-line hook". ${MEMORY_INDEX_NAME} is only an index; never put the fact itself in it.`,
    "- Save when the operator asks you to remember something, states a lasting preference, or corrects you. Update or delete a memory that proves wrong. Do not save what the repository already records.",
  ].join("\n");
}

export function loadProjectContext(opts: LoadContextOpts): ProjectContext {
  const home = opts.home ?? getEmberConfigHomeDir();
  const limits: ContextLimits = { ...DEFAULT_CONTEXT_LIMITS, ...opts.limits };
  const root = findProjectRoot(opts.cwd);
  const memoryDir = memoryDirFor(opts.cwd, home);
  const memoryIndexPath = join(memoryDir, MEMORY_INDEX_NAME);

  // Instruction files in reading order (user, then root down to cwd); empty ones are skipped.
  type Candidate = { file: LoadedContextFile; text: string; cut: number };
  const candidates: Candidate[] = [];
  for (const f of discoverInstructionFiles({ cwd: opts.cwd, home })) {
    const raw = readInstructionText(f.path);
    if (raw === null || raw.trim() === "") continue;
    const clipped = clipChars(raw.trim(), limits.fileChars);
    const label = f.scope === "user" ? "EMBER.md (user)" : relative(root, f.path).replace(/\\/g, "/");
    candidates.push({
      file: {
        kind: f.scope,
        label,
        path: f.path,
        chars: raw.trim().length,
        included: clipped.text.length,
        status: clipped.cut > 0 ? "truncated" : "full",
      },
      text: clipped.text,
      cut: clipped.cut,
    });
  }

  // Spend the total budget from the end of the list: the file nearest the cwd matters most.
  let budget = limits.totalChars;
  for (let i = candidates.length - 1; i >= 0; i--) {
    const c = candidates[i]!;
    if (c.file.included <= budget) {
      budget -= c.file.included;
    } else {
      c.file.status = "omitted";
      c.file.included = 0;
    }
  }

  const sections: string[] = [];
  const kept = candidates.filter((c) => c.file.status !== "omitted");
  if (kept.length > 0) {
    sections.push(
      "# Standing instructions\nFollow these. When two files disagree, the later one applies.\n\n" +
        kept
          .map((c) => {
            const heading = c.file.kind === "user" ? "User instructions" : "Project instructions";
            const note = c.cut > 0 ? `\n[truncated: ${c.cut} more characters; read ${c.file.path} for the rest]` : "";
            return `## ${heading} (${c.file.path})\n${c.text}${note}`;
          })
          .join("\n\n"),
    );
  }

  const files: LoadedContextFile[] = candidates.map((c) => c.file);

  // Memory index.
  const indexRaw = existsSync(memoryIndexPath) ? readIndex(memoryIndexPath) : "";
  const hasIndex = indexRaw.trim() !== "";
  const memoryParts: string[] = [];
  if (opts.memoryGuidance !== false) memoryParts.push(memoryGuidanceText(memoryDir));
  if (hasIndex) {
    const clipped = clipIndex(indexRaw.trim(), limits);
    const note = clipped.cut > 0 ? `\n[truncated: ${clipped.cut} more characters; read ${memoryIndexPath} for the rest]` : "";
    memoryParts.push(`## ${MEMORY_INDEX_NAME}\n${clipped.text}${note}`);
    files.push({
      kind: "memory",
      label: MEMORY_INDEX_NAME,
      path: memoryIndexPath,
      chars: indexRaw.trim().length,
      included: clipped.text.length,
      status: clipped.cut > 0 ? "truncated" : "full",
      entries: countEntries(indexRaw),
    });
  } else if (opts.memoryGuidance !== false) {
    memoryParts.push(`## ${MEMORY_INDEX_NAME}\n(empty: nothing saved yet)`);
  }
  if (memoryParts.length > 0) sections.push(`# Memory\n${memoryParts.join("\n\n")}`);

  return { prompt: sections.join("\n\n"), files, memoryDir, memoryIndexPath };
}

/** `prompt` with the project context appended; unchanged when there is none. */
export function appendProjectContext(prompt: string, ctx: Pick<ProjectContext, "prompt">): string {
  if (ctx.prompt === "") return prompt;
  return prompt === "" ? ctx.prompt : `${prompt}\n\n${ctx.prompt}`;
}

/**
 * The system prompt an engine starts with: `base` plus the project context. Memory guidance is
 * only added to a prompt that exists; the reference seat runs with none and gets just the
 * files it has been given.
 */
export function systemPromptWithContext(
  base: string,
  opts: { cwd: string; home?: string; limits?: Partial<ContextLimits> },
): { prompt: string; context: ProjectContext } {
  const context = loadProjectContext({ ...opts, memoryGuidance: base.trim() !== "" });
  return { prompt: appendProjectContext(base, context), context };
}

function formatBytes(chars: number): string {
  return chars >= 1024 ? `${(chars / 1024).toFixed(1)} KB` : `${chars} chars`;
}

function statusSuffix(f: LoadedContextFile): string {
  if (f.status === "omitted") return " - LEFT OUT (over the total size cap)";
  if (f.status === "truncated") return ` - cut to ${formatBytes(f.included)}`;
  return "";
}

/** One line for the transcript at startup; null when nothing was loaded. */
export function contextNoticeLine(ctx: ProjectContext): string | null {
  if (ctx.files.length === 0) return null;
  const parts = ctx.files.map((f) => {
    const what = f.kind === "memory" ? `memory index (${f.entries ?? 0} entries)` : f.kind === "user" ? "EMBER.md (user)" : f.label;
    return f.status === "omitted" ? `${what} [left out: too large]` : f.status === "truncated" ? `${what} [cut]` : what;
  });
  return `Loaded ${parts.join(", ")}. /memory shows details.`;
}

/** Name and one-line description of each memory file beside the index. */
export function listMemoryFiles(memoryDir: string, max = 50): Array<{ name: string; description: string }> {
  let names: string[];
  try {
    names = readdirSync(memoryDir).filter((n) => n.toLowerCase().endsWith(".md") && n !== MEMORY_INDEX_NAME).sort();
  } catch {
    return [];
  }
  return names.slice(0, max).map((name) => {
    const m = /^description:\s*(.+)$/m.exec(readIndex(join(memoryDir, name)).slice(0, 2000));
    return { name, description: m ? m[1]!.trim() : "" };
  });
}

/** Everything `/memory` reports. */
export function describeLoadedContext(ctx: ProjectContext, limits: ContextLimits = DEFAULT_CONTEXT_LIMITS): string {
  const lines: string[] = [];
  if (ctx.files.length === 0) {
    lines.push("Nothing loaded: no EMBER.md, AGENTS.md or CLAUDE.md found, and no memory index yet.");
  } else {
    lines.push("Loaded into the system prompt:");
    for (const f of ctx.files) {
      const detail = f.kind === "memory" ? `${f.entries ?? 0} entries, ${formatBytes(f.chars)}` : formatBytes(f.chars);
      lines.push(`  ${f.kind.padEnd(7)} ${f.label}  (${detail}${statusSuffix(f)})  ${f.path}`);
    }
  }
  lines.push(`Memory directory: ${ctx.memoryDir}`);
  const mem = listMemoryFiles(ctx.memoryDir);
  if (mem.length === 0) {
    lines.push("Memory files: none yet. Ask the model to remember something and it will write one there.");
  } else {
    lines.push(`Memory files (${mem.length}):`);
    for (const m of mem) lines.push(`  ${m.name}${m.description ? ` - ${m.description}` : ""}`);
  }
  lines.push(
    `Size caps: ${limits.fileChars} characters per instruction file, ${limits.totalChars} in total (nearest the working directory kept first); ` +
      `memory index ${limits.memoryIndexLines} lines / ${limits.memoryIndexChars} characters.`,
  );
  return lines.join("\n");
}

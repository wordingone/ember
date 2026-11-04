// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compact-instructions.ts -- standing instructions appended to every compaction summary.
//
// Two sources, both optional:
//   - the `compactInstructions` field of settings.json (user / project / local, merged), and
//   - a "Compact Instructions" section in any EMBER.md / AGENTS.md / CLAUDE.md that the
//     instruction-file loader would read for this cwd.

import { loadSettingsFromDisk } from "../settings.ts";
import { discoverInstructionFiles, readInstructionText } from "./instruction-files.ts";

const SECTION_HEADING = /^(#{1,6})\s*(?:compact(?:ion)?|summary)\s+instructions\s*#*\s*$/i;

/** Body of the first "Compact Instructions" (or "Summary Instructions") section, or null. */
export function extractCompactSection(markdown: string): string | null {
  const lines = markdown.split(/\r?\n/);
  let start = -1;
  let level = 0;
  for (let i = 0; i < lines.length; i++) {
    const m = SECTION_HEADING.exec(lines[i]!.trim());
    if (m) {
      start = i + 1;
      level = m[1]!.length;
      break;
    }
  }
  if (start < 0) return null;
  const body: string[] = [];
  for (let i = start; i < lines.length; i++) {
    const h = /^(#{1,6})\s/.exec(lines[i]!);
    if (h && h[1]!.length <= level) break;
    body.push(lines[i]!);
  }
  const text = body.join("\n").trim();
  return text.length > 0 ? text : null;
}

export interface StandingCompactDeps {
  cwd: string;
  home?: string;
  loadSettings?: (cwd: string) => Promise<Record<string, unknown>>;
}

/** All standing compaction instructions for `cwd`, joined; undefined when there are none. */
export async function loadStandingCompactInstructions(deps: StandingCompactDeps): Promise<string | undefined> {
  const parts: string[] = [];
  try {
    const settings = await (deps.loadSettings ?? ((c) => loadSettingsFromDisk(c)))(deps.cwd);
    const field = settings["compactInstructions"];
    if (typeof field === "string" && field.trim() !== "") parts.push(field.trim());
  } catch {
    // unreadable settings never block a compaction
  }
  for (const file of discoverInstructionFiles({ cwd: deps.cwd, ...(deps.home !== undefined ? { home: deps.home } : {}) })) {
    const text = readInstructionText(file.path);
    const section = text === null ? null : extractCompactSection(text);
    if (section !== null) parts.push(section);
  }
  return parts.length > 0 ? parts.join("\n\n") : undefined;
}

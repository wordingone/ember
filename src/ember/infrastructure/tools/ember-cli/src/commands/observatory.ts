// commands/observatory.ts — /observatory slash command.
// Shows the loop's recent cognitive-mode timeline and current state.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import type { CognitiveMode } from "../cognitive-mode.ts";
import { modeGlyph } from "../cognitive-mode.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TIMELINE_DISPLAY = 20;
const HEADER = "=== Observatory: Cognitive Mode Timeline ===";

// ---------------------------------------------------------------------------
// Pure rendering (AC7-AC8)
// ---------------------------------------------------------------------------

/**
 * Returns a deterministic multi-line view of the cognitive-mode timeline.
 *   Line 1: header
 *   Line 2: current mode (last entry) — or "no activity yet" if empty
 *   Line 3: compact timeline of last ≤20 glyphs (omitted when history is empty)
 *
 * Takes `CognitiveMode[]` so it is trivially testable without a running loop.
 */
export function runObservatory(history: CognitiveMode[]): string {
  const lines: string[] = [HEADER];

  if (history.length === 0) {
    lines.push("no activity yet");
    return lines.join("\n");
  }

  const current = history[history.length - 1]!;
  const g = modeGlyph(current);
  lines.push(`current: ${g.glyph} ${current}`);

  const recent = history.slice(-MAX_TIMELINE_DISPLAY);
  const timeline = recent.map((m) => modeGlyph(m).glyph).join(" ");
  lines.push(`timeline: ${timeline}`);

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface ObservatoryDeps {
  getModeHistory: () => CognitiveMode[];
}

// ---------------------------------------------------------------------------
// Factory (AC6)
// ---------------------------------------------------------------------------

/** Creates the /observatory command with injected deps. */
export function createObservatoryCommand(deps: ObservatoryDeps): RegistryCommand {
  return {
    name: "observatory",
    aliases: ["obs"],
    description: "Show the loop cognitive-mode timeline and current state",
    isEnabled(): boolean {
      return true;
    },
    async execute(_args: string, _ctx: CommandContext) {
      const history = deps.getModeHistory();
      return { type: "message" as const, message: runObservatory(history) };
    },
  };
}

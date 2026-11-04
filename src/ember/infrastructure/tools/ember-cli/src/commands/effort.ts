// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/effort.ts -- /effort [off|low|medium|high|max] (issue #2370).
// No argument shows the current level; an argument sets and persists it.

import type { RegistryCommand } from "../types/command-types.ts";
import {
  DEFAULT_EFFORT_LEVEL,
  EFFORT_LEVELS,
  describeEffortLevel,
  getEffortLevel,
  parseEffortLevel,
  setEffortLevel,
} from "../services/effort-level.ts";

const USAGE = `Usage: /effort [${EFFORT_LEVELS.join("|")}]`;

export function createEffortCommand(): RegistryCommand {
  return {
    name: "effort",
    description: `Set how hard the model thinks (${EFFORT_LEVELS.join("/")})`,
    isEnabled: () => true,
    async execute(args: string) {
      const arg = args.trim();
      if (arg === "") {
        const level = getEffortLevel();
        const suffix = level === DEFAULT_EFFORT_LEVEL ? " (default)" : "";
        return {
          type: "message" as const,
          message: `Thinking effort: ${level}${suffix} -- ${describeEffortLevel(level)}\n${USAGE}`,
        };
      }
      const level = parseEffortLevel(arg);
      if (level === null) {
        return { type: "message" as const, message: `Unknown effort level "${arg}".\n${USAGE}`, exitCode: 1 };
      }
      try {
        await setEffortLevel(level);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        return {
          type: "message" as const,
          message: `Thinking effort set to ${level} for this session, but it could not be saved: ${detail}`,
        };
      }
      return {
        type: "message" as const,
        message: `Thinking effort set to ${level} -- ${describeEffortLevel(level)}. Applies from the next request.`,
      };
    },
  };
}

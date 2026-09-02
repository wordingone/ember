// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/watch.ts — /watch slash command.
// Toggles the live telemetry view on/off; uses the EXISTING startTelemetryWatch/getState API.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  startTelemetryWatch,
  getState,
  DEFAULT_CHANNEL_PATH,
  type TelemetryWatchHandle,
} from "../../../../../../../tools/ember-cli/src/services/telemetry-watch.ts";

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface WatchDeps {
  startTelemetryWatch?: typeof startTelemetryWatch;
  getState?: typeof getState;
  fileExists?: (path: string) => boolean;
}

// ---------------------------------------------------------------------------
// Factory (AC1)
// ---------------------------------------------------------------------------

/** Creates the /watch command with injected deps. */
export function createWatchCommand(deps: WatchDeps = {}): RegistryCommand {
  const startWatch = deps.startTelemetryWatch ?? startTelemetryWatch;
  const getWatchState = deps.getState ?? getState;
  const fileExists = deps.fileExists ?? (() => true); // Default: assume file exists

  // Per-instance state (not module-level) for proper isolation in tests
  let watchHandle: TelemetryWatchHandle | null = null;
  let isWatching = false;
  let currentPath = "";

  return {
    name: "watch",
    description: "Toggle the live telemetry view on/off",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      const path = args.trim() || DEFAULT_CHANNEL_PATH;

      // AC3: check if path exists
      if (!fileExists(path)) {
        return {
          type: "message" as const,
          message: `channel not found: ${path}`,
        };
      }

      // AC2: idempotent toggle on/off
      // If already watching the same path, stay on (idempotent)
      if (isWatching && currentPath === path) {
        return {
          type: "message" as const,
          message: `watching ${path}`,
        };
      }

      // If watching a different path, switch to new path
      if (isWatching && currentPath !== path) {
        if (watchHandle) {
          watchHandle.stop();
        }
        watchHandle = startWatch({ channelPath: path });
        currentPath = path;
        return {
          type: "message" as const,
          message: `watching ${path}`,
        };
      }

      // If not watching, toggle on
      if (!isWatching) {
        watchHandle = startWatch({ channelPath: path });
        isWatching = true;
        currentPath = path;
        return {
          type: "message" as const,
          message: `watching ${path}`,
        };
      }

      // If watching and called without args (toggle off)
      if (watchHandle) {
        watchHandle.stop();
      }
      watchHandle = null;
      isWatching = false;
      currentPath = "";
      return {
        type: "message" as const,
        message: "watch off",
      };
    },
  };
}

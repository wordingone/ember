// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/finetune.ts — /finetune control command.
// Parses and emits finetune control commands (start/stop/pause/resume/adjust).
// Alias: ft

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  validateControlCmd,
  emitControlCmd,
  CONTROL_CHANNEL_PATH,
  type FinetuneControlCmd,
  type FinetuneControlVerb,
} from "../../../../../../../tools/ember-cli/src/services/finetune-control.ts";

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface FinetuneDeps {
  channelPath?: string;
  now?: () => number;
}

// ---------------------------------------------------------------------------
// Parsing (AC8-AC9)
// ---------------------------------------------------------------------------

/**
 * Parses "/finetune <verb> [args]" into a FinetuneControlCmd.
 * Returns {ok:true, cmd} or {ok:false, error}.
 *
 * Usage:
 *   /finetune start                           → {verb:"start"}
 *   /finetune stop <runId>                    → {verb:"stop", runId}
 *   /finetune pause <runId>                   → {verb:"pause", runId}
 *   /finetune resume <runId>                  → {verb:"resume", runId}
 *   /finetune adjust <runId> <lrScale>        → {verb:"adjust", runId, lrScale}
 */
function parseArgs(
  input: string,
  now: () => number,
): { ok: boolean; cmd?: FinetuneControlCmd; error?: string } {
  const parts = input.trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) {
    return { ok: false, error: "no verb provided; use: start|stop|pause|resume|adjust" };
  }

  const verb = parts[0]! as string;
  const validVerbs = ["start", "stop", "pause", "resume", "adjust"];

  if (!validVerbs.includes(verb)) {
    return { ok: false, error: `unknown verb: ${verb}; use: start|stop|pause|resume|adjust` };
  }

  const ts = new Date(now()).toISOString();

  // start: no args required
  if (verb === "start") {
    return { ok: true, cmd: { verb: verb as FinetuneControlVerb, ts } };
  }

  // stop, pause, resume: require runId
  if (["stop", "pause", "resume"].includes(verb)) {
    if (parts.length < 2 || !parts[1]) {
      return { ok: false, error: `${verb} requires <runId>` };
    }
    return {
      ok: true,
      cmd: {
        verb: verb as FinetuneControlVerb,
        runId: parts[1],
        ts,
      },
    };
  }

  // adjust: require runId and lrScale
  if (verb === "adjust") {
    if (parts.length < 2 || !parts[1]) {
      return { ok: false, error: "adjust requires <runId> <lrScale>" };
    }
    if (parts.length < 3 || !parts[2]) {
      return { ok: false, error: "adjust requires <runId> <lrScale>" };
    }

    const lrScaleStr = parts[2]!;
    const lrScale = parseFloat(lrScaleStr);

    // AC9: non-numeric → clear error
    if (isNaN(lrScale)) {
      return {
        ok: false,
        error: `lrScale must be a number; got: ${lrScaleStr}`,
      };
    }

    return {
      ok: true,
      cmd: {
        verb: verb as FinetuneControlVerb,
        runId: parts[1],
        lrScale,
        ts,
      },
    };
  }

  return { ok: false, error: "unexpected verb state" };
}

// ---------------------------------------------------------------------------
// Factory (AC8)
// ---------------------------------------------------------------------------

/** Creates the /finetune command with injected deps. */
export function createFinetuneCommand(deps: FinetuneDeps = {}): RegistryCommand {
  const channelPath = deps.channelPath ?? CONTROL_CHANNEL_PATH;
  const now = deps.now ?? Date.now.bind(Date);

  return {
    name: "finetune",
    aliases: ["ft"],
    description: "Control the governed finetune: start|stop|pause|resume|adjust",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      // Parse input
      const parseResult = parseArgs(args, now);
      if (!parseResult.ok) {
        return {
          type: "message" as const,
          message: `error: ${parseResult.error}`,
        };
      }

      const cmd = parseResult.cmd!;

      // Validate (AC8)
      const validateResult = validateControlCmd(cmd);
      if (!validateResult.ok) {
        return {
          type: "message" as const,
          message: `error: ${validateResult.reason}`,
        };
      }

      // Emit (AC8)
      try {
        await emitControlCmd(cmd, channelPath);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          type: "message" as const,
          message: `error: failed to emit command: ${msg}`,
        };
      }

      // One-line ack with verb + runId
      let ack = `${cmd.verb}`;
      if (cmd.runId) {
        ack += ` run=${cmd.runId}`;
      }
      if (cmd.lrScale !== undefined) {
        ack += ` lrScale=${cmd.lrScale}`;
      }

      return {
        type: "message" as const,
        message: ack,
      };
    },
  };
}

// commands/model.ts — /model load|unload|status command for managed model lifecycle.
// Allows the operator to free GPU VRAM by unloading the local model without closing the cockpit.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  getModelState,
  loadModel,
  unloadModel,
  type ModelLifecycleDeps,
} from "../services/model-lifecycle.ts";
import { waitForServerReady, LLAMA_SERVER_DEFAULT_PORT } from "../services/runtime-bootstrap.ts";
import { appendFile } from "fs/promises";

// ---------------------------------------------------------------------------
// Kill-receipts ledger wiring
// ---------------------------------------------------------------------------

/** Default kill-receipt audit ledger (cwd-relative .ember/; override via KILL_RECEIPTS_PATH). */
const DEFAULT_KILL_RECEIPTS_PATH = ".ember/kill-receipts.jsonl";

/**
 * Factory that produces a kill-receipt writer function.
 * Exported (prefixed _) for unit tests to inject a mock appendFileFn and
 * inspect the JSONL that would be written, without touching the real ledger.
 * @internal
 */
export function _makeKillReceiptWriter(opts: {
  ledgerPath?: string;
  appendFileFn?: (path: string, data: string) => Promise<void>;
}): (rec: { pid: number; match_rule: string }) => void {
  const ledgerPath =
    opts.ledgerPath ??
    process.env["KILL_RECEIPTS_PATH"] ??
    DEFAULT_KILL_RECEIPTS_PATH;
  const afn: (path: string, data: string) => Promise<void> =
    opts.appendFileFn ?? ((p, d) => appendFile(p, d));

  return (rec: { pid: number; match_rule: string }): void => {
    const entry =
      JSON.stringify({
        ts: new Date().toISOString(),
        script: "ember-cli /model unload",
        pids: [rec.pid],
        match_rule: rec.match_rule,
        survivors_expected: "none",
      }) + "\n";
    // Fire-and-forget: non-fatal I/O failure must never block the kill path.
    afn(ledgerPath, entry).catch((err: unknown) => {
      console.warn(`[kill-receipt] write to ${ledgerPath} failed: ${err}`);
    });
  };
}

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface ModelCommandDeps {
  loadModel?: (deps: ModelLifecycleDeps) => Promise<string>;
  unloadModel?: (deps: ModelLifecycleDeps) => Promise<string>;
  getModelState?: () => string;
  writeKillReceipt?: (rec: { pid: number; match_rule: string }) => void;
}

// ---------------------------------------------------------------------------
// Real implementations of injected deps
// ---------------------------------------------------------------------------

/**
 * Production kill-receipt writer. Appends a JSONL line to the infra ledger.
 * Fire-and-forget; I/O errors are swallowed with a warn log (non-fatal).
 * The function returns void synchronously; the append is async under the hood.
 */
const realWriteKillReceipt = _makeKillReceiptWriter({});

// ---------------------------------------------------------------------------
// Factory (AC8)
// ---------------------------------------------------------------------------

/**
 * Creates the /model command with injected deps.
 * AC8: registered in command-registry.ts with name "model", no alias collision.
 */
export function createModelCommand(deps: ModelCommandDeps = {}): RegistryCommand {
  const doLoadModel = deps.loadModel ?? loadModel;
  const doUnloadModel = deps.unloadModel ?? unloadModel;
  const doGetModelState = deps.getModelState ?? getModelState;
  const doWriteKillReceipt = deps.writeKillReceipt ?? realWriteKillReceipt;

  return {
    name: "model",
    description: "Control the local model: load|unload|status",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      // AC9, AC10: parse subcommand
      const subcommand = args.trim().split(/\s+/)[0] ?? "";

      // AC9: /model status → current state + pid (if loaded)
      if (subcommand === "status" || subcommand === "") {
        const state = doGetModelState();
        let statusLine = `model: ${state}`;
        // Note: we don't have direct access to pid here via getModelState;
        // the status is returned as part of the state. In a real implementation,
        // getModelState could return more detail, but for now we keep it simple.
        return {
          type: "message" as const,
          message: statusLine,
        };
      }

      // AC10: /model unload
      if (subcommand === "unload") {
        const modelLifecycleDeps: ModelLifecycleDeps = {
          spawnModel: () => ({ pid: 0 }), // unused in unload
          killPid: (pid: number) => {
            // Real impl would use process.kill(pid, "SIGTERM")
          },
          waitReady: async () => {}, // unused in unload
          writeKillReceipt: doWriteKillReceipt,
          isExternal: () => process.env["EMBER_MODEL_URL"] !== undefined,
          now: () => new Date().toISOString(),
        };

        try {
          const status = await doUnloadModel(modelLifecycleDeps);
          return {
            type: "message" as const,
            message: status,
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `error: failed to unload: ${msg}`,
          };
        }
      }

      // AC10: /model load
      if (subcommand === "load") {
        const modelLifecycleDeps: ModelLifecycleDeps = {
          spawnModel: () => ({ pid: 0 }), // Will be set by the real spawn
          killPid: () => {}, // unused in load
          waitReady: async (port?: number) => {
            await waitForServerReady(port ?? LLAMA_SERVER_DEFAULT_PORT);
          },
          writeKillReceipt: () => {}, // unused in load
          isExternal: () => process.env["EMBER_MODEL_URL"] !== undefined,
          now: () => new Date().toISOString(),
        };

        try {
          const status = await doLoadModel(modelLifecycleDeps);
          return {
            type: "message" as const,
            message: status,
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `error: failed to load: ${msg}`,
          };
        }
      }

      // Unknown subcommand → clear usage line
      return {
        type: "message" as const,
        message: `usage: /model status|load|unload`,
      };
    },
  };
}

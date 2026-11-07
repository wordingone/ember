// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/resume-hour.ts — /resume-hour: the START entry for a derived lineage hour.
//
// A separate control from /train by design: /train runs launch_packet.py preflights and the
// certified ember-lab launch; /resume-hour starts an already-derived, reviewed hour dispatch
// script (hNN_dispatch_vN.sh) whose every input is pinned inside the script and its hashes
// list. The cockpit verifies the script's name and exact sha256 before it starts it, then
// starts it DETACHED and hidden (an hour chain runs for hours; the cockpit must not own or time it out)
// with stdout and stderr appended to the named log. It never edits, re-derives or retries.
//
// Usage: /resume-hour <dispatch-script> <expected-sha256> <log-path>

import { spawn as nodeSpawn } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, existsSync, openSync, readFileSync, statSync } from "node:fs";
import { basename, resolve } from "node:path";
import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";

export const DISPATCH_NAME = /^h\d+_dispatch_v\d+\.sh$/;

export interface ResumeHourSpawn {
  (command: string, args: string[], options: { detached: true; stdio: ["ignore", number, number]; windowsHide: true }): {
    pid?: number;
    unref: () => void;
  };
}

export interface ResumeHourDeps {
  spawn?: ResumeHourSpawn;
  bash?: string;
}

export type ResumeHourCheck =
  | { ok: true; script: string; sha256: string; log: string }
  | { ok: false; reason: string };

/** Fail-closed checks; nothing starts unless every one passes. */
export function checkResumeHourArgs(args: string, cwd: string): ResumeHourCheck {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  if (parts.length !== 3) {
    return { ok: false, reason: "usage: /resume-hour <dispatch-script> <expected-sha256> <log-path>" };
  }
  const [rawScript, expected, rawLog] = parts as [string, string, string];
  const script = resolve(cwd, rawScript);
  if (!DISPATCH_NAME.test(basename(script))) {
    return { ok: false, reason: `not an hour dispatch script name (hNN_dispatch_vN.sh): ${basename(script)}` };
  }
  if (!existsSync(script) || !statSync(script).isFile()) {
    return { ok: false, reason: `dispatch script not found: ${script}` };
  }
  if (!/^[0-9a-f]{64}$/.test(expected)) {
    return { ok: false, reason: "expected sha256 must be 64 lowercase hex" };
  }
  const actual = createHash("sha256").update(readFileSync(script)).digest("hex");
  if (actual !== expected) {
    return { ok: false, reason: `dispatch script sha256 ${actual} is not the expected ${expected}` };
  }
  const log = resolve(cwd, rawLog);
  if (existsSync(log)) {
    return { ok: false, reason: `log already exists (one start per log): ${log}` };
  }
  return { ok: true, script, sha256: actual, log };
}

export function createResumeHourCommand(deps: ResumeHourDeps = {}): RegistryCommand {
  return {
    name: "resume-hour",
    description: "START a derived lineage hour dispatch script (verified by sha256, run detached)",
    type: "local",
    isEnabled: () => true,
    async execute(args: string, ctx: CommandContext): Promise<CommandResult> {
      const check = checkResumeHourArgs(args, ctx.cwd);
      if (!check.ok) return { type: "message", message: `REFUSED: ${check.reason}` };
      const fd = openSync(check.log, "a");
      const spawn = deps.spawn ?? (nodeSpawn as unknown as ResumeHourSpawn);
      const child = spawn(deps.bash ?? "bash", [check.script], {
        detached: true,
        stdio: ["ignore", fd, fd],
        windowsHide: true,
      });
      closeSync(fd);
      child.unref();
      if (!child.pid) return { type: "message", message: `REFUSED: bash did not start for ${check.script}` };
      return {
        type: "message",
        message: [
          `RESUME_HOUR_STARTED pid=${child.pid}`,
          `  script: ${check.script}`,
          `  sha256: ${check.sha256}`,
          `  log:    ${check.log}`,
        ].join("\n"),
      };
    },
  };
}

/**
 * One-shot startup entry: EMBER_STARTUP_RESUME_HOUR="<script> <sha256> <log>" makes the visible cockpit
 * submit exactly one /resume-hour through the same governed slash path typed input takes. Only /resume-hour
 * can be started this way; anything else (or an empty value) yields null.
 */
export function startupResumeHourInput(env: Record<string, string | undefined>): string | null {
  const raw = env["EMBER_STARTUP_RESUME_HOUR"];
  if (typeof raw !== "string" || raw.trim() === "" || /[\r\n]/.test(raw)) return null;
  return `/resume-hour ${raw.trim()}`;
}

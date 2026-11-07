// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, it, expect } from "bun:test";
import { createHash } from "node:crypto";
import { mkdtempSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { REDIRECT, checkResumeHourArgs, hourEnv, createResumeHourCommand, resolveHourBash, startupResumeHourInput } from "./resume-hour.ts";
import type { CommandContext } from "../types/command-types.ts";

function world() {
  const dir = mkdtempSync(join(tmpdir(), "resume-hour-"));
  const script = join(dir, "h39_dispatch_v1.sh");
  writeFileSync(script, "echo hour\n");
  const sha = createHash("sha256").update("echo hour\n").digest("hex");
  return { dir, script, sha, log: join(dir, "start.log") };
}

const ctx = (cwd: string) => ({ cwd } as unknown as CommandContext);

describe("/resume-hour", () => {
  it("refuses a script that is not an hour dispatch", () => {
    const w = world();
    const other = join(w.dir, "train.sh");
    writeFileSync(other, "x");
    const r = checkResumeHourArgs(`${other} ${w.sha} ${w.log}`, w.dir);
    expect(r.ok).toBe(false);
  });

  it("refuses a sha256 mismatch and never spawns", async () => {
    const w = world();
    let spawned = 0;
    const cmd = createResumeHourCommand({ spawn: () => { spawned++; return { pid: 1, unref() {} }; } });
    const out = await cmd.execute(`${w.script} ${"0".repeat(64)} ${w.log}`, ctx(w.dir));
    expect(String((out as { message: string }).message)).toContain("REFUSED");
    expect(spawned).toBe(0);
  });

  it("refuses an existing log (one start per log)", () => {
    const w = world();
    writeFileSync(w.log, "");
    expect(checkResumeHourArgs(`${w.script} ${w.sha} ${w.log}`, w.dir).ok).toBe(false);
  });

  it("refuses wrong arity", () => {
    const w = world();
    expect(checkResumeHourArgs(`${w.script} ${w.sha}`, w.dir).ok).toBe(false);
  });

  it("starts bash on the verified script, detached, logging to the named file", async () => {
    const w = world();
    const calls: unknown[][] = [];
    let unrefs = 0;
    const cmd = createResumeHourCommand({
      bash: "bash-test",
      spawn: (c, a, o) => { calls.push([c, a, o]); return { pid: 4242, unref() { unrefs++; } }; },
    });
    const out = await cmd.execute(`${w.script} ${w.sha} ${w.log}`, ctx(w.dir));
    expect(String((out as { message: string }).message)).toContain("RESUME_HOUR_STARTED pid=4242");
    expect(calls.length).toBe(1);
    const [c, a, o] = calls[0] as [string, string[], { detached: boolean }];
    expect(c).toBe("bash-test");
    expect(a).toEqual(["-c", REDIRECT, w.script, w.log]);
    expect(o.detached).toBe(true);
    expect(unrefs).toBe(1);
    expect(existsSync(w.log)).toBe(true);
  });

  it("startup entry yields exactly one /resume-hour, and nothing for other or unsafe values", () => {
    expect(startupResumeHourInput({ EMBER_STARTUP_RESUME_HOUR: " a b c " })).toBe("/resume-hour a b c");
    expect(startupResumeHourInput({})).toBe(null);
    expect(startupResumeHourInput({ EMBER_STARTUP_RESUME_HOUR: "  " })).toBe(null);
    expect(startupResumeHourInput({ EMBER_STARTUP_RESUME_HOUR: "a b c\n/train" })).toBe(null);
  });

  it("never resolves the System32 bash shim", () => {
    expect(resolveHourBash({ EMBER_RESUME_HOUR_BASH: "C:\\WINDOWS\\system32\\bash.exe" }, "win32")).toBe(null);
    expect(resolveHourBash({}, "linux")).toBe("/bin/bash");
    expect(resolveHourBash({ EMBER_RESUME_HOUR_BASH: "/usr/bin/bash" }, "linux")).toBe("/usr/bin/bash");
  });

  it("drops every EMBER_* variable from the hour's environment", () => {
    const e = hourEnv({ EMBER_API_KEY: "k", ember_model_seat: "s", EMBER_STARTUP_RESUME_HOUR: "x", X5_RECEIPT: "r", PATH: "p" });
    expect(e).toEqual({ X5_RECEIPT: "r", PATH: "p" });
  });
});

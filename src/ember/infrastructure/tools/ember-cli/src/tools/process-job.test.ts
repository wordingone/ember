// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/process-job.test.ts -- #2380 S27/S28: a process a tool call leaves running ends with the
// session, not with the window.
//
// Each case runs a CHILD bun process that plays "ember": it runs a tool call that starts a
// background python (printing its pid), then exits. The test then asks the OS whether that python
// is still alive. The control runs the same child with the job disabled and proves the python
// outlives its parent, so the "gone" assertion cannot pass by accident. Every background python
// sleeps for a bounded time (12 s) and ends on its own; nothing here kills anything.

import { describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { findGitBash } from "./bash-tool.ts";

const isWin = process.platform === "win32";
const here = import.meta.dir;
const toolUrl = (file: string): string => pathToFileURL(join(here, file)).href;

function alive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch { return false; }
}
async function waitUntil(predicate: () => boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 100));
  }
  return predicate();
}

/** Runs `script` in a fresh bun process (the stand-in for an ember session) and returns the pid
 *  the script printed as its last stdout line. The child has exited when this returns. */
function runSession(script: string, env: Record<string, string> = {}): { pid: number; stdout: string } {
  const dir = mkdtempSync(join(tmpdir(), "ember-job-test-"));
  try {
    const file = join(dir, "session.ts");
    writeFileSync(file, script);
    const run = spawnSync(process.execPath, [file], {
      env: { ...process.env, ...env },
      encoding: "utf-8",
      timeout: 60_000,
      windowsHide: true,
    });
    const lines = String(run.stdout).trim().split(/\r?\n/);
    const last = lines[lines.length - 1] ?? "";
    const parsed = JSON.parse(last) as { pid: number };
    return { pid: parsed.pid, stdout: String(run.stdout) };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const BACKGROUND_PY = "import os,time; print(os.getpid(), flush=True); time.sleep(12)";

function bashSession(): string {
  return `
    import { bashTool } from ${JSON.stringify(toolUrl("bash-tool.ts"))};
    const ctx: any = { cwd: process.cwd(), abortController: new AbortController(), getAppState: () => ({}) };
    const out: any = (await bashTool.call({ command: ${JSON.stringify(`python -c "${BACKGROUND_PY}" &`)} } as any, ctx, async () => true, undefined as any)).data;
    const pid = Number(String(out.stdout).trim().split(/\\s+/)[0]);
    console.log(JSON.stringify({ pid }));
    setTimeout(() => process.exit(0), 300);
  `;
}

function powershellSession(): string {
  // Start-Process joins -ArgumentList items with spaces and no quoting, so the script is quoted by hand.
  const command = `$p = Start-Process python -ArgumentList '-c','"${BACKGROUND_PY}"' -WindowStyle Hidden -PassThru; $p.Id`;
  return `
    import { powerShellTool } from ${JSON.stringify(toolUrl("powershell-tool.ts"))};
    const ctx: any = { cwd: process.cwd(), abortController: new AbortController(), getAppState: () => ({}) };
    const out: any = (await powerShellTool.call({ command: ${JSON.stringify(command)} } as any, ctx, async () => true, undefined as any)).data;
    const pid = Number(String(out.stdout).trim().split(/\\s+/)[0]);
    console.log(JSON.stringify({ pid }));
    setTimeout(() => process.exit(0), 300);
  `;
}

describe.if(isWin)("a background process ends with the session (#2380 S27/S28)", () => {
  test.if(findGitBash() !== null)("control: without the job object a Bash background process outlives its session", async () => {
    const { pid } = runSession(bashSession(), { EMBER_DISABLE_PROCESS_JOB: "1" });
    expect(pid).toBeGreaterThan(0);
    // The session is gone; the python is still there. (It ends by itself after 12 s.)
    expect(alive(pid)).toBe(true);
  }, 60_000);

  test.if(findGitBash() !== null)("Bash: the background python is gone once the session exits", async () => {
    const { pid } = runSession(bashSession());
    expect(pid).toBeGreaterThan(0);
    expect(await waitUntil(() => !alive(pid), 5_000)).toBe(true);
  }, 60_000);

  test("PowerShell Start-Process -WindowStyle Hidden: gone once the session exits", async () => {
    const { pid } = runSession(powershellSession());
    expect(pid).toBeGreaterThan(0);
    expect(await waitUntil(() => !alive(pid), 5_000)).toBe(true);
  }, 60_000);

  test("PowerShell control: the same Start-Process outlives its session when the job is disabled", async () => {
    const { pid } = runSession(powershellSession(), { EMBER_DISABLE_PROCESS_JOB: "1" });
    expect(pid).toBeGreaterThan(0);
    expect(alive(pid)).toBe(true);
  }, 60_000);
});

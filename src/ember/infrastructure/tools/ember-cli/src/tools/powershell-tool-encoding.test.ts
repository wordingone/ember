// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { tmpdir } from "os";
import { powerShellTool } from "./powershell-tool.ts";

const isWin = process.platform === "win32";
const ctx = () => ({ cwd: tmpdir(), abortController: new AbortController(), getAppState: () => ({}) }) as any;
async function run(command: string, timeout?: number): Promise<any> {
  return (await powerShellTool.call({ command, ...(timeout ? { timeout } : {}) } as any, ctx(), async () => true, undefined as any)).data;
}

test.if(isWin)("quotes and unicode arrive byte-exact", async () => {
  const out = await run(`Write-Output "a ""quoted"" 'mix' cafe"`);
  expect(out.stdout.trim()).toBe(`a "quoted" 'mix' cafe`);
}, 30000);

test.if(isWin)("a timeout says so", async () => {
  const out = await run("Start-Sleep -Seconds 20", 2000);
  expect(out.returnCodeInterpretation).toContain("timed out");
}, 30000);

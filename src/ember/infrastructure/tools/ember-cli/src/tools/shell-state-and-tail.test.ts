// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/shell-state-and-tail.test.ts -- #2380 S12 (a lost cd / variable says so) and S24 (a running
// shell command reports the last line it printed).
import { afterEach, describe, expect, test } from "bun:test";
import { tmpdir } from "node:os";
import { bashTool, findGitBash } from "./bash-tool.ts";
import { powerShellTool } from "./powershell-tool.ts";
import { onToolProgress, OutputTail, type ToolProgressEvent } from "../core/tool-progress.ts";
import { onlyChangesShellState, shellStateNote } from "./shell-state-note.ts";

const isWin = process.platform === "win32";
const off: Array<() => void> = [];
afterEach(() => { for (const f of off.splice(0)) f(); });

function ctx(toolUseId?: string) {
  return { cwd: tmpdir(), abortController: new AbortController(), getAppState: () => ({}), ...(toolUseId ? { toolUseId } : {}) } as any;
}
async function bash(command: string, toolUseId?: string): Promise<any> {
  return (await bashTool.call({ command } as any, ctx(toolUseId), async () => true, undefined as any)).data;
}
async function ps(command: string): Promise<any> {
  return (await powerShellTool.call({ command } as any, ctx(), async () => true, undefined as any)).data;
}

describe("S12: a call whose only effect is lost shell state says so", () => {
  test("bash: cd / export / assignment alone are state-only; used in the same call they are not", () => {
    for (const lost of ["cd sub", "cd /d C:\\x", "export FOO=1", "FOO=bar", "cd a; export B=2", "cd a\nexport B=2", "pushd x"]) {
      expect(onlyChangesShellState(lost, "bash")).toBe(true);
    }
    for (const used of ["cd sub && make", "cd sub; ls", "FOO=1 ./run.sh", "export FOO=1 && echo $FOO", "echo hi", "X=1; echo $X", ""]) {
      expect(onlyChangesShellState(used, "bash")).toBe(false);
    }
  });

  test("cmd and PowerShell flavours", () => {
    expect(onlyChangesShellState("set FOO=1", "cmd")).toBe(true);
    expect(onlyChangesShellState("cd /d C:\\work", "cmd")).toBe(true);
    expect(onlyChangesShellState("set FOO=1 && echo %FOO%", "cmd")).toBe(false);
    expect(onlyChangesShellState("Set-Location C:\\work", "powershell")).toBe(true);
    expect(onlyChangesShellState("$env:FOO = 'x'", "powershell")).toBe(true);
    expect(onlyChangesShellState("$x = 5; $x", "powershell")).toBe(false);
    expect(onlyChangesShellState("cd sub; ls", "powershell")).toBe(false);
  });

  test("the note names where the next call starts and shows the chained form", () => {
    const note = shellStateNote("cd sub", "bash", "C:\\proj");
    expect(note).toContain("do NOT carry over");
    expect(note).toContain("C:\\proj");
    expect(note).toContain("cd sub && make");
    expect(shellStateNote("echo hi", "bash", "C:\\proj")).toBeNull();
  });

  test.if(isWin)("Bash tool: `cd` alone gets the note in its result text; `cd x && pwd` does not", async () => {
    const alone = await bash("cd .");
    expect(alone.returnCodeInterpretation).toContain("do NOT carry over");
    const chained = await bash("cd . && echo fine");
    expect(chained.returnCodeInterpretation).not.toContain("carry over");
    // and the note reaches the model: it is part of the tool_result text
    const block = bashTool.mapToolResultToToolResultBlockParam(alone, "t");
    expect(String(block.content)).toContain("do NOT carry over");
  }, 30_000);

  test.if(isWin)("PowerShell tool: a lone Set-Location gets the note", async () => {
    const out = await ps("Set-Location .");
    expect(out.returnCodeInterpretation).toContain("do NOT carry over");
    const used = await ps("Set-Location .; Get-Location | Out-Null");
    expect(used.returnCodeInterpretation).not.toContain("carry over");
  }, 60_000);
});

describe("S24: output tail", () => {
  test("OutputTail keeps the last non-empty line, handles CR progress rewrites and ANSI", () => {
    const tail = new OutputTail();
    tail.push("alpha\nbeta\n\n");
    expect(tail.lastLine()).toBe("beta");
    tail.push("downloading 10%\rdownloading 55%\r");
    expect(tail.lastLine()).toBe("downloading 55%");
    tail.push("\x1b[32mgreen done\x1b[0m\n");
    expect(tail.lastLine()).toBe("green done");
    const small = new OutputTail(16);
    small.push("x".repeat(100) + "\nlast line here");
    expect(small.lastLine()).toBe("last line here");
  });

  test.if(isWin && findGitBash() !== null)("a running Bash command reports its last line before it finishes", async () => {
    const events: ToolProgressEvent[] = [];
    off.push(onToolProgress((e) => events.push(e)));
    const seenWhileRunning: string[] = [];
    const run = bash("echo first-line; sleep 1.2; echo second-line; sleep 1.2; echo third-line", "call-tail-1");
    // sample what the screen would see while the command is still running
    const sampler = setInterval(() => {
      const last = [...events].reverse().find((e) => e.kind === "output" && e.toolUseId === "call-tail-1") as { tail: string } | undefined;
      if (last && seenWhileRunning[seenWhileRunning.length - 1] !== last.tail) seenWhileRunning.push(last.tail);
    }, 100);
    const out = await run;
    clearInterval(sampler);
    expect(out.stdout).toContain("third-line");
    expect(seenWhileRunning).toContain("first-line");
    expect(seenWhileRunning).toContain("second-line");
    // events are all for this call, and the burst's final line is not lost
    const outputs = events.filter((e) => e.kind === "output") as Array<{ toolUseId: string; tail: string }>;
    expect(outputs.every((e) => e.toolUseId === "call-tail-1")).toBe(true);
    expect(outputs[outputs.length - 1]!.tail).toBe("third-line");
  }, 30_000);

  test.if(isWin && findGitBash() !== null)("without a tool-use id (run outside the loop) nothing is reported", async () => {
    const events: ToolProgressEvent[] = [];
    off.push(onToolProgress((e) => events.push(e)));
    await bash("echo quiet");
    expect(events).toEqual([]);
  }, 30_000);
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Regressions from the shell blind test (S03-S05 quoting, S08 multi-line, S15 timeout wording,
// S17 the timed-out child kept running).
import { test, expect } from "bun:test";
import { tmpdir } from "os";
import { bashTool, findGitBash } from "./bash-tool.ts";

const isWin = process.platform === "win32";

function ctx() {
  return {
    cwd: tmpdir(),
    abortController: new AbortController(),
    getAppState: () => ({}),
  } as any;
}
async function run(command: string, timeout?: number): Promise<any> {
  return (await bashTool.call({ command, ...(timeout ? { timeout } : {}) } as any, ctx(), async () => true, undefined as any)).data;
}

test.if(isWin)("double quotes group words the way the shell defines", async () => {
  const out = await run('echo "hello world"');
  // bash strips the quotes; cmd.exe (no Git Bash installed) prints them.
  expect(out.stdout.trim()).toBe(findGitBash() ? "hello world" : '"hello world"');
});

// Blind test S05-S07: the Bash tool ran cmd.exe, so mkdir -p made a "-p" folder and $VAR stayed literal.
test.if(isWin && findGitBash() !== null)("bash syntax works when Git Bash is installed", async () => {
  const out = await run('X=abc; mkdir -p "$TMP/ember-bt-$X/a b" && echo "v=$X" && test -d "$TMP/ember-bt-$X/a b" && echo dir-ok; rm -rf "$TMP/ember-bt-$X"');
  expect(out.stdout).toContain("v=abc");
  expect(out.stdout).toContain("dir-ok");
});

test.if(isWin)("a quoted path and quoted python args", async () => {
  const out = await run(`python -c "import sys; print(sys.argv[1:])" x "y z"`);
  expect(out.stdout.trim()).toBe("['x', 'y z']");
});

test.if(isWin)("every line of a multi-line command runs", async () => {
  const out = await run("echo LINE-ONE\necho LINE-TWO");
  expect(out.stdout).toContain("LINE-ONE");
  expect(out.stdout).toContain("LINE-TWO");
});

test.if(isWin)("a timeout says so", async () => {
  const out = await run("ping -n 30 127.0.0.1", 1500);
  expect(out.returnCodeInterpretation).toContain("timed out");
}, 20000);

// Blind test S27: a command that leaves a background process running stalled until the timeout.
test.if(isWin && findGitBash() !== null)("a background process does not hold the tool until its timeout", async () => {
  const t0 = Date.now();
  const out = await run("sleep 8 & echo started", 20_000);
  expect(out.stdout).toContain("started");
  expect(Date.now() - t0).toBeLessThan(6_000);
});

// #2380 S27 live check (2026-11-04): this exact command through Git Bash hit the 120 s timeout with a
// cmd banner and prompt as its output. Git Bash's path conversion turned `/b` into `B:/`, so cmd.exe
// ran interactively and waited on stdin. Now: stdin is closed and `start`/`cmd` keep their switches.
test.if(isWin && findGitBash() !== null)("`start /b python` returns promptly through Git Bash", async () => {
  const t0 = Date.now();
  const out = await run('start /b python -c "import time; time.sleep(4)"', 60_000);
  expect(out.returnCodeInterpretation ?? "").not.toContain("timed out");
  expect(out.stdout ?? "").not.toContain("Microsoft Windows");
  expect(Date.now() - t0).toBeLessThan(15_000);
}, 70_000);

test.if(isWin && findGitBash() !== null)("`cmd /c echo` works through Git Bash", async () => {
  const out = await run("cmd /c echo ember-s27-ok", 30_000);
  expect(out.stdout).toContain("ember-s27-ok");
  expect(out.stdout).not.toContain("Microsoft Windows");
}, 40_000);

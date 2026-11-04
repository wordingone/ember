// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// bash-tool-stdin-start.test.ts — #2380 S27 live check (2026-11-04, Windows 11, Git Bash as the
// shell): `start /b python -c "...sleep(555)"` through the Bash tool returned only after 120 s,
// "Command timed out", with a cmd banner and prompt as its output and no python started.
// Mechanism these tests pin (the Windows half is inferred, not observed here): Git Bash's path
// conversion turns `/b` and `/c` into drive paths, cmd.exe gets no `/c`, runs as an interactive
// shell, and waits on the tool's stdin pipe, which nothing ever closed.
// They run the Bash tool's real spawn path with a real bash on any platform, and put a fake
// `cmd.exe` first on PATH that logs its argv and, like an interactive cmd, reads stdin when it
// is not given `/c`.
import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { executeCommandWithShell, GIT_BASH_PRELUDE, shellInvocation } from "./bash-tool.ts";

const BASH = ["/bin/bash", "/usr/bin/bash"].find((p) => existsSync(p)) ?? null;
let dir = "";
let log = "";
const savedPath = process.env["PATH"];

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), "ember-s27-"));
  log = join(dir, "argv.log");
  const fake = join(dir, "cmd.exe");
  writeFileSync(fake, [
    "#!/bin/bash",
    `printf '%s\\n' "$*" >> "${log}"`,
    'for a in "$@"; do case "$a" in /c|/C) exit 0 ;; esac; done',
    'echo "Microsoft Windows [fake]"; printf "C:\\\\>"',
    "read -r line",            // an interactive cmd waits for a line of input
    "exit 0",
    "",
  ].join("\n"));
  chmodSync(fake, 0o755);
  process.env["PATH"] = `${dir}:${savedPath}`;
});

afterAll(() => {
  process.env["PATH"] = savedPath;
  rmSync(dir, { recursive: true, force: true });
});

const run = (command: string, timeout = 10_000) =>
  executeCommandWithShell(command, timeout, new AbortController().signal, dir, BASH);

describe("Bash tool: no stdin, and cmd/start keep their switches (#2380 S27)", () => {
  test("the shell is never given a stdin pipe", () => {
    expect(shellInvocation("echo hi", "bash").stdio[0]).toBe("ignore");
    expect(shellInvocation("echo hi", null).stdio[0]).toBe("ignore");
    expect(shellInvocation("echo a\necho b", null).stdio[0]).toBe("ignore");
  });

  test.if(BASH !== null)("a command that waits for input returns at once instead of at the timeout", async () => {
    const t0 = Date.now();
    const out = await run('read -r x; echo "read-exit=$?"', 8_000);
    expect(out.timedOut).toBe(false);
    expect(out.stdout.toString()).toContain("read-exit=1");
    expect(Date.now() - t0).toBeLessThan(4_000);
  });

  test.if(BASH !== null)("an interactive cmd.exe (the live banner-and-prompt case) ends at once", async () => {
    const t0 = Date.now();
    // Bypass the wrappers: `command` calls the fake cmd.exe with no /c, as path conversion did.
    const out = await run("command cmd.exe B:/ python", 8_000);
    expect(out.timedOut).toBe(false);
    expect(out.stdout.toString()).toContain("Microsoft Windows [fake]");
    expect(Date.now() - t0).toBeLessThan(4_000);
  });

  test.if(BASH !== null)("`start /b python -c ...` reaches cmd.exe as `/d /c start /b python -c ...`", async () => {
    rmSync(log, { force: true });
    const out = await run('start /b python -c "import time; time.sleep(555)"');
    expect(out.timedOut).toBe(false);
    expect(readFileSync(log, "utf-8").trim()).toBe("/d /c start /b python -c import time; time.sleep(555)");
  });

  test.if(BASH !== null)("`cmd /c` and the Git Bash idiom `cmd //c` both reach cmd.exe as `/c`", async () => {
    rmSync(log, { force: true });
    await run("cmd /c echo one && cmd //c echo two && cmd.exe /C echo three");
    expect(readFileSync(log, "utf-8").trim().split("\n")).toEqual(["/c echo one", "/c echo two", "/C echo three"]);
  });

  test.if(BASH !== null)("`&` inside a start argument is escaped for cmd, as Git's own start script does", async () => {
    rmSync(log, { force: true });
    await run('start "https://example.com/?a=1&b=2"');
    expect(readFileSync(log, "utf-8").trim()).toBe("/d /c start https://example.com/?a=1^&b=2");
  });

  test.if(BASH !== null)("the prelude does not move line numbers in the command's errors", async () => {
    const out = await run("true\nno-such-command-ember-s27");
    expect(out.stderr).toContain("line 2");
    expect(GIT_BASH_PRELUDE.includes("\n")).toBe(false);
  });

  test.if(BASH !== null)("the wrappers are not exported to scripts the command runs", async () => {
    const out = await run('bash -c "type -t start || echo none"');
    expect(out.stdout.toString().trim()).toBe("none");
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/hooks.test.ts — issue #2376 acceptance, at unit level:
//   * hook settings parse (nested and flat forms) and merge across settings files
//   * a hook runs with a timeout and captured output; exit code 2 blocks, others do not
//   * a PreToolUse hook blocks a Bash call in the real query loop and the model reads the reason
//   * UserPromptSubmit blocks / adds context, Stop asks to continue at most once

import { afterAll, afterEach, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { query } from "../core/query-engine.ts";
import type { LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";
import { buildTool } from "../core/tool-interface.ts";
import type { Tool, ToolUseContext } from "../core/tool-interface.ts";
import {
  HookRunner,
  matcherMatches,
  parseHooksConfig,
  runHookCommand,
  setActiveHookRunner,
  setHookWarningSink,
} from "./hooks.ts";
import { loadHooksConfig } from "./runtime.ts";
import { applyUserPromptSubmitHooks, runStopHooks } from "./repl-seam.ts";

const dirs: string[] = [];
const dir = (): string => {
  const d = mkdtempSync(join(tmpdir(), "ember-hooks-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) {
    try { rmSync(d, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }); } catch { /* ignore */ }
  }
});
afterEach(() => {
  setActiveHookRunner(null);
  setHookWarningSink(null);
});

const BUN = process.execPath.replace(/\\/g, "/");

/** Writes a hook script and returns the command line that runs it. */
function script(root: string, name: string, body: string): string {
  const path = join(root, name).replace(/\\/g, "/");
  writeFileSync(path, body);
  return `"${BUN}" run "${path}"`;
}

const BLOCK_RM = `
const input = JSON.parse(await Bun.stdin.text());
if (input.hook_event_name === "PreToolUse" && /rm -rf/.test(input.tool_input.command ?? "")) {
  console.error("refusing rm -rf: use the trash instead");
  process.exit(2);
}
`;

describe("hook settings", () => {
  it("parses the nested form and the flat form, and drops what it cannot run", () => {
    const warnings: string[] = [];
    const cfg = parseHooksConfig(
      {
        PreToolUse: [
          { matcher: "Bash", hooks: [{ type: "command", command: "a", timeout: 5 }] },
          { matcher: "Edit|Write", command: "b" },
          { hooks: [{ type: "prompt", prompt: "x" }] },
        ],
        Stop: [{ hooks: [{ command: "c" }] }],
        Nonsense: [],
      },
      (m) => warnings.push(m),
    );
    expect(cfg.PreToolUse).toEqual([
      { matcher: "Bash", hooks: [{ command: "a", timeout: 5 }] },
      { matcher: "Edit|Write", hooks: [{ command: "b" }] },
    ]);
    expect(cfg.Stop).toEqual([{ hooks: [{ command: "c" }] }]);
    expect(warnings.some((w) => w.includes("Nonsense"))).toBe(true);
    expect(warnings.some((w) => w.includes("only"))).toBe(true);
  });

  it("matchers are whole-name regexes; empty and * match every tool", () => {
    expect(matcherMatches("Bash", "Bash")).toBe(true);
    expect(matcherMatches("Bash", "BashOutput")).toBe(false);
    expect(matcherMatches("Edit|Write", "Write")).toBe(true);
    expect(matcherMatches("mcp__tiny__.*", "mcp__tiny__echo")).toBe(true);
    expect(matcherMatches("*", "Anything")).toBe(true);
    expect(matcherMatches(undefined, "Anything")).toBe(true);
    expect(matcherMatches("([", "Anything")).toBe(false);
  });

  it("merges hooks from user and project settings files without replacing either", async () => {
    const home = dir();
    const proj = dir();
    writeFileSync(join(home, "settings.json"), JSON.stringify({ hooks: { Stop: [{ hooks: [{ command: "user-stop" }] }] } }));
    mkdirSync(join(proj, ".ember"), { recursive: true });
    writeFileSync(
      join(proj, ".ember", "settings.json"),
      JSON.stringify({ hooks: { Stop: [{ hooks: [{ command: "proj-stop" }] }], PreToolUse: [{ matcher: "Bash", hooks: [{ command: "p" }] }] } }),
    );
    writeFileSync(join(proj, ".ember", "settings.local.json"), "{ broken");
    const warnings: string[] = [];
    const cfg = await loadHooksConfig(proj, home, (m) => warnings.push(m));
    expect(cfg.Stop!.flatMap((e) => e.hooks.map((h) => h.command))).toEqual(["user-stop", "proj-stop"]);
    expect(cfg.PreToolUse).toHaveLength(1);
    expect(warnings.some((w) => w.includes("settings.local.json"))).toBe(true);
  });
});

describe("running a hook command", () => {
  it("passes the event as JSON on stdin and captures stdout; exit 0 does not block", async () => {
    const root = dir();
    const cmd = script(root, "echo.ts", `const i = JSON.parse(await Bun.stdin.text()); console.log("saw " + i.tool_name + " " + i.cwd.length);`);
    const r = await runHookCommand({ command: cmd }, { hook_event_name: "PreToolUse", tool_name: "Bash", cwd: root }, root);
    expect(r.exitCode).toBe(0);
    expect(r.blocked).toBe(false);
    expect(r.stdout).toContain("saw Bash");
  });

  it("exit code 2 blocks and stderr is the reason", async () => {
    const root = dir();
    const cmd = script(root, "block.ts", BLOCK_RM);
    const r = await runHookCommand({ command: cmd }, { hook_event_name: "PreToolUse", tool_input: { command: "rm -rf /" } }, root);
    expect(r.blocked).toBe(true);
    expect(r.reason).toBe("refusing rm -rf: use the trash instead");
  });

  it("a JSON block decision on stdout blocks too", async () => {
    const root = dir();
    const cmd = script(root, "json.ts", `console.log(JSON.stringify({ decision: "block", reason: "policy says no" }));`);
    const r = await runHookCommand({ command: cmd }, {}, root);
    expect(r.exitCode).toBe(0);
    expect(r.blocked).toBe(true);
    expect(r.reason).toBe("policy says no");
    const deny = script(root, "deny.ts", `console.log(JSON.stringify({ hookSpecificOutput: { permissionDecision: "deny", permissionDecisionReason: "denied by hook" } }));`);
    expect((await runHookCommand({ command: deny }, {}, root)).reason).toBe("denied by hook");
  });

  it("another non-zero exit is not a block", async () => {
    const root = dir();
    const cmd = script(root, "one.ts", `console.error("oops"); process.exit(1);`);
    const r = await runHookCommand({ command: cmd }, {}, root);
    expect(r.exitCode).toBe(1);
    expect(r.blocked).toBe(false);
  });

  it("a hook past its timeout is stopped, reported, and does not block", async () => {
    const root = dir();
    const cmd = script(root, "slow.ts", `await new Promise((r) => setTimeout(r, 20000));`);
    const t0 = Date.now();
    const r = await runHookCommand({ command: cmd, timeout: 0.7 }, {}, root);
    expect(Date.now() - t0).toBeLessThan(6000);
    expect(r.timedOut).toBe(true);
    expect(r.blocked).toBe(false);
    const runner = new HookRunner({ Stop: [{ hooks: [{ command: cmd, timeout: 0.5 }] }] }, { cwd: root });
    const outcome = await runner.run("Stop");
    expect(outcome.blocked).toBe(false);
    expect(outcome.warnings[0]).toContain("timed out");
  }, 20_000);

  it("a command that does not exist is a non-blocking warning", async () => {
    const root = dir();
    const runner = new HookRunner({ Stop: [{ hooks: [{ command: "ember-no-such-hook-binary-xyz" }] }] }, { cwd: root });
    const outcome = await runner.run("Stop");
    expect(outcome.blocked).toBe(false);
    expect(outcome.warnings).toHaveLength(1);
  });
});

function ctx(tools: Tool[]): ToolUseContext {
  return {
    options: { tools, mainLoopModel: "test" },
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 10000, maxSizeBytes: 1024 * 1024 },
    globLimits: { maxResults: 100 },
    toolUseId: "t",
    setSDKStatus: undefined,
  } as unknown as ToolUseContext;
}

/** A stand-in "Bash" tool that records the commands it was actually asked to run. */
function fakeBash(ran: string[]): Tool {
  return buildTool<{ command: string }, string>({
    name: "Bash",
    description: () => "fake bash",
    call: async (args) => {
      ran.push(args.command);
      return { data: `ran: ${args.command}` };
    },
    mapToolResultToToolResultBlockParam: (c, id) => ({ type: "tool_result", tool_use_id: id, content: String(c) }),
  }) as unknown as Tool;
}

async function runTurn(tools: Tool[], commands: string[]): Promise<string[]> {
  let n = 0;
  const deps: LoopDepsOverrides = {
    callModel: async () => {
      const res: ModelResponse =
        n < commands.length
          ? { role: "assistant", content: [{ type: "tool_use", id: `c${n}`, name: "Bash", input: { command: commands[n++] } }], stop_reason: "tool_use" }
          : { role: "assistant", content: [{ type: "text", text: "done" }], stop_reason: "end_turn" };
      return res;
    },
    generateUuid: () => Math.random().toString(),
  };
  const results: string[] = [];
  for await (const ev of query(
    { messages: [{ role: "user", content: [{ type: "text", text: "go" }] }], systemPrompt: "", toolUseContext: ctx(tools), maxTurns: commands.length + 2 },
    deps,
  )) {
    if (ev.type === "user") {
      for (const b of ev.message.content as Array<{ type: string; content?: string; is_error?: boolean }>) {
        if (b.type === "tool_result") results.push(`${b.is_error ? "ERR " : ""}${b.content}`);
      }
    }
  }
  return results;
}

describe("hooks in the query loop", () => {
  it("a PreToolUse hook blocks a Bash call; the model reads the hook's stderr and the call never runs", async () => {
    const root = dir();
    const cmd = script(root, "block.ts", BLOCK_RM);
    setActiveHookRunner(new HookRunner({ PreToolUse: [{ matcher: "Bash", hooks: [{ command: cmd, timeout: 20 }] }] }, { cwd: root }));
    const ran: string[] = [];
    const results = await runTurn([fakeBash(ran)], ["rm -rf /tmp/x", "echo fine"]);
    expect(ran).toEqual(["echo fine"]); // the blocked command never reached the tool
    expect(results[0]).toBe("ERR PreToolUse hook blocked Bash: refusing rm -rf: use the trash instead");
    expect(results[1]).toBe("ran: echo fine");
  }, 30_000);

  it("a hook whose matcher does not select the tool does not run", async () => {
    const root = dir();
    const marker = join(root, "ran.txt").replace(/\\/g, "/");
    const cmd = script(root, "mark.ts", `import { writeFileSync } from "node:fs"; writeFileSync("${marker}", "x"); process.exit(2);`);
    setActiveHookRunner(new HookRunner({ PreToolUse: [{ matcher: "Write", hooks: [{ command: cmd }] }] }, { cwd: root }));
    const ran: string[] = [];
    const results = await runTurn([fakeBash(ran)], ["echo hi"]);
    expect(results).toEqual(["ran: echo hi"]);
    expect(await Bun.file(marker).exists()).toBe(false);
  }, 30_000);

  it("a PostToolUse hook that exits 2 adds its message to the result", async () => {
    const root = dir();
    const cmd = script(root, "post.ts", `const i = JSON.parse(await Bun.stdin.text()); console.error("lint: " + i.tool_response); process.exit(2);`);
    setActiveHookRunner(new HookRunner({ PostToolUse: [{ hooks: [{ command: cmd }] }] }, { cwd: root }));
    const ran: string[] = [];
    const results = await runTurn([fakeBash(ran)], ["echo hi"]);
    expect(ran).toEqual(["echo hi"]);
    expect(results[0]).toContain("ran: echo hi");
    expect(results[0]).toContain("PostToolUse hook: lint: ran: echo hi");
  }, 30_000);

  it("a hook that cannot run never blocks the tool (fail open) and the REPL is told", async () => {
    const root = dir();
    const warnings: string[] = [];
    setHookWarningSink((m) => warnings.push(m));
    setActiveHookRunner(new HookRunner({ PreToolUse: [{ hooks: [{ command: "ember-no-such-hook-binary-xyz" }] }] }, { cwd: root }));
    const ran: string[] = [];
    const results = await runTurn([fakeBash(ran)], ["echo hi"]);
    expect(ran).toEqual(["echo hi"]);
    expect(results).toEqual(["ran: echo hi"]);
    expect(warnings.length).toBe(1);
  }, 30_000);
});

describe("prompt and stop hooks", () => {
  it("UserPromptSubmit exit 2 blocks the prompt; stdout of a passing hook becomes context", async () => {
    const root = dir();
    setActiveHookRunner(
      new HookRunner(
        { UserPromptSubmit: [{ hooks: [{ command: script(root, "p.ts", `const i = JSON.parse(await Bun.stdin.text()); if (i.prompt.includes("secret")) { console.error("no secrets"); process.exit(2); } console.log("branch: main");`) }] }] },
        { cwd: root },
      ),
    );
    const blocked = await applyUserPromptSubmitHooks("my secret key");
    expect(blocked.blocked).toBe(true);
    expect(blocked.reason).toBe("no secrets");
    const ok = await applyUserPromptSubmitHooks("hello");
    expect(ok.blocked).toBe(false);
    expect(ok.prompt).toBe("hello\n\n[UserPromptSubmit hook output]\nbranch: main");
  }, 30_000);

  it("with no hooks configured nothing changes", async () => {
    expect(await applyUserPromptSubmitHooks("hello")).toEqual({ blocked: false, prompt: "hello" });
    expect(await runStopHooks(false)).toEqual({});
  });

  it("Stop exit 2 asks the model to continue once, never twice in a row", async () => {
    const root = dir();
    setActiveHookRunner(
      new HookRunner({ Stop: [{ hooks: [{ command: script(root, "s.ts", `console.error("tests are still failing"); process.exit(2);`) }] }] }, { cwd: root }),
    );
    expect(await runStopHooks(false)).toEqual({ continueWith: "tests are still failing" });
    expect(await runStopHooks(true)).toEqual({}); // the continuation turn itself: no second request
  }, 30_000);
});

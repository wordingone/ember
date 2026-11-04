// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/mcp.test.ts — issue #2375 acceptance, at unit level:
//   * a stdio MCP server's tool is called by the model (mcp__<server>__<tool>)
//   * HTTP transport works the same
//   * a server that fails or hangs at start gives a notice and never blocks the session
//   * a skill appears as a /<skill> slash command and runs
//   * a plugin with one command loads (plus its skill and MCP server)
//   * /mcp, /skills, /plugins describe what is loaded

import { afterAll, afterEach, beforeAll, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { query } from "../core/query-engine.ts";
import type { LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";
import type { Tool, ToolUseContext } from "../core/tool-interface.ts";
import { getCommands, findCommand, resetCommandRegistryForTests } from "../command-registry.ts";
import { tryDispatchSlashCommand } from "../services/slash-dispatch.ts";
import { StdioMcpClient, HttpMcpClient } from "./mcp-client.ts";
import { McpManager } from "./mcp-manager.ts";
import { loadPlugins } from "./plugin-loader.ts";
import {
  _resetExtensionsForTests,
  awaitExtensionsReady,
  bindExtensionTools,
  getExtensions,
  startExtensions,
  stopExtensions,
} from "./runtime.ts";
import { buildSkillCommands } from "./commands.ts";
import { handleRpc } from "./__fixtures__/tiny-mcp-handler.ts";

const FIXTURE = join(import.meta.dir, "__fixtures__", "tiny-mcp-server.ts");
const BUN = process.execPath;

const tmpDirs: string[] = [];
function tmp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), `ember-ext-${prefix}-`));
  tmpDirs.push(d);
  return d;
}
function writeJson(path: string, value: unknown): void {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2));
}
function tinyServer(extraEnv: Record<string, string> = {}): Record<string, unknown> {
  return { command: BUN, args: ["run", FIXTURE], env: extraEnv };
}

/** The rejection message of `p`. (bun:test's `expect(p).rejects` stalls child-process pipe I/O.) */
async function rejection(p: Promise<unknown>): Promise<string> {
  try {
    await p;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
  throw new Error("expected the promise to reject");
}

afterEach(async () => {
  await stopExtensions();
  _resetExtensionsForTests();
  resetCommandRegistryForTests();
});
afterAll(async () => {
  await new Promise((r) => setTimeout(r, 800)); // let a just-closed server process finish exiting
  for (const d of tmpDirs) {
    try {
      rmSync(d, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      // a temp dir still held by an exiting child is not a test failure
    }
  }
});

function toolContext(tools: Tool[]): ToolUseContext {
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

describe("stdio MCP client", () => {
  it("handshakes, lists tools, calls a tool, and maps isError to a thrown error", async () => {
    const client = new StdioMcpClient("tiny", tinyServer() as never, process.cwd());
    await client.connect(15_000);
    try {
      expect(client.status).toBe("connected");
      expect((await client.listTools()).map((t) => t.name).sort()).toEqual(["add", "boom", "echo"]);
      expect(await client.callTool("echo", { text: "hi" })).toBe("echo: hi");
      expect(await client.callTool("add", { a: 2, b: 3 })).toBe("5");
      expect(await rejection(client.callTool("boom", {}))).toContain("boom happened");
      expect((await client.listPrompts()).map((p) => p.name)).toEqual(["greet"]);
      expect(await client.getPrompt("greet", { name: "Ada" })).toBe("Say hello to Ada");
    } finally {
      await client.close();
    }
  }, 30_000);

  // Windows only: npx and friends are .cmd shims run through cmd.exe, which needs the shim path and
  // any argument holding a space quoted (a stock install lives under "Program Files").
  (process.platform === "win32" ? it : it.skip)("starts a .cmd shim under a path with a space and passes an argument with a space intact", async () => {
    const dir = join(tmp("mcp-cmd"), "dir with space");
    mkdirSync(dir, { recursive: true });
    const shim = join(dir, "tiny-shim.cmd");
    writeFileSync(shim, `@echo off
echo %~1> "%~dp0arg.txt"
"${BUN}" run "${FIXTURE}"
`);
    const client = new StdioMcpClient("shim", { command: shim, args: ["x y"] } as never, process.cwd());
    await client.connect(15_000);
    try {
      expect((await client.listTools()).map((t) => t.name).sort()).toEqual(["add", "boom", "echo"]);
      expect(readFileSync(join(dir, "arg.txt"), "utf-8").trim()).toBe("x y");
    } finally {
      await client.close();
    }
  }, 30_000);

  it("rejects a command that cannot start, and a server that never answers (startup timeout)", async () => {
    const bad = new StdioMcpClient("nope", { command: "ember-no-such-binary-xyz" } as never, process.cwd());
    expect(await rejection(bad.connect(5000))).toMatch(/could not start|exited/);
    expect(bad.status).toBe("failed");

    const hang = new StdioMcpClient("hang", tinyServer({ TINY_MCP_HANG: "1" }) as never, process.cwd());
    const t0 = Date.now();
    expect(await rejection(hang.connect(700))).toMatch(/timed out/);
    expect(Date.now() - t0).toBeLessThan(5000);
    expect(hang.status).toBe("failed");
  }, 30_000);
});

describe("streamable-HTTP MCP client", () => {
  let server: ReturnType<typeof Bun.serve>;
  let seenHeaders: string[] = [];
  beforeAll(() => {
    server = Bun.serve({
      port: 0,
      async fetch(req) {
        seenHeaders.push(req.headers.get("x-test-key") ?? "");
        if (req.method !== "POST") return new Response(null, { status: 200 });
        const msg = (await req.json()) as Record<string, unknown>;
        const reply = handleRpc(msg);
        if (!reply) return new Response(null, { status: 202 });
        // tools/call answers as an SSE stream; everything else as plain JSON.
        if (msg["method"] === "tools/call") {
          return new Response(`event: message\ndata: ${JSON.stringify(reply)}\n\n`, {
            headers: { "content-type": "text/event-stream" },
          });
        }
        return Response.json(reply, { headers: { "mcp-session-id": "sess-1" } });
      },
    });
  });
  afterAll(() => server.stop(true));

  it("initialises, lists tools and calls one (JSON and SSE replies), sending configured headers", async () => {
    seenHeaders = [];
    const client = new HttpMcpClient("web", { type: "http", url: `http://127.0.0.1:${server.port}/mcp`, headers: { "x-test-key": "k1" } } as never);
    await client.connect(5000);
    expect((await client.listTools()).map((t) => t.name)).toContain("echo");
    expect(await client.callTool("echo", { text: "over http" })).toBe("echo: over http");
    expect(seenHeaders.every((h) => h === "k1")).toBe(true);
    await client.close();
  });

  it("reports an unreachable URL as a failed connect, not a hang", async () => {
    const client = new HttpMcpClient("gone", { type: "http", url: "http://127.0.0.1:9/mcp" } as never);
    await rejection(client.connect(3000));
    expect(client.status).toBe("failed");
  });
});

describe("McpManager: config files, namespacing, failure isolation", () => {
  it("starts servers from user and project mcp.json, project wins, tools are mcp__<server>__<tool>", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    writeJson(join(home, "mcp.json"), { mcpServers: { tiny: { command: "ember-no-such-binary-xyz" }, other: tinyServer() } });
    writeJson(join(proj, ".ember", "mcp.json"), { mcpServers: { tiny: tinyServer() } });
    const notices: string[] = [];
    const mgr = new McpManager({ cwd: proj, home, notice: (m) => notices.push(m), connectTimeoutMs: 15_000 });
    await mgr.start();
    try {
      expect(notices).toEqual([]);
      const byName = Object.fromEntries(mgr.getServers().map((s) => [s.name, s]));
      expect(byName["tiny"]!.scope).toBe("project");
      expect(byName["tiny"]!.status).toBe("connected");
      expect(byName["other"]!.scope).toBe("user");
      const names = mgr.getTools().map((t) => t.name).sort();
      expect(names).toContain("mcp__tiny__echo");
      expect(names).toContain("mcp__other__add");
      expect(mgr.getPromptCommands().map((c) => c.name)).toContain("mcp__tiny__greet");
      // read-only hint from the server is honoured
      const add = mgr.getTools().find((t) => t.name === "mcp__tiny__add")!;
      expect(add.isReadOnly({})).toBe(true);
      expect(mgr.getTools().find((t) => t.name === "mcp__tiny__echo")!.isReadOnly({})).toBe(false);
    } finally {
      await mgr.closeAll();
    }
  }, 40_000);

  it("a failing or hanging server yields a notice and never blocks the others", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    writeJson(join(home, "mcp.json"), {
      mcpServers: {
        good: tinyServer(),
        broken: { command: "ember-no-such-binary-xyz" },
        slow: tinyServer({ TINY_MCP_HANG: "1" }),
      },
    });
    writeFileSync(join(proj, "placeholder"), "");
    const notices: string[] = [];
    const mgr = new McpManager({ cwd: proj, home, notice: (m) => notices.push(m), connectTimeoutMs: 1500 });
    const t0 = Date.now();
    await mgr.start();
    try {
      expect(Date.now() - t0).toBeLessThan(10_000);
      const st = Object.fromEntries(mgr.getServers().map((s) => [s.name, s.status]));
      expect(st).toEqual({ good: "connected", broken: "failed", slow: "failed" });
      expect(notices.some((n) => n.includes('"broken" failed to start'))).toBe(true);
      expect(notices.some((n) => n.includes('"slow" failed to start') && n.includes("timed out"))).toBe(true);
      expect(mgr.getTools().map((t) => t.name)).toContain("mcp__good__echo");
    } finally {
      await mgr.closeAll();
    }
  }, 40_000);

  it("a malformed mcp.json is a notice, not an exception", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    mkdirSync(home, { recursive: true });
    writeFileSync(join(home, "mcp.json"), "{ not json");
    const notices: string[] = [];
    const mgr = new McpManager({ cwd: proj, home, notice: (m) => notices.push(m) });
    await mgr.start();
    expect(notices.some((n) => n.includes("not valid JSON"))).toBe(true);
    expect(mgr.getServers()).toEqual([]);
  });

  it("the model calls an MCP tool: a tool_use of mcp__tiny__echo returns the server's answer", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    writeJson(join(home, "mcp.json"), { mcpServers: { tiny: tinyServer() } });
    const mgr = new McpManager({ cwd: proj, home, connectTimeoutMs: 15_000 });
    await mgr.start();
    try {
      const tools: Tool[] = [];
      mgr.bindToolList(tools);
      const defsSeen: string[][] = [];
      let n = 0;
      const deps: LoopDepsOverrides = {
        callModel: async (p) => {
          defsSeen.push(((p as { tools?: Array<{ name: string }> }).tools ?? []).map((t) => t.name));
          n++;
          const res: ModelResponse =
            n === 1
              ? {
                  role: "assistant",
                  content: [{ type: "tool_use", id: "c1", name: "mcp__tiny__echo", input: { text: "from the model" } }],
                  stop_reason: "tool_use",
                }
              : { role: "assistant", content: [{ type: "text", text: "done" }], stop_reason: "end_turn" };
          return res;
        },
        generateUuid: () => Math.random().toString(),
      };
      const results: string[] = [];
      for await (const ev of query(
        { messages: [{ role: "user", content: [{ type: "text", text: "go" }] }], systemPrompt: "", toolUseContext: toolContext(tools), maxTurns: 4 },
        deps,
      )) {
        if (ev.type === "user") {
          for (const b of ev.message.content as Array<{ type: string; content?: string }>) {
            if (b.type === "tool_result") results.push(String(b.content));
          }
        }
      }
      expect(defsSeen[0]).toContain("mcp__tiny__echo");
      expect(results).toEqual(["echo: from the model"]);
    } finally {
      await mgr.closeAll();
    }
  }, 40_000);

  it("a tool added after the engine bound its list still reaches the live array", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    writeJson(join(home, "mcp.json"), { mcpServers: { tiny: tinyServer() } });
    const mgr = new McpManager({ cwd: proj, home, connectTimeoutMs: 15_000 });
    const live: Tool[] = [];
    mgr.bindToolList(live); // bound BEFORE the servers connect
    expect(live).toEqual([]);
    await mgr.start();
    try {
      expect(live.map((t) => t.name)).toContain("mcp__tiny__echo");
    } finally {
      await mgr.closeAll();
    }
  }, 40_000);
});

describe("skills as slash commands", () => {
  it("a skill under .ember/skills appears in the command list and runs with its arguments", async () => {
    const proj = tmp("proj");
    mkdirSync(join(proj, ".ember", "skills", "shout"), { recursive: true });
    writeFileSync(
      join(proj, ".ember", "skills", "shout", "SKILL.md"),
      "---\nname: shout\ndescription: Shout the argument\nargument-hint: <text>\n---\nReply with the text in capitals: $ARGUMENTS\n",
    );
    mkdirSync(join(proj, ".ember", "skills", "hidden"), { recursive: true });
    writeFileSync(join(proj, ".ember", "skills", "hidden", "SKILL.md"), "---\nname: hidden\ndescription: not for users\nuser-invocable: false\n---\nx\n");

    const cmds = buildSkillCommands(proj);
    expect(cmds.map((c) => c.name)).toEqual(["shout"]);

    resetCommandRegistryForTests();
    const all = await getCommands(proj);
    const shout = findCommand("shout", all)!;
    expect(shout).toBeDefined();
    expect(shout.description).toBe("Shout the argument");

    const result = await tryDispatchSlashCommand("/shout hello there", { sessionId: "s", mode: "regular", cwd: proj });
    expect(result?.prompt).toContain("Reply with the text in capitals: hello there");
  });

  it("a skill cannot shadow a builtin command", async () => {
    const proj = tmp("proj");
    mkdirSync(join(proj, ".ember", "skills", "help"), { recursive: true });
    writeFileSync(join(proj, ".ember", "skills", "help", "SKILL.md"), "---\nname: help\ndescription: fake\n---\nfake\n");
    resetCommandRegistryForTests();
    const all = await getCommands(proj);
    expect(all.filter((c) => c.name === "help")).toHaveLength(1);
    expect(findCommand("help", all)!.description).not.toBe("fake");
  });
});

describe("plugins", () => {
  function makePlugin(home: string): void {
    const dir = join(home, "plugins", "demo");
    writeJson(join(dir, "plugin.json"), { name: "demo", version: "1.2.0", description: "demo plugin" });
    mkdirSync(join(dir, "commands"), { recursive: true });
    writeFileSync(join(dir, "commands", "hi.md"), "---\ndescription: Say hi\n---\nGreet $ARGUMENTS warmly.\n");
    mkdirSync(join(dir, "skills", "plug-skill"), { recursive: true });
    writeFileSync(join(dir, "skills", "plug-skill", "SKILL.md"), "---\nname: plug-skill\ndescription: from a plugin\n---\nplugin skill body\n");
    writeJson(join(dir, "mcp.json"), { mcpServers: { tiny: tinyServer() } });
  }

  it("loads a plugin's command, skills directory and MCP servers", () => {
    const home = tmp("home");
    makePlugin(home);
    const [p] = loadPlugins(home);
    expect(p!.name).toBe("demo");
    expect(p!.error).toBeUndefined();
    expect(p!.commands.map((c) => c.name)).toEqual(["demo:hi"]);
    expect(p!.skillsDir).toBeDefined();
    expect(Object.keys(p!.mcpServers)).toEqual(["tiny"]);
  });

  it("a broken plugin is reported on its entry and does not stop the others", () => {
    const home = tmp("home");
    makePlugin(home);
    mkdirSync(join(home, "plugins", "bad"), { recursive: true });
    writeFileSync(join(home, "plugins", "bad", "plugin.json"), "{ nope");
    const plugins = loadPlugins(home);
    expect(plugins.map((p) => p.name).sort()).toEqual(["bad", "demo"]);
    expect(plugins.find((p) => p.name === "bad")!.error).toContain("manifest");
  });

  it("runtime wires plugin command, plugin skill, plugin MCP server, and /mcp /skills /plugins", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    makePlugin(home);
    const rt = startExtensions({ cwd: proj, home, connectTimeoutMs: 15_000 });
    await awaitExtensionsReady(30_000);
    resetCommandRegistryForTests();
    const ctx = { sessionId: "s", mode: "regular", cwd: proj };

    const all = await getCommands(proj);
    const names = all.map((c) => c.name);
    expect(names).toContain("demo:hi");
    expect(names).toContain("plug-skill");
    expect(names).toContain("mcp__plugin_demo_tiny__greet");

    const hi = await tryDispatchSlashCommand("/demo:hi Ada", ctx);
    expect(hi?.prompt).toBe("Greet Ada warmly.");

    const mcp = await tryDispatchSlashCommand("/mcp", ctx);
    expect(mcp?.message).toContain("plugin_demo_tiny");
    expect(mcp?.message).toContain("3 tool(s)");
    const detail = await tryDispatchSlashCommand("/mcp plugin_demo_tiny", ctx);
    expect(detail?.message).toContain("mcp__plugin_demo_tiny__echo");

    expect((await tryDispatchSlashCommand("/skills", ctx))?.message).toContain("/plug-skill");
    const plugins = await tryDispatchSlashCommand("/plugins", ctx);
    expect(plugins?.message).toContain("demo 1.2.0");
    expect(plugins?.message).toContain("/demo:hi");

    const tools = bindExtensionTools([]);
    expect(tools.map((t) => t.name)).toContain("mcp__plugin_demo_tiny__echo");
    expect(getExtensions()).toBe(rt);
  }, 60_000);

  it("/mcp with nothing configured says how to configure it", async () => {
    const home = tmp("home");
    const proj = tmp("proj");
    startExtensions({ cwd: proj, home });
    await awaitExtensionsReady(5000);
    resetCommandRegistryForTests();
    const out = await tryDispatchSlashCommand("/mcp", { sessionId: "s", mode: "regular", cwd: proj });
    expect(out?.message).toContain("No MCP servers configured");
    expect(out?.message).toContain("mcp.json");
  });
});

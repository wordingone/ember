// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind tests S38 / W28 (issue #2379, #2381): a headless -p run executed `rm -f`, a curl to
// 127.0.0.1 and a write outside the working directory with no approval. Without
// --dangerously-skip-permissions it now refuses them, with a reason the model can relay.
import { describe, test, expect } from "bun:test";
import { runHeadlessPrompt } from "../cli/headless-repl.ts";
import type { QueryEvent } from "./query-engine.ts";
import { buildTool, type PermissionBehavior, type Tool } from "./tool-interface.ts";
import type { LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";
import { headlessRefusalReason, headlessCanUseTool, BYPASS_PERMISSIONS_FLAG } from "./headless-permissions.ts";
import { isDeletionCommand } from "./destructive-command.ts";
import { isBlockedHost, privateHostInCommand } from "./private-hosts.ts";
import { bashTool } from "../tools/bash-tool.ts";
import { powerShellTool } from "../tools/powershell-tool.ts";
import { parseHeadlessPrint } from "../entrypoints/process-entry.ts";

/** A tool that records whether it ran; its permission verdict is fixed by the test. */
function fakeTool(name: string, behavior: PermissionBehavior, message?: string, readOnly = false) {
  const ran: unknown[] = [];
  const tool = buildTool<{ command?: string; file_path?: string }, string>({
    name,
    description: () => name,
    inputJSONSchema: { type: "object" },
    isReadOnly: () => readOnly,
    checkPermissions: async (input) => ({ behavior, updatedInput: input, message }),
    call: async (input) => { ran.push(input); return { data: "ran" }; },
    mapToolResultToToolResultBlockParam: (data, id) => ({ type: "tool_result", tool_use_id: id, content: data }),
  });
  return { tool: tool as unknown as Tool, ran };
}

/** Run one headless prompt in which the model calls `tool` once with `input`, then says "done". */
async function headless(tool: Tool, input: Record<string, unknown>, bypass: boolean) {
  let turn = 0;
  const toolUse: ModelResponse = {
    role: "assistant",
    content: [{ type: "tool_use", id: "tool-1", name: tool.name, input }],
    stop_reason: "tool_use",
  };
  const done: ModelResponse = { role: "assistant", content: [{ type: "text", text: "done" }], stop_reason: "end_turn" };
  const deps: LoopDepsOverrides = {
    callModel: async () => (turn++ === 0 ? toolUse : done),
    generateUuid: () => `uuid-${turn}`,
  };
  const messages: unknown[] = [];
  const surface = {
    write(_e: QueryEvent): void {},
    prependUserMessage(content: string): void { messages.push({ type: "user", content: [{ type: "text", text: content }] }); },
    [Symbol.asyncIterator]() {
      let i = 0;
      return { next: async () => (i < messages.length ? { value: messages[i++], done: false } : { value: undefined, done: true }) } as AsyncIterator<unknown>;
    },
  } as Parameters<typeof runHeadlessPrompt>[1];
  const { events } = await runHeadlessPrompt("do it", surface, [tool], { bypassPermissions: bypass }, deps);
  const result = events
    .filter((e) => e.type === "user")
    .flatMap((e) => (e as { message: { content: unknown[] } }).message.content)
    .find((b) => (b as { tool_use_id?: string }).tool_use_id === "tool-1") as { content: string; is_error?: boolean } | undefined;
  return { result };
}

describe("headless -p without a permission flag", () => {
  test("a call the tool marks 'ask' is refused with its reason and the flag name; the tool does not run", async () => {
    const { tool, ran } = fakeTool("Write", "ask", "C:\\elsewhere\\x.txt is outside the working directory (C:\\proj).");
    const { result } = await headless(tool, { file_path: "C:\\elsewhere\\x.txt" }, false);
    expect(ran).toHaveLength(0);
    expect(result?.is_error).toBe(true);
    expect(result?.content).toContain("outside the working directory");
    expect(result?.content).toContain(BYPASS_PERMISSIONS_FLAG);
  });

  test("a shell command that deletes files is refused", async () => {
    const { tool, ran } = fakeTool("Bash", "allow");
    const { result } = await headless(tool, { command: "rm -f notes.txt" }, false);
    expect(ran).toHaveLength(0);
    expect(result?.is_error).toBe(true);
    expect(result?.content).toContain("deletes files");
    expect(result?.content).toContain(BYPASS_PERMISSIONS_FLAG);
  });

  test("a read-only call is allowed", async () => {
    const { tool, ran } = fakeTool("Bash", "allow", undefined, true);
    const { result } = await headless(tool, { command: "ls -la" }, false);
    expect(ran).toHaveLength(1);
    expect(result?.is_error).toBeUndefined();
    expect(result?.content).toBe("ran");
  });

  test("W31: a call the tool allows but that is not read-only (Write, curl download) is refused like the TUI default mode would", async () => {
    const w = fakeTool("Write", "allow");
    const rw = (await headless(w.tool, { file_path: "notes.txt" }, false)).result;
    expect(w.ran).toHaveLength(0);
    expect(rw?.is_error).toBe(true);
    expect(rw?.content).toContain(BYPASS_PERMISSIONS_FLAG);
    const b = fakeTool("Bash", "allow");
    const rb = (await headless(b.tool, { command: "curl -o x.bin https://example.com/x.bin" }, false)).result;
    expect(b.ran).toHaveLength(0);
    expect(rb?.is_error).toBe(true);
    expect(rb?.content).toContain(BYPASS_PERMISSIONS_FLAG);
  });

  test("a hard deny stays denied", async () => {
    const { tool, ran } = fakeTool("Bash", "deny", "Command denied by rule: x");
    const { result } = await headless(tool, { command: "ls" }, false);
    expect(ran).toHaveLength(0);
    expect(result?.content).toContain("denied by rule");
  });

  test("with --dangerously-skip-permissions the same calls run", async () => {
    const a = fakeTool("Write", "ask", "outside the working directory");
    expect((await headless(a.tool, { file_path: "C:\\elsewhere\\x.txt" }, true)).result?.content).toBe("ran");
    expect(a.ran).toHaveLength(1);
    const b = fakeTool("Bash", "allow");
    expect((await headless(b.tool, { command: "rm -f notes.txt" }, true)).result?.content).toBe("ran");
    expect(b.ran).toHaveLength(1);
  });
});

describe("headlessRefusalReason / headlessCanUseTool", () => {
  test("reasons", () => {
    expect(headlessRefusalReason("Read", { file_path: "a" }, "allow", undefined, true)).toBeNull();
    expect(headlessRefusalReason("Bash", { command: "git status" }, "allow", undefined, true)).toBeNull();
    expect(headlessRefusalReason("Write", { file_path: "a" }, "allow")).toContain("not read-only");
    expect(headlessRefusalReason("Bash", { command: "del a.txt" }, "allow")).toContain("deletes files");
    expect(headlessRefusalReason("PowerShell", { command: "Remove-Item a.txt" }, "allow")).toContain("deletes files");
    expect(headlessRefusalReason("Write", {}, "ask", "reason x")).toBe("reason x");
    expect(headlessRefusalReason("Write", {}, "ask")).toContain("asked for approval");
  });

  test("the predicate returns a refusal object with the text, never a bare false", async () => {
    const stderr = process.stderr.write.bind(process.stderr);
    process.stderr.write = (() => true) as typeof process.stderr.write;
    try {
      const d = await headlessCanUseTool({ name: "Bash" } as Tool, { command: "rm a" }, "allow");
      expect(typeof d).toBe("object");
      expect((d as { reason: string }).reason).toContain(BYPASS_PERMISSIONS_FLAG);
      expect(await headlessCanUseTool({ name: "Bash", isReadOnly: () => true } as unknown as Tool, { command: "ls" }, "allow")).toBe(true);
    } finally {
      process.stderr.write = stderr;
    }
  });
});

describe("isDeletionCommand", () => {
  test("deleting commands, wherever they sit in the line", () => {
    for (const c of [
      "rm notes.txt", "rm -f a", "cd x && del a.txt", "ls; rmdir old", "Remove-Item .\\a.txt", "ri a.txt",
      "find . -name '*.tmp' -delete", "cmd /c del a.txt", "powershell -c \"Remove-Item a\"", "ls | xargs rm",
      "sudo rm a", "echo x\nrm a",
    ]) expect(isDeletionCommand(c)).toBe(true);
  });

  test("commands that merely contain those letters are not", () => {
    for (const c of [
      "ls -la", "grep rm file.txt", "echo rm", "python del_file.py", "git rm a.txt", "git status", "format-list",
      "cat confirm.txt", "npm run build", "dir /b", "mkdir out", "echo \"remove-item is a cmdlet\"",
    ]) expect(isDeletionCommand(c)).toBe(false);
  });
});

describe("private and loopback addresses (W28)", () => {
  test("isBlockedHost covers the forms WebFetch used to miss", () => {
    for (const h of [
      "localhost", "LOCALHOST", "localhost.", "app.localhost", "127.0.0.1", "127.1.2.3", "10.0.0.5", "192.168.1.1",
      "172.16.0.1", "172.31.255.255", "169.254.169.254", "0.0.0.0", "[::1]", "::1", "[::ffff:127.0.0.1]",
      "[::ffff:7f00:1]", "[fd00::1]", "[fe80::1]",
    ]) expect(isBlockedHost(h)).toBe(true);
    for (const h of ["example.com", "8.8.8.8", "172.32.0.1", "172.15.0.1", "192.169.0.1", "11.0.0.1", "[2606:4700::1111]", ""]) {
      expect(isBlockedHost(h)).toBe(false);
    }
  });

  test("a shell command that connects to such a host is found", () => {
    expect(privateHostInCommand("curl -s http://127.0.0.1:8080/health")).toBe("127.0.0.1");
    expect(privateHostInCommand("curl http://localhost:5000")).toBe("localhost");
    expect(privateHostInCommand("curl -s http://[::1]:8080/x")).toBe("[::1]");
    expect(privateHostInCommand("wget https://user:pw@192.168.0.7/f")).toBe("192.168.0.7");
    expect(privateHostInCommand("nc 10.1.2.3 22")).toBe("10.1.2.3");
    expect(privateHostInCommand("Invoke-WebRequest -Uri http://localhost:8000/x")).toBe("localhost");
    expect(privateHostInCommand("python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:9/')\"")).toBe("127.0.0.1");
  });

  test("public hosts and non-network commands are left alone", () => {
    expect(privateHostInCommand("curl https://example.com/a")).toBeNull();
    expect(privateHostInCommand("echo 127.0.0.1 > hosts.txt")).toBeNull();
    expect(privateHostInCommand("git clone https://github.com/a/b")).toBeNull();
    expect(privateHostInCommand("ping 127.0.0.1")).toBeNull();
  });

  test("Bash and PowerShell ask for such a command", async () => {
    const ctx = { getAppState: () => ({}) } as any;
    const b = await bashTool.checkPermissions({ command: "curl -s http://127.0.0.1:8080/health" } as any, ctx);
    expect(b.behavior).toBe("ask");
    expect(b.message).toContain("127.0.0.1");
    const ok = await bashTool.checkPermissions({ command: "curl -s https://example.com" } as any, ctx);
    expect(ok.behavior).toBe("allow");
    const p = await powerShellTool.checkPermissions({ command: "Invoke-WebRequest http://localhost:5000/x" } as any, ctx);
    expect(p.behavior).toBe("ask");
  });
});

describe("-p argument parsing with the bypass flag", () => {
  test("the prompt is found on either side of --dangerously-skip-permissions", () => {
    const base = ["bun", "main.ts"];
    expect(parseHeadlessPrint([...base, "-p", "do it"])).toEqual({ found: true, prompt: "do it" });
    expect(parseHeadlessPrint([...base, "-p", "do it", BYPASS_PERMISSIONS_FLAG])).toEqual({ found: true, prompt: "do it" });
    expect(parseHeadlessPrint([...base, BYPASS_PERMISSIONS_FLAG, "-p", "do it"])).toEqual({ found: true, prompt: "do it" });
    expect(parseHeadlessPrint([...base, "-p", BYPASS_PERMISSIONS_FLAG, "do it"])).toEqual({ found: true, prompt: "do it" });
    expect(parseHeadlessPrint([...base, "-p", BYPASS_PERMISSIONS_FLAG])).toEqual({ found: true, prompt: null });
  });
});

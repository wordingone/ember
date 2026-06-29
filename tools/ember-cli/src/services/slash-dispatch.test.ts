// services/slash-dispatch.test.ts — behavioral tests for the slash-command dispatch
// seam. Asserts the registry IS consulted for slash input and is NOT for ordinary
// input (the latter must fall through to a normal model turn). Locks the contract so a
// regression that silently sends "/help" to the model is caught.

import { describe, it, expect } from "bun:test";
import { parseSlashInput, tryDispatchSlashCommand, type SlashDispatchDeps } from "./slash-dispatch.ts";
import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";

const CTX: CommandContext = { sessionId: "s1", mode: "default", cwd: "/tmp/x" };

function cmd(over: Partial<RegistryCommand> & { name: string }): RegistryCommand {
  return {
    description: over.description ?? `the ${over.name} command`,
    isEnabled: over.isEnabled ?? (() => true),
    execute: over.execute ?? (async () => ({ type: "message", message: `${over.name} default` })),
    ...over,
  };
}

function deps(commands: RegistryCommand[], onFind?: (n: string) => RegistryCommand | undefined): SlashDispatchDeps {
  return {
    getCommands: async () => commands,
    findCommand: onFind
      ? (n) => onFind(n)
      : (n, cmds) => cmds.find((c) => c.name === n || (c.aliases ?? []).includes(n)),
  };
}

describe("parseSlashInput", () => {
  it("splits name and args", () => {
    expect(parseSlashInput("/help")).toEqual({ name: "help", args: "" });
    expect(parseSlashInput("/model load qwen")).toEqual({ name: "model", args: "load qwen" });
    expect(parseSlashInput("  /watch  on  ")).toEqual({ name: "watch", args: "on" });
  });
  it("returns null for non-slash and bare slash", () => {
    expect(parseSlashInput("hello world")).toBeNull();
    expect(parseSlashInput("/")).toBeNull();
    expect(parseSlashInput("   /   ")).toBeNull();
    expect(parseSlashInput("not /a command")).toBeNull();
  });
});

describe("tryDispatchSlashCommand — non-slash falls through", () => {
  it("returns null and never touches the registry for ordinary input", async () => {
    let getCalled = false;
    const d: SlashDispatchDeps = {
      getCommands: async () => { getCalled = true; return []; },
      findCommand: () => undefined,
    };
    const out = await tryDispatchSlashCommand("just a normal message", CTX, d);
    expect(out).toBeNull();
    expect(getCalled).toBe(false); // no registry work for non-slash input
  });
});

describe("tryDispatchSlashCommand — dispatch", () => {
  it("executes the matched command with parsed args + ctx and returns its result", async () => {
    const calls: Array<{ args: string; ctx: CommandContext }> = [];
    const model = cmd({
      name: "model",
      execute: async (args, ctx) => {
        calls.push({ args, ctx });
        return { type: "message", message: `model says ${args}` } as CommandResult;
      },
    });
    const out = await tryDispatchSlashCommand("/model load x", CTX, deps([model]));
    expect(calls[0]?.args).toBe("load x");
    expect(calls[0]?.ctx).toEqual(CTX);
    expect(out).toEqual({ type: "message", message: "model says load x" });
  });

  it("resolves aliases", async () => {
    const c = cmd({ name: "observatory", aliases: ["obs"], execute: async () => ({ type: "message", message: "ok" }) });
    const out = await tryDispatchSlashCommand("/obs", CTX, deps([c]));
    expect(out).toEqual({ type: "message", message: "ok" });
  });

  it("returns an unknown-command message listing available enabled commands", async () => {
    const out = await tryDispatchSlashCommand("/nope", CTX, deps([cmd({ name: "model" }), cmd({ name: "watch" })]));
    expect(out?.message).toContain("Unknown command: /nope");
    expect(out?.message).toContain("/model");
    expect(out?.message).toContain("/watch");
  });

  it("reports disabled commands without executing them", async () => {
    let ran = false;
    const c = cmd({ name: "finetune", isEnabled: () => false, execute: async () => { ran = true; return; } });
    const out = await tryDispatchSlashCommand("/finetune", CTX, deps([c]));
    expect(ran).toBe(false);
    expect(out?.message).toContain("not available");
  });

  it("supplies a default message when a command returns void", async () => {
    const c = cmd({ name: "clear", execute: async () => { /* side effect only */ } });
    const out = await tryDispatchSlashCommand("/clear", CTX, deps([c]));
    expect(out).toEqual({ type: "message", message: "/clear ran." });
  });
});

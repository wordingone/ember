// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { ReplScreen, type ReplScreenProps } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";
import { resetCommandRegistryForTests, setCommandRegistryDeps } from "../../../../../../../tools/ember-cli/src/command-registry.ts";
import { createTrainCommand } from "../../../../../../../tools/ember-cli/src/commands/train.ts";
import { sessionIdForAppRoot } from "./app-shell.ts";
import { buildInteractiveReplElement } from "../../../../../../../tools/ember-cli/src/entrypoints/process-entry.ts";

describe("mounted process-entry session identity handoff", () => {
  it("passes the minted session identity into the production REPL element", () => {
    type Node = { type: unknown; props: Record<string, unknown> | null; children: unknown[] };
    const fakeReact = {
      createElement(type: unknown, props: Record<string, unknown> | null, ...children: unknown[]): Node {
        return { type, props, children };
      },
    };
    const repl = () => null;
    const tree = buildInteractiveReplElement(fakeReact, "InkApp", repl, {
      config: { model: "ember" },
      cwd: "/same/checkout",
      sessionId: "mounted-root-a",
      modelSeat: { phase: "ABSENT" },
      onExit: () => {},
    }) as Node;
    const replNode = tree.children[0] as Node;
    expect(replNode.props?.sessionId).toBe("mounted-root-a");
  });
});

describe("AppRoot session identity", () => {
  it("keeps two same-CWD roots on distinct live session identities", () => {
    const cwd = "/same/checkout";
    const first = sessionIdForAppRoot(cwd, "repl-session-a");
    const second = sessionIdForAppRoot(cwd, "repl-session-b");

    expect(first).toBe("repl-session-a");
    expect(second).toBe("repl-session-b");
    expect(first).not.toBe(second);
  });

  it("mints a distinct identity when an AppRoot caller omits one", () => {
    const cwd = "/same/checkout";
    expect(sessionIdForAppRoot(cwd)).not.toBe(sessionIdForAppRoot(cwd));
  });

  it("gives two same-CWD AppRoot identities independent null-preflight budgets", async () => {
    const cwd = "/same/checkout";
    const firstSession = sessionIdForAppRoot(cwd, "app-root-a");
    const secondSession = sessionIdForAppRoot(cwd, "app-root-b");
    const spawns: Array<{ executable: string; args: string[] }> = [];
    const makeCommand = () => createTrainCommand({
      pythonBin: "python",
      repoRoot: "/fake/ember",
      runLaunchPacket: (executable, args) => {
        spawns.push({ executable, args });
        return { status: null, stdout: "" };
      },
    });

    const first = await makeCommand().execute("", {
      sessionId: firstSession,
      mode: "test",
      cwd,
    });
    const second = await makeCommand().execute("", {
      sessionId: secondSession,
      mode: "test",
      cwd,
    });

    expect(first?.message).toContain("attempt 2");
    expect(second?.message).toContain("attempt 2");
    expect(spawns).toHaveLength(4);
    expect(spawns[1]).toEqual(spawns[0]);
    expect(spawns[3]).toEqual(spawns[2]);
  });

  it("threads each mounted REPL identity through real keyboard slash dispatch", async () => {
    resetCommandRegistryForTests();
    const cwd = "/same/checkout";
    const seenSessionIds: string[] = [];
    const spawns: Array<{ executable: string; args: string[] }> = [];
    const train = createTrainCommand({
      pythonBin: "python",
      repoRoot: "/fake/ember",
      runLaunchPacket: (executable, args) => {
        spawns.push({ executable, args });
        return { status: null, stdout: "" };
      },
    });
    const mountedCommand = {
      ...train,
      async execute(args: string, ctx: Parameters<typeof train.execute>[1]) {
        seenSessionIds.push(ctx.sessionId);
        return train.execute(args, ctx);
      },
    };
    setCommandRegistryDeps({
      getBuiltinCommands: () => [mountedCommand],
      getSkillDirCommands: async () => [],
      getPluginCommands: async () => [],
      getDynamicSkillCommands: async () => [],
      getMcpCommandList: () => [],
    });

    const flush = async (): Promise<void> => {
      for (let i = 0; i < 8; i++) {
        await new Promise<void>((resolve) => setImmediate(resolve));
      }
    };
    const dispatchFromMountedRoot = async (sessionId: string, submissions: number): Promise<void> => {
      let raw = "";
      const replProps: ReplScreenProps = {
        config: { model: "ember", permissionMode: "bypass", baseSystemPrompt: "" },
        cwd,
        sessionId,
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      };
      const element = React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns: 100, rows: 34 } },
        React.createElement(ReplScreen, replProps),
      );
      const handle = mountInk(element, {
        stream: { write(chunk: string) { raw += chunk; } },
        stdout: { columns: 100, rows: 34 },
      });
      for (let submission = 0; submission < submissions; submission++) {
        for (const key of "/train ") _deliverKeyEvent(key, {});
        _deliverKeyEvent("return", {});
        await flush();
      }
      handle.unmount();
      expect(raw.length).toBeGreaterThan(0);
    };

    await dispatchFromMountedRoot("mounted-root-a", 2);
    await dispatchFromMountedRoot("mounted-root-b", 1);
    resetCommandRegistryForTests();

    expect(seenSessionIds).toEqual([
      "mounted-root-a",
      "mounted-root-a",
      "mounted-root-b",
    ]);
    expect(spawns).toHaveLength(5);
    expect(spawns[1]).toEqual(spawns[0]);
    expect(spawns[4]).toEqual(spawns[3]);
  });
});

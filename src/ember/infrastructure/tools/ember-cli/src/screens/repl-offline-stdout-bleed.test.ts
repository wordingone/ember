// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// #1698: OFFLINE-mode watcher pollers (memory-footprint, serving-topology) used to
// console.warn on every failed poll tick. Ink only ever writes rendered frames through the
// stream this component is mounted with -- it NEVER touches the process's raw
// stdout/stderr -- so a console.warn call bypasses the renderer's own frame-write channel
// entirely and lands directly on the real terminal, at poll cadence (1s/5s), independently
// of whatever the renderer itself is drawing that tick. That is the exact bleed-through
// mechanism the issue describes: raw fragments interleaving with and overwriting panel
// borders/titles/sparklines.
//
// This test mounts the real ReplScreen (the actual production entry point, same technique as
// repl-host-telemetry-wiring.test.ts) with no EMBER_LAB_PIPE set -- the OFFLINE state the
// issue is about -- and spies on console.warn/console.error while both watcher pollers fire
// at least once. Zero calls through those channels are allowed for either poller's failure
// class; a real failure must reach the operator only through the deduped activity feed
// (services/poll-failure-dedup.ts, unit-tested separately, wired into repl.ts).
import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { ReplScreen } from "../screens/repl.ts";

async function wait(ms: number): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, ms));
}

describe("OFFLINE-mode watcher pollers never write raw console output (regression #1698)", () => {
  let mounted: ReturnType<typeof mountInk> | null = null;
  let warnSpy: ReturnType<typeof spyOn>;
  let errorSpy: ReturnType<typeof spyOn>;
  const previousPipe = process.env.EMBER_LAB_PIPE;

  beforeEach(() => {
    delete process.env.EMBER_LAB_PIPE;
    warnSpy = spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    mounted?.unmount();
    mounted = null;
    warnSpy.mockRestore();
    errorSpy.mockRestore();
    if (previousPipe === undefined) delete process.env.EMBER_LAB_PIPE;
    else process.env.EMBER_LAB_PIPE = previousPipe;
  });

  test("mounting REPL offline and letting both pollers fire produces zero raw console writes", async () => {
    resetCommandRegistryForTests();
    let raw = "";
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const columns = 120, rows = 44;
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config,
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    );
    mounted = mountInk(element, {
      stream: { write(s: string) { raw += s; } },
      stdout: { columns, rows },
    });

    // memory-footprint and serving-topology both poll immediately on start() (before their
    // first interval tick); this window is generous enough for both first-poll failures to
    // resolve and, pre-fix, reach console.warn.
    await wait(1500);

    const offenders = [...warnSpy.mock.calls, ...errorSpy.mock.calls]
      .map((args) => String(args[0]))
      .filter((text) => text.includes("[memory-footprint]") || text.includes("[serving-topology]"));

    expect(offenders).toEqual([]);
    void raw;
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, it } from "bun:test";
import React from "react";

import {
  DISABLE_MOUSE_TRACKING,
  ENABLE_MOUSE_TRACKING,
  ENTER_ALT_SCREEN,
  EXIT_ALT_SCREEN,
  HIDE_CURSOR,
  SHOW_CURSOR,
} from "./termio.ts";
import { AlternateScreen } from "./components.ts";
import { createTerminalSessionController } from "./terminal-session.ts";
import { mountInk } from "./reconciler.ts";

describe("terminal session ownership", () => {
  it("enters the alternate buffer, hides the hardware cursor, and enables full pointer reporting", () => {
    const writes: string[] = [];
    const session = createTerminalSessionController({ write: (value) => writes.push(value) });

    session.enter();

    expect(writes.join("")).toBe(ENTER_ALT_SCREEN + HIDE_CURSOR + ENABLE_MOUSE_TRACKING);
  });

  it("restores pointer mode, cursor visibility, and the primary buffer exactly once", () => {
    const writes: string[] = [];
    const session = createTerminalSessionController({ write: (value) => writes.push(value) });
    session.enter();
    session.exit();
    session.exit();

    expect(writes.join("")).toBe(
      ENTER_ALT_SCREEN + HIDE_CURSOR + ENABLE_MOUSE_TRACKING +
      DISABLE_MOUSE_TRACKING + SHOW_CURSOR + EXIT_ALT_SCREEN,
    );
  });

  it("does not emit teardown sequences when ownership was never acquired", () => {
    const writes: string[] = [];
    const session = createTerminalSessionController({ write: (value) => writes.push(value) });

    session.exit();

    expect(writes).toEqual([]);
  });

  it("keeps AlternateScreen declarative under the sole terminal-session controller", () => {
    const controllerWrites: string[] = [];
    const renderWrites: string[] = [];
    const globalWrites: string[] = [];
    const originalStdoutWrite = process.stdout.write;
    process.stdout.write = ((chunk: string | Uint8Array) => {
      globalWrites.push(String(chunk));
      return true;
    }) as typeof process.stdout.write;

    try {
      const session = createTerminalSessionController({
        write: (value) => controllerWrites.push(value),
      });
      session.enter();
      const handle = mountInk(
        React.createElement(
          AlternateScreen,
          { enableMouseTracking: true },
          React.createElement(React.Fragment, null),
        ),
        {
          stream: { write: (value: string) => renderWrites.push(value) },
          stdout: { columns: 80, rows: 24 },
        },
      );
      handle.unmount();
      session.exit();

      expect(globalWrites).toEqual([]);
      expect(controllerWrites.join("")).toBe(
        ENTER_ALT_SCREEN + HIDE_CURSOR + ENABLE_MOUSE_TRACKING +
        DISABLE_MOUSE_TRACKING + SHOW_CURSOR + EXIT_ALT_SCREEN,
      );
    } finally {
      process.stdout.write = originalStdoutWrite;
    }
  });

  it("restores terminal modes when the mounted application throws during render", () => {
    const writes: string[] = [];
    const stream = { write: (value: string) => writes.push(value) };
    const session = createTerminalSessionController(stream);
    const RenderCrash = (): React.ReactElement => { throw new Error("render-crash"); };

    session.enter();
    expect(() => mountInk(React.createElement(RenderCrash), {
      stream,
      stdout: { columns: 80, rows: 24 },
      onError: () => session.exit(),
    })).toThrow("render-crash");

    const output = writes.join("");
    const teardown = DISABLE_MOUSE_TRACKING + SHOW_CURSOR + EXIT_ALT_SCREEN;
    expect(output.startsWith(ENTER_ALT_SCREEN + HIDE_CURSOR + ENABLE_MOUSE_TRACKING)).toBe(true);
    expect(output.endsWith(teardown)).toBe(true);
    expect(output.split(teardown)).toHaveLength(2);
    expect(session.active).toBe(false);
  });
});

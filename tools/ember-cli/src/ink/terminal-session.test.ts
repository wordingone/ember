// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, it } from "bun:test";

import {
  DISABLE_MOUSE_TRACKING,
  ENABLE_MOUSE_TRACKING,
  ENTER_ALT_SCREEN,
  EXIT_ALT_SCREEN,
  HIDE_CURSOR,
  SHOW_CURSOR,
} from "./termio.ts";
import { createTerminalSessionController } from "./terminal-session.ts";

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
});

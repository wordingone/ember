// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import xtermHeadless from "@xterm/headless";
import { READY_OSC } from "./ready-sentinel.ts";

describe("readiness OSC terminal behavior", () => {
  test("the lifecycle ConPTY parser consumes the OSC without printing readiness text", async () => {
    const { Terminal } = xtermHeadless;
    const terminal = new Terminal({ cols: 40, rows: 4, allowProposedApi: true });
    try {
      await new Promise<void>((done) => {
        terminal.write(`before${READY_OSC}after`, done);
      });
      const line = terminal.buffer.active.getLine(0)?.translateToString(true) ?? "";
      expect(line).toBe("beforeafter");
      expect(line).not.toContain("EMBER_READY");
    } finally {
      terminal.dispose();
    }
  });
});

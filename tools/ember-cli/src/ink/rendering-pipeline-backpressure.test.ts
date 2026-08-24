// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #898: a slow ConPTY must not turn the 140 ms idle repaint into an unbounded
// native stdout queue. The first rejected write owns the one queued patch; later frames
// are suppressed until drain, then recovery is a full repaint because the terminal never
// observed the suppressed intermediate frames.
import { describe, expect, test } from "bun:test";
import React from "react";
import { Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

describe("renderer stdout backpressure (issue #898)", () => {
  test("queues at most one rejected patch and full-repaints after drain", () => {
    const writes: string[] = [];
    let drain: (() => void) | null = null;
    let drainRegistrations = 0;
    let writableLength = 0;
    let writableNeedDrain = false;
    let rejectWrites = true;
    const stream = {
      get writableLength(): number { return writableLength; },
      get writableNeedDrain(): boolean { return writableNeedDrain; },
      write(value: string): boolean {
        writes.push(value);
        writableLength += Buffer.byteLength(value);
        if (rejectWrites) {
          writableNeedDrain = true;
          return false;
        }
        return true;
      },
      once(event: "drain", listener: () => void): void {
        expect(event).toBe("drain");
        drainRegistrations += 1;
        drain = listener;
      },
    };

    const handle = mountInk(React.createElement(Text, null, "frame-0"), {
      stream,
      stdout: { columns: 40, rows: 4 },
    });
    handle.update(React.createElement(Text, null, "frame-1"));
    handle.update(React.createElement(Text, null, "frame-2"));

    expect(writes).toHaveLength(1);
    expect(drainRegistrations).toBe(1);
    expect(drain).not.toBeNull();

    writableLength = 0;
    writableNeedDrain = false;
    rejectWrites = false;
    drain!();

    expect(writes).toHaveLength(2);
    const repaint = writes[1]!;
    expect(repaint).toContain("\x1b[2J");
    expect(repaint).toContain("\x1b[H");
    expect(repaint.indexOf("\x1b[2J")).toBeLessThan(repaint.indexOf("frame-2"));
    expect(repaint).toContain("frame-2");

    handle.update(React.createElement(Text, null, "recovered"));
    expect(writes).toHaveLength(3);
    expect(writes[2]).toContain("recovered");
    handle.unmount();
  });
});

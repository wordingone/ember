// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import React from "react";
import { Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { READY_OSC, emitReadySentinel } from "./ready-sentinel.ts";

function fakeStream(): { chunks: string[]; stream: { write(c: string | Uint8Array): boolean } } {
  const chunks: string[] = [];
  return {
    chunks,
    stream: {
      write(c: string | Uint8Array): boolean {
        chunks.push(typeof c === "string" ? c : Buffer.from(c).toString("utf8"));
        return true;
      },
    },
  };
}

describe("renderer-owned readiness sentinel", () => {
  test("an unrelated stdout write cannot grant readiness before the renderer flushes", () => {
    const { chunks, stream } = fakeStream();
    let readinessCalls = 0;

    stream.write("unrelated boot diagnostic");
    expect(chunks).toEqual(["unrelated boot diagnostic"]);
    expect(chunks).not.toContain(READY_OSC);

    const handle = mountInk(
      React.createElement(Text, null, "first real frame"),
      {
        stream,
        stdout: { columns: 40, rows: 6 },
        onFirstFrameFlushed: () => {
          readinessCalls += 1;
          emitReadySentinel(stream);
        },
      },
    );

    expect(readinessCalls).toBe(1);
    expect(chunks.filter((chunk) => chunk === READY_OSC)).toHaveLength(1);
    expect(chunks.indexOf(READY_OSC)).toBeGreaterThan(0);

    handle.update(React.createElement(Text, null, "second real frame"));
    expect(readinessCalls).toBe(1);
    expect(chunks.filter((chunk) => chunk === READY_OSC)).toHaveLength(1);
    handle.unmount();
  });

  test("no renderer mount means no readiness sentinel", () => {
    const { chunks } = fakeStream();
    expect(chunks).toEqual([]);
  });

  test("sentinel is an OSC sequence: ESC ] payload BEL, no printable frame impact", () => {
    expect(READY_OSC.startsWith("\u001b]")).toBe(true);
    expect(READY_OSC.endsWith("\u0007")).toBe(true);
    expect(READY_OSC).toContain("EMBER_READY");
  });
});

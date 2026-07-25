// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import { READY_OSC, armReadySentinel } from "./ready-sentinel.ts";

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

describe("armReadySentinel", () => {
  test("no write, no sentinel: arming alone emits nothing", () => {
    const { chunks, stream } = fakeStream();
    armReadySentinel(stream);
    expect(chunks).toEqual([]);
  });

  test("sentinel is appended exactly once, directly after the first write", () => {
    const { chunks, stream } = fakeStream();
    armReadySentinel(stream);
    stream.write("frame-1");
    stream.write("frame-2");
    stream.write("frame-3");
    expect(chunks).toEqual(["frame-1", READY_OSC, "frame-2", "frame-3"]);
  });

  test("wrapper removes itself after firing (write restored to the original)", () => {
    const { chunks, stream } = fakeStream();
    const before = stream.write;
    armReadySentinel(stream);
    expect(stream.write).not.toBe(before);
    stream.write("frame-1");
    expect(stream.write).toBe(before);
    expect(chunks.filter((c) => c === READY_OSC)).toHaveLength(1);
  });

  test("sentinel is an OSC sequence: ESC ] payload BEL, no printable frame impact", () => {
    expect(READY_OSC.startsWith("\u001b]")).toBe(true);
    expect(READY_OSC.endsWith("\u0007")).toBe(true);
    expect(READY_OSC).toContain("EMBER_READY");
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind-test follow-up (#2381): an escape sequence or mouse report split across two reads.
//
// With mouse tracking on, a busy process (a long reply being rendered) can read a mouse report in
// two pieces. The bridge used to deliver a lone ESC as an Escape keypress at once, so the rest of
// the report ("[<35;10;5M") was typed into the prompt and the Escape interrupted the running turn.
// A report left unfinished stayed in the decoder for good, and ate or prefixed whatever was typed
// next ("hat number", "35;10;5What number"). These tests drive the real bridge, readline and
// decoder with fake stdin, and fail on the old bridge.

import { describe, expect, it } from "bun:test";
import { EventEmitter } from "node:events";
import React from "react";

import { Text } from "./components.ts";
import { useInput } from "./hooks.ts";
import { mountInk } from "./reconciler.ts";
import { ESCAPE_HOLD_MS, STALE_PARTIAL_MS, startStdinBridge } from "./stdin-bridge.ts";
import { createSgrMouseDecoder } from "./termio.ts";

class FakeStdin extends EventEmitter {
  isTTY = true;
  setRawMode(_mode: boolean): void {}
  resume(): void {}
  pause(): void {}
}

interface Rig {
  send(chunk: string): void;
  /** Characters that reached a text input. */
  typed(): string;
  /** "escape" / "up" key presses, in order, each with the time it arrived. */
  keys(): string[];
  keyTimes(): number[];
  stop(): void;
}

function rig(): Rig {
  const typed: string[] = [];
  const keys: string[] = [];
  const times: number[] = [];
  const Probe = (): React.ReactElement => {
    useInput((input, key) => {
      if (key.escape) { keys.push("escape"); times.push(Date.now()); }
      else if (key.upArrow) { keys.push("up"); times.push(Date.now()); }
      else if (input && !key.ctrl && !key.meta && !key.alt) typed.push(input);
    });
    return React.createElement(Text, null, "probe");
  };
  const handle = mountInk(React.createElement(Probe), { stream: { write() {} }, stdout: { columns: 20, rows: 2 } });
  const stdin = new FakeStdin();
  const stopBridge = startStdinBridge({ stdin: stdin as never });
  return {
    send: (chunk) => { stdin.emit("data", chunk); },
    typed: () => typed.join(""),
    keys: () => [...keys],
    keyTimes: () => [...times],
    stop: () => { stopBridge(); handle.unmount(); },
  };
}

const settle = (ms = 20) => Bun.sleep(ms);

describe("a lone ESC", () => {
  it("is still delivered as an Escape press, within the hold, when nothing follows", async () => {
    const r = rig();
    const sentAt = Date.now();
    r.send("\x1b");
    expect(r.keys()).toEqual([]); // held, not yet decided
    await settle(ESCAPE_HOLD_MS + 60);
    expect(r.keys()).toEqual(["escape"]);
    const delay = r.keyTimes()[0]! - sentAt;
    expect(delay).toBeGreaterThanOrEqual(ESCAPE_HOLD_MS - 5);
    expect(delay).toBeLessThan(ESCAPE_HOLD_MS + 60);
    r.stop();
  });

  it("two ESC bytes in one read are one Escape press", async () => {
    const r = rig();
    r.send("\x1b\x1b");
    await settle(ESCAPE_HOLD_MS + 60);
    expect(r.keys()).toEqual(["escape"]);
    r.stop();
  });

  it("followed by typed text is an Escape press and then the text, never alt+letter", async () => {
    const r = rig();
    r.send("\x1b");
    await settle(5);
    r.send("W");
    await settle(ESCAPE_HOLD_MS + 40);
    expect(r.keys()).toEqual(["escape"]);
    expect(r.typed()).toBe("W");
    r.stop();
  });

  it("followed by the rest of a mouse report (split after ESC): no Escape, nothing typed from the report", async () => {
    const r = rig();
    r.send("\x1b");
    await settle(5);
    r.send("[<35;10;5M");
    await settle(5);
    r.send("What number");
    await settle(ESCAPE_HOLD_MS + 40);
    expect(r.keys()).toEqual([]);
    expect(r.typed()).toBe("What number");
    r.stop();
  });

  it("followed by the rest of an arrow key (split after ESC) is that arrow key, not an Escape", async () => {
    const r = rig();
    r.send("\x1b");
    await settle(5);
    r.send("[A");
    await settle(ESCAPE_HOLD_MS + 40);
    expect(r.keys()).toEqual(["up"]);
    expect(r.typed()).toBe("");
    r.stop();
  });
});

describe("a mouse report left unfinished", () => {
  it("cut off in digits, then typing right after: none of the digits are typed", async () => {
    const r = rig();
    r.send("\x1b[<35;10;5");
    r.send("What number");
    await settle();
    expect(r.typed()).toBe("What number");
    expect(r.keys()).toEqual([]);
    r.stop();
  });

  it("cut off at ESC [ and never finished: typing later keeps its first character", async () => {
    const r = rig();
    r.send("\x1b[");
    await settle(STALE_PARTIAL_MS + 60);
    r.send("What number");
    await settle();
    expect(r.typed()).toBe("What number");
    r.stop();
  });

  it("cut off in digits and never finished: typing later is not prefixed by them", async () => {
    const r = rig();
    r.send("\x1b[<35;10;5");
    await settle(STALE_PARTIAL_MS + 60);
    r.send("What number");
    await settle();
    expect(r.typed()).toBe("What number");
    r.stop();
  });

  it("an unfinished report followed by a whole one: the whole one still decodes and nothing is typed", async () => {
    const r = rig();
    r.send("\x1b[<35;1");
    r.send("\x1b[<35;10;5Mok");
    await settle();
    expect(r.typed()).toBe("ok");
    r.stop();
  });
});

describe("the rest of a report that arrives after its ESC was already delivered", () => {
  it("is dropped, in one piece or in several", async () => {
    const r = rig();
    r.send("\x1b");
    await settle(ESCAPE_HOLD_MS + 40); // the Escape press fires
    r.send("[<35;10;5M");
    await settle(5);
    r.send("ab");
    await settle();
    expect(r.keys()).toEqual(["escape"]);
    expect(r.typed()).toBe("ab");

    r.send("\x1b");
    await settle(ESCAPE_HOLD_MS + 40);
    r.send("[<35;10");
    r.send(";5M");
    r.send("cd");
    await settle();
    expect(r.keys()).toEqual(["escape", "escape"]);
    expect(r.typed()).toBe("abcd");
    r.stop();
  });

  it("only within a short window: text typed later that looks like a report is kept", async () => {
    const r = rig();
    r.send("\x1b");
    await settle(ESCAPE_HOLD_MS + 40);
    await settle(320);
    r.send("[<1;2;3M");
    await settle();
    expect(r.typed()).toBe("[<1;2;3M");
    r.stop();
  });
});

describe("decoder", () => {
  it("reports and drops a partial report, and what follows it", () => {
    const d = createSgrMouseDecoder();
    expect(d.push("\x1b[<35;10;5")).toEqual({ events: [], passthrough: "" });
    expect(d.hasPending()).toBe(true);
    d.discardPending();
    expect(d.hasPending()).toBe(false);
    expect(d.push(";7M")).toEqual({ events: [], passthrough: "" });
    expect(d.push("hi")).toEqual({ events: [], passthrough: "hi" });
  });

  it("drops the digits of a truncated report that is followed by other input, and keeps the other input", () => {
    const d = createSgrMouseDecoder();
    expect(d.push("\x1b[<35;10;5What")).toEqual({ events: [], passthrough: "What" });
    expect(d.push("\x1b[<35;10M!")).toEqual({ events: [], passthrough: "!" });
  });

  it("keeps a malformed sequence with no digits as keyboard input", () => {
    const d = createSgrMouseDecoder();
    expect(d.push("\x1b[<x;2;1M")).toEqual({ events: [], passthrough: "\x1b[<x;2;1M" });
  });
});

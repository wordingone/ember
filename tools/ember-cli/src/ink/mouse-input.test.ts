// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, it } from "bun:test";
import { EventEmitter } from "node:events";
import React from "react";
import type { ClickEvent, PointerEvent } from "./event-system.ts";

import { Box, Text } from "./components.ts";
import { useInput } from "./hooks.ts";
import { mountInk } from "./reconciler.ts";
import { startStdinBridge } from "./stdin-bridge.ts";
import { createSgrMouseDecoder } from "./termio.ts";

class FakeStdin extends EventEmitter {
  isTTY = true;
  rawModes: boolean[] = [];
  resumed = false;
  paused = false;

  setRawMode(mode: boolean): void {
    this.rawModes.push(mode);
  }
  resume(): void {
    this.resumed = true;
  }
  pause(): void {
    this.paused = true;
  }
}

describe("SGR mouse decoder", () => {
  it("decodes a left-button press and converts terminal coordinates to zero-based cells", () => {
    const decoder = createSgrMouseDecoder();

    expect(decoder.push("\x1b[<0;7;4M")).toEqual({
      events: [{
        kind: "press",
        col: 6,
        row: 3,
        button: 0,
        modifiers: { ctrl: false, shift: false, alt: false, meta: false },
      }],
      passthrough: "",
    });
  });

  it("retains an incomplete sequence until the remaining bytes arrive", () => {
    const decoder = createSgrMouseDecoder();

    expect(decoder.push("\x1b[<0;12")).toEqual({ events: [], passthrough: "" });
    expect(decoder.push(";9M")).toEqual({
      events: [{
        kind: "press",
        col: 11,
        row: 8,
        button: 0,
        modifiers: { ctrl: false, shift: false, alt: false, meta: false },
      }],
      passthrough: "",
    });
  });

  it("preserves adjacent keyboard bytes while extracting the mouse sequence", () => {
    const decoder = createSgrMouseDecoder();

    expect(decoder.push("a\x1b[<0;2;1Mb")).toEqual({
      events: [{
        kind: "press",
        col: 1,
        row: 0,
        button: 0,
        modifiers: { ctrl: false, shift: false, alt: false, meta: false },
      }],
      passthrough: "ab",
    });
  });

  it("decodes release, hover motion, and wheel direction without treating malformed input as pointer authority", () => {
    const decoder = createSgrMouseDecoder();

    expect(decoder.push("\x1b[<0;2;1m\x1b[<35;3;2M\x1b[<64;4;3M\x1b[<65;5;4M")).toEqual({
      events: [
        {
          kind: "release", col: 1, row: 0, button: 0,
          modifiers: { ctrl: false, shift: false, alt: false, meta: false },
        },
        {
          kind: "move", col: 2, row: 1, button: null,
          modifiers: { ctrl: false, shift: false, alt: false, meta: false },
        },
        {
          kind: "wheel", col: 3, row: 2, button: null, deltaY: -1,
          modifiers: { ctrl: false, shift: false, alt: false, meta: false },
        },
        {
          kind: "wheel", col: 4, row: 3, button: null, deltaY: 1,
          modifiers: { ctrl: false, shift: false, alt: false, meta: false },
        },
      ],
      passthrough: "",
    });

    expect(decoder.push("\x1b[<0;0;1M\x1b[<4294967296;2;1M\x1b[<x;2;1M")).toEqual({
      events: [],
      passthrough: "\x1b[<x;2;1M",
    });
  });
});

describe("production mouse bridge and mounted-tree hit testing", () => {
  it("uses native raw-mode capability when compiled ConPTY does not report isTTY", () => {
    const calls: string[] = [];
    const stdin = new FakeStdin();
    stdin.isTTY = false;
    const handle = mountInk(
      React.createElement(Box, { width: 6, height: 1, onClick: () => calls.push("click") }, React.createElement(Text, null, "PAUSE")),
      { stream: { write() {} }, stdout: { columns: 10, rows: 2 } },
    );
    const stop = startStdinBridge({ stdin: stdin as never, emitKeypressEvents: () => {} });

    stdin.emit("data", "\x1b[<0;2;1M");

    expect(stdin.rawModes).toEqual([true]);
    expect(calls).toEqual(["click"]);
    stop();
    expect(stdin.rawModes).toEqual([true, false]);
    handle.unmount();
  });

  it("routes adjacent keyboard bytes without leaking mouse bytes to key handlers", () => {
    const keys: string[] = [];
    const stdin = new FakeStdin();
    const KeyboardProbe = (): React.ReactElement => {
      useInput((input) => keys.push(input));
      return React.createElement(Text, null, "probe");
    };
    const handle = mountInk(React.createElement(KeyboardProbe), {
      stream: { write() {} },
      stdout: { columns: 20, rows: 2 },
    });
    const stop = startStdinBridge({
      stdin: stdin as never,
      emitKeypressEvents: (stream) => {
        stream.on("data", (chunk) => {
          for (const character of chunk.toString()) {
            (stream as EventEmitter).emit("keypress", character, { name: character });
          }
        });
      },
    });

    stdin.emit("data", "a\x1b[<0;2;1Mb");

    expect(keys).toEqual(["a", "b"]);
    stop();
    handle.unmount();
  });

  it("dispatches one click to the deepest visible control with terminal and local coordinates", () => {
    const calls: unknown[] = [];
    const stdin = new FakeStdin();
    const tree = React.createElement(
      Box,
      { flexDirection: "column", width: 20, height: 4 },
      React.createElement(Box, { key: "top", width: 20, height: 1 }),
      React.createElement(
        Box,
        { key: "row", flexDirection: "row", width: 20, height: 1 },
        React.createElement(Box, { key: "left", width: 2, height: 1, flexShrink: 0 }),
        React.createElement(
          Box,
          {
            key: "control",
            width: 6,
            height: 1,
            flexShrink: 0,
            onClick: (event) => {
              const click = event as ClickEvent;
              calls.push({
                col: click.col, row: click.row,
                localCol: click.localCol, localRow: click.localRow,
              });
            },
          },
          React.createElement(Text, null, "START"),
        ),
      ),
    );
    const handle = mountInk(tree, {
      stream: { write() {} },
      stdout: { columns: 20, rows: 4 },
    });
    const stop = startStdinBridge({
      stdin: stdin as never,
      emitKeypressEvents: () => {},
    });

    stdin.emit("data", Buffer.from("\x1b[<0;3;2M"));

    expect(calls).toEqual([{ col: 2, row: 1, localCol: 0, localRow: 0 }]);
    stop();
    handle.unmount();
  });

  it("uses current geometry and handler after update and removes dispatch authority on unmount", () => {
    const calls: string[] = [];
    const stdin = new FakeStdin();
    const control = (label: string, width: number) => React.createElement(
      Box,
      { width, height: 1, onClick: () => calls.push(label) },
      React.createElement(Text, null, label),
    );
    const handle = mountInk(control("old", 2), {
      stream: { write() {} },
      stdout: { columns: 10, rows: 2 },
    });
    const stop = startStdinBridge({
      stdin: stdin as never,
      emitKeypressEvents: () => {},
    });

    handle.update(control("new", 5));
    stdin.emit("data", "\x1b[<0;5;1M");
    expect(calls).toEqual(["new"]);

    handle.unmount();
    stdin.emit("data", "\x1b[<0;1;1M");
    expect(calls).toEqual(["new"]);
    stop();
  });

  it("does not dispatch outside an overflow-hidden ancestor", () => {
    let calls = 0;
    const stdin = new FakeStdin();
    const tree = React.createElement(
      Box,
      { width: 2, height: 1, overflow: "hidden" },
      React.createElement(Box, {
        width: 5,
        height: 1,
        flexShrink: 0,
        onClick: () => { calls += 1; },
      }),
    );
    const handle = mountInk(tree, {
      stream: { write() {} },
      stdout: { columns: 10, rows: 2 },
    });
    const stop = startStdinBridge({
      stdin: stdin as never,
      emitKeypressEvents: () => {},
    });

    stdin.emit("data", "\x1b[<0;4;1M");
    expect(calls).toBe(0);

    stop();
    handle.unmount();
  });

  it("dispatches exact hover transitions and wheel direction to the pointed region", () => {
    const calls: string[] = [];
    const stdin = new FakeStdin();
    const tree = React.createElement(
      Box,
      { width: 12, height: 2 },
      React.createElement(Box, {
        width: 6,
        height: 1,
        flexShrink: 0,
        onMouseEnter: () => calls.push("enter"),
        onMouseMove: () => calls.push("move"),
        onMouseLeave: () => calls.push("leave"),
        onWheel: (event) => calls.push(`wheel:${(event as PointerEvent).deltaY}`),
      }),
    );
    const handle = mountInk(tree, {
      stream: { write() {} },
      stdout: { columns: 12, rows: 2 },
    });
    const stop = startStdinBridge({
      stdin: stdin as never,
      emitKeypressEvents: () => {},
    });

    stdin.emit("data", "\x1b[<35;2;1M");
    stdin.emit("data", "\x1b[<64;2;1M");
    stdin.emit("data", "\x1b[<35;10;1M");

    expect(calls).toEqual(["enter", "move", "wheel:-1", "leave"]);
    stop();
    handle.unmount();
  });
});

// components/message-renderers-operator-tag.test.ts — ember #165 acceptance:
// a prompt injected via the operator pipe renders with a visible [operator] tag
// in the transcript row, distinguishing it from keyboard-typed input.

import { describe, it, expect } from "bun:test";
import React from "react";
import { UserTextMessage } from "./message-renderers.ts";

function ser(el: React.ReactElement): string {
  return JSON.stringify(el, (_k, v) => (typeof v === "function" ? undefined : v));
}

describe("UserTextMessage — origin tag (ember #165)", () => {
  it("keyboard-origin (default, no origin prop) renders no [operator] tag", () => {
    const el = UserTextMessage({ text: "hello world" });
    expect(ser(el)).not.toContain("[operator]");
  });

  it("origin: 'keyboard' explicitly also renders no [operator] tag", () => {
    const el = UserTextMessage({ text: "hello world", origin: "keyboard" });
    expect(ser(el)).not.toContain("[operator]");
  });

  it("origin: 'operator' renders a visible [operator] tag alongside the 'You' header", () => {
    const el = UserTextMessage({ text: "prompt from the pipe", origin: "operator" });
    const s = ser(el);
    expect(s).toContain("[operator]");
    expect(s).toContain("You");
    expect(s).toContain("prompt from the pipe");
  });

  it("the [operator] tag survives in brief layout too", () => {
    const el = UserTextMessage({ text: "brief operator line", origin: "operator", brief: true });
    expect(ser(el)).toContain("[operator]");
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";
import { Box, Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { VirtualMessageList, virtualMessageWindow } from "./app-shell.ts";

describe("fixed transcript viewport", () => {
  test("stays bottom-anchored at offset zero", () => {
    expect(virtualMessageWindow(10, 3, 0)).toEqual({ start: 7, end: 10, offset: 0 });
  });

  test("wheel offset reveals older messages without exceeding the finite viewport", () => {
    expect(virtualMessageWindow(10, 3, 2)).toEqual({ start: 5, end: 8, offset: 2 });
  });

  test("clamps empty, oversized, and negative inputs", () => {
    expect(virtualMessageWindow(0, 3, 50)).toEqual({ start: 0, end: 0, offset: 0 });
    expect(virtualMessageWindow(2, 5, 50)).toEqual({ start: 0, end: 2, offset: 0 });
    expect(virtualMessageWindow(10, 3, -4)).toEqual({ start: 7, end: 10, offset: 0 });
  });

  test("keeps the end of the latest multiline result visible inside the flex-allocated transcript", () => {
    let rendered = "";
    const messages = [
      { id: "old", role: "assistant", content: "old" },
      { id: "latest", role: "assistant", content: "latest" },
    ] as any;
    const tree = React.createElement(
      Box,
      { flexDirection: "column", height: 8, width: 40 },
      React.createElement(
        Box,
        { flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
        React.createElement(VirtualMessageList, {
          messages,
          viewportRows: 20,
          renderMessage: (message: any) => React.createElement(
            Box,
            { flexDirection: "column" },
            ...Array.from({ length: message.id === "latest" ? 6 : 2 }, (_, index) => React.createElement(
              Text,
              { key: index },
              message.id === "latest" && index === 5 ? "LATEST-END" : `${message.id}-${index}`,
            )),
          ),
        }),
      ),
      React.createElement(Box, { height: 2, flexShrink: 0 }, React.createElement(Text, null, "PROMPT")),
    );

    mountInk(tree, {
      stream: { write(value: string) { rendered += value; } },
      stdout: { columns: 40, rows: 8 },
    });

    const frame = buildFrame(40, 8);
    parseRenderedIntoFrame(rendered, frame, new StylePool());
    const finalFrame = frame.cells
      .map((row) => row.map((cell) => cell?.char ?? " ").join(""))
      .join("\n");
    expect(finalFrame).toContain("LATEST-END");
    expect(finalFrame).toContain("PROMPT");
  });

  test("keeps a short newest result visible after an oversized prior result", () => {
    let rendered = "";
    const messages = [
      { id: "oversized-prior", role: "assistant", content: "prior" },
      { id: "new-command", role: "user", content: "/watch" },
      { id: "new-result", role: "assistant", content: "WATCHING-RESULT" },
    ] as any;
    const tree = React.createElement(
      Box,
      { flexDirection: "column", height: 8, width: 40 },
      React.createElement(
        Box,
        { flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
        React.createElement(VirtualMessageList, {
          messages,
          viewportRows: 20,
          renderMessage: (message: any) => React.createElement(
            Box,
            { flexDirection: "column" },
            ...Array.from(
              { length: message.id === "oversized-prior" ? 12 : 1 },
              (_, index) => React.createElement(
                Text,
                { key: index },
                message.id === "new-result" ? message.content : message.id + "-" + index,
              ),
            ),
          ),
        }),
      ),
      React.createElement(Box, { height: 2, flexShrink: 0 }, React.createElement(Text, null, "PROMPT")),
    );
    mountInk(tree, {
      stream: { write(value: string) { rendered += value; } },
      stdout: { columns: 40, rows: 8 },
    });
    const frame = buildFrame(40, 8);
    parseRenderedIntoFrame(rendered, frame, new StylePool());
    const finalFrame = frame.cells
      .map((row) => row.map((cell) => cell?.char ?? " ").join(""))
      .join("\n");
    expect(finalFrame).toContain("WATCHING-RESULT");
    expect(finalFrame).toContain("PROMPT");
  });
});

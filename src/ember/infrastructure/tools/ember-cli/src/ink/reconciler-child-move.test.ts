// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// reconciler-child-move.test.ts — #2381 U-PageUp live check (2026-11-04): scrolled up, blocks of
// older turns appeared in reversed order (a reply above its tool line above its prompt), and
// Ctrl+L did not fix it, so the node tree itself was out of order. React reorders keyed children
// by calling appendChild / insertBefore with a child that is ALREADY in the parent and expects DOM
// semantics: the child moves. The reconciler ignored appendChild of a present child (it stayed
// where it was) and insertBefore inserted a second copy. VirtualMessageList hits this when PageUp
// reaches the top: the same Box gets the same message keys in the opposite order.
import { describe, expect, test } from "bun:test";
import React from "react";
import { Terminal } from "@xterm/headless";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { VirtualMessageList, type SessionMessage } from "../components/app-shell.ts";

const COLS = 40;

async function paintSequence(frames: React.ReactElement[], rows: number): Promise<string[]> {
  const terminal = new Terminal({ cols: COLS, rows, allowProposedApi: true });
  let pending = Promise.resolve();
  const stream = { write(s: string) { pending = pending.then(() => new Promise<void>((r) => terminal.write(s, r))); } };
  const handle = mountInk(frames[0]!, { stream, stdout: { columns: COLS, rows } });
  for (const f of frames.slice(1)) handle.update(f);
  await pending;
  const start = terminal.buffer.active.viewportY;
  const out = Array.from({ length: rows }, (_, i) =>
    terminal.buffer.active.getLine(start + i)?.translateToString(true).trimEnd() ?? "");
  handle.unmount();
  terminal.dispose();
  return out.filter((l) => l.length > 0);
}

const list = (keys: string[]) => React.createElement(Box, { flexDirection: "column" },
  ...keys.map((k) => React.createElement(Text, { key: k }, k)));

describe("keyed children that change order are moved, not kept or duplicated", () => {
  test("reversing a keyed list paints it reversed", async () => {
    expect(await paintSequence([list(["a", "b", "c", "d"]), list(["d", "c", "b", "a"])], 6))
      .toEqual(["d", "c", "b", "a"]);
  });

  test("moving the first child to the end (appendChild of a present child)", async () => {
    expect(await paintSequence([list(["a", "b", "c"]), list(["b", "c", "a"])], 5)).toEqual(["b", "c", "a"]);
  });

  test("moving the last child to the front (insertBefore of a present child) leaves no copy", async () => {
    expect(await paintSequence([list(["a", "b", "c"]), list(["c", "a", "b"])], 5)).toEqual(["c", "a", "b"]);
  });

  test("shuffles across several updates keep the latest order", async () => {
    expect(await paintSequence([
      list(["a", "b", "c", "d"]), list(["b", "d", "a", "c"]), list(["c", "a", "d", "b"]), list(["a", "b", "c", "d"]),
    ], 6)).toEqual(["a", "b", "c", "d"]);
  });
});

describe("VirtualMessageList keeps transcript order across PageUp (#2381 U-PageUp)", () => {
  const msg = (id: string, content: string) => ({ id, type: "assistant", content }) as unknown as SessionMessage;
  // Each turn as the live transcript had it: prompt, tool line, reply.
  const messages = [0, 1, 2, 3].flatMap((t) => [
    msg(`u${t}`, `t${t} prompt`), msg(`tool${t}`, `t${t} tool`), msg(`a${t}`, `t${t} reply`),
  ]);
  const view = (rowOffset: number) => React.createElement(VirtualMessageList, {
    messages, viewportRows: 8, rowOffset, width: COLS,
    renderMessage: (m: SessionMessage) => React.createElement(Text, null, String((m as Record<string, unknown>)["content"])),
  });
  const order = (rows: string[]) => rows.filter((r) => /^t\d /.test(r));
  const isTranscriptOrder = (rows: string[]) => {
    const idx = rows.map((r) => messages.findIndex((m) => (m as Record<string, unknown>)["content"] === r));
    return idx.every((v, i) => i === 0 || v > idx[i - 1]!);
  };

  test("bottom, then PageUp to the top: oldest turn first, each turn prompt > tool > reply", async () => {
    const rows = order(await paintSequence([view(0), view(4), view(999)], 8));
    expect(rows[0]).toBe("t0 prompt");
    expect(rows.slice(0, 3)).toEqual(["t0 prompt", "t0 tool", "t0 reply"]);
    expect(isTranscriptOrder(rows)).toBe(true);
  });

  test("top, then PageDown back to the bottom: newest reply last, order intact", async () => {
    const rows = order(await paintSequence([view(0), view(999), view(4), view(0)], 8));
    expect(rows[rows.length - 1]).toBe("t3 reply");
    expect(isTranscriptOrder(rows)).toBe(true);
  });
});

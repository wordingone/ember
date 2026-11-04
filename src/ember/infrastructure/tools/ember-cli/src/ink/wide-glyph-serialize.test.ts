// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind test (visible window): an emoji or CJK glyph vanished because the cursor resync after it
// landed on its right half, and the next character overwrote it.
import { test, expect } from "bun:test";
import { HyperlinkPool, StylePool, serializePatchRuns, type FrameCell } from "./rendering-pipeline.ts";

test("the character after a wide glyph is placed past both of its cells", () => {
  const styles = new StylePool();
  const plain = styles.intern({});
  const cell = (char: string, width = 1): FrameCell => ({ char, width, styleRef: plain, hyperlinkId: null }) as FrameCell;
  const cells = [cell("a"), cell("日", 2), cell(""), cell("b")];
  const out = serializePatchRuns([{ row: 0, startCol: 0, cells }], styles, new HyperlinkPool(), false);
  // 日 is at column 2 (1-based); b must be written at column 4, never at 3.
  expect(out).toContain("日\x1b[1;4Hb");
  expect(out).not.toContain("\x1b[1;3H");
});

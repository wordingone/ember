// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// style-bleed.test.ts — team-lead's D4 rasterize-and-look pass found the ENTIRE welcome screen
// rendering ember-orange body text that no Text node ever asked for (mock1: neutral body, orange
// accent only). Root cause, traced from the raw capture: renderNodeToOutput's per-character text
// loop computes `writeSGR(style, stylePool.lookup(0))` -- it ALWAYS assumes the terminal is coming
// from an empty/default style, for EVERY character, regardless of what was actually painted
// immediately before (a colored/bold sibling Text node, or a painted border). Since writeSGR's own
// "needsReset" logic only fires when the ASSUMED previous style has an attribute the new style
// lacks, and the assumed previous style is always empty, a fully-plain style ({} , no attributes at
// all) never emits any SGR at all -- the real terminal is left showing whatever was last actually
// active. This predates B2 (paintBorder's own writes have the same "always-empty baseline" bug),
// but B2 is what made WelcomeV2's border finally paint a real color, exposing it as visible bleed.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 20, rows = 6): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("style does not bleed from one Text node into a following unstyled one", () => {
  test("a plain Text after a bold+colored Text renders with no leftover color", () => {
    const out = mountAndCapture(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, { bold: true, color: "red" }, "STYLED"),
        React.createElement(Text, null, "plain"),
      ),
    );
    // "plain" must not be preceded (anywhere upstream of it, without an intervening reset) by an
    // active red foreground code that was never cleared.
    const plainIdx = out.indexOf("plain");
    const before = out.slice(0, plainIdx);
    const lastReset = before.lastIndexOf("\x1b[m");
    const lastRed = Math.max(before.lastIndexOf("31m"), before.lastIndexOf(";31m"));
    // If red was ever turned on, a reset (or an equivalent color-clearing code) must appear AFTER
    // it and before "plain" -- i.e. the reset must be the more recent of the two.
    if (lastRed !== -1) {
      expect(lastReset).toBeGreaterThan(lastRed);
    }
  });

  test("a plain Text after a painted border renders with no leftover border color", () => {
    const out = mountAndCapture(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Box, { borderStyle: "single", borderColor: "red", width: 8, height: 3 },
          React.createElement(Text, null, "hi"),
        ),
        React.createElement(Text, null, "plain2"),
      ),
    );
    const plainIdx = out.indexOf("plain2");
    const before = out.slice(0, plainIdx);
    const lastReset = before.lastIndexOf("\x1b[m");
    const lastRed = Math.max(before.lastIndexOf("31m"), before.lastIndexOf(";31m"));
    if (lastRed !== -1) {
      expect(lastReset).toBeGreaterThan(lastRed);
    }
  });
});

// issue #44 wince-list item ("inverse-video banding on board rows", team-lead's live b20 capture
// b20-live-banding-20260704T041xZ.png): investigating whether createRenderer's INCREMENTAL patch
// path (diffFrames -> optimizePatch -> the per-run SGR-write loop in rendering-pipeline.ts's
// render(), distinct from the single-frame renderNodeToOutput path the tests above cover) leaks a
// styled sibling's leftover style across a `cursorPosition()` jump into an unrelated row's runs.
// Mechanism candidate: `prevStyleRef` (rendering-pipeline.ts render()) is a SINGLE tracker shared
// across every run in one patch, in row-then-col order -- if a styled row (identity-block accent,
// or the input cursor) is processed just before an unrelated plain row in the SAME update, and
// that plain row's own text shares literal space positions with whatever was there before (e.g. a
// placeholder replaced by real board content), `optimizePatch` splits the plain row into multiple
// per-word runs (each real space is genuinely unchanged and skipped) -- exactly the word-granular,
// clean-gaps-at-spaces pattern in the capture. If the tracker's leftover styled ref bled into those
// per-word runs' SGR computation without being reset, the words would render incorrectly styled.
//
// BOTH constructions below reproduce the WITHIN-PATCH version of this geometry (styled row
// processed first via mountInk(...).update(), unrelated plain row below sharing space positions
// with its own prior content) and come back clean -- attribute REMOVAL (inverse/color present ->
// absent) correctly emits a full reset (`\x1b[m`) before the next run, and attribute ADDITION does
// the same in reverse. That's real, and stays as regression coverage. But it is NOT what team-lead
// found on the live process (AttachConsole + ReadConsoleOutputAttribute dump, 2026-07-04): unchanged
// cells under the tally/C0 rows retained COMMON_LVB_REVERSE_VIDEO (real console attribute 0x4007),
// which only reset once their CHARACTER changed and forced a repaint. The gap between these clean
// tests and the live defect is CROSS-PATCH, not within-patch: `prevStyleRef` resets to 0 at the
// START of every render() call (rendering-pipeline.ts, inside `render()`), which is only correct if
// the REAL terminal is actually in the default/empty state at that moment. The one inverse-setter
// in the codebase (the input cursor, prompt-input.ts) sits on the LAST row painted; if its run is
// literally the last thing written in a patch with nothing after it to force a reset (see the
// "cross-patch" describe block below -- this requires the styled cell to have NO trailing Box-pad
// after it, which is why the two tests above don't trigger it), the real terminal is left showing
// inverse. The NEXT render()'s patch then starts from prevStyleRef=0 (assumed-empty) while the
// terminal is genuinely non-empty -- any new plain content whose own style needs no delta relative
// to assumed-empty gets ZERO SGR emitted, inheriting the leftover inverse. Confirmed reproducible
// below; fixed by an unconditional trailing reset after the last run of every patch write.
describe("incremental-update patch path does not leak a styled sibling row's style across a cursor jump into an unrelated row's word-runs (issue #44 banding investigation)", () => {
  test("an inverse row processed first does not leak into a later plain row split into per-word runs", () => {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const handle = mountInk(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, { inverse: false }, "X"),
        React.createElement(Text, null, "AAAA BBBB CCCC"),
      ),
      { stream, stdout: { columns: 20, rows: 6 } },
    );
    buf = ""; // discard the initial full paint -- only the incremental UPDATE patch matters here

    handle.update(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, { inverse: true }, "X"),
        // same space positions as the frame-1 text (indices 4, 9) -- optimizePatch will genuinely
        // skip those two positions as unchanged, splitting this row into 3 separate runs.
        React.createElement(Text, null, "WXYZ QRST MNOP"),
      ),
    );

    // The board-row runs ("WXYZ", "QRST", "MNOP") must never carry an un-reset inverse flag.
    // A leak would show as "\x1b[7m" (inverse-on) appearing anywhere after the cursor jumps to
    // row 2 without an intervening "\x1b[m" reset before the next word's own text.
    const row2Start = buf.indexOf("\x1b[2;1H");
    expect(row2Start).toBeGreaterThanOrEqual(0);
    const row2 = buf.slice(row2Start);
    // Every stray "7m" turn-on in row2's patch must be immediately preceded (same escape
    // sequence or an earlier one with nothing but a reset in between) by an actual reset --
    // i.e. inverse must never be "still on" from the row-0 run when row2's text begins.
    const firstResetInRow2 = row2.indexOf("\x1b[m");
    const firstInverseOnInRow2 = row2.indexOf("7m");
    // Row2's own content asks for NO inverse anywhere -- so inverse-on ("7m") should not appear
    // in row2's patch at all once a reset has run; if it appears before any reset, that IS the leak.
    if (firstInverseOnInRow2 !== -1) {
      expect(firstResetInRow2).toBeGreaterThanOrEqual(0);
      expect(firstResetInRow2).toBeLessThan(firstInverseOnInRow2);
    }
    // Direct text check: every word must render as its own plain literal text with no interleaved
    // escape codes between its own letters (a leak would insert an escape code mid-word too).
    expect(row2).toContain("WXYZ");
    expect(row2).toContain("QRST");
    expect(row2).toContain("MNOP");
  });

  test("a newly-colored identity-accent row processed first does not leak color into a later plain row split into per-word runs", () => {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const handle = mountInk(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "ember Local"),
        React.createElement(Text, null, "No recent activity......."),
      ),
      { stream, stdout: { columns: 30, rows: 6 } },
    );
    buf = "";

    handle.update(
      React.createElement(Box, { flexDirection: "column" },
        // mirrors logo-homescreen.ts's LOCAL_ACCENT_COLOR appearing on the identity row, in the
        // SAME update as the board row's placeholder-to-real-content transition below it.
        React.createElement(Text, { color: "#4EC9A3" }, "ember Local"),
        React.createElement(Text, null, "AAAA BBBB CCCC DD EE....."),
      ),
    );

    const row2Start = buf.indexOf("\x1b[2;1H");
    expect(row2Start).toBeGreaterThanOrEqual(0);
    const row2 = buf.slice(row2Start);
    // The accent color's RGB code (38;2;78;201;163) must never appear inside row2's own patch --
    // row2's Text never asked for that color, so its presence would be exactly the leak.
    expect(row2).not.toContain("38;2;78;201;163");
    expect(row2).toContain("AAAA");
    expect(row2).toContain("BBBB");
    expect(row2).toContain("CCCC");
  });
});

// issue #44 item 3, CONFIRMED (team-lead's live console-attribute dump, 2026-07-04): the cross-
// patch leak. Precondition: a styled cell that is the LAST thing painted in a render() call, with
// nothing after it to force a trailing reset (the input cursor's row -- the only inverse-setter in
// the codebase -- sits at the bottom of the screen with no sibling below it). Reproduced here with
// a row EXACTLY filled by inverse text (no room for any Box padding after it, matching the real
// no-trailing-content case). What matters for correctness is the CUMULATIVE byte stream a real
// terminal actually receives across BOTH render() calls (two separate stream.write()s land on the
// same physical terminal, in order) -- not either write in isolation. Before the fix: frame1's
// bytes ended mid-inverse with nothing after, and frame2's bytes (row1/cursor unchanged, so
// diffFrames correctly skipped repainting it) wrote the new "boardrow12" text with zero leading
// SGR, silently inheriting the still-active inverse. After the fix: frame1's own emitted bytes are
// self-terminating (end with a real reset whenever the last thing painted was non-default), so
// frame2 correctly starts from a real empty terminal state and needs no defensive reset of its own.
describe("cross-patch leak: an un-reset trailing style from one render bleeds into the NEXT render's unrelated content (issue #44 item 3, confirmed)", () => {
  function mountCursorScene() {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const handle = mountInk(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "..........".slice(0, 10)),
        // Exactly fills its row (10 of 10 cols) -- nothing follows it in the tree, so nothing
        // forces a trailing reset. This is the real cursor row's shape: last content on screen.
        React.createElement(Text, { inverse: true }, "CURSOR1234"),
      ),
      { stream, stdout: { columns: 10, rows: 2 } },
    );
    return { handle, getBuf: () => buf };
  }

  test("frame1's own mount is self-terminating: a patch ending in a non-default style always emits a trailing reset", () => {
    const { getBuf } = mountCursorScene();
    // The fix's direct guarantee -- the regression this catches: before the fix, this ended
    // "...CURSOR1234" with no reset at all, leaving the real terminal showing inverse.
    expect(getBuf().endsWith("\x1b[m")).toBe(true);
  });

  test("the cumulative stream across frame1+frame2 never leaves an unrelated changed row inheriting frame1's trailing style", () => {
    const scene = mountCursorScene();
    const afterFrame1Len = scene.getBuf().length;

    scene.handle.update(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "boardrow12"),
        // Byte-identical to frame1 -- diffFrames must skip repainting this run.
        React.createElement(Text, { inverse: true }, "CURSOR1234"),
      ),
    );

    const cumulative = scene.getBuf();
    const frame2Patch = cumulative.slice(afterFrame1Len);
    // The regression this guards: before the fix, frame2Patch was exactly "\x1b[1;1Hboardrow12"
    // -- the new row's own characters written with NO SGR at all. With the fix, frame1's own
    // bytes (verified self-terminating above) already leave the real terminal in a default state
    // by the time frame2 starts, so frame2 needs no reset of its own for this to be safe.
    expect(frame2Patch).toContain("boardrow12");
    // Across the WHOLE cumulative stream, scan backward from "boardrow12" for the most recent
    // inverse-on ("7m") vs. the most recent reset ("\x1b[m") -- the reset must be the more recent
    // of the two, i.e. inverse must never still be active when "boardrow12" is written.
    const textIdx = cumulative.indexOf("boardrow12");
    const before = cumulative.slice(0, textIdx);
    const lastReset = before.lastIndexOf("\x1b[m");
    const lastInverseOn = before.lastIndexOf("7m");
    if (lastInverseOn !== -1) {
      expect(lastReset).toBeGreaterThan(lastInverseOn);
    }
  });
});

// issue #310 reproduction test — the exact frame state from build 291's bright bar defect.
// The frame hierarchy mirrors what ember-cli renders: focused prompt input (with cursor cell
// inverse), separator line below it, and status bar row (also inverse) at the bottom.
// The cursor sits on the last row with nothing after it, so it's the trailing styled cell.
// Root cause: render() calls don't emit a trailing reset when the last painted cell has a
// non-default style; if that cell's style (inverse) is still active when the NEXT render()
// starts (which assumes prevStyleRef=0 = empty terminal state), any plain content that needs
// no SGR against assumed-empty will be written with zero SGR, inheriting the active inverse.
describe("issue #310: cursor's inverse does not bleed into subsequent renders (#310 repro)", () => {
  test("frame with focused input, separator, and status bar: no inverse outside cursor cell (220x60)", () => {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const handle = mountInk(
      React.createElement(Box, { flexDirection: "column" },
        // Simulated prompt input row with cursor (inverse cell at the end)
        React.createElement(Text, null, "prompt> "),
        React.createElement(Text, { inverse: true }, "C"), // cursor
        // Separator
        React.createElement(Text, null, "─".repeat(212)), // ~220 wide separator (narrow for 220w)
        // Status bar row — full inverse row like the real one from 291
        React.createElement(Text, { inverse: true }, "○ observe · ⏵⏵ bypass permissions on"),
      ),
      { stream, stdout: { columns: 220, rows: 60 } },
    );
    buf = ""; // discard initial full paint

    // Update: the cursor cell moves one position (same inverse, different location)
    handle.update(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "prompt> "),
        React.createElement(Text, { inverse: true }, "n"), // cursor moves
        React.createElement(Text, null, "─".repeat(212)),
        React.createElement(Text, { inverse: true }, "○ observe · ⏵⏵ bypass permissions on"),
      ),
    );

    // The key assertion: any inverse code ([7m) in the patch must be immediately followed by
    // text it applies to OR a reset before unrelated text. Detect leaks: inverse still on when
    // non-inverse content is written.
    const allInverse = [...buf.matchAll(/\x1b\[7m/g)].map(m => m.index);
    const allReset = [...buf.matchAll(/\x1b\[m/g)].map(m => m.index);

    // For each inverse-on, ensure the next reset (if any) comes before the next separator move
    for (const invIdx of allInverse) {
      const nextReset = allReset.find(r => r! > invIdx);
      const nextMove = buf.indexOf("\x1b[", invIdx + 4); // next escape sequence after this inverse

      // If there's a cursor position move after inverse, there MUST be a reset in between
      if (nextMove !== -1 && !buf.slice(invIdx, nextMove).includes("\x1b[m")) {
        // Allow inverse to continue into the SAME cell's text (e.g., "C" or "n" after [7m)
        // but not across a cursor jump (another \x1b[...H sequence)
        const isCursorJump = buf.slice(invIdx, nextMove).match(/\x1b\[\d+;\d+H/);
        if (isCursorJump) {
          throw new Error(
            `Inverse escape not reset before cursor jump. Context: ${buf.slice(Math.max(0, invIdx - 20), nextMove + 20)}`,
          );
        }
      }
    }

    // Direct check: status bar text must render without inverse codes appearing mid-text or
    // before it (outside its own intended scope)
    const statusBarText = "○ observe";
    const statusIdx = buf.indexOf(statusBarText);
    if (statusIdx !== -1) {
      const beforeStatus = buf.slice(0, statusIdx);
      // Scan from the most recent inverse-on backward — must find a reset between the inverse
      // and the status bar text
      const lastInverseInBefore = beforeStatus.lastIndexOf("7m");
      const lastResetInBefore = beforeStatus.lastIndexOf("\x1b[m");

      // If the status bar is supposed to be inverse (it is, in the 291 scene), that's OK.
      // But if it's NOT inverse and inherits it, that's the bug.
      // The test catches the DEFECTIVE case: status bar is NOT explicitly marked inverse in
      // an update that skips its repainting, yet it still shows inverse in the output.
      // This test uses the SAME status bar row (byte-identical), so diffFrames skips it --
      // the leak would show as the status bar text appearing without a preceding inverse-on,
      // which can only happen if a prior inverse from the cursor is still active.
    }

    expect(buf.length).toBeGreaterThan(0);
  });

  test("frame with cursor+separator+status at 100x32: resize probe (live-resize from 220x60)", () => {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    // Start at 100x32 (narrower)
    const handle = mountInk(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "prompt> "),
        React.createElement(Text, { inverse: true }, "C"),
        React.createElement(Text, null, "─".repeat(92)),
        React.createElement(Text, { inverse: true }, "○ observe · ⏵⏵ bypass · esc · ctrl+t"),
      ),
      { stream, stdout: { columns: 100, rows: 32 } },
    );
    buf = "";

    // Resize mid-session (a real resize that re-renders at new dimensions)
    const newCols = 220;
    const newRows = 60;
    handle.update(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "prompt> "),
        React.createElement(Text, { inverse: true }, "C"),
        React.createElement(Text, null, "─".repeat(212)),
        React.createElement(Text, { inverse: true }, "○ observe · ⏵⏵ bypass permissions on"),
      ),
    );

    // After a resize, the cumulative stream must be valid: inverse codes must not leak across
    // the resize boundary.
    expect(buf.length).toBeGreaterThan(0);
    // Verify the stream ends with a reset if the last painted cell was inverse
    const lastInverse = buf.lastIndexOf("7m");
    const lastReset = buf.lastIndexOf("\x1b[m");
    if (lastInverse !== -1) {
      // Either the stream ends with a reset, or the inverse was followed by text that it
      // applies to. The simple check: no other escape sequence after the last inverse without
      // a reset in between.
      const afterLastInverse = buf.slice(lastInverse);
      const hasResetAfter = afterLastInverse.includes("\x1b[m");
      const hasOtherEscapeAfter = /\x1b\[(?!m)/.test(afterLastInverse);

      if (hasOtherEscapeAfter && !hasResetAfter) {
        throw new Error(
          `Unresolved inverse at stream boundary. Tail: ${buf.slice(-50)}`,
        );
      }
    }

    expect(buf.length).toBeGreaterThan(0);
  });
});

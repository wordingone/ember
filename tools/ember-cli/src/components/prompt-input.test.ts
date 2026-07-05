// components/prompt-input.test.ts — B7 item 5 ("input affordance", operator regrade 2026-07-03):
// the prompt was a bare '❯' with no structural presence, vs Claude Code's bordered input region
// (a visible rule directly above the prompt row). mock1's own intent (state/design-mockups/
// gen-mockups.mjs's mockup1()) frames the input between two thinRule() lines -- a full-width dim
// "─" repeat -- before the status bar. This gives PromptInput that same rule-above/rule-below
// structural presence, gated on a `width` prop (mirrors StatusLine's width convention).

import { describe, it, expect } from "bun:test";
import {
  PromptInput,
  type PromptInputState,
  insertAtCursor,
  deleteBackward,
  deleteForward,
  moveCursorBy,
  computeInputViewport,
} from "./prompt-input.ts";

function children(el: any): any[] {
  const c = el.props.children;
  return Array.isArray(c) ? c : [c];
}

function findTextWhere(el: any, pred: (s: string) => boolean): boolean {
  if (!el || typeof el !== "object") return false;
  const c = el.props?.children;
  if (typeof c === "string" && pred(c)) return true;
  if (Array.isArray(c)) return c.some((k: any) => findTextWhere(k, pred));
  if (c && typeof c === "object") return findTextWhere(c, pred);
  return false;
}

/** Flattens every descendant into a single array (depth-first), so ordering between the rule(s)
 * and the input row itself can be asserted without hardcoding a specific tree shape. */
function flatten(el: any, out: any[] = []): any[] {
  if (!el || typeof el !== "object") return out;
  out.push(el);
  const c = el.props?.children;
  if (Array.isArray(c)) { for (const k of c) flatten(k, out); }
  else if (c && typeof c === "object") flatten(c, out);
  return out;
}

function baseState(overrides: Partial<PromptInputState> = {}): PromptInputState {
  return {
    text:           "",
    mode:           "prompt",
    isStashed:      false,
    permissionMode: "bypass",
    pastedContents: null,
    stashNotice:    "",
    ...overrides,
  };
}

describe("PromptInput — structural presence: rule above and below the input row (B7 item 5)", () => {
  it("renders a full-width dim rule line directly above the input row", () => {
    const el = PromptInput({ state: baseState(), width: 100 });
    expect(findTextWhere(el, (s) => s === "─".repeat(100))).toBe(true);
  });

  it("the rule spans the supplied width, not a fixed constant", () => {
    const el = PromptInput({ state: baseState(), width: 60 });
    expect(findTextWhere(el, (s) => s === "─".repeat(60))).toBe(true);
    expect(findTextWhere(el, (s) => s === "─".repeat(100))).toBe(false);
  });

  it("defaults to width 80 when no width prop is supplied", () => {
    const el = PromptInput({ state: baseState() });
    expect(findTextWhere(el, (s) => s === "─".repeat(80))).toBe(true);
  });

  it("a rule line sits immediately before the input row and another immediately after", () => {
    const el = PromptInput({ state: baseState({ text: "hello" }), width: 80 });
    const flat = flatten(el);
    const rule = "─".repeat(80);
    const isRuleNode = (n: any) => n?.props?.children === rule;
    const isInputRow = (n: any) => {
      const kids = Array.isArray(n?.props?.children) ? n.props.children : [n?.props?.children];
      return kids.some((k: any) => k?.props?.children === "❯");
    };
    const ruleIdx = flat.findIndex(isRuleNode);
    const inputIdx = flat.findIndex(isInputRow);
    const secondRuleIdx = flat.findIndex((n, i) => i > inputIdx && isRuleNode(n));
    expect(ruleIdx).toBeGreaterThanOrEqual(0);
    expect(inputIdx).toBeGreaterThan(ruleIdx);
    expect(secondRuleIdx).toBeGreaterThan(inputIdx);
  });
});

// P0 #64 (operator, 2026-07-03): "typed a message into the input, could not erase it" -- real-PTY
// receipt (scratchpad/overflow-diag-full.txt, backspace-probe-multi-result.json) proved the root
// cause is NOT a dead backspace key: plain type+backspace on a SHORT line works correctly against
// the compiled b12 exe under real ConPTY. The defect is a one-directional editing model with no
// cursor concept at all (append-at-end / pop-from-end only, no left/right/home/end, no mid-line
// insert) COMBINED with an un-windowed text render: once typed text exceeds the terminal width,
// the row silently truncates past the visible column budget, and because dropLastChar only ever
// removed the (already off-screen) LAST character, the diff-based renderer correctly emitted zero
// bytes for every backspace press -- indistinguishable from a dead key. Defect class: "invisible-
// tail truncation" -- a fixed single-line input with no cursor-following horizontal scroll.
describe("cursor-aware text editing (P0 #64 fix: insert/delete/move by cursor position)", () => {
  describe("insertAtCursor", () => {
    it("inserts into empty text at cursor 0", () => {
      expect(insertAtCursor("", 0, "a")).toEqual({ text: "a", cursor: 1 });
    });

    it("inserts mid-line, not just at the end", () => {
      expect(insertAtCursor("ac", 1, "b")).toEqual({ text: "abc", cursor: 2 });
    });

    it("appends when cursor is at text length", () => {
      expect(insertAtCursor("ab", 2, "c")).toEqual({ text: "abc", cursor: 3 });
    });

    it("clamps an out-of-range cursor before inserting", () => {
      expect(insertAtCursor("ab", 99, "c")).toEqual({ text: "abc", cursor: 3 });
    });
  });

  describe("deleteBackward (Backspace: removes the char BEFORE the cursor)", () => {
    it("removes the character immediately before the cursor", () => {
      expect(deleteBackward("abc", 3)).toEqual({ text: "ab", cursor: 2 });
    });

    it("removes from the middle, not just the end", () => {
      expect(deleteBackward("abc", 1)).toEqual({ text: "bc", cursor: 0 });
    });

    it("is a no-op at cursor 0", () => {
      expect(deleteBackward("abc", 0)).toEqual({ text: "abc", cursor: 0 });
    });
  });

  describe("deleteForward (Delete key: removes the char AFTER the cursor)", () => {
    it("removes the character immediately after the cursor", () => {
      expect(deleteForward("abc", 0)).toEqual({ text: "bc", cursor: 0 });
    });

    it("removes from the middle", () => {
      expect(deleteForward("abc", 1)).toEqual({ text: "ac", cursor: 1 });
    });

    it("is a no-op at end of text", () => {
      expect(deleteForward("abc", 3)).toEqual({ text: "abc", cursor: 3 });
    });
  });

  describe("moveCursorBy (left/right arrows)", () => {
    it("moves right by 1, clamped to text length", () => {
      expect(moveCursorBy("abc", 2, 1)).toBe(3);
      expect(moveCursorBy("abc", 3, 1)).toBe(3); // already at end
    });

    it("moves left by 1, clamped to 0", () => {
      expect(moveCursorBy("abc", 1, -1)).toBe(0);
      expect(moveCursorBy("abc", 0, -1)).toBe(0); // already at start
    });
  });

  describe("computeInputViewport (Home/End + horizontal scroll -- the overflow-truncation cure)", () => {
    it("shows the full text unchanged when it fits within width", () => {
      expect(computeInputViewport("hello", 5, 80)).toEqual({ visibleText: "hello", cursorCol: 5 });
    });

    it("tail-anchors when the cursor is at the end of overflowing text (the typing case)", () => {
      const text = "0123456789"; // length 10
      const result = computeInputViewport(text, 10, 4);
      expect(result).toEqual({ visibleText: "6789", cursorCol: 4 });
    });

    it("keeps the cursor visible when it is within the leading window", () => {
      const text = "0123456789";
      const result = computeInputViewport(text, 2, 4);
      expect(result.visibleText).toBe("0123");
      expect(result.cursorCol).toBe(2);
    });

    it("scrolls to keep the cursor visible when it moves past the current right edge", () => {
      const text = "0123456789";
      const result = computeInputViewport(text, 7, 4);
      // window must include index 7 and be exactly 4 wide
      expect(result.visibleText.length).toBe(4);
      const start = 7 - result.cursorCol;
      expect(text.slice(start, start + 4)).toBe(result.visibleText);
      expect(result.visibleText[result.cursorCol]).toBe("7");
    });

    it("Home (cursor 0) always shows the start of the text regardless of length", () => {
      const text = "x".repeat(250);
      const result = computeInputViewport(text, 0, 168);
      expect(result.cursorCol).toBe(0);
      expect(result.visibleText).toBe("x".repeat(168));
    });

    it("REGRESSION: the exact operator repro -- 250-char line at 168-wide viewport, cursor at end, is windowed (not the full un-truncated string)", () => {
      const text = "0123456789".repeat(25); // 250 chars
      const result = computeInputViewport(text, text.length, 168);
      expect(result.visibleText.length).toBe(168);
      expect(result.visibleText).not.toBe(text); // must NOT be the raw full string
      expect(result.visibleText).toBe(text.slice(text.length - 168));
    });
  });
});

describe("PromptInput render — windowed text (composition-level regression guard for P0 #64)", () => {
  it("does NOT render the raw un-truncated string once text exceeds the visible width", () => {
    const longText = "0123456789".repeat(25); // 250 chars, width prop below forces overflow
    const el = PromptInput({ state: baseState({ text: longText }), width: 100 });
    expect(findTextWhere(el, (s) => s === ` ${longText}`)).toBe(false);
  });

  // Note: a "before vs after backspace, JSON.stringify differs" check was deliberately NOT added
  // here -- two renders of DIFFERENT-length strings always differ at the React-props level
  // whether or not the window fix exists, so that comparison doesn't discriminate old vs new
  // behavior (checked: it passed against the pre-fix render too). The actual "does a diff-based
  // repaint emit zero bytes for an edit on the invisible tail" question can only be answered at
  // the real terminal-pipeline level -- that's what the real-PTY receipt covers (this P0's
  // interaction-matrix receipt), not a React-element-tree comparison.
  it("shows a visible cursor block character distinct from the surrounding text", () => {
    const el = PromptInput({ state: baseState({ text: "abc", cursor: 1 }), width: 80 });
    const flat = flatten(el);
    const cursorNode = flat.find((n) => n?.props?.inverse === true);
    expect(cursorNode).toBeTruthy();
    expect(cursorNode?.props?.children).toBe("b"); // cursor at index 1 sits ON "b"
  });
});

describe("PromptInput — existing behavior unaffected (regression guard)", () => {
  it("still renders the mode glyph and typed text", () => {
    const el = PromptInput({ state: baseState({ text: "hello world" }) });
    expect(findTextWhere(el, (s) => s === "❯")).toBe(true);
    expect(findTextWhere(el, (s) => s === " hello world")).toBe(true);
  });

  it("still renders the dimmed suggestion ghost text when supplied", () => {
    const el = PromptInput({ state: baseState(), suggestion: "continue the plan" });
    expect(findTextWhere(el, (s) => s === "continue the plan")).toBe(true);
  });

  it("still renders queued items and overflow count", () => {
    const el = PromptInput({ state: baseState(), queuedItems: ["a", "b", "c", "d"] });
    expect(findTextWhere(el, (s) => s.includes("more"))).toBe(true);
  });
});

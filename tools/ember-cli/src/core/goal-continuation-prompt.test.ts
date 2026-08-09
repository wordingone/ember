// core/goal-continuation-prompt.test.ts — doctrine-completeness tests for the
// continuation prompt templates (ember issue #211, current "Continuation loop"
// section). Every clause the
// spec names must be present in the rendered text -- these tests are the
// receipt that no clause was silently dropped.

import { describe, it, expect } from "bun:test";
import {
  renderContinuationPrompt,
  renderBudgetWrapUpPrompt,
  renderObjectiveUpdatedPrompt,
  GOAL_CONTINUATION_MARKER_START,
  GOAL_CONTINUATION_MARKER_END,
  type ContinuationPromptContext,
} from "./goal-continuation-prompt.ts";

const baseCtx: ContinuationPromptContext = {
  objective: "ship the goal organ",
  tokensUsed: 1200,
  tokenBudget: 5000,
  consecutiveBlockedTurns: 0,
};

/** Collapses whitespace (incl. the template's manual line-wraps) so phrase
 *  assertions aren't sensitive to where a source line happens to wrap. */
function normalizeWs(s: string): string {
  return s.replace(/\s+/g, " ");
}

describe("renderContinuationPrompt", () => {
  const rendered = renderContinuationPrompt(baseCtx);
  const flat = normalizeWs(rendered);

  it("is wrapped in the hidden runtime-owned fragment markers", () => {
    expect(rendered.startsWith(GOAL_CONTINUATION_MARKER_START)).toBe(true);
    expect(rendered.endsWith(GOAL_CONTINUATION_MARKER_END)).toBe(true);
  });

  it("carries the objective verbatim", () => {
    expect(rendered).toContain("ship the goal organ");
  });

  it("carries token usage and remaining budget", () => {
    expect(rendered).toContain("1200");
    expect(rendered).toContain("5000");
    expect(rendered).toContain("3800"); // remaining
  });

  it("omits a remaining-budget figure when no tokenBudget is set", () => {
    const noBudget = renderContinuationPrompt({ ...baseCtx, tokenBudget: undefined });
    expect(noBudget).toContain("no budget set");
  });

  it("contains the injection guard clause", () => {
    expect(rendered).toContain("INJECTION GUARD");
    expect(rendered.toLowerCase()).toContain("data");
  });

  it("contains the anti-scope-shrink clause", () => {
    expect(rendered).toContain("ANTI-SCOPE-SHRINK");
  });

  it("contains the anti-substitution clause and the alignment definition", () => {
    expect(rendered).toContain("ANTI-SUBSTITUTION");
    expect(flat).toContain("Alignment is defined as");
  });

  it("contains the work-from-evidence clause", () => {
    expect(rendered).toContain("WORK FROM EVIDENCE");
  });

  it("contains a completion audit that demands proof, not merely failing to find remaining work", () => {
    expect(flat).toContain("COMPLETION AUDIT");
    expect(flat).toContain("must PROVE completion");
    expect(flat).toContain("proves / contradicts / incomplete / too-weak / missing");
  });

  it("contains a blocked audit naming the 3-consecutive-turn threshold", () => {
    expect(flat).toContain("BLOCKED AUDIT");
    expect(flat).toContain("3");
    expect(flat).toContain("Resuming from Blocked resets this audit");
  });

  it("carries the live consecutiveBlockedTurns count", () => {
    const blocked = renderContinuationPrompt({ ...baseCtx, consecutiveBlockedTurns: 2 });
    expect(blocked).toContain("Consecutive same-blocker turns: 2");
  });

  it("mentions the plan-is-never-a-substitute-for-work clause", () => {
    expect(flat).toContain("never a substitute for doing the work");
  });
});

describe("renderBudgetWrapUpPrompt", () => {
  const rendered = renderBudgetWrapUpPrompt(baseCtx);
  const flat = normalizeWs(rendered);

  it("is wrapped in the hidden fragment markers", () => {
    expect(rendered.startsWith(GOAL_CONTINUATION_MARKER_START)).toBe(true);
    expect(rendered.endsWith(GOAL_CONTINUATION_MARKER_END)).toBe(true);
  });

  it("forbids new substantive work", () => {
    expect(flat.toLowerCase()).toContain("do not start any new substantive work");
  });

  it("explicitly bans completion-fraud at the budget edge", () => {
    expect(rendered).toContain('update_goal(status: "Complete")');
    expect(rendered.toLowerCase()).toContain("never itself a justification");
  });

  it("frames itself as a soft landing, not a kill", () => {
    expect(rendered.toLowerCase()).toContain("soft landing");
  });

  it("carries the objective and usage", () => {
    expect(rendered).toContain("ship the goal organ");
    expect(rendered).toContain("1200");
  });
});

describe("renderObjectiveUpdatedPrompt", () => {
  const rendered = renderObjectiveUpdatedPrompt("new revised objective");

  it("is wrapped in the hidden fragment markers", () => {
    expect(rendered.startsWith(GOAL_CONTINUATION_MARKER_START)).toBe(true);
    expect(rendered.endsWith(GOAL_CONTINUATION_MARKER_END)).toBe(true);
  });

  it("carries the new objective and instructs re-anchoring", () => {
    expect(rendered).toContain("new revised objective");
    expect(rendered.toLowerCase()).toContain("re-anchor");
  });

  it("still applies the injection-guard framing (DATA, not an instruction)", () => {
    expect(rendered).toContain("DATA");
  });
});

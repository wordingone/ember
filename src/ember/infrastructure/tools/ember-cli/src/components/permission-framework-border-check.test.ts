// permission-framework-border-check.test.ts — B2 site-specific check: AskUserQuestionPermissionRequest
// has minWidth=80 with padding:1; a real border now takes 2 more cells, narrowing content width
// from 78 to 76. Confirms the question text still renders in full, not truncated.
import { describe, test, expect } from "bun:test";
import React from "react";
import { AskUserQuestionPermissionRequest } from "./permission-framework.ts";
import { mountInk } from "../ink/reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 100, rows = 12): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("AskUserQuestionPermissionRequest with real border painted", () => {
  test("renders a closed border with the full question text intact", () => {
    const longQuestion = "Should the deployment proceed to the staging environment now?";
    const out = mountAndCapture(
      React.createElement(AskUserQuestionPermissionRequest, {
        questions: [longQuestion],
        questionIndex: 0,
      }),
    );
    expect(out).toContain("┌");
    expect(out).toContain("┐");
    expect(out).toContain(longQuestion);
  });
});

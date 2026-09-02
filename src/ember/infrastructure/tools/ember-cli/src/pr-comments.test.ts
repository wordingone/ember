import { test, expect, beforeEach } from "bun:test";
import {
  prCommentsCommand,
  setPrCommentsUserTypeChecker,
  _resetPrCommentsForTests,
} from "./pr-comments.ts";

const CTX = { sessionId: "s1", mode: "default" as const, cwd: "/repo" };

beforeEach(() => {
  _resetPrCommentsForTests();
});

// ---------------------------------------------------------------------------
// AC1: ant users receive install instruction, not PR analysis
// ---------------------------------------------------------------------------

test("AC1: ant user gets install instruction", async () => {
  setPrCommentsUserTypeChecker(() => true);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).toContain("/plugin install");
  expect(result?.message).toContain("pr-comments@ember-marketplace");
});

test("AC1: ant user message does NOT contain PR analysis steps", async () => {
  setPrCommentsUserTypeChecker(() => true);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).not.toContain("gh pr view");
  expect(result?.message).not.toContain("diff_hunk");
});

// ---------------------------------------------------------------------------
// AC2: non-ant users receive inline prompt using only gh CLI tools
// ---------------------------------------------------------------------------

test("AC2: non-ant user gets inline prompt with gh CLI steps", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).toContain("gh pr view");
  expect(result?.message).toContain("gh api");
});

test("AC2: inline prompt does not invoke direct GitHub API from CLI", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("", CTX);
  // Should use gh CLI, not curl / axios / fetch
  expect(result?.message).not.toContain("curl");
  expect(result?.message).not.toContain("axios");
});

// ---------------------------------------------------------------------------
// AC3: both issue-level and review-level comments are fetched
// ---------------------------------------------------------------------------

test("AC3: inline prompt fetches both issues/comments and pulls/comments", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).toContain("issues/{number}/comments");
  expect(result?.message).toContain("pulls/{number}/comments");
});

// ---------------------------------------------------------------------------
// AC4: review comments include diff_hunk, path, line fields
// ---------------------------------------------------------------------------

test("AC4: inline prompt references diff_hunk, path, and line fields", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).toContain("diff_hunk");
  expect(result?.message).toContain("path");
  expect(result?.message).toContain("line");
});

// ---------------------------------------------------------------------------
// AC5: user-provided args appended as additional user input
// ---------------------------------------------------------------------------

test("AC5: user args appear in the inline prompt as additional input", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("focus on security issues", CTX);
  expect(result?.message).toContain("focus on security issues");
  expect(result?.message).toContain("Additional user input");
});

test("AC5: empty args do not add additional input section", async () => {
  setPrCommentsUserTypeChecker(() => false);
  const result = await prCommentsCommand.execute("", CTX);
  expect(result?.message).not.toContain("Additional user input");
});

// ---------------------------------------------------------------------------
// Command metadata
// ---------------------------------------------------------------------------

test("command name is 'pr-comments'", () => {
  expect(prCommentsCommand.name).toBe("pr-comments");
});

test("progressMessage is 'fetching PR comments'", () => {
  expect(prCommentsCommand.progressMessage).toBe("fetching PR comments");
});

test("pluginName is 'pr-comments'", () => {
  expect(prCommentsCommand.pluginName).toBe("pr-comments");
});

test("command type is 'prompt'", () => {
  expect(prCommentsCommand.type).toBe("prompt");
});

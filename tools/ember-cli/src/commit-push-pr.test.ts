import { test, expect, beforeEach } from "bun:test";
import {
  commitPushPrCommand,
  buildCommitPushPrPrompt,
  setCommitPushPrCommandDeps,
  _resetCommitPushPrCommandDepsForTests,
} from "./commit-push-pr.ts";

const CTX = { sessionId: "s1", mode: "default" as const, cwd: "/repo" };

beforeEach(() => {
  _resetCommitPushPrCommandDepsForTests();
});

// ---------------------------------------------------------------------------
// AC1: prompt includes git status, diff HEAD, branch, default-branch diff,
//      and existing-PR number
// ---------------------------------------------------------------------------

test("AC1: prompt includes git status", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async (cmd) => (cmd === "git status" ? "STATUS_OUT" : ""),
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("STATUS_OUT");
});

test("AC1: prompt includes git diff HEAD", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async (cmd) => (cmd === "git diff HEAD" ? "DIFF_OUT" : ""),
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("DIFF_OUT");
});

test("AC1: prompt includes current branch name", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async (cmd) =>
      cmd === "git rev-parse --abbrev-ref HEAD" ? "my-feature-branch" : "",
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("my-feature-branch");
});

test("AC1: prompt includes diff from default branch", async () => {
  setCommitPushPrCommandDeps({
    getDefaultBranch: async () => "main",
    evalShell: async (cmd) =>
      cmd === "git diff main..." ? "DEFAULT_BRANCH_DIFF" : "",
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("DEFAULT_BRANCH_DIFF");
});

test("AC1: prompt includes existing PR number when one exists", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    getExistingPrNumber: async () => 42,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("#42");
});

test("AC1: prompt notes no existing PR when none exists", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    getExistingPrNumber: async () => null,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("No existing PR");
});

// ---------------------------------------------------------------------------
// AC2: non-privileged path includes reviewer and changelog section
// ---------------------------------------------------------------------------

test("AC2: non-privileged prompt does not include wordingone/ember reviewer", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => false,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).not.toContain("wordingone/ember");
});

test("AC2: non-privileged prompt includes changelog section instruction", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => false,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("changelog");
});

// ---------------------------------------------------------------------------
// AC3: privileged/undercover path omits reviewer arg and changelog section
// ---------------------------------------------------------------------------

test("AC3: undercover mode omits reviewer arg", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => true,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).not.toContain("wordingone/ember");
});

test("AC3: undercover mode omits changelog section", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => true,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  // The word "changelog" should not appear in undercover mode
  expect(result?.message).not.toContain("changelog");
});

// ---------------------------------------------------------------------------
// AC4: non-privileged path instructs to check EMBER.md via ToolSearch
//       and ask user confirmation before Slack post
// ---------------------------------------------------------------------------

test("AC4: non-privileged prompt references ToolSearch for EMBER.md Slack channels", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => false,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).toContain("EMBER.md");
  expect(result?.message).toContain("ToolSearch");
});

test("AC4: non-privileged prompt requires user confirmation before Slack post", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    isUndercoverMode: () => false,
  });
  const result = await commitPushPrCommand.execute("", CTX);
  const msg = result?.message ?? "";
  expect(msg.toLowerCase()).toContain("confirmation");
});

// ---------------------------------------------------------------------------
// AC5: user-supplied args appended verbatim to prompt
// ---------------------------------------------------------------------------

test("AC5: user args are appended verbatim to the prompt", async () => {
  setCommitPushPrCommandDeps({ evalShell: async () => "" });
  const result = await commitPushPrCommand.execute(
    "squash the previous 3 commits first",
    CTX,
  );
  expect(result?.message).toContain("squash the previous 3 commits first");
});

test("AC5: empty args do not add an extra section", async () => {
  setCommitPushPrCommandDeps({ evalShell: async () => "" });
  const result = await commitPushPrCommand.execute("", CTX);
  expect(result?.message).not.toContain("Additional instructions");
});

// ---------------------------------------------------------------------------
// AC6: progress message is 'creating commit and PR'
// ---------------------------------------------------------------------------

test("AC6: progressMessage is 'creating commit and PR'", () => {
  expect(commitPushPrCommand.progressMessage).toBe("creating commit and PR");
});

// ---------------------------------------------------------------------------
// Command metadata
// ---------------------------------------------------------------------------

test("command name is 'commit-push-pr'", () => {
  expect(commitPushPrCommand.name).toBe("commit-push-pr");
});

test("command type is 'prompt'", () => {
  expect(commitPushPrCommand.type).toBe("prompt");
});

test("buildCommitPushPrPrompt includes attribution block", async () => {
  setCommitPushPrCommandDeps({
    evalShell: async () => "",
    getPrAttributionBlock: () => "Co-authored-by: CI Bot <ci@example.com>",
  });
  const prompt = await buildCommitPushPrPrompt("", "/repo");
  expect(prompt).toContain("Co-authored-by: CI Bot <ci@example.com>");
});

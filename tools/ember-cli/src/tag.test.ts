import { test, expect, beforeEach } from "bun:test";
import {
  tagCommand,
  executeTagToggle,
  setTagCommandDeps,
  _resetTagCommandDepsForTests,
} from "./tag.ts";

const CTX = { sessionId: "sess-1", mode: "default" as const, cwd: "/repo" };

beforeEach(() => {
  _resetTagCommandDepsForTests();
});

// ---------------------------------------------------------------------------
// AC1: command is absent for non-ant users
// ---------------------------------------------------------------------------

test("AC1: isEnabled returns false for non-ant users", () => {
  setTagCommandDeps({ isAntUser: () => false });
  expect(tagCommand.isEnabled()).toBe(false);
});

test("AC1: isEnabled returns true for ant users", () => {
  setTagCommandDeps({ isAntUser: () => true });
  expect(tagCommand.isEnabled()).toBe(true);
});

// ---------------------------------------------------------------------------
// AC2: missing tag name shows help component / usage examples
// ---------------------------------------------------------------------------

test("AC2: empty args returns help message with usage examples", async () => {
  const result = await executeTagToggle("", CTX);
  expect(result.outcome).toBe("help");
  expect(result.message).toContain("Usage:");
  expect(result.message).toContain("/tag");
});

test("AC2: whitespace-only args treated as empty — shows help", async () => {
  const result = await executeTagToggle("   ", CTX);
  expect(result.outcome).toBe("help");
});

// ---------------------------------------------------------------------------
// AC3: tag name is sanitized via recursivelySanitizeUnicode
// ---------------------------------------------------------------------------

test("AC3: sanitized tag name is used when saving", async () => {
  const savedTags: string[] = [];
  setTagCommandDeps({
    recursivelySanitizeUnicode: (s) => s.replace(/[^a-z0-9-]/gi, ""),
    saveTag: async (_id, tag) => { savedTags.push(tag); },
    getCurrentSessionTag: async () => null,
    trackEvent: () => {},
  });
  await executeTagToggle("my@tag!", CTX);
  expect(savedTags[0]).toBe("mytag"); // special chars stripped
});

test("AC3: sanitizer is called before any tag save", async () => {
  let sanitizerCalled = false;
  setTagCommandDeps({
    recursivelySanitizeUnicode: (s) => { sanitizerCalled = true; return s; },
    getCurrentSessionTag: async () => null,
    saveTag: async () => {},
    trackEvent: () => {},
  });
  await executeTagToggle("valid-tag", CTX);
  expect(sanitizerCalled).toBe(true);
});

// ---------------------------------------------------------------------------
// AC4: if no tag exists, save the new tag and emit tengu_tag_command_add
// ---------------------------------------------------------------------------

test("AC4: adds new tag when session has no existing tag", async () => {
  const savedTags: string[] = [];
  const events: string[] = [];
  setTagCommandDeps({
    getCurrentSessionTag: async () => null,
    saveTag: async (_id, tag) => { savedTags.push(tag); },
    trackEvent: (name) => { events.push(name); },
  });
  const result = await executeTagToggle("my-tag", CTX);
  expect(result.outcome).toBe("added");
  expect(savedTags[0]).toBe("my-tag");
  expect(events).toContain("ember_tag_command_add");
});

test("AC4: success message for new tag is displayed (includes tag name)", async () => {
  setTagCommandDeps({
    getCurrentSessionTag: async () => null,
    saveTag: async () => {},
    trackEvent: () => {},
  });
  const result = await executeTagToggle("release", CTX);
  expect(result.message).toContain("release");
});

// ---------------------------------------------------------------------------
// AC5: if tag already exists, show removal confirmation dialog
// ---------------------------------------------------------------------------

test("AC5: when tag exists, confirmRemoveTag is called with the existing tag", async () => {
  const confirmCalls: string[] = [];
  setTagCommandDeps({
    getCurrentSessionTag: async () => "existing-tag",
    confirmRemoveTag: async (tag) => { confirmCalls.push(tag); return false; },
    saveTag: async () => {},
    trackEvent: () => {},
  });
  await executeTagToggle("new-tag", CTX);
  expect(confirmCalls).toContain("existing-tag");
});

// ---------------------------------------------------------------------------
// AC6: confirming removal saves empty string and emits remove_confirmed
// ---------------------------------------------------------------------------

test("AC6: confirmed removal saves empty string for the tag", async () => {
  const savedValues: string[] = [];
  setTagCommandDeps({
    getCurrentSessionTag: async () => "old-tag",
    confirmRemoveTag: async () => true,
    saveTag: async (_id, tag) => { savedValues.push(tag); },
    trackEvent: () => {},
  });
  const result = await executeTagToggle("whatever", CTX);
  expect(result.outcome).toBe("removed");
  expect(savedValues[0]).toBe(""); // empty string removes the tag
});

test("AC6: confirmed removal emits tengu_tag_command_remove_confirmed", async () => {
  const events: string[] = [];
  setTagCommandDeps({
    getCurrentSessionTag: async () => "old-tag",
    confirmRemoveTag: async () => true,
    saveTag: async () => {},
    trackEvent: (name) => { events.push(name); },
  });
  await executeTagToggle("whatever", CTX);
  expect(events).toContain("ember_tag_command_remove_confirmed");
});

// ---------------------------------------------------------------------------
// AC7: cancelling removal emits remove_cancelled with no state change
// ---------------------------------------------------------------------------

test("AC7: cancelled removal emits tengu_tag_command_remove_cancelled", async () => {
  const events: string[] = [];
  setTagCommandDeps({
    getCurrentSessionTag: async () => "keep-this",
    confirmRemoveTag: async () => false,
    saveTag: async () => {},
    trackEvent: (name) => { events.push(name); },
  });
  const result = await executeTagToggle("whatever", CTX);
  expect(result.outcome).toBe("cancelled");
  expect(events).toContain("ember_tag_command_remove_cancelled");
});

test("AC7: cancelled removal does NOT call saveTag", async () => {
  let saveCalled = false;
  setTagCommandDeps({
    getCurrentSessionTag: async () => "keep-this",
    confirmRemoveTag: async () => false,
    saveTag: async () => { saveCalled = true; },
    trackEvent: () => {},
  });
  await executeTagToggle("whatever", CTX);
  expect(saveCalled).toBe(false);
});

// ---------------------------------------------------------------------------
// Command metadata
// ---------------------------------------------------------------------------

test("command name is 'tag'", () => {
  expect(tagCommand.name).toBe("tag");
});

test("command type is 'local-jsx'", () => {
  expect((tagCommand as { type?: string }).type).toBe("local-jsx");
});

// ---------------------------------------------------------------------------
// execute wrapper
// ---------------------------------------------------------------------------

test("execute returns message type result", async () => {
  setTagCommandDeps({
    isAntUser: () => true,
    getCurrentSessionTag: async () => null,
    saveTag: async () => {},
    trackEvent: () => {},
  });
  const result = await tagCommand.execute("my-tag", CTX);
  expect(result?.type).toBe("message");
});

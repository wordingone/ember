// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { z } from "zod";
import { badToolArgumentsMessage, BAD_TOOL_ARGUMENTS_KEY } from "./tool-input-check.ts";

const tool = { name: "Write", inputSchema: z.object({ file_path: z.string(), content: z.string(), n: z.number().optional() }) };

test("unparseable arguments get an actionable message", () => {
  const m = badToolArgumentsMessage(tool, { [BAD_TOOL_ARGUMENTS_KEY]: { receivedChars: 31000 } });
  expect(m).toContain("31000");
  expect(m).toContain("cut off");
});
test("an empty call names the missing fields", () => {
  const m = badToolArgumentsMessage(tool, {});
  expect(m).toContain("file_path");
  expect(m).toContain("no arguments");
});
test("valid input passes; a loose present value is left to the tool", () => {
  expect(badToolArgumentsMessage(tool, { file_path: "a", content: "b" })).toBeNull();
  expect(badToolArgumentsMessage(tool, { file_path: "a", content: "b", n: "5" })).toBeNull();
});
test("a tool without a schema is not checked", () => {
  expect(badToolArgumentsMessage({ name: "X" }, {})).toBeNull();
});

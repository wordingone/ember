// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 renderer/census evidence consumer

import { expect, test } from "bun:test";
import {
  parseIssue898RendererCensusArgs,
  runIssue898RendererCensusCli,
} from "./issue898-renderer-census-evidence.ts";

const ARGV = [
  "--soak-receipt", "B:\\root\\soak\\soak-receipt.json",
  "--polls", "B:\\root\\soak\\polls.jsonl",
  "--renderer", "B:\\root\\renderer.jsonl",
  "--output", "B:\\evidence\\renderer-census-receipt.json",
  "--source-commit", "a".repeat(40),
  "--cockpit-pid", "31808",
  "--cockpit-process-start-token", "639231623825394551",
  "--receipt-written-at", "2026-08-24T12:05:49.000Z",
] as const;

test("parses the exact evidence invocation", () => {
  expect(parseIssue898RendererCensusArgs([...ARGV])).toEqual({
    soakReceiptPath: "B:\\root\\soak\\soak-receipt.json",
    pollsPath: "B:\\root\\soak\\polls.jsonl",
    rendererPath: "B:\\root\\renderer.jsonl",
    outputPath: "B:\\evidence\\renderer-census-receipt.json",
    sourceCommit: "a".repeat(40),
    cockpitPid: 31808,
    cockpitProcessStartToken: "639231623825394551",
    receiptWrittenAt: "2026-08-24T12:05:49.000Z",
  });
});

test.each([
  ["missing flag", ARGV.slice(0, -2), "ISSUE898_RENDERER_CENSUS_ARGS_INVALID"],
  ["duplicate flag", [...ARGV, "--output", "B:\\other.json"], "ISSUE898_RENDERER_CENSUS_ARGS_INVALID"],
  ["unknown flag", [...ARGV, "--unknown", "value"], "ISSUE898_RENDERER_CENSUS_ARGS_INVALID"],
  ["zero PID", ARGV.map((value, index) => index === 11 ? "0" : value), "ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID"],
  ["coerced PID", ARGV.map((value, index) => index === 11 ? "1e3" : value), "ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID"],
  ["unsafe PID", ARGV.map((value, index) => index === 11 ? "9007199254740992" : value), "ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID"],
] as const)("refuses %s", (_name, argv, error) => {
  expect(() => parseIssue898RendererCensusArgs([...argv])).toThrow(error);
});

test("runs the sealer and prints one canonical summary line", () => {
  const lines: string[] = [];
  const receipt = runIssue898RendererCensusCli([...ARGV], {
    seal: (input) => {
      expect(input.outputPath).toBe("B:\\evidence\\renderer-census-receipt.json");
      return {
        schema_version: "ember-issue898-renderer-census-evidence-v1",
        verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION",
        receipt_sha256: "b".repeat(64),
      };
    },
    writeLine: (line) => lines.push(line),
  });
  expect(receipt.receipt_sha256).toBe("b".repeat(64));
  expect(lines).toEqual([JSON.stringify({
    schema_version: "ember-issue898-renderer-census-evidence-v1",
    verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION",
    output_path: "B:\\evidence\\renderer-census-receipt.json",
    receipt_sha256: "b".repeat(64),
  })]);
});

test("propagates a sealing refusal without printing success", () => {
  const lines: string[] = [];
  expect(() => runIssue898RendererCensusCli([...ARGV], {
    seal: () => { throw new Error("NAMED_REFUSAL"); },
    writeLine: (line) => lines.push(line),
  })).toThrow("NAMED_REFUSAL");
  expect(lines).toEqual([]);
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { censusWindowsServingProcesses } from "./serving-topology-census.ts";


describe("Windows serving topology census", () => {
  test("returns exact process identity rows for evaluator-side ownership filtering", async () => {
    const rows = await censusWindowsServingProcesses({
      runPowerShell: async () => JSON.stringify([
        { Id: 71, ProcessName: "llama-server.exe", CommandLine: "llama-server.exe --port 8000" },
        { Id: 72, ProcessName: "python.exe", CommandLine: "python src/ember/governance/scripts/serve_cbase_openai.py" },
        { Id: 73, ProcessName: "unrelated.exe", CommandLine: "unrelated.exe" },
      ]),
    });
    expect(rows).toEqual([
      { pid: 71, name: "llama-server.exe", command_line: "llama-server.exe --port 8000" },
      { pid: 72, name: "python.exe", command_line: "python src/ember/governance/scripts/serve_cbase_openai.py" },
      { pid: 73, name: "unrelated.exe", command_line: "unrelated.exe" },
    ]);
  });

  test("fails closed on unreadable, malformed, or duplicate OS rows", async () => {
    await expect(censusWindowsServingProcesses({ runPowerShell: async () => "not-json" }))
      .rejects.toThrow("SERVING_CENSUS_JSON_INVALID");
    await expect(censusWindowsServingProcesses({
      runPowerShell: async () => JSON.stringify({ Id: 0, ProcessName: "x", CommandLine: "x" }),
    })).rejects.toThrow("SERVING_CENSUS_ROW_INVALID");
    await expect(censusWindowsServingProcesses({
      runPowerShell: async () => JSON.stringify([
        { Id: 71, ProcessName: "x", CommandLine: "x" },
        { Id: 71, ProcessName: "x", CommandLine: "x" },
      ]),
    })).rejects.toThrow("SERVING_CENSUS_PID_DUPLICATE:71");
  });
});

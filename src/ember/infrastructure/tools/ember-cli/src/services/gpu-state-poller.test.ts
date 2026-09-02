// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/gpu-state-poller.test.ts — issue #447: nvidia-smi-sourced GPU state.

import { describe, test, expect } from "bun:test";
import {
  parseNvidiaSmiMemoryOutput,
  parseNvidiaSmiComputeAppsOutput,
  pollGpuState,
  classifyGpuActivity,
  formatGpuStateLine,
  type ExecFn,
} from "./gpu-state-poller.ts";

describe("parseNvidiaSmiMemoryOutput", () => {
  test("parses a single-GPU CSV line, converting MiB to GiB", () => {
    const out = parseNvidiaSmiMemoryOutput("18432, 24576, 42\n");
    expect(out).toEqual([{ vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 }]);
  });

  test("parses multiple GPU lines", () => {
    const out = parseNvidiaSmiMemoryOutput("1024, 8192, 5\n2048, 8192, 10\n");
    expect(out.length).toBe(2);
    expect(out[1]).toEqual({ vramUsedGib: 2, vramTotalGib: 8, utilPct: 10 });
  });

  test("skips malformed lines rather than throwing", () => {
    const out = parseNvidiaSmiMemoryOutput("not, a, number\n18432, 24576, 42\n");
    expect(out).toEqual([{ vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 }]);
  });

  test("returns [] for empty input", () => {
    expect(parseNvidiaSmiMemoryOutput("")).toEqual([]);
    expect(parseNvidiaSmiMemoryOutput("   \n  \n")).toEqual([]);
  });

  test("returns [] for a line with too few fields", () => {
    expect(parseNvidiaSmiMemoryOutput("18432, 24576\n")).toEqual([]);
  });
});

describe("parseNvidiaSmiComputeAppsOutput", () => {
  test("parses one process name per line", () => {
    expect(parseNvidiaSmiComputeAppsOutput("llama-server.exe\npython.exe\n")).toEqual([
      "llama-server.exe",
      "python.exe",
    ]);
  });

  test("returns [] for empty output (idle GPU, not an error)", () => {
    expect(parseNvidiaSmiComputeAppsOutput("")).toEqual([]);
  });

  test("skips blank lines", () => {
    expect(parseNvidiaSmiComputeAppsOutput("llama-server.exe\n\n\n")).toEqual(["llama-server.exe"]);
  });
});

describe("pollGpuState", () => {
  function fakeExec(memoryOut: string, computeOut: string, opts?: { memoryThrows?: boolean; computeThrows?: boolean }): ExecFn {
    return async (_cmd, args) => {
      const isMemoryQuery = args.some((a) => a.includes("--query-gpu"));
      if (isMemoryQuery) {
        if (opts?.memoryThrows) throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
        return { stdout: memoryOut, exitCode: 0 };
      }
      if (opts?.computeThrows) throw new Error("compute query failed");
      return { stdout: computeOut, exitCode: 0 };
    };
  }

  test("returns combined memory + compute-process snapshot on success", async () => {
    const result = await pollGpuState({ exec: fakeExec("18432, 24576, 42\n", "llama-server.exe\n") });
    expect(result).toEqual({
      memory: { vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 },
      computeProcessNames: ["llama-server.exe"],
    });
  });

  test("returns null when nvidia-smi binary is not found (ENOENT)", async () => {
    const result = await pollGpuState({ exec: fakeExec("", "", { memoryThrows: true }) });
    expect(result).toBeNull();
  });

  test("returns null when the memory query yields no parseable reading", async () => {
    const result = await pollGpuState({ exec: fakeExec("garbage output", "") });
    expect(result).toBeNull();
  });

  test("degrades to an empty process list when the compute-apps query fails, memory still returned", async () => {
    const result = await pollGpuState({ exec: fakeExec("18432, 24576, 42\n", "", { computeThrows: true }) });
    expect(result).toEqual({
      memory: { vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 },
      computeProcessNames: [],
    });
  });

  test("empty compute-apps output (idle GPU) yields an empty process list, not null", async () => {
    const result = await pollGpuState({ exec: fakeExec("1024, 8192, 0\n", "") });
    expect(result).toEqual({
      memory: { vramUsedGib: 1, vramTotalGib: 8, utilPct: 0 },
      computeProcessNames: [],
    });
  });
});

describe("classifyGpuActivity", () => {
  test("no compute processes -> idle", () => {
    expect(classifyGpuActivity([], false)).toBe("idle");
    expect(classifyGpuActivity([], true)).toBe("idle"); // process list wins: no process at all means idle
  });

  test("processes present + a fresh active run -> training-active (corroborated, not guessed)", () => {
    expect(classifyGpuActivity(["python.exe"], true)).toBe("training-active");
  });

  test("processes present, no fresh run, llama-server named process -> llama-server-only", () => {
    expect(classifyGpuActivity(["llama-server.exe"], false)).toBe("llama-server-only");
  });

  test("matches llama-server names case-insensitively and with underscore variant", () => {
    expect(classifyGpuActivity(["LLAMA-SERVER"], false)).toBe("llama-server-only");
    expect(classifyGpuActivity(["llama_server.exe"], false)).toBe("llama-server-only");
  });

  test("processes present, no fresh run, unrecognized process name -> compute-active (never guesses training)", () => {
    expect(classifyGpuActivity(["python.exe"], false)).toBe("compute-active");
  });
});

describe("formatGpuStateLine", () => {
  test("returns null when no GPU snapshot is available", () => {
    expect(formatGpuStateLine(null, false)).toBeNull();
  });

  test("formats VRAM to one decimal place with the classification", () => {
    const gpu = { memory: { vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 }, computeProcessNames: ["llama-server.exe"] };
    expect(formatGpuStateLine(gpu, false)).toEqual({ text: "GPU: 18.0/24.0 GiB \xB7 llama-server-only" });
  });

  test("reflects training-active when corroborated by a fresh run", () => {
    const gpu = { memory: { vramUsedGib: 20, vramTotalGib: 24, utilPct: 90 }, computeProcessNames: ["python.exe"] };
    expect(formatGpuStateLine(gpu, true)).toEqual({ text: "GPU: 20.0/24.0 GiB \xB7 training-active" });
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { CATALOG, choosePlan, fileForQuant, parsePullArgs, PULL_USAGE, vramBudget, type RepoFile } from "./model-pull.ts";

const GiB = 1024 ** 3;
const coder = CATALOG.find((c) => c.repo.includes("Qwen3-Coder"))!;
const files: RepoFile[] = [
  { path: "M-Q5_K_M.gguf", size: 21.7e9, sha256: "a" },
  { path: "M-UD-Q4_K_XL.gguf", size: 17.7e9, sha256: "b" },
  { path: "M-Q4_K_M.gguf", size: 18.6e9, sha256: "c" },
  { path: "M-Q3_K_M.gguf", size: 14.7e9, sha256: "d" },
  { path: "M-Q8_0-00001-of-00002.gguf", size: 1e9, sha256: "e" },
];

describe("ember pull selection", () => {
  it("matches quant tags exactly and skips split shards", () => {
    expect(fileForQuant(files, "Q4_K_M")?.path).toBe("M-Q4_K_M.gguf");
    expect(fileForQuant(files, "UD-Q4_K_XL")?.path).toBe("M-UD-Q4_K_XL.gguf");
    expect(fileForQuant(files, "Q8_0")).toBeUndefined();
  });

  it("prefers a usable context over a better quant", () => {
    const plan = choosePlan(coder, files, 22 * GiB, 0.53);
    expect(plan?.file.path).toBe("M-UD-Q4_K_XL.gguf");
    expect(plan?.nCtx).toBe(65536);
  });

  it("falls back down the quant list on a smaller card", () => {
    const plan = choosePlan(coder, files, 16 * GiB, 0.53);
    expect(plan?.file.path).toBe("M-Q3_K_M.gguf");
  });

  it("returns null when nothing fits", () => {
    expect(choosePlan(coder, files, 8 * GiB, 0.53)).toBeNull();
  });

  it("sizes against memory already in use, not only the card total", () => {
    expect(vramBudget({ gpuName: "x", vramTotalBytes: 24 * GiB, vramFreeBytes: 10 * GiB, ramBytes: 0 })).toBe(9.5 * GiB);
    expect(vramBudget({ gpuName: "x", vramTotalBytes: 24 * GiB, vramFreeBytes: 23.5 * GiB, ramBytes: 0 })).toBe(22 * GiB);
  });

  it("parses explicit repo:quant and defaults to --auto", () => {
    expect(parsePullArgs([]).auto).toBe(true);
    expect(parsePullArgs(["Qwen/Qwen3-8B-GGUF:Q8_0", "--dry-run"])).toMatchObject({ explicit: "Qwen/Qwen3-8B-GGUF:Q8_0", dryRun: true });
  });

  it("--help prints usage and an unknown option is refused instead of starting a real pull (#2377)", () => {
    expect(parsePullArgs(["--help"]).help).toBe(true);
    expect(parsePullArgs(["-h"]).help).toBe(true);
    expect(() => parsePullArgs(["--dry-rn"])).toThrow(/unknown option --dry-rn/);
    expect(() => parsePullArgs(["Qwen/Qwen3-8B-GGUF", "--yes"])).toThrow(/unknown option --yes/);
    expect(PULL_USAGE).toContain("--dry-run");
    expect(PULL_USAGE).toContain("--models-dir");
  });

  it("every catalog repo is owned by a trusted publisher", async () => {
    const { TRUSTED_OWNERS } = await import("./model-pull.ts");
    for (const c of CATALOG) expect(TRUSTED_OWNERS).toContain(c.repo.split("/")[0]!);
  });
});

// ---- turbo-aware fit rule ----------------------------------------------------
import { choosePlan as choosePlanLegacy, choosePlanKv } from "./model-pull.ts";
import { kvScale, type KvChoice } from "./llama-backend.ts";

const choice = (t: string): KvChoice => ({ k: t, v: t, scale: kvScale(t, t), evidence: "test" });
const STOCK = [choice("q8_0")];
const TURBO = [choice("q8_0"), choice("turbo4"), choice("turbo3")];
const big = CATALOG.find((c) => c.repo.includes("Qwen3.8-27B"))!;
const bigFiles: RepoFile[] = [
  { path: "M-UD-Q5_K_XL.gguf", size: 20.8e9, sha256: "a" },
  { path: "M-UD-Q4_K_XL.gguf", size: 17.6e9, sha256: "b" },
  { path: "M-UD-Q3_K_XL.gguf", size: 13e9, sha256: "c" },
  { path: "mmproj-F16.gguf", size: 0.9e9, sha256: "m" },
];

describe("fit rule with TurboQuant KV", () => {
  it("is identical to the legacy rule on stock llama.cpp (q8_0 only), without stretch", () => {
    const legacy = choosePlanLegacy(big, bigFiles, 22 * GiB, 0.53);
    const stock = choosePlanKv(big, bigFiles, 22 * GiB, STOCK);
    expect(stock?.file.path).toBe(legacy?.file.path);
    expect(stock?.nCtx).toBe(legacy?.nCtx);
  });

  it("uses turbo KV to buy a better quant at the same context", () => {
    const stock = choosePlanKv(big, bigFiles, 22 * GiB, STOCK)!;
    const turbo = choosePlanKv(big, bigFiles, 22 * GiB, TURBO)!;
    expect(stock.file.path).toBe("M-UD-Q4_K_XL.gguf");
    expect(turbo.file.path).toBe("M-UD-Q5_K_XL.gguf");
    expect(["turbo4", "turbo3"]).toContain(turbo.kv.k);
    expect(turbo.nCtx).toBe(stock.nCtx);
  });

  it("prefers the best-quality KV type that fits (q8_0 when it fits)", () => {
    expect(choosePlanKv(big, bigFiles, 40 * GiB, TURBO)!.kv.k).toBe("q8_0");
  });

  it("stretches the context past 64K with leftover memory, never past the model's native window", () => {
    const small = CATALOG.find((c) => c.name === "qwen3-4b-instruct-2507")!;
    const files: RepoFile[] = [{ path: "M-Q8_0.gguf", size: 4.3e9, sha256: "a" }];
    expect(choosePlanKv(small, files, 22 * GiB, TURBO, { stretch: true })!.nCtx).toBe(131072);
    expect(choosePlanKv(small, files, 22 * GiB, TURBO)!.nCtx).toBe(65536);
    expect(choosePlanKv({ ...small, nativeCtx: 98304 }, files, 22 * GiB, TURBO, { stretch: true })!.nCtx).toBe(98304);
    const noNative: typeof small = { ...small };
    delete noNative.nativeCtx;
    expect(choosePlanKv(noNative, files, 22 * GiB, TURBO, { stretch: true })!.nCtx).toBe(65536);
  });

  it("turbo makes a context fit that q8_0 cannot", () => {
    const f: RepoFile[] = [{ path: "M-UD-Q4_K_XL.gguf", size: 17.6e9, sha256: "b" }, { path: "mmproj-F16.gguf", size: 0.9e9, sha256: "m" }];
    const budget = 20.0 * GiB;
    expect(choosePlanKv(big, f, budget, STOCK)!.nCtx).toBeLessThan(65536);
    expect(choosePlanKv(big, f, budget, TURBO)!.nCtx).toBe(65536);
  });

  it("parses the new pull flags", () => {
    expect(parsePullArgs(["--calibrate"])).toMatchObject({ calibrate: true, auto: false });
    expect(parsePullArgs(["--no-calibrate", "--skip-slot"])).toMatchObject({ noCalibrate: true, skipSlot: true, auto: true });
    expect(parsePullArgs(["--calibrate", "--probe-template", "qwen36"]).probeTemplate).toBe("qwen36");
    expect(() => parsePullArgs(["--probe-template", "llama3"])).toThrow();
  });
});

// ---- first run on a machine with no llama-server (issue #2377) -----------------
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ensureLlamaServer, runPull } from "./model-pull.ts";
import { findInstalledRuntime, RUNTIME_COMPLETE_MARKER } from "./runtime-fetch.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";

describe("ensureLlamaServer", () => {
  const base = { cfgBinary: undefined, home: "H", noRuntimeUpdate: false, find: () => null, findInstalled: () => null };
  const quiet = () => { const lines: string[] = []; return { lines, log: (s: string) => { lines.push(s); } }; };

  it("uses a server that is already configured and fetches nothing", async () => {
    let fetched = 0;
    const q = quiet();
    const r = await ensureLlamaServer({ ...base, dryRun: false, log: q.log, find: () => "C:/x/llama-server.exe", fetchRuntime: async () => { fetched++; return "no"; } });
    expect(r).toEqual({ binary: "C:/x/llama-server.exe" });
    expect(fetched).toBe(0);
  });

  it("reuses a runtime fetched earlier before touching the network", async () => {
    let fetched = 0;
    const q = quiet();
    const r = await ensureLlamaServer({ ...base, dryRun: false, log: q.log, findInstalled: () => "H/runtime/b1/llama-server.exe", fetchRuntime: async () => { fetched++; return "no"; } });
    expect(r.binary).toBe("H/runtime/b1/llama-server.exe");
    expect(fetched).toBe(0);
  });

  it("fetches the official runtime on Windows when none exists", async () => {
    const calls: string[] = [];
    const q = quiet();
    const r = await ensureLlamaServer({ ...base, dryRun: false, log: q.log, platform: "win32", fetchRuntime: async (root) => { calls.push(root); return join(root, "b9", "llama-server.exe"); } });
    expect(r.binary).toBe(join("H", "runtime", "b9", "llama-server.exe"));
    expect(calls).toEqual([join("H", "runtime")]);
    expect(q.lines.join("\n")).toContain("fetching the official ggml-org/llama.cpp build");
  });

  it("a dry run reports the missing server and downloads nothing", async () => {
    let fetched = 0;
    const q = quiet();
    const r = await ensureLlamaServer({ ...base, dryRun: true, log: q.log, platform: "win32", fetchRuntime: async () => { fetched++; return "no"; } });
    expect(r).toEqual({ binary: null });
    expect(fetched).toBe(0);
    expect(q.lines.join("\n")).toContain("a real `ember pull` will fetch");
  });

  it("--no-runtime-update and non-Windows hosts stop with the manual fix and exit code 2", async () => {
    for (const o of [{ platform: "win32" as const, noRuntimeUpdate: true }, { platform: "linux" as const, noRuntimeUpdate: false }]) {
      const q = quiet();
      const r = await ensureLlamaServer({ ...base, dryRun: false, log: q.log, ...o, fetchRuntime: async () => { throw new Error("must not fetch"); } });
      expect(r).toEqual({ binary: null, code: 2 });
      expect(q.lines.join("\n")).toContain("set EMBER_LLAMA_SERVER");
    }
  });

  it("a failed fetch exits 2 and names the cause and the manual fix", async () => {
    const q = quiet();
    const r = await ensureLlamaServer({ ...base, dryRun: false, log: q.log, platform: "win32", fetchRuntime: async () => { throw new Error("no NVIDIA driver found (nvidia-smi); cannot choose a CUDA build"); } });
    expect(r).toEqual({ binary: null, code: 2 });
    const text = q.lines.join("\n");
    expect(text).toContain("no NVIDIA driver found");
    expect(text).toContain("set EMBER_LLAMA_SERVER");
  });
});

describe("findInstalledRuntime", () => {
  it("is null for a missing root, and ignores an interrupted fetch with no completion marker", () => {
    const root = join(import.meta.dir, "__runtime_fixture_2377__");
    try {
      expect(findInstalledRuntime(root)).toBeNull();
      mkdirSync(join(root, "b2"), { recursive: true });
      writeFileSync(join(root, "b2", "llama-server.exe"), "x");
      expect(findInstalledRuntime(root)).toBeNull();
      mkdirSync(join(root, "b1"), { recursive: true });
      writeFileSync(join(root, "b1", "llama-server.exe"), "x");
      writeFileSync(join(root, "b1", RUNTIME_COMPLETE_MARKER), "b1\n");
      expect(findInstalledRuntime(root)).toBe(join(root, "b1", "llama-server.exe"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("ember pull --dry-run on a fresh machine", () => {
  it("plans from the repo listing with no llama-server, no GPU probe and no files written", async () => {
    const home = join(import.meta.dir, "__ember_home_that_must_stay_absent_2377__");
    const origHome = process.env["EMBER_HOME"];
    process.env["EMBER_HOME"] = home;
    _resetConfigHomeMemo();
    const lines: string[] = [];
    try {
      const code = await runPull({
        auto: true, dryRun: true, log: (s) => { lines.push(s); },
        device: { gpuName: "Test GPU", vramTotalBytes: 24 * GiB, vramFreeBytes: 23.5 * GiB, ramBytes: 64 * GiB },
        listFiles: async () => bigFiles,
        findServer: () => null,
      });
      const text = lines.join("\n");
      expect(code).toBe(0);
      expect(text).toContain("no llama-server found");
      expect(text).toContain("selected unsloth/Qwen3.8-27B-GGUF");
      expect(text).toContain("dry run: nothing downloaded or changed");
      expect(existsSync(home)).toBe(false);
    } finally {
      if (origHome === undefined) delete process.env["EMBER_HOME"]; else process.env["EMBER_HOME"] = origHome;
      _resetConfigHomeMemo();
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("a real pull with no llama-server and --no-runtime-update stops before any download", async () => {
    const home = join(import.meta.dir, "__ember_home_that_must_stay_absent_2377b__");
    const origHome = process.env["EMBER_HOME"];
    process.env["EMBER_HOME"] = home;
    _resetConfigHomeMemo();
    const lines: string[] = [];
    try {
      const code = await runPull({
        auto: true, noRuntimeUpdate: true, log: (s) => { lines.push(s); },
        device: { gpuName: "Test GPU", vramTotalBytes: 24 * GiB, vramFreeBytes: 23.5 * GiB, ramBytes: 64 * GiB },
        listFiles: async () => { throw new Error("must not list"); },
        findServer: () => null,
      });
      expect(code).toBe(2);
      expect(lines.join("\n")).toContain("set EMBER_LLAMA_SERVER");
      expect(existsSync(home)).toBe(false);
    } finally {
      if (origHome === undefined) delete process.env["EMBER_HOME"]; else process.env["EMBER_HOME"] = origHome;
      _resetConfigHomeMemo();
      rmSync(home, { recursive: true, force: true });
    }
  });
});

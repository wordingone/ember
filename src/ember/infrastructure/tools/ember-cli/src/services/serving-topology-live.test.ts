import { afterEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createLiveServingTopologyService } from "./serving-topology-live.ts";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture() {
  const repoRoot = mkdtempSync(join(tmpdir(), "issue1282-c2-repo-"));
  const stateRoot = mkdtempSync(join(tmpdir(), "issue1282-c2-state-"));
  roots.push(repoRoot, stateRoot);
  mkdirSync(join(repoRoot, "state"), { recursive: true });
  const registryPath = join(repoRoot, "state", "serving-registry.json");
  const alarmPath = join(stateRoot, "serving-alarms.jsonl");
  const writeRows = (pids: number[]) => writeFileSync(
    registryPath,
    pids.map((pid) => JSON.stringify({
      port: 8000 + pid,
      model_path: `model-${pid}.gguf`,
      pid,
      launched_by: "ember-lab",
      ts: "2026-08-10T12:00:00Z",
      device: "cuda",
    })).join("\n") + (pids.length ? "\n" : ""),
    "utf8",
  );
  return { repoRoot, registryPath, alarmPath, writeRows };
}

describe("live serving topology service", () => {
  test("healthy exact sets emit no alarm", async () => {
    const { repoRoot, alarmPath, writeRows } = fixture();
    writeRows([41]);
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      census: async () => [{ pid: 41, name: "llama-server.exe", command_line: "llama-server.exe" }],
    });
    await service.pollOnce();
    expect(existsSync(alarmPath)).toBe(false);
  });

  test("writes external alarm before notifying and dedupes one drift episode", async () => {
    const { repoRoot, alarmPath, writeRows } = fixture();
    writeRows([]);
    const events: string[] = [];
    let livePid: number | null = 42;
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      now: () => 1,
      census: async () => livePid === null ? [] : [
        { pid: livePid, name: "llama-server.exe", command_line: "llama-server.exe" },
      ],
      notifyOperator: (alarm) => {
        events.push(`notify:${alarm.unregistered_live_pids.join(",")}`);
        expect(existsSync(alarmPath)).toBe(true);
      },
    });
    await service.pollOnce();
    await service.pollOnce();
    expect(events).toEqual(["notify:42"]);
    expect(readFileSync(alarmPath, "utf8").trim().split("\n")).toHaveLength(1);

    livePid = null;
    await service.pollOnce();
    livePid = 42;
    await service.pollOnce();
    expect(events).toEqual(["notify:42", "notify:42"]);
  });

  test("retries failed operator visibility without duplicating the durable alarm", async () => {
    const { repoRoot, alarmPath, writeRows } = fixture();
    writeRows([]);
    let attempts = 0;
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      census: async () => [
        { pid: 45, name: "llama-server.exe", command_line: "llama-server.exe" },
      ],
      notifyOperator: () => {
        attempts += 1;
        if (attempts === 1) throw new Error("transcript unavailable");
      },
    });
    await expect(service.pollOnce()).rejects.toThrow("transcript unavailable");
    await service.pollOnce();
    expect(attempts).toBe(2);
    expect(readFileSync(alarmPath, "utf8").trim().split("\n")).toHaveLength(1);
  });

  test("dead row emits its own synthetic drift receipt", async () => {
    const { repoRoot, alarmPath, writeRows } = fixture();
    writeRows([43]);
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      census: async () => [],
    });
    await service.pollOnce();
    const alarm = JSON.parse(readFileSync(alarmPath, "utf8").trim());
    expect(alarm.dead_registry_pids).toEqual([43]);
    expect(alarm.unregistered_live_pids).toEqual([]);
  });

  test("a missing canonical registry is empty authority and still detects a live server", async () => {
    const { repoRoot, alarmPath } = fixture();
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      census: async () => [
        { pid: 44, name: "llama-server.exe", command_line: "llama-server.exe" },
      ],
    });
    await service.pollOnce();
    const alarm = JSON.parse(readFileSync(alarmPath, "utf8").trim());
    expect(alarm.unregistered_live_pids).toEqual([44]);
    expect(alarm.registry_pids).toEqual([]);
  });

  test("malformed registry and in-checkout alarm paths fail closed", async () => {
    const { repoRoot, registryPath, writeRows } = fixture();
    writeFileSync(registryPath, "not-json\n", "utf8");
    const malformed = createLiveServingTopologyService({
      repoRoot,
      alarmPath: join(tmpdir(), `issue1282-c2-alarm-${process.pid}.jsonl`),
      census: async () => [],
    });
    await expect(malformed.pollOnce()).rejects.toThrow("SERVING_REGISTRY_JSON_INVALID");
    writeRows([]);
    expect(() => createLiveServingTopologyService({
      repoRoot,
      alarmPath: join(repoRoot, "state", "serving-alarms.jsonl"),
      census: async () => [],
    })).toThrow("SERVING_ALARM_PATH_IN_CHECKOUT");
  });

  test("starts one explicit five-second cadence and stops it on cockpit teardown", async () => {
    const { repoRoot, alarmPath, writeRows } = fixture();
    writeRows([]);
    let polls = 0;
    let scheduledMs: number | null = null;
    let scheduled: (() => void) | null = null;
    let cleared: unknown = null;
    const token = { topology: true } as unknown as ReturnType<typeof setInterval>;
    const service = createLiveServingTopologyService({
      repoRoot,
      alarmPath,
      census: async () => { polls += 1; return []; },
      setIntervalFn: ((callback: () => void, ms: number) => {
        scheduled = callback;
        scheduledMs = ms;
        return token;
      }) as typeof setInterval,
      clearIntervalFn: ((handle: ReturnType<typeof setInterval>) => {
        cleared = handle;
      }) as typeof clearInterval,
    });

    service.start();
    service.start();
    await service.pollOnce();
    expect(polls).toBe(1);
    expect(scheduledMs).toBe(5_000);
    expect(service.isRunning()).toBe(true);

    scheduled?.();
    await service.pollOnce();
    expect(polls).toBe(2);
    service.stop();
    expect(cleared).toBe(token);
    expect(service.isRunning()).toBe(false);
  });
});

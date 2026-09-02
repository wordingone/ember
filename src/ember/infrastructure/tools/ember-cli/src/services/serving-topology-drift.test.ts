import { describe, expect, test } from "bun:test";
import {
  evaluateServingTopology,
  type LiveServingProcess,
  type ServingRegistryRow,
} from "./serving-topology-drift.ts";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

const row = (pid: number): ServingRegistryRow => ({
  port: 8080 + pid,
  model_path: `model-${pid}.gguf`,
  pid,
  launched_by: "ember-lab",
  ts: "2026-08-10T12:00:00Z",
  device: "cuda",
});

const live = (pid: number, commandLine = "llama-server.exe --port 8080"): LiveServingProcess => ({
  pid,
  name: "llama-server.exe",
  command_line: commandLine,
});

describe("serving topology drift", () => {
  test("matching exact pid sets are healthy and emit no alarm", () => {
    expect(evaluateServingTopology([live(41), live(42)], [row(41), row(42)], () => 1)).toEqual({
      status: "healthy",
      live_pids: [41, 42],
      registry_pids: [41, 42],
    });
  });

  test("unregistered live server emits an operator alarm", () => {
    expect(evaluateServingTopology([live(41), live(43)], [row(41)], () => 1)).toMatchObject({
      status: "drift",
      alarm: {
        schema_version: "ember-serving-topology-drift-v1",
        unregistered_live_pids: [43],
        dead_registry_pids: [],
        action: "notify_operator",
      },
    });
  });

  test("dead registry row emits an operator alarm", () => {
    expect(evaluateServingTopology([live(41)], [row(41), row(44)], () => 1)).toMatchObject({
      status: "drift",
      alarm: {
        unregistered_live_pids: [],
        dead_registry_pids: [44],
      },
    });
  });

  test("equal counts cannot hide a swapped unregistered and dead pid", () => {
    expect(evaluateServingTopology([live(45)], [row(46)], () => 1)).toMatchObject({
      status: "drift",
      alarm: {
        unregistered_live_pids: [45],
        dead_registry_pids: [46],
      },
    });
  });

  test("foreign processes are excluded before set reconciliation", () => {
    expect(evaluateServingTopology([
      live(41),
      { pid: 99, name: "python.exe", command_line: "python unrelated.py" },
    ], [row(41)], () => 1)).toMatchObject({ status: "healthy" });
  });

  test("malformed or duplicate registry authority fails closed", () => {
    expect(() => evaluateServingTopology([live(41)], [{ ...row(41), port: 0 }], () => 1))
      .toThrow("SERVING_REGISTRY_ROW_INVALID");
    expect(() => evaluateServingTopology([live(41)], [row(41), row(41)], () => 1))
      .toThrow("SERVING_REGISTRY_PID_DUPLICATE:41");
  });
});

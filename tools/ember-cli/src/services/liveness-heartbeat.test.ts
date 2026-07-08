// services/liveness-heartbeat.test.ts — heartbeat writer + reader tests (issue #413).

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  createLivenessHeartbeatWriter,
  heartbeatAge,
  readHeartbeatRow,
} from "./liveness-heartbeat.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-liveness-heartbeat-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

describe("createLivenessHeartbeatWriter", () => {
  test("resolves filePath under <repoRoot>/tools/ember-cli/state/cockpit-heartbeat.json", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });

    expect(writer.filePath).toBe(
      path.join(scratchDir, "tools", "ember-cli", "state", "cockpit-heartbeat.json"),
    );
    expect(fs.existsSync(path.dirname(writer.filePath))).toBe(true);
  });

  test("write() overwrites the file with a fresh {ts, pid, version} row", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 4242, version: "abc123" });

    writer.write(Date.UTC(2026, 6, 7, 12, 0, 0));
    const first = JSON.parse(fs.readFileSync(writer.filePath, "utf8"));
    expect(first.pid).toBe(4242);
    expect(first.version).toBe("abc123");
    expect(first.ts).toBe(new Date(Date.UTC(2026, 6, 7, 12, 0, 0)).toISOString());

    writer.write(Date.UTC(2026, 6, 7, 12, 0, 5));
    const second = JSON.parse(fs.readFileSync(writer.filePath, "utf8"));
    expect(second.ts).toBe(new Date(Date.UTC(2026, 6, 7, 12, 0, 5)).toISOString());
    // Overwritten in place, never appended -- one row, not a growing log.
    expect(fs.readFileSync(writer.filePath, "utf8").trim().split("\n").length).toBe(1);
  });

  test("defaults pid to process.pid and version to \"unknown\" when not supplied", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
    writer.write();
    const row = JSON.parse(fs.readFileSync(writer.filePath, "utf8"));
    expect(row.pid).toBe(process.pid);
    expect(row.version).toBe("unknown");
  });

  test("fails open: write() never throws even when the target directory cannot be created", () => {
    // A plain FILE sits where the writer expects a directory (ENOTDIR-shaped collision) --
    // a realistic disk problem, same technique as operator-receipts.test.ts's equivalent case.
    const blockerPath = path.join(scratchDir, "tools");
    fs.writeFileSync(blockerPath, "not a directory");

    expect(() => {
      const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
      writer.write();
    }).not.toThrow();
  });
});

describe("heartbeatAge", () => {
  test("returns the elapsed ms between the row's ts and nowMs", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
    const writtenAt = Date.UTC(2026, 6, 7, 12, 0, 0);
    writer.write(writtenAt);

    const age = heartbeatAge(writer.filePath, writtenAt + 5_000);
    expect(age).toBe(5_000);
  });

  test("returns null when the file does not exist", () => {
    expect(heartbeatAge(path.join(scratchDir, "does-not-exist.json"))).toBeNull();
  });

  test("returns null when the file is not valid JSON (torn/partial write)", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, "{not valid json");
    expect(heartbeatAge(filePath)).toBeNull();
  });

  test("returns null when ts is missing or not a string", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, JSON.stringify({ pid: 1, version: "x" }));
    expect(heartbeatAge(filePath)).toBeNull();
  });

  test("returns null when ts is unparseable", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, JSON.stringify({ ts: "not-a-date", pid: 1, version: "x" }));
    expect(heartbeatAge(filePath)).toBeNull();
  });
});

describe("readHeartbeatRow", () => {
  test("returns the parsed row when ts and pid are both valid", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 777, version: "v1" });
    writer.write(Date.UTC(2026, 6, 7, 12, 0, 0));

    const row = readHeartbeatRow(writer.filePath);
    expect(row).toEqual({
      ts: new Date(Date.UTC(2026, 6, 7, 12, 0, 0)).toISOString(),
      pid: 777,
      version: "v1",
    });
  });

  test("returns null when the file does not exist", () => {
    expect(readHeartbeatRow(path.join(scratchDir, "does-not-exist.json"))).toBeNull();
  });

  test("returns null when the file is not valid JSON", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, "{not valid json");
    expect(readHeartbeatRow(filePath)).toBeNull();
  });

  test("returns null when pid is missing (stricter than heartbeatAge's ts-only check)", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, JSON.stringify({ ts: new Date().toISOString(), version: "x" }));
    expect(readHeartbeatRow(filePath)).toBeNull();
    // heartbeatAge itself is untouched -- still ts-only, still returns a real age here.
    expect(heartbeatAge(filePath)).not.toBeNull();
  });

  test("returns null when pid is not a number", () => {
    const filePath = path.join(scratchDir, "heartbeat.json");
    fs.writeFileSync(filePath, JSON.stringify({ ts: new Date().toISOString(), pid: "777", version: "x" }));
    expect(readHeartbeatRow(filePath)).toBeNull();
  });
});

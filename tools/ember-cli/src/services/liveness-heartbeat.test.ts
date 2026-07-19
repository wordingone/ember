// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

// ---------------------------------------------------------------------------------------
// Issue #666 — a writer LAUNCHED FROM a worktree cwd must land its heartbeat at the MAIN
// checkout's contract path (the path the watchdog polls), via the real resolution chain
// (no repoRoot override) — production-shaped, not hand-built paths.
// ---------------------------------------------------------------------------------------

describe("issue #666 — writer launched from a worktree cwd", () => {
  test("heartbeat file resolves under the main checkout, not the worktree", () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-666-"));
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    try {
      const mainRoot = path.join(scratch, "main-checkout");
      fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), { recursive: true });
      fs.writeFileSync(path.join(mainRoot, "GOAL.md"), "# fixture\n");
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });

      const worktreeRoot = path.join(scratch, "wt", "lane");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
      fs.writeFileSync(path.join(worktreeRoot, "GOAL.md"), "# fixture\n");
      fs.writeFileSync(
        path.join(worktreeRoot, ".git"),
        `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`,
      );

      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(path.join(worktreeRoot, "tools", "ember-cli"));

      const writer = createLivenessHeartbeatWriter({ pid: 4242, version: "t" });
      const expected = path.join(path.resolve(mainRoot), "tools", "ember-cli", "state", "cockpit-heartbeat.json");
      expect(writer.filePath).toBe(expected);

      writer.write();
      // The watchdog-side read of the MAIN-tree path sees the row the writer just wrote.
      expect(readHeartbeatRow(expected)?.pid).toBe(4242);
      // And nothing landed at the worktree-derived path (the old divergent behavior).
      expect(fs.existsSync(path.join(worktreeRoot, "tools", "ember-cli", "state", "cockpit-heartbeat.json"))).toBe(false);
    } finally {
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------------------
// PR954 round 2 — createLivenessHeartbeatWriter must use the STRICT resolver
// (resolveEmberRepoRoot, never resolveEmberRepoRootOrCwd's silent cwd fallback). On
// resolution failure it returns an INERT writer: filePath=null, a no-op write, exactly
// one explicit warning, and zero mkdir/zero writes anywhere on disk. A heartbeat file
// written to the wrong (unverified) root is worse than no heartbeat at all — an inert
// writer is honest about "I could not establish where to write", where the old
// resolveEmberRepoRootOrCwd fallback silently wrote to cwd instead.
// ---------------------------------------------------------------------------------------

describe("PR954 round 2 — inert writer on strict-resolver failure", () => {
  test("no repoRoot override + unresolvable repo root -> inert writer: filePath is null", () => {
    const arbitraryCwd = path.join(scratchDir, "no-repo-here");
    fs.mkdirSync(arbitraryCwd, { recursive: true });
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    try {
      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(arbitraryCwd);

      const warnCalls: unknown[][] = [];
      const originalWarn = console.warn;
      console.warn = (...args: unknown[]) => {
        warnCalls.push(args);
      };
      let writer: ReturnType<typeof createLivenessHeartbeatWriter>;
      try {
        writer = createLivenessHeartbeatWriter({});
      } finally {
        console.warn = originalWarn;
      }

      expect(writer.filePath).toBeNull();
      // Exactly one explicit warning on construction.
      expect(warnCalls.length).toBe(1);
      expect(String(warnCalls[0]?.[0])).toMatch(/repo root/i);
    } finally {
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
    }
  });

  test("inert writer's write() is a true no-op: never throws, never creates a directory, never writes a file", () => {
    const arbitraryCwd = path.join(scratchDir, "no-repo-here-2");
    fs.mkdirSync(arbitraryCwd, { recursive: true });
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    try {
      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(arbitraryCwd);

      const originalWarn = console.warn;
      console.warn = () => {};
      let writer: ReturnType<typeof createLivenessHeartbeatWriter>;
      try {
        writer = createLivenessHeartbeatWriter({});
      } finally {
        console.warn = originalWarn;
      }

      // Snapshot the scratch tree before write(); it must be byte-for-byte unchanged
      // after -- no mkdir, no file.
      const before = fs.readdirSync(scratchDir, { recursive: true } as never);
      expect(() => writer.write()).not.toThrow();
      const after = fs.readdirSync(scratchDir, { recursive: true } as never);
      expect(after).toEqual(before);
      expect(fs.existsSync(path.join(arbitraryCwd, "tools"))).toBe(false);
    } finally {
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
    }
  });

  test("a resolvable repo root still produces a live (non-inert) writer, unaffected by the inert path", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 99, version: "v" });
    expect(writer.filePath).not.toBeNull();
    writer.write(Date.UTC(2026, 6, 7, 12, 0, 0));
    expect(fs.existsSync(writer.filePath as string)).toBe(true);
  });
});

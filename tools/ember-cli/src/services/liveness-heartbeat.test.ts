// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/liveness-heartbeat.test.ts — heartbeat writer + reader tests (issue #413).

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execSync } from "node:child_process";
import {
  createLivenessHeartbeatWriter,
  shouldSuppressForHeadlessCapture,
  HEADLESS_CAPTURE_ENV,
  heartbeatAge,
  readHeartbeatRow,
} from "./liveness-heartbeat.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";

let scratchDir: string;
/** #413/#1330: every test's heartbeat now resolves through emberStatePath(), whose default
 *  branch keys off EMBER_HOME. Pinned to a fresh per-test scratch dir so tests never touch
 *  the real ~/.ember and never collide with each other or a concurrently running cockpit. */
let emberHomeDir: string;
const SAVED_EMBER_HOME = process.env["EMBER_HOME"];
const SAVED_EMBER_STATE_ROOT = process.env["EMBER_STATE_ROOT"];

/** PR954 round 3: `writer.filePath` is `string | null` (inert-writer contract), but every
 *  test here constructs its writer with a known-resolvable `repoRoot`, so the writer is
 *  never actually inert. Narrows loud-and-explicit at each call site instead of an
 *  `as string` cast -- an unexpected `null` here means a real regression in the writer's
 *  resolution, and should fail the test, not be papered over. */
function requireFilePath(filePath: string | null): string {
  if (filePath === null) {
    throw new Error("expected a live (non-inert) heartbeat writer, got filePath === null");
  }
  return filePath;
}

/** PR954 round 5 (reviewer reject P1-B): probed ONCE, synchronously, at module load --
 *  whether a real `icacls /deny "...:(R)"` actually blocks `fs.readFileSync` in THIS
 *  process. An elevated/inherited token can silently bypass a deny ACE (observed on this
 *  box: `Get-Item`/`Test-Path` stayed readable under a full deny even though
 *  `Get-Content`/`fs.readFileSync` did not) -- the real-ACL test below is `skipIf`'d when
 *  this probe shows the deny doesn't bite, so it never passes vacuously; the deterministic
 *  monkeypatched-`fs.readFileSync` leg further down always runs regardless. */
const realAclDenialEffective: boolean = (() => {
  const probeDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-acl-probe-"));
  const probeFile = path.join(probeDir, "probe.txt");
  fs.writeFileSync(probeFile, "probe");
  const user = `${process.env["USERDOMAIN"]}\\${process.env["USERNAME"]}`;
  let effective = true;
  try {
    execSync(`icacls "${probeFile}" /deny "${user}:(R)"`, { stdio: "pipe" });
    try {
      fs.readFileSync(probeFile, "utf8");
      effective = false;
    } catch {
      effective = true;
    }
    execSync(`icacls "${probeFile}" /reset`, { stdio: "pipe" });
  } catch {
    effective = false;
  }
  fs.rmSync(probeDir, { recursive: true, force: true });
  if (!effective) {
    console.warn(
      "[PR954 round 5] icacls /deny does NOT block fs.readFileSync in this process " +
        "(elevated/inherited token bypass) -- the real-ACL test will be SKIPPED; the " +
        "deterministic monkeypatched-fs.readFileSync leg covers this regardless.",
    );
  }
  return effective;
})();

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-liveness-heartbeat-"));
  emberHomeDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-liveness-heartbeat-home-"));
  delete process.env["EMBER_STATE_ROOT"];
  process.env["EMBER_HOME"] = emberHomeDir;
  _resetConfigHomeMemo();
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
  fs.rmSync(emberHomeDir, { recursive: true, force: true });
  if (SAVED_EMBER_HOME === undefined) delete process.env["EMBER_HOME"];
  else process.env["EMBER_HOME"] = SAVED_EMBER_HOME;
  if (SAVED_EMBER_STATE_ROOT === undefined) delete process.env["EMBER_STATE_ROOT"];
  else process.env["EMBER_STATE_ROOT"] = SAVED_EMBER_STATE_ROOT;
  _resetConfigHomeMemo();
});

describe("createLivenessHeartbeatWriter", () => {
  test("resolves filePath under emberStatePath(repoRoot, 'cockpit-heartbeat.json'), never inside the checkout", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });

    expect(writer.filePath).toBe(emberStatePath(scratchDir, "cockpit-heartbeat.json"));
    expect(fs.existsSync(path.dirname(requireFilePath(writer.filePath)))).toBe(true);
    // #413/#1330: the whole point of the relocation -- nothing lands under the checkout.
    expect(fs.existsSync(path.join(scratchDir, "tools", "ember-cli", "state"))).toBe(false);
  });

  test("write() overwrites the file with a fresh {ts, pid, version} row", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 4242, version: "abc123" });

    writer.write(Date.UTC(2026, 6, 7, 12, 0, 0));
    const first = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
    expect(first.pid).toBe(4242);
    expect(first.version).toBe("abc123");
    expect(first.ts).toBe(new Date(Date.UTC(2026, 6, 7, 12, 0, 0)).toISOString());

    writer.write(Date.UTC(2026, 6, 7, 12, 0, 5));
    const second = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
    expect(second.ts).toBe(new Date(Date.UTC(2026, 6, 7, 12, 0, 5)).toISOString());
    // Overwritten in place, never appended -- one row, not a growing log.
    expect(fs.readFileSync(requireFilePath(writer.filePath), "utf8").trim().split("\n").length).toBe(1);
  });

  test("defaults pid to process.pid and version to \"unknown\" when not supplied", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
    writer.write();
    const row = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
    expect(row.pid).toBe(process.pid);
    expect(row.version).toBe("unknown");
  });

  test("persists a bounded telemetry diagnostic snapshot for installed soak evidence", () => {
    const writer = createLivenessHeartbeatWriter({
      repoRoot: scratchDir,
      pid: 4242,
      version: "abc123",
      telemetryDiagnostics: () => ({
        pollAttempts: 17,
        pollsCompleted: 16,
        overlapPollsSkipped: 1,
        channelBytesRead: 4096,
        maxSingleReadBytes: 1024,
        maxPollReadBytes: 2048,
        partialLineBytes: 7,
        oversizedPartialLinesDropped: 2,
      }),
    });

    writer.write(Date.UTC(2026, 6, 30, 12, 0, 0));
    const row = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
    expect(row.telemetry).toEqual({
      pollAttempts: 17,
      pollsCompleted: 16,
      overlapPollsSkipped: 1,
      channelBytesRead: 4096,
      maxSingleReadBytes: 1024,
      maxPollReadBytes: 2048,
      partialLineBytes: 7,
      oversizedPartialLinesDropped: 2,
    });
  });

  test("omits invalid or throwing telemetry diagnostics without stopping the heartbeat", () => {
    const invalid = createLivenessHeartbeatWriter({
      repoRoot: scratchDir,
      telemetryDiagnostics: () => ({
        pollAttempts: Number.NaN,
        pollsCompleted: 0,
        overlapPollsSkipped: 0,
        channelBytesRead: 0,
        maxSingleReadBytes: 0,
        maxPollReadBytes: 0,
        partialLineBytes: 0,
        oversizedPartialLinesDropped: 0,
      }),
    });
    invalid.write();
    expect(JSON.parse(fs.readFileSync(requireFilePath(invalid.filePath), "utf8")).telemetry).toBeUndefined();

    const throwing = createLivenessHeartbeatWriter({
      repoRoot: scratchDir,
      telemetryDiagnostics: () => { throw new Error("diagnostic source failed"); },
    });
    expect(() => throwing.write()).not.toThrow();
    expect(JSON.parse(fs.readFileSync(requireFilePath(throwing.filePath), "utf8")).telemetry).toBeUndefined();
  });

  test("fails open: write() never throws even when the target directory cannot be created", () => {
    // A plain FILE sits where the writer expects a directory (ENOTDIR-shaped collision) --
    // a realistic disk problem, same technique as operator-receipts.test.ts's equivalent case.
    const blockerPath = path.dirname(emberStatePath(scratchDir, "cockpit-heartbeat.json"));
    fs.mkdirSync(path.dirname(blockerPath), { recursive: true });
    fs.writeFileSync(blockerPath, "not a directory");

    expect(() => {
      const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
      writer.write();
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------------------
// #1330 relocation review (rev-1330) follow-up finding, now closed here: the writer must
// land at the SAME external, never-censused root every other cockpit-mutable file uses --
// never inside tools/ember-cli/state/, gitignored or not, because the completion verifier's
// census enrolls ignored files too.
// ---------------------------------------------------------------------------------------

describe("#413/#1330 -- heartbeat writes through the relocated external state root", () => {
  test("honors an EMBER_STATE_ROOT override verbatim, same as every other cockpit-mutable writer", () => {
    const overrideRoot = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-state-root-override-"));
    try {
      process.env["EMBER_STATE_ROOT"] = overrideRoot;

      const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 1111, version: "ov" });
      expect(writer.filePath).toBe(path.join(overrideRoot, "cockpit-heartbeat.json"));

      writer.write(Date.UTC(2026, 6, 7, 12, 0, 0));
      expect(readHeartbeatRow(requireFilePath(writer.filePath))?.pid).toBe(1111);
      expect(fs.existsSync(path.join(scratchDir, "tools", "ember-cli", "state"))).toBe(false);
    } finally {
      fs.rmSync(overrideRoot, { recursive: true, force: true });
    }
  });

  test("never writes anywhere under <repoRoot>/tools/ember-cli/state, gitignored or not", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 2222, version: "ig" });
    for (let i = 0; i < 3; i += 1) writer.write(Date.UTC(2026, 6, 7, 12, 0, i));

    expect(fs.existsSync(path.join(scratchDir, "tools", "ember-cli", "state"))).toBe(false);
    expect(requireFilePath(writer.filePath).toLowerCase()).not.toBe(
      path.join(scratchDir, "tools", "ember-cli", "state", "cockpit-heartbeat.json").toLowerCase(),
    );
  });
});

describe("heartbeatAge", () => {
  test("returns the elapsed ms between the row's ts and nowMs", () => {
    const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir });
    const writtenAt = Date.UTC(2026, 6, 7, 12, 0, 0);
    writer.write(writtenAt);

    const age = heartbeatAge(requireFilePath(writer.filePath), writtenAt + 5_000);
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

    const row = readHeartbeatRow(requireFilePath(writer.filePath));
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
      fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });

      const worktreeRoot = path.join(scratch, "wt", "lane");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
      fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.writeFileSync(
        path.join(worktreeRoot, ".git"),
        `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`,
      );

      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(path.join(worktreeRoot, "tools", "ember-cli"));

      const writer = createLivenessHeartbeatWriter({ pid: 4242, version: "t" });
      const expected = emberStatePath(path.resolve(mainRoot), "cockpit-heartbeat.json");
      expect(writer.filePath).toBe(expected);

      writer.write();
      // The watchdog-side read of the MAIN-checkout-keyed state root sees the row the writer just wrote.
      expect(readHeartbeatRow(expected)?.pid).toBe(4242);
      // And nothing landed in-tree at either the main checkout or the worktree-derived path
      // (in-tree writes are categorically gone now, not just re-pointed at the main root).
      expect(fs.existsSync(path.join(mainRoot, "tools", "ember-cli", "state"))).toBe(false);
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
    expect(fs.existsSync(requireFilePath(writer.filePath))).toBe(true);
  });
});

// ---------------------------------------------------------------------------------------
// PR954 round 4 — reviewer coverage gaps closed at the WRITER level (createLivenessHeartbeatWriter
// via the real resolution chain — cwd + .git FILE — never a repoRoot override): a RELATIVE
// gitdir pointer resolves to a live writer at the correct main root, and a genuinely
// UNREADABLE .git FILE (real ACL deny, not just malformed content) produces an inert writer,
// never a silent fall-through to the worktree-local path.
// ---------------------------------------------------------------------------------------

describe("PR954 round 4 — writer-level coverage: relative gitdir + genuinely unreadable .git", () => {
  test("a RELATIVE gitdir pointer (relative to the .git FILE's own directory) resolves to a live writer at the main checkout", () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-r4-rel-"));
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    try {
      const mainRoot = path.join(scratch, "relative-main");
      fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), { recursive: true });
      fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });

      const worktreeRoot = path.join(scratch, "relative-wt");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
      fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      // Relative to the directory CONTAINING the .git file (the worktree root itself) --
      // the real on-disk shape when the main checkout and worktree share a common parent.
      fs.writeFileSync(path.join(worktreeRoot, ".git"), "gitdir: ../relative-main/.git/worktrees/lane\n");

      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(path.join(worktreeRoot, "tools", "ember-cli"));

      const writer = createLivenessHeartbeatWriter({ pid: 5252, version: "rel" });
      const expected = emberStatePath(path.resolve(mainRoot), "cockpit-heartbeat.json");
      expect(writer.filePath).toBe(expected);

      writer.write();
      expect(readHeartbeatRow(expected)?.pid).toBe(5252);
    } finally {
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  // PR954 round 5 (reviewer reject P1-B): the real-ACL fixture below used to write an
  // INVALID pointer (`gitdir: somewhere`). If the ACL deny didn't actually bite in this
  // process (elevated/inherited token bypass), the invalid pointer alone would still
  // produce an inert writer -- for the WRONG reason -- and the test never discriminated
  // unreadability at all. Repaired: (1) the fixture now points at a VALID, marker-valid
  // worktrees/<name> target that WOULD resolve successfully absent the deny; (2) denial
  // effectiveness is proven in-process (module-level probe above, `skipIf`'d loudly when
  // not effective, plus a per-fixture re-check right before asserting); (3) a separate,
  // fully deterministic monkeypatched-fs.readFileSync leg (below) always runs regardless
  // of ACL bypass.
  test.skipIf(!realAclDenialEffective)(
    "a genuinely UNREADABLE .git FILE (real ACL deny of a VALID worktree-shape pointer) produces an inert writer, never a silent fall-through",
    () => {
      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-r5-unreadable-real-"));
      const savedCwd = process.cwd();
      const savedEnv = process.env["EMBER_REPO_ROOT"];
      const dotGit = path.join(scratch, "worktree", ".git");
      let denied = false;
      try {
        const mainRoot = path.join(scratch, "main");
        fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), { recursive: true });
        fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
        fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });

        const worktreeRoot = path.join(scratch, "worktree");
        fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
        fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
        // VALID worktree-shape pointer -- this WOULD resolve successfully (to mainRoot)
        // if the deny below did not take effect, so an inert result can only be
        // attributed to the read denial, never an invalid-pointer red herring.
        fs.writeFileSync(dotGit, `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`);

        const user = `${process.env["USERDOMAIN"]}\\${process.env["USERNAME"]}`;
        execSync(`icacls "${dotGit}" /deny "${user}:(R)"`, { stdio: "pipe" });
        denied = true;

        // Re-prove denial effectiveness against THIS exact fixture file right before
        // asserting -- the module-level probe covers the general case; this covers any
        // per-file surprise. A failure here means the skipIf guard above was wrong for
        // this specific file, and the test fails loudly rather than passing vacuously.
        let thisFileDenied = true;
        try {
          fs.readFileSync(dotGit, "utf8");
          thisFileDenied = false;
        } catch {
          thisFileDenied = true;
        }
        expect(thisFileDenied).toBe(true);

        delete process.env["EMBER_REPO_ROOT"];
        process.chdir(worktreeRoot);

        const warnCalls: unknown[][] = [];
        const originalWarn = console.warn;
        console.warn = (...args: unknown[]) => {
          warnCalls.push(args);
        };
        let writer: ReturnType<typeof createLivenessHeartbeatWriter>;
        try {
          writer = createLivenessHeartbeatWriter({ pid: 7373, version: "unreadable" });
        } finally {
          console.warn = originalWarn;
        }

        expect(writer.filePath).toBeNull();
        expect(warnCalls.length).toBe(1);
        expect(String(warnCalls[0]?.[0])).toMatch(/repo root/i);
        expect(fs.existsSync(path.join(mainRoot, "tools", "ember-cli", "state"))).toBe(false);
      } finally {
        if (denied) {
          try {
            execSync(`icacls "${dotGit}" /reset`, { stdio: "pipe" });
          } catch {
            // best-effort ACL reset -- never let cleanup mask the test's own result.
          }
        }
        process.chdir(savedCwd);
        if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
        else process.env["EMBER_REPO_ROOT"] = savedEnv;
        fs.rmSync(scratch, { recursive: true, force: true });
      }
    },
  );

  test("deterministic leg: fs.readFileSync monkeypatched to throw an EACCES-shaped error for a VALID worktree-shape pointer produces an inert writer, regardless of real-ACL bypass", () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-r5-unreadable-mock-"));
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    const originalReadFileSync = fs.readFileSync;
    try {
      const mainRoot = path.join(scratch, "main");
      fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), { recursive: true });
      fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });

      const worktreeRoot = path.join(scratch, "worktree");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
      fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      const dotGit = path.join(worktreeRoot, ".git");
      // Same VALID worktree-shape-pointer discipline as the real-ACL leg above -- this
      // fixture would ALSO resolve successfully absent the monkeypatch.
      fs.writeFileSync(dotGit, `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`);

      // @ts-expect-error -- deliberate monkeypatch of the shared fs module object;
      // repo-root.ts imports the SAME `fs` default export, so this is visible to it.
      fs.readFileSync = (targetPath: fs.PathOrFileDescriptor, ...rest: unknown[]) => {
        if (targetPath === dotGit) {
          const err = new Error(`EACCES: permission denied, open '${dotGit}' (simulated)`) as NodeJS.ErrnoException;
          err.code = "EACCES";
          throw err;
        }
        // @ts-expect-error -- forwarding to the real implementation for every other path.
        return originalReadFileSync.apply(fs, [targetPath, ...rest]);
      };

      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(worktreeRoot);

      const warnCalls: unknown[][] = [];
      const originalWarn = console.warn;
      console.warn = (...args: unknown[]) => {
        warnCalls.push(args);
      };
      let writer: ReturnType<typeof createLivenessHeartbeatWriter>;
      try {
        writer = createLivenessHeartbeatWriter({ pid: 8484, version: "mocked-unreadable" });
      } finally {
        console.warn = originalWarn;
      }

      expect(writer.filePath).toBeNull();
      expect(warnCalls.length).toBe(1);
      expect(String(warnCalls[0]?.[0])).toMatch(/repo root/i);
      expect(fs.existsSync(path.join(mainRoot, "tools", "ember-cli", "state"))).toBe(false);
    } finally {
      fs.readFileSync = originalReadFileSync;
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });

  // PR954 round 5 (reviewer reject P1-A): dangling gitdir target was previously covered
  // only at the repo-root.test.ts resolver level and the PS watchdog-invocation level --
  // never at the WRITER level (createLivenessHeartbeatWriter itself). Closes that gap:
  // the writer must go inert (filePath === null, no writes) when the worktree's gitdir
  // pointer targets a directory that does not exist on disk.
  test("a DANGLING gitdir pointer (target directory absent) produces an inert writer, never a silent fall-through to the worktree-local path", () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "ember-hb-r5-dangling-"));
    const savedCwd = process.cwd();
    const savedEnv = process.env["EMBER_REPO_ROOT"];
    try {
      const mainRoot = path.join(scratch, "main");
      fs.mkdirSync(mainRoot, { recursive: true });
      fs.writeFileSync(path.join(mainRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.mkdirSync(path.join(mainRoot, "tools", "ember-cli"), { recursive: true });
      // Deliberately do NOT create <mainRoot>/.git/worktrees/lane -- the pointer target
      // must not exist for this test.
      const danglingTarget = path.join(mainRoot, ".git", "worktrees", "lane");
      expect(fs.existsSync(danglingTarget)).toBe(false);

      const worktreeRoot = path.join(scratch, "worktree");
      fs.mkdirSync(path.join(worktreeRoot, "tools", "ember-cli"), { recursive: true });
      fs.writeFileSync(path.join(worktreeRoot, "docs/domains/governance/authority/GOAL.md"), "# fixture\n");
      fs.writeFileSync(path.join(worktreeRoot, ".git"), `gitdir: ${danglingTarget}\n`);

      delete process.env["EMBER_REPO_ROOT"];
      process.chdir(worktreeRoot);

      const warnCalls: unknown[][] = [];
      const originalWarn = console.warn;
      console.warn = (...args: unknown[]) => {
        warnCalls.push(args);
      };
      let writer: ReturnType<typeof createLivenessHeartbeatWriter>;
      try {
        writer = createLivenessHeartbeatWriter({ pid: 9595, version: "dangling" });
      } finally {
        console.warn = originalWarn;
      }

      expect(writer.filePath).toBeNull();
      expect(warnCalls.length).toBe(1);
      expect(String(warnCalls[0]?.[0])).toMatch(/repo root/i);
      expect(fs.existsSync(path.join(mainRoot, "tools", "ember-cli", "state"))).toBe(false);
      expect(fs.existsSync(path.join(worktreeRoot, "tools", "ember-cli", "state"))).toBe(false);

      // The true no-op contract: write() is a no-op too.
      expect(() => writer.write()).not.toThrow();
      expect(fs.existsSync(path.join(mainRoot, "tools", "ember-cli", "state"))).toBe(false);
    } finally {
      process.chdir(savedCwd);
      if (savedEnv === undefined) delete process.env["EMBER_REPO_ROOT"];
      else process.env["EMBER_REPO_ROOT"] = savedEnv;
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
});

describe("headless-capture suppression", () => {
  // The defect these cover: a capture harness driving the compiled binary can publish a
  // heartbeat that falsely looks like a live operator cockpit to census/activity consumers.
  // Headless capture therefore suppresses all authoritative liveness publication. Observed
  // 2026-07-26: a palette-capture run inside an isolated worktree left a fresh heartbeat in the
  // MAIN repo's state dir, because this module resolves to the main root by design.

  test("SUPPRESSED ON THE SUCCESS PATH: a resolvable repoRoot still yields an inert writer", () => {
    // This is the load-bearing case. Resolution SUCCEEDS here, which is every normal run and the
    // only path whose file the watchdog ever polls -- so a guard placed after resolution would
    // leave this exact case writing. The would-be path is computed independently of the writer.
    const wouldBePath = emberStatePath(scratchDir, "cockpit-heartbeat.json");

    const writer = createLivenessHeartbeatWriter({
      repoRoot: scratchDir,
      env: { [HEADLESS_CAPTURE_ENV]: "1" },
    });

    expect(writer.filePath).toBeNull();
    writer.write(Date.UTC(2026, 6, 26, 0, 0, 0));
    expect(fs.existsSync(wouldBePath)).toBe(false);
    // Nothing is created on the way there either -- not even the directory.
    expect(fs.existsSync(path.dirname(wouldBePath))).toBe(false);
  });

  test("write() stays a no-op across repeated calls on a suppressed writer", () => {
    const wouldBePath = emberStatePath(scratchDir, "cockpit-heartbeat.json");
    const writer = createLivenessHeartbeatWriter({
      repoRoot: scratchDir,
      env: { [HEADLESS_CAPTURE_ENV]: "1" },
    });

    for (let i = 0; i < 5; i += 1) writer.write(Date.UTC(2026, 6, 26, 0, 0, i));

    expect(fs.existsSync(wouldBePath)).toBe(false);
  });

  test("an absent or empty value leaves the writer LIVE", () => {
    for (const env of [{}, { [HEADLESS_CAPTURE_ENV]: "" }]) {
      const writer = createLivenessHeartbeatWriter({ repoRoot: scratchDir, pid: 7, version: "v", env });
      writer.write(Date.UTC(2026, 6, 26, 1, 0, 0));

      const row = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
      expect(row.pid).toBe(7);
      fs.rmSync(requireFilePath(writer.filePath));
    }
  });

  test("a value that is not exactly \"1\" is a typo, not an intent -- the writer stays LIVE", () => {
    // Fail-safe direction. Going inert on a garbled value would take a real cockpit's heartbeat
    // away and provoke the very relaunch this guard exists to prevent, so only "1" suppresses.
    for (const raw of ["true", "TRUE", "yes", "0", "false", " 1", "1 "]) {
      const writer = createLivenessHeartbeatWriter({
        repoRoot: scratchDir,
        pid: 9,
        version: "v",
        env: { [HEADLESS_CAPTURE_ENV]: raw },
      });

      expect(writer.filePath).not.toBeNull();
      writer.write(Date.UTC(2026, 6, 26, 2, 0, 0));
      const row = JSON.parse(fs.readFileSync(requireFilePath(writer.filePath), "utf8"));
      expect(row.pid).toBe(9);
      fs.rmSync(requireFilePath(writer.filePath));
    }
  });

  test("shouldSuppressForHeadlessCapture maps every input class", () => {
    expect(shouldSuppressForHeadlessCapture({})).toBe(false);
    expect(shouldSuppressForHeadlessCapture({ [HEADLESS_CAPTURE_ENV]: undefined })).toBe(false);
    expect(shouldSuppressForHeadlessCapture({ [HEADLESS_CAPTURE_ENV]: "" })).toBe(false);
    expect(shouldSuppressForHeadlessCapture({ [HEADLESS_CAPTURE_ENV]: "1" })).toBe(true);
    expect(shouldSuppressForHeadlessCapture({ [HEADLESS_CAPTURE_ENV]: "true" })).toBe(false);
    expect(shouldSuppressForHeadlessCapture({ [HEADLESS_CAPTURE_ENV]: "0" })).toBe(false);
  });

  test("defaults to the real process env when none is injected", () => {
    // The production call site passes no env, so the default parameter is the shipped behaviour.
    const saved = process.env[HEADLESS_CAPTURE_ENV];
    try {
      delete process.env[HEADLESS_CAPTURE_ENV];
      expect(shouldSuppressForHeadlessCapture()).toBe(false);

      process.env[HEADLESS_CAPTURE_ENV] = "1";
      expect(shouldSuppressForHeadlessCapture()).toBe(true);
      expect(createLivenessHeartbeatWriter({ repoRoot: scratchDir }).filePath).toBeNull();
    } finally {
      if (saved === undefined) delete process.env[HEADLESS_CAPTURE_ENV];
      else process.env[HEADLESS_CAPTURE_ENV] = saved;
    }
  });
});

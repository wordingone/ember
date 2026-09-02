// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { existsSync, mkdirSync, realpathSync, rmSync } from "fs";
import { join } from "path";

import { emberScratchDir } from "./ember-scratch.ts";

// NO-TEMP policy regression coverage: emberScratchDir must never depend on
// system temp (os.tmpdir() / %TEMP% / TMPDIR), and its returned path must be
// deterministic + canonicalized regardless of how the environment's temp
// variable is cased or whether it points somewhere bogus.

describe("emberScratchDir", () => {
  it("returns a canonicalized path under EMBER_HOME, creating it recursively", () => {
    const emberHome = join(process.cwd(), ".ember-scratch-test-home");
    rmSync(emberHome, { force: true, recursive: true });
    const previousEmberHome = process.env.EMBER_HOME;
    process.env.EMBER_HOME = emberHome;
    try {
      const dir = emberScratchDir("unit-test-purpose");
      expect(existsSync(dir)).toBe(true);
      expect(dir).toBe(realpathSync.native(dir));
      expect(dir.includes(".runtime")).toBe(true);
      expect(dir.includes("unit-test-purpose")).toBe(true);
      expect(dir.endsWith(String(process.pid))).toBe(true);
    } finally {
      if (previousEmberHome === undefined) {
        delete process.env.EMBER_HOME;
      } else {
        process.env.EMBER_HOME = previousEmberHome;
      }
      rmSync(emberHome, { force: true, recursive: true });
    }
  });

  it("is unaffected by process.env.TEMP being differently-cased or bogus", () => {
    const emberHome = join(process.cwd(), ".ember-scratch-test-home-2");
    rmSync(emberHome, { force: true, recursive: true });
    const previousEmberHome = process.env.EMBER_HOME;
    const previousTemp = process.env.TEMP;
    const previousTmp = process.env.TMP;
    process.env.EMBER_HOME = emberHome;
    // A bogus, wrongly-cased system temp value. If emberScratchDir ever
    // regresses to consulting os.tmpdir()/%TEMP%, this would either throw
    // (path does not exist) or return a path rooted there instead of under
    // EMBER_HOME — either way the assertions below would fail.
    process.env.TEMP = "C:\\NONEXISTENT-BOGUS-TEMP-DIR-CASING-PROBE";
    process.env.TMP = "C:\\NONEXISTENT-BOGUS-TEMP-DIR-CASING-PROBE";
    try {
      mkdirSync(emberHome, { recursive: true });
      const dir = emberScratchDir("case-independence-probe");
      expect(existsSync(dir)).toBe(true);
      expect(dir.toLowerCase().includes("bogus")).toBe(false);
      const canonicalEmberHome = realpathSync.native(emberHome);
      expect(dir.startsWith(canonicalEmberHome)).toBe(true);
    } finally {
      if (previousEmberHome === undefined) {
        delete process.env.EMBER_HOME;
      } else {
        process.env.EMBER_HOME = previousEmberHome;
      }
      if (previousTemp === undefined) {
        delete process.env.TEMP;
      } else {
        process.env.TEMP = previousTemp;
      }
      if (previousTmp === undefined) {
        delete process.env.TMP;
      } else {
        process.env.TMP = previousTmp;
      }
      rmSync(emberHome, { force: true, recursive: true });
    }
  });
});

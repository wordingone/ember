// generate-version.test.ts — B7 gate ask (2026-07-03): the welcome screen must show the real
// build version, wired from package.json at build time, never an env-var-dependent fallback.
import { describe, test, expect } from "bun:test";
import { versionFileContents } from "./generate-version.ts";

describe("versionFileContents", () => {
  test("emits an EMBER_VERSION export matching package.json's version field", () => {
    const out = versionFileContents({ version: "1.4.2" });
    expect(out).toContain('export const EMBER_VERSION = "1.4.2";');
  });

  test("quotes the version as a string literal even for a placeholder like 0.0.0", () => {
    const out = versionFileContents({ version: "0.0.0" });
    expect(out).toContain('export const EMBER_VERSION = "0.0.0";');
  });

  test("output is valid TypeScript with exactly one export", () => {
    const out = versionFileContents({ version: "2.0.0-beta.1" });
    const matches = out.match(/export const EMBER_VERSION/g) ?? [];
    expect(matches.length).toBe(1);
    expect(out).toContain('"2.0.0-beta.1"');
  });
});

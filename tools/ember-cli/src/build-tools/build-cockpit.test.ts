// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import {
  buildCommitBanner,
  cockpitCompileArgs,
  requireBuildCommit,
  requireCleanTrackedStatus,
} from "./build-cockpit.ts";

describe("cockpit build commit binding", () => {
  it("accepts only an exact lowercase Git commit", () => {
    expect(requireBuildCommit("a".repeat(40) + "\n")).toBe("a".repeat(40));
    expect(() => requireBuildCommit("A".repeat(40))).toThrow();
    expect(() => requireBuildCommit("a".repeat(39))).toThrow();
  });

  it("rejects any dirty tracked source before compiling", () => {
    expect(() => requireCleanTrackedStatus(" M scripts/runtime.py\n")).toThrow(
      "dirty tracked source bytes",
    );
    expect(() => requireCleanTrackedStatus("")).not.toThrow();
  });

  it("emits a literal global bootstrap banner", () => {
    expect(buildCommitBanner("b".repeat(40))).toBe(
      "globalThis.__EMBER_BUILD_COMMIT__=\"" + "b".repeat(40) + "\";",
    );
  });

  it("brands every compiled Windows binary as Ember", () => {
    const commit = "c".repeat(40);
    expect(cockpitCompileArgs(commit, "owned-temp/ember.exe")).toEqual([
      "build",
      "./entrypoints/main.ts",
      "--compile",
      "--outfile",
      "owned-temp/ember.exe",
      "--banner",
      buildCommitBanner(commit),
      "--windows-title",
      "Ember",
      "--windows-publisher",
      "wordingone",
      "--windows-version",
      "0.1.0.0",
      "--windows-description",
      "Ember local AI laboratory",
    ]);
  });
});

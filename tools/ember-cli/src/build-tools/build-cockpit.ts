// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { spawnSync } from "child_process";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const cockpitIconPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
  "assets",
  "ember.ico",
);

export function requireBuildCommit(value: string): string {
  const commit = value.trim();
  if (!/^[0-9a-f]{40}$/.test(commit)) {
    throw new Error("cockpit build requires an exact lowercase Git commit");
  }
  return commit;
}

export function buildCommitBanner(commit: string): string {
  return "globalThis.__EMBER_BUILD_COMMIT__=" + JSON.stringify(requireBuildCommit(commit)) + ";";
}

export function cockpitWindowsMetadataArgs(): string[] {
  return [
    "--windows-title",
    "Ember",
    "--windows-publisher",
    "wordingone",
    "--windows-version",
    "0.1.0.0",
    "--windows-description",
    "Ember local AI laboratory",
    "--windows-icon",
    cockpitIconPath,
  ];
}

export function cockpitCompileArgs(commit: string, outfile = "ember.exe"): string[] {
  return [
    "build",
    "./entrypoints/main.ts",
    "--compile",
    "--outfile",
    outfile,
    "--banner",
    buildCommitBanner(commit),
    ...cockpitWindowsMetadataArgs(),
  ];
}

export function requireCleanTrackedStatus(status: string): void {
  if (status.trim() !== "") {
    throw new Error("cockpit build refuses dirty tracked source bytes");
  }
}

if (import.meta.main) {
  const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
  const repositoryRoot = join(sourceRoot, "..", "..", "..");
  const git = spawnSync("git", ["-C", repositoryRoot, "rev-parse", "HEAD"], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 15_000,
  });
  if (git.status !== 0) {
    throw new Error("cannot resolve exact Ember source commit for cockpit build");
  }
  const commit = requireBuildCommit(git.stdout ?? "");
  const status = spawnSync(
    "git",
    ["-C", repositoryRoot, "status", "--porcelain", "--untracked-files=no"],
    { encoding: "utf8", windowsHide: true, timeout: 15_000 },
  );
  if (status.status !== 0) {
    throw new Error("cannot verify clean tracked Ember source for cockpit build");
  }
  requireCleanTrackedStatus(status.stdout ?? "");
  // EMBER_BUILD_OUTFILE lets the launcher compile STRAIGHT into the external cockpit
  // state root (issue #1330). The old default emits `ember.exe` beside the sources, i.e.
  // inside the tree the completion verifier censuses by totality -- a transient in-tree
  // writer that reds a run that happens to be censusing during a build.
  const outfile = process.env["EMBER_BUILD_OUTFILE"] ?? "ember.exe";
  const result = spawnSync(
    process.execPath,
    cockpitCompileArgs(commit, outfile),
    { cwd: sourceRoot, stdio: "inherit", windowsHide: true },
  );
  if (result.status !== 0) {
    throw new Error("cockpit build failed with exit code " + result.status);
  }
}

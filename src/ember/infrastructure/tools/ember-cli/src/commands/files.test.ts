// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// /files — acceptance test suite
// Spec: specs/commands/files.md

import { describe, it, expect } from "bun:test";
import { createFilesCommand } from "./files.ts";
import type { CommandContext } from "../types/command-types.ts";

const mockContext: CommandContext = {
  sessionId: "test-session",
  mode: "default",
  cwd: "/test",
};

describe("/files", () => {
  describe("AC1: command absent for non-ant users", () => {
    it("isEnabled() returns false when USER_TYPE is undefined", () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => [],
        getUserType: () => undefined,
      });
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns false when USER_TYPE is 'external'", () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => [],
        getUserType: () => "external",
      });
      expect(cmd.isEnabled()).toBe(false);
    });

    it("isEnabled() returns true when USER_TYPE is 'ant'", () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => [],
        getUserType: () => "ant",
      });
      expect(cmd.isEnabled()).toBe(true);
    });
  });

  describe("AC2: output lists all file paths, sorted", () => {
    it("lists sorted file paths from the cache", async () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => ["/c/zebra.ts", "/a/alpha.ts", "/b/beta.ts"],
        getUserType: () => "ant",
      });
      const result = await cmd.execute("", mockContext);
      const message = (result as { message: string }).message;
      const lines = message.split("\n");
      expect(lines).toEqual(["/a/alpha.ts", "/b/beta.ts", "/c/zebra.ts"]);
    });

    it("returns a descriptive message when no files are loaded", async () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => [],
        getUserType: () => "ant",
      });
      const result = await cmd.execute("", mockContext);
      expect((result as { message: string }).message).toContain("no files");
    });
  });

  describe("AC3: works in non-interactive (headless) sessions", () => {
    it("execute completes without error in any session mode", async () => {
      const cmd = createFilesCommand({
        getCachedFilePaths: () => ["/path/to/file.ts"],
        getUserType: () => "ant",
      });
      const headlessCtx: CommandContext = {
        sessionId: "headless-session",
        mode: "default",
        cwd: "/project",
      };
      const result = await cmd.execute("", headlessCtx);
      expect(result).toBeDefined();
      expect((result as { type: string }).type).toBe("message");
    });
  });
});

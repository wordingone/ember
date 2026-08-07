// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";

const SRC_DIR = resolve(import.meta.dir);

function text(value: Uint8Array | undefined): string {
  return new TextDecoder().decode(value ?? new Uint8Array());
}

describe("compiled goal-session live path", () => {
  test("runs the real compiled ember entrypoint and emits path-free evidence", () => {
    const tempBase = process.env["TEMP"] ?? process.env["TMP"] ?? "C:\\tmp";
    const tempRoot = mkdtempSync(join(tempBase, "ember-goal-live-"));
    const executable = join(tempRoot, "ember-goal-live.exe");
    try {
      const build = Bun.spawnSync(
        ["bun", "build", "./entrypoints/main.ts", "--compile", "--outfile", executable],
        { cwd: SRC_DIR, stdout: "pipe", stderr: "pipe" },
      );
      expect(build.exitCode, text(build.stderr)).toBe(0);

      const run = Bun.spawnSync([executable, "goal-session-smoke"], {
        cwd: SRC_DIR,
        stdout: "pipe",
        stderr: "pipe",
      });
      const stdout = text(run.stdout).trim();
      expect(run.exitCode, text(run.stderr)).toBe(0);
      const receipt = JSON.parse(stdout.split(/\r?\n/).at(-1) ?? "null") as Record<string, any>;
      expect(receipt).toEqual(JSON.parse(readFileSync(join(SRC_DIR, "fixtures", "goal-live-session-receipt-v1.json"), "utf8")));
      expect(receipt.schema_version).toBe("ember-goal-live-session-receipt-v1");
      expect(receipt.result).toBe("MEASURED");
      expect(receipt.model).toBe("deterministic-local-stub-v1");
      expect(receipt.zero_user_input_after_boot).toBe(true);
      expect(receipt.autonomous_continuations).toBeGreaterThanOrEqual(3);
      expect(receipt.continuation_events).toBeGreaterThanOrEqual(3);
      expect(receipt.premature_complete_refusal).toEqual({
        tool_validation: true,
        store_boundary: true,
      });
      expect(receipt.complete_transition).toMatchObject({
        status: "Complete",
        audit_bound: true,
        requirement_ids: ["continuations", "preemption"],
      });
      expect(receipt.user_preemption).toEqual({
        outcome: "queued_user_input",
        start_turn_calls: 0,
        receipt_event: "continuation_skipped",
      });
      expect(receipt.frame_captures).toHaveLength(3);
      expect(receipt.frame_captures.map((frame: any) => frame.phase)).toEqual([
        "preemption",
        "continuations",
        "completion",
      ]);
      for (const frame of receipt.frame_captures) {
        expect(frame.frame_sha256).toMatch(/^[0-9a-f]{64}$/);
        expect(frame.source_binding).toEqual({
          id: "ember-goal-live-session-source-v1",
          sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        });
        expect(frame.event_count).toBeGreaterThan(0);
      }
      expect(receipt.events.filter((event: any) => event.event === "continuation_fired").length)
        .toBeGreaterThanOrEqual(3);
      expect(receipt.events.some((event: any) => event.event === "continuation_skipped")).toBe(true);
      expect(receipt.events[0]).toMatchObject({ goalId: "goal-live-preemption-v1", event: "created" });
      expect(receipt.events[1]).toMatchObject({ goalId: "goal-live-preemption-v1", event: "continuation_skipped" });
      expect(receipt.events.findIndex((event: any) => event.event === "status_changed"))
        .toBeGreaterThan(1);

      const serialized = JSON.stringify(receipt);
      expect(serialized).not.toContain(SRC_DIR);
      expect(serialized).not.toContain(tempRoot);
      expect(serialized).not.toMatch(/[A-Za-z]:\\/);
      expect(serialized).not.toContain("filePath");
    } finally {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  });
});

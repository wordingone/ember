// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { validateGoalLiveFrameCapture } from "./services/goal-live-session-frames.ts";

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
      const expectedReceipt = JSON.parse(readFileSync(join(SRC_DIR, "fixtures", "goal-live-session-receipt-v1.json"), "utf8"));
      for (const [index, frame] of expectedReceipt.frame_captures.entries()) {
        frame.source_binding.executable_sha256 = receipt.frame_captures[index].source_binding.executable_sha256;
      }
      expect(receipt).toEqual(expectedReceipt);
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
      const orderingCompleteIndex = receipt.events.findIndex((event: any) =>
        event.event === "status_changed" && event.detail?.to === "Complete");
      const orderingContinuationIndices = receipt.events
        .map((event: any, index: number) => event.event === "continuation_fired" ? index : -1)
        .filter((index: number) => index >= 0);
      expect(orderingContinuationIndices.length).toBeGreaterThanOrEqual(3);
      expect(orderingContinuationIndices.every((index: number) => index < orderingCompleteIndex)).toBe(true);
      const orderingAudit = receipt.events[orderingCompleteIndex]?.detail?.completionAudit?.requirements ?? [];
      expect(orderingAudit.every((item: any) =>
        typeof item.evidence === "string" && /(receipt index|receipt indices)/.test(item.evidence))).toBe(true);
      const auditIndices = orderingAudit.flatMap((item: any) =>
        Array.from(String(item.evidence).matchAll(/receipt (?:index|indices) ([0-9,]+)/g))
          .flatMap((match) => match[1].split(",").map((value) => Number(value)))
      );
      expect(auditIndices.length).toBeGreaterThanOrEqual(4);
      expect(auditIndices.every((index: number) => Number.isInteger(index) && index < orderingCompleteIndex)).toBe(true);
      const executableSha = createHash("sha256").update(readFileSync(executable)).digest("hex");
      const sourceSha = createHash("sha256").update(readFileSync(join(SRC_DIR, "services", "goal-live-session-frames.ts"))).digest("hex");
      for (const frame of receipt.frame_captures) {
        expect(frame.frame_sha256).toMatch(/^[0-9a-f]{64}$/);
        expect(frame.frame_bytes_base64).toMatch(/^[A-Za-z0-9+/]+={0,2}$/);
        expect(frame.width).toBeGreaterThan(0);
        expect(frame.height).toBeGreaterThan(0);
        expect(frame.sequence).toBeGreaterThan(0);
        expect(frame.receipt_start_index).toBeLessThanOrEqual(frame.receipt_end_index);
        expect(frame.source_binding).toEqual({
          id: "ember-goal-live-session-source-v1",
          sha256: sourceSha,
          executable_sha256: executableSha,
        });
        expect(frame.event_count).toBeGreaterThan(0);
        const frameBytes = Buffer.from(frame.frame_bytes_base64, "base64");
        expect(frame.frame_sha256).toBe(createHash("sha256").update(frameBytes).digest("hex"));
        const tampered = { ...frame, frame_bytes_base64: Buffer.from(frameBytes.map((value, index) => index === 0 ? value ^ 1 : value)).toString("base64") };
        expect(() => validateGoalLiveFrameCapture(tampered, receipt.events, frame.source_binding)).toThrow();
      }
      expect(receipt.events.filter((event: any) => event.event === "continuation_fired").length)
        .toBeGreaterThanOrEqual(3);
      expect(receipt.events.some((event: any) => event.event === "continuation_skipped")).toBe(true);
      expect(receipt.events[0]).toMatchObject({ goalId: "goal-live-preemption-v1", event: "created" });
      expect(receipt.events[1]).toMatchObject({ goalId: "goal-live-preemption-v1", event: "continuation_skipped" });

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

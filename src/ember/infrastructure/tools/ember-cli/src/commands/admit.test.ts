// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { createAdmitCommand } from "./admit.ts";


describe("/admit command", () => {
  it("constructs a candidate without selecting, loading, or training", async () => {
    const calls: Array<{ executable: string; args: string[]; cwd: string }> = [];
    const command = createAdmitCommand({
      producerPath: "C:/ember/src/ember/governance/scripts/ember_admission/produce_candidate.py",
      pythonExecutable: "python",
      verifyReceipt: () => "a".repeat(64),
      runProducer(executable, args, cwd) {
        calls.push({ executable, args, cwd });
        return {
          status: 0,
          stdout: JSON.stringify({
            candidate_sha256: "a".repeat(64),
            candidate_id: "candidate-one",
            producer_receipt_sha256: "b".repeat(64),
            ok: true,
            selected: false,
            loaded: false,
            training_started: false,
          }),
        };
      },
    });

    const result = await command.execute(
      "--workspace C:/operator --descriptor C:/operator/admission.json --output-root C:/candidates",
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(command.name).toBe("admit");
    expect(command.description).toContain("candidate");
    expect(command.description).toContain("without selecting or loading");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.args).toEqual([
      "C:/ember/src/ember/governance/scripts/ember_admission/produce_candidate.py",
      "--workspace", "C:/operator",
      "--descriptor", "C:/operator/admission.json",
      "--output-root", "C:/candidates",
    ]);
    expect(result).toEqual({
      type: "message",
      message: `admission candidate produced: ${"a".repeat(64)}\nselected=false loaded=false training_started=false`,
    });
    expect(calls[0]?.args.join(" ")).not.toContain("current.json");
    expect(calls[0]?.args.join(" ")).not.toContain("certified_train_launch");
  });

  it("fails closed on missing or unknown options without spawning", async () => {
    let calls = 0;
    const command = createAdmitCommand({
      runProducer() {
        calls += 1;
        return { status: 0, stdout: "{}" };
      },
    });

    const result = await command.execute(
      "--workspace C:/operator --unknown value",
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("usage:");
    expect(calls).toBe(0);
  });

  it("refuses any output namespace overlapping the live owned selection before spawning", async () => {
    const overlappingRoots = [
      "C:/config/owned",
      "C:/config/owned/current.json",
      "C:/config/owned/current.json/candidates",
      ...(process.platform === "win32" ? ["c:/CONFIG/OWNED"] : []),
    ];
    for (const outputRoot of overlappingRoots) {
      let calls = 0;
      const command = createAdmitCommand({
        getConfigHome: () => "C:/config",
        runProducer() {
          calls += 1;
          return { status: 0, stdout: "{}" };
        },
      });

      const result = await command.execute(
        `--workspace C:/operator --descriptor C:/operator/admission.json --output-root ${outputRoot}`,
        { sessionId: "s", mode: "local", cwd: "C:/ember" },
      );

      expect(result).toEqual({
        type: "message",
        message: "admission output overlaps live owned selection",
        exitCode: 2,
      });
      expect(calls).toBe(0);
    }
  });

  it("rejects reserved candidate ids returned by the producer", async () => {
    let verificationCalls = 0;
    const command = createAdmitCommand({
      runProducer() {
        return {
          status: 0,
          stdout: JSON.stringify({
            candidate_id: "current.json",
            candidate_sha256: "a".repeat(64),
            producer_receipt_sha256: "b".repeat(64),
            ok: true,
            selected: false,
            loaded: false,
            training_started: false,
          }),
        };
      },
      verifyReceipt() {
        verificationCalls += 1;
        return null;
      },
    });

    const result = await command.execute(
      "--workspace C:/operator --descriptor C:/operator/admission.json --output-root C:/candidates",
      { sessionId: "s", mode: "local", cwd: "C:/ember" },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("invalid authority evidence");
    expect(verificationCalls).toBe(0);
  });
});

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/custody.test.ts — unit tests for the /custody status (alias /seat) command.

import { describe, it, expect } from "bun:test";
import { createCustodyCommand, renderCustodyStatus } from "./custody.ts";
import type { CommandContext } from "../types/command-types.ts";
import type { ModelSeatDecision } from "../entrypoints/model-seat.ts";
import type { CustodyBindingsDeps } from "../services/custody-bindings.ts";

/** In-memory fs double for the `/custody set`/status bindings seam -- mirrors
 *  services/custody-bindings.test.ts's makeMemFs so both suites round-trip
 *  through the exact same production read/write code path. */
function makeMemBindingsFs(initial: Record<string, string> = {}): {
  bindingsFs: CustodyBindingsDeps;
  files: Record<string, string>;
} {
  const files: Record<string, string> = { ...initial };
  const dirs = new Set<string>();
  const bindingsFs: CustodyBindingsDeps = {
    existsSync: (p: string) => p in files || dirs.has(p),
    readFileSync: (p: string) => {
      if (!(p in files)) throw new Error(`ENOENT: ${p}`);
      return files[p]!;
    },
    writeFileSync: (p: string, data: string) => {
      files[p] = data;
    },
    mkdirSync: (p: string) => {
      dirs.add(p);
    },
  };
  return { bindingsFs, files };
}

const mockCtx: CommandContext = {
  sessionId: "test-session",
  mode: "test",
  cwd: "/test",
};

// ---------------------------------------------------------------------------
// Fixture decisions (mirrors entrypoints/model-seat.test.ts's fixture shapes)
// ---------------------------------------------------------------------------

const OWNED_ADMITTED_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "OWNED_ADMITTED",
  source: "owned-manifest",
  argv: ["node", "ember"],
  ownedIdentity: {
    checkpointSha256: "a".repeat(64),
    endpointUrl: "http://127.0.0.1:8083",
    identityUrl: "http://127.0.0.1:8083/v1/models",
    modelConfigSha256: "d".repeat(64),
    serverSourceSha256: "e".repeat(64),
    tokenizerSha256: "f".repeat(64),
    modelName: "ember-owned:a" + "a".repeat(11),
    launch: {
      pythonExecutable: "python",
      serverPath: "/repo/server.py",
      checkpointDir: "/repo/checkpoints/rung-7",
      tokenizerPath: "/repo/tokenizer.json",
      mode: "INTERACTIVE",
      authorityKind: "ADMISSION",
      modelConfigPath: "/repo/model-config.json",
      runManifestPath: "/repo/run-manifest.json",
      trustedVerifierRegistryPath: "/repo/trusted-verifiers.json",
    },
  },
};

const OWNED_DEVELOPMENT_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "OWNED_DEVELOPMENT",
  source: "owned-development-manifest",
  argv: ["node", "ember"],
  ownedIdentity: {
    seat: "OWNED_DEVELOPMENT",
    checkpointSha256: "9".repeat(64),
    endpointUrl: "http://127.0.0.1:8083",
    identityUrl: "http://127.0.0.1:8083/v1/models",
    modelConfigSha256: "d".repeat(64),
    serverSourceSha256: "e".repeat(64),
    tokenizerSha256: "f".repeat(64),
    modelName: "ember-owned-development:" + "9".repeat(12),
    claimStatus: "NON_ADMISSIBLE",
    tokensSeen: 2048,
  },
};

const REFERENCE_ONLY_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "REFERENCE_ONLY",
  source: "flag",
  argv: ["node", "ember"],
  referenceModelName: "qwen3-5",
};

const OFFLINE_DECISION: ModelSeatDecision = {
  allowed: true,
  seat: "OFFLINE",
  source: "gpu-free",
  argv: ["node", "ember"],
};

const REFUSED_DECISION: ModelSeatDecision = {
  allowed: false,
  seat: null,
  source: "none",
  argv: ["node", "ember"],
  error: "no admitted owned Ember identity is available",
};

describe("/custody status (alias /seat)", () => {
  describe("registration", () => {
    it("has name 'custody', alias 'seat', and is enabled", () => {
      const cmd = createCustodyCommand();
      expect(cmd.name).toBe("custody");
      expect(cmd.aliases).toEqual(["seat"]);
      expect(cmd.isEnabled()).toBe(true);
      expect(cmd.description.toLowerCase()).toContain("seat");
    });
  });

  describe("owned seats render OWNED_*", () => {
    it("renders OWNED_ADMITTED with checkpoint dir and structured-outputs field", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: OWNED_ADMITTED");
      expect(result?.message).toContain("source: owned-manifest");
      expect(result?.message).toContain("checkpointDir: /repo/checkpoints/rung-7");
      expect(result?.message).toContain("checkpoint: " + "a".repeat(64));
      expect(result?.message).toContain("structuredOutputs:");
    });

    it("renders OWNED_DEVELOPMENT with claimStatus/tokensSeen and a graceful missing-checkpointDir line", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_DEVELOPMENT_DECISION,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: OWNED_DEVELOPMENT");
      expect(result?.message).toContain("source: owned-development-manifest");
      expect(result?.message).toContain("claimStatus: NON_ADMISSIBLE");
      expect(result?.message).toContain("tokensSeen: 2048");
      // No `launch` on this fixture -- must render gracefully, never crash/undefined.
      expect(result?.message).toContain("checkpointDir: unavailable (no launch descriptor)");
    });

    it("treats empty args and the /seat alias identically to 'status'", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
      });

      const viaEmpty = await cmd.execute("", mockCtx);
      const viaAlias = await cmd.execute("status", mockCtx);

      expect(viaEmpty?.message).toBe(viaAlias?.message);
      expect(viaEmpty?.message).toContain("custody: OWNED_ADMITTED");
    });
  });

  describe("reference seat renders REFERENCE_ONLY", () => {
    it("renders REFERENCE_ONLY with the labeled model name, never a bare routing id", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => REFERENCE_ONLY_DECISION,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: REFERENCE_ONLY");
      expect(result?.message).toContain("source: flag");
      expect(result?.message).toContain("model: REFERENCE_ONLY: qwen3-5");
      expect(result?.message).toContain("structuredOutputs: false");
    });
  });

  describe("offline renders OFFLINE", () => {
    it("renders OFFLINE with an explicit offline reason line", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OFFLINE_DECISION,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: OFFLINE");
      expect(result?.message).toContain("source: gpu-free");
      expect(result?.message).toContain("offline reason:");
      expect(result?.message).not.toContain("checkpoint");
    });
  });

  describe("fail-gracefully: never crash", () => {
    it("renders UNRESOLVED (never throws) when the seat decision is refused (seat === null)", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => REFUSED_DECISION,
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: UNRESOLVED");
      expect(result?.message).toContain("no admitted owned Ember identity is available");
    });

    it("renders UNRESOLVED (never throws) when seat resolution itself throws", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => {
          throw new Error("resolver subprocess crashed");
        },
      });

      const result = await cmd.execute("status", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("custody: UNRESOLVED");
      expect(result?.message).toContain("resolver subprocess crashed");
    });

    it("renderCustodyStatus itself never throws for a refused decision", () => {
      const message = renderCustodyStatus(REFUSED_DECISION);
      expect(message).toContain("UNRESOLVED");
    });
  });

  describe("unknown subcommand", () => {
    it("returns a usage line for an unrecognized subcommand", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
      });

      const result = await cmd.execute("bogus", mockCtx);

      expect(result?.type).toBe("message");
      expect(result?.message).toContain("usage: /custody status");
    });
  });

  describe("/custody set <root_id>=<path>", () => {
    it("writes a binding + round-trips it back via a read", async () => {
      const { bindingsFs } = makeMemBindingsFs();
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
        bindingsFs,
      });

      const setResult = await cmd.execute("set benchmark-root=/mnt/data/bench", mockCtx);
      expect(setResult?.type).toBe("message");
      expect(setResult?.exitCode).toBeUndefined();
      expect(setResult?.message).toContain("benchmark-root");
      expect(setResult?.message).toContain("/mnt/data/bench");

      const statusResult = await cmd.execute("status", mockCtx);
      expect(statusResult?.message).toContain("bindings:");
      expect(statusResult?.message).toContain("benchmark-root -> /mnt/data/bench");
    });

    it("accepts the --binding flag form", async () => {
      const { bindingsFs } = makeMemBindingsFs();
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
        bindingsFs,
      });

      const result = await cmd.execute("set --binding benchmark-root=/mnt/data/bench", mockCtx);
      expect(result?.message).toContain("benchmark-root");

      const status = await cmd.execute("status", mockCtx);
      expect(status?.message).toContain("bindings:");
    });

    it("read-merge-write: a second binding never clobbers the first", async () => {
      const { bindingsFs } = makeMemBindingsFs();
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
        bindingsFs,
      });

      await cmd.execute("set benchmark-root=/mnt/data/bench", mockCtx);
      await cmd.execute("set external-data-root=/mnt/data/external", mockCtx);

      const status = await cmd.execute("status", mockCtx);
      expect(status?.message).toContain("benchmark-root -> /mnt/data/bench");
      expect(status?.message).toContain("external-data-root -> /mnt/data/external");
    });

    it("fails closed (exitCode 1) on a malformed argument, never writing", async () => {
      const { bindingsFs, files } = makeMemBindingsFs();
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
        bindingsFs,
      });

      const result = await cmd.execute("set benchmark-root", mockCtx);
      expect(result?.exitCode).toBe(1);
      expect(Object.keys(files).length).toBe(0);
    });

    it("fails closed (exitCode 1) with no argument at all", async () => {
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
      });

      const result = await cmd.execute("set", mockCtx);
      expect(result?.exitCode).toBe(1);
      expect(result?.message).toContain("usage:");
    });
  });

  describe("/custody status with an absent bindings store", () => {
    it("falls back cleanly (no bindings section) when the store does not exist", async () => {
      const { bindingsFs } = makeMemBindingsFs();
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
        resolveRepoRoot: () => "/repo",
        bindingsFs,
      });

      const result = await cmd.execute("status", mockCtx);
      expect(result?.message).not.toContain("bindings:");
      expect(result?.message).toContain("custody: OWNED_ADMITTED");
    });
  });

  describe("read-only: no mutation", () => {
    it("never touches process.env", async () => {
      const before = { ...process.env };
      const cmd = createCustodyCommand({
        getModelSeatDecision: () => OWNED_ADMITTED_DECISION,
      });

      await cmd.execute("status", mockCtx);

      expect(process.env).toEqual(before);
    });
  });
});

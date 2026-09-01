// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join, resolve } from "path";

import {
  captureDevelopmentResolver,
  loadOwnedDevelopmentIdentity,
  loadOwnedModelIdentity,
  OwnedSeatStaleBindingError,
  verifyOwnedEndpointIdentity,
} from "./owned-seat-loader.ts";
import { emberScratchDir } from "../utils/ember-scratch.ts";

const CHECKPOINT = "d".repeat(64);

describe("owned seat loader", () => {
  it("authenticates the complete runtime closure against Git and snapshots it before execution", () => {
    const root = mkdtempSync(join(tmpdir(), "ember-bootstrap-test-"));
    const sourceCommit = "a".repeat(40);
    const trustedSources = [
      "configs/ember-restart-3b.json",
      "src/ember/governance/scripts/ember_restart/development_cli_seat.py",
      "src/ember/governance/scripts/ember_restart/prediction_contract.py",
      "scripts/ember_restart_eval_checkpoint_consumer.py",
      "scripts/ember_restart_eval_raw_forward.py",
      "domains/model/tokenizer/tokenizer.json",
      "tools/ember-restart-3b/batch.py",
      "tools/ember-restart-3b/checkpoint_artifacts.py",
      "tools/ember-restart-3b/infer.py",
      "tools/ember-restart-3b/model.py",
      "tools/ember-restart-3b/parameter_counter.py",
      "tools/ember-restart-3b/serve_owned_openai.py",
    ];
    const runtimeFiles = [
      ...trustedSources,
      "parameter-evidence/parameter_counter.py",
      "parameter-evidence/step2-realization-receipt.json",
      "parameter-evidence/trusted-verifiers.json",
    ];
    try {
      for (const relativePath of runtimeFiles) {
        const path = join(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, relativePath === "src/ember/governance/scripts/ember_restart/development_cli_seat.py"
          ? "# exact resolver\n"
          : "exact:" + relativePath + "\n");
      }
      const files = Object.fromEntries(runtimeFiles.map((relativePath) => {
        const payload = readFileSync(join(root, relativePath));
        return [relativePath, {
          bytes: payload.byteLength,
          sha256: new Bun.CryptoHasher("sha256").update(payload).digest("hex"),
        }];
      }));
      const index = {
        schema_version: "ember-owned-runtime-bundle-v1",
        source_commit: sourceCommit,
        files,
      };
      const indexBytes = new TextEncoder().encode(JSON.stringify(index));
      writeFileSync(join(root, "runtime-bundle-index.json"), indexBytes);
      const manifest = {
        runtime_bundle: {
          index_path: "runtime-bundle-index.json",
          sha256: new Bun.CryptoHasher("sha256").update(indexBytes).digest("hex"),
        },
      };
      const manifestPath = join(root, "development.json");
      writeFileSync(manifestPath, JSON.stringify(manifest));
      const readGitBlob = (_repoRoot: string, _commit: string, relativePath: string) =>
        readFileSync(join(root, relativePath));

      const captured = captureDevelopmentResolver(manifestPath, root, sourceCommit, readGitBlob);
      writeFileSync(join(root, "scripts", "ember_restart", "development_cli_seat.py"), "# drifted resolver\n");
      expect(new TextDecoder().decode(readFileSync(captured.resolverPath))).toBe(
        "# exact resolver\n",
      );
      expect(captured.manifestSha256).toMatch(/^[0-9a-f]{64}$/);
      expect(captured.runtimeIndexSha256).toBe(manifest.runtime_bundle.sha256);
      expect(existsSync(captured.manifestPath)).toBe(true);
      captured.cleanup();
      expect(existsSync(captured.resolverPath)).toBe(false);
      expect(() => captureDevelopmentResolver(manifestPath, root, "b".repeat(40), readGitBlob)).toThrow(
        "exact compiled cockpit commit",
      );
      expect(() => captureDevelopmentResolver(
        manifestPath,
        root,
        sourceCommit,
        (_repoRoot, _commit, relativePath) =>
          relativePath === "tools/ember-restart-3b/model.py"
            ? new TextEncoder().encode("forged\n")
            : readFileSync(join(root, relativePath)),
      )).toThrow("embedded Git commit");
    } finally {
      rmSync(root, { force: true, recursive: true });
    }
  });

  // Acceptance map: state/specs/cockpit-stale-binding-demotion-acceptance-map-2026-07-25.md
  // Section 5, tests 1-4. This describe block proves the loader-level half: exactly one of
  // the 39 throws (line 209, stale source_commit) is the typed OwnedSeatStaleBindingError, and
  // every other throw this fixture can reach -- including a plain Error whose message is
  // byte-identical to line 209's string -- is NOT that type. process-entry.test.ts proves the
  // consumer-level half (the catch demotes on instanceof and nothing else).
  describe("OwnedSeatStaleBindingError -- typed, not message-matched (map section 3 + 5)", () => {
    function buildFixture(root: string) {
      const sourceCommit = "a".repeat(40);
      const trustedSources = [
        "configs/ember-restart-3b.json",
        "src/ember/governance/scripts/ember_restart/development_cli_seat.py",
        "src/ember/governance/scripts/ember_restart/prediction_contract.py",
        "scripts/ember_restart_eval_checkpoint_consumer.py",
        "scripts/ember_restart_eval_raw_forward.py",
        "domains/model/tokenizer/tokenizer.json",
        "tools/ember-restart-3b/batch.py",
        "tools/ember-restart-3b/checkpoint_artifacts.py",
        "tools/ember-restart-3b/infer.py",
        "tools/ember-restart-3b/model.py",
        "tools/ember-restart-3b/parameter_counter.py",
        "tools/ember-restart-3b/serve_owned_openai.py",
      ];
      const runtimeFiles = [
        ...trustedSources,
        "parameter-evidence/parameter_counter.py",
        "parameter-evidence/step2-realization-receipt.json",
        "parameter-evidence/trusted-verifiers.json",
      ];
      for (const relativePath of runtimeFiles) {
        const path = join(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, relativePath === "src/ember/governance/scripts/ember_restart/development_cli_seat.py"
          ? "# exact resolver\n"
          : "exact:" + relativePath + "\n");
      }
      const files = Object.fromEntries(runtimeFiles.map((relativePath) => {
        const payload = readFileSync(join(root, relativePath));
        return [relativePath, {
          bytes: payload.byteLength,
          sha256: new Bun.CryptoHasher("sha256").update(payload).digest("hex"),
        }];
      }));
      const index = {
        schema_version: "ember-owned-runtime-bundle-v1",
        source_commit: sourceCommit,
        files,
      };
      const indexBytes = new TextEncoder().encode(JSON.stringify(index));
      writeFileSync(join(root, "runtime-bundle-index.json"), indexBytes);
      const manifest = {
        runtime_bundle: {
          index_path: "runtime-bundle-index.json",
          sha256: new Bun.CryptoHasher("sha256").update(indexBytes).digest("hex"),
        },
      };
      const manifestPath = join(root, "development.json");
      writeFileSync(manifestPath, JSON.stringify(manifest));
      const readGitBlob = (_repoRoot: string, _commit: string, relativePath: string) =>
        readFileSync(join(root, relativePath));
      return { sourceCommit, manifestPath, readGitBlob, index, indexBytes };
    }

    it("test 1 (D1 RED): stale source_commit throws OwnedSeatStaleBindingError, not a plain Error", () => {
      const root = mkdtempSync(join(tmpdir(), "ember-stale-binding-test-"));
      try {
        const { manifestPath, readGitBlob } = buildFixture(root);
        let caught: unknown;
        try {
          captureDevelopmentResolver(manifestPath, root, "b".repeat(40), readGitBlob);
        } catch (error) {
          caught = error;
        }
        expect(caught).toBeInstanceOf(OwnedSeatStaleBindingError);
        expect((caught as Error).message).toContain("exact compiled cockpit commit");
        // D4: the demotion banner names the remedy -- both escapes, in the operator's words.
        expect((caught as Error).message).toContain("--reference-seat");
        expect((caught as Error).message).toContain("EMBER_GPU_FREE=1");
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 2a (D2 RED, line 201): index content hash mismatch throws a plain Error, not OwnedSeatStaleBindingError", () => {
      const root = mkdtempSync(join(tmpdir(), "ember-tamper-index-test-"));
      try {
        const { manifestPath, readGitBlob } = buildFixture(root);
        // Corrupt the index bytes on disk after the manifest's sha256 was computed against
        // the original bytes -- this is the tamper case, not the stale-commit case.
        writeFileSync(join(root, "runtime-bundle-index.json"), "{}");
        let caught: unknown;
        try {
          captureDevelopmentResolver(manifestPath, root, "a".repeat(40), readGitBlob);
        } catch (error) {
          caught = error;
        }
        expect(caught).not.toBeInstanceOf(OwnedSeatStaleBindingError);
        expect((caught as Error).message).toBe("runtime bundle index content hash mismatch");
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 2b (D2 RED, line 224): an invalid trusted-source binding throws a plain Error, not OwnedSeatStaleBindingError", () => {
      const root = mkdtempSync(join(tmpdir(), "ember-tamper-binding-test-"));
      try {
        const { sourceCommit, index, readGitBlob } = buildFixture(root);
        const corruptIndex = {
          ...index,
          files: {
            ...index.files,
            "tools/ember-restart-3b/model.py": { bytes: -1, sha256: "not-a-hash" },
          },
        };
        const corruptIndexBytes = new TextEncoder().encode(JSON.stringify(corruptIndex));
        writeFileSync(join(root, "runtime-bundle-index.json"), corruptIndexBytes);
        const manifest = {
          runtime_bundle: {
            index_path: "runtime-bundle-index.json",
            sha256: new Bun.CryptoHasher("sha256").update(corruptIndexBytes).digest("hex"),
          },
        };
        const manifestPath = join(root, "development.json");
        writeFileSync(manifestPath, JSON.stringify(manifest));
        let caught: unknown;
        try {
          captureDevelopmentResolver(manifestPath, root, sourceCommit, readGitBlob);
        } catch (error) {
          caught = error;
        }
        expect(caught).not.toBeInstanceOf(OwnedSeatStaleBindingError);
        expect((caught as Error).message).toBe(
          "trusted runtime source binding is invalid: tools/ember-restart-3b/model.py",
        );
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 2c (D2 RED, line 239): a source-byte mismatch against the embedded Git commit throws a plain Error, not OwnedSeatStaleBindingError", () => {
      const root = mkdtempSync(join(tmpdir(), "ember-tamper-source-test-"));
      try {
        const { sourceCommit, manifestPath } = buildFixture(root);
        const forgingReadGitBlob = (_repoRoot: string, _commit: string, relativePath: string) =>
          relativePath === "tools/ember-restart-3b/model.py"
            ? new TextEncoder().encode("forged\n")
            : readFileSync(join(root, relativePath));
        let caught: unknown;
        try {
          captureDevelopmentResolver(manifestPath, root, sourceCommit, forgingReadGitBlob);
        } catch (error) {
          caught = error;
        }
        expect(caught).not.toBeInstanceOf(OwnedSeatStaleBindingError);
        expect((caught as Error).message).toBe(
          "runtime source does not match the embedded Git commit: tools/ember-restart-3b/model.py",
        );
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 2d (D2 RED, line 220 + ORDER): an unrecognised schema throws a plain Error even when the commit is ALSO stale -- schema is checked first and never demotes", () => {
      // The schema check and the stale-commit check were split out of one compound
      // condition, so the branch that decides which of them wins is exactly the byte a
      // future refactor would fold back together. This test pins the ORDER, not just the
      // disposition: the fixture is bad in BOTH ways at once, so a merged compound
      // condition would throw the typed error and turn this RED. Testing schema-mismatch
      // alone would leave the conjunction -- the case where a demotable defect and a
      // non-demotable one are present together -- unproved, and that conjunction is the
      // only input class on which the ordering is observable.
      const root = mkdtempSync(join(tmpdir(), "ember-schema-order-test-"));
      try {
        const { index, readGitBlob } = buildFixture(root);
        const wrongSchemaIndex = { ...index, schema_version: "ember-owned-runtime-bundle-v2" };
        const wrongSchemaBytes = new TextEncoder().encode(JSON.stringify(wrongSchemaIndex));
        writeFileSync(join(root, "runtime-bundle-index.json"), wrongSchemaBytes);
        const manifest = {
          runtime_bundle: {
            index_path: "runtime-bundle-index.json",
            sha256: new Bun.CryptoHasher("sha256").update(wrongSchemaBytes).digest("hex"),
          },
        };
        const manifestPath = join(root, "development.json");
        writeFileSync(manifestPath, JSON.stringify(manifest));
        let caught: unknown;
        try {
          // "b" x40 is a well-formed commit id that is NOT the fixture's source_commit,
          // so the stale-commit branch is live and reachable at the same time.
          captureDevelopmentResolver(manifestPath, root, "b".repeat(40), readGitBlob);
        } catch (error) {
          caught = error;
        }
        expect(caught).not.toBeInstanceOf(OwnedSeatStaleBindingError);
        expect((caught as Error).message).toBe("runtime bundle index schema is not recognised");
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 2e (D2 RED, sibling traversal): a MALFORMED source_commit is fatal, not demotable -- every shape, each with a stale expectation", () => {
      // The demotion branch is the only lenient outcome here, and `!==` gives
      // the same answer for "different" and "malformed". Without a shape check
      // ahead of it, null / an object / uppercase / non-hex / wrong-length all
      // took the permitted OFFLINE demotion instead of staying fatal.
      //
      // Enumerated rather than sampled: one representative per way the field can
      // be wrong. Test 2d pinned the schema-vs-stale traversal and this is its
      // sibling -- proving one traversal is not proving the set.
      const malformed: Array<[string, unknown]> = [
        ["null", null],
        ["object", { sha: "a".repeat(40) }],
        ["uppercase hex", "A".repeat(40)],
        ["non-hex", "z".repeat(40)],
        ["too short", "a".repeat(39)],
        ["empty string", ""],
      ];
      for (const [label, value] of malformed) {
        const root = mkdtempSync(join(tmpdir(), "ember-badcommit-test-"));
        try {
          const { index, readGitBlob } = buildFixture(root);
          const badIndex = { ...index, source_commit: value };
          const badBytes = new TextEncoder().encode(JSON.stringify(badIndex));
          writeFileSync(join(root, "runtime-bundle-index.json"), badBytes);
          const manifestPath = join(root, "development.json");
          writeFileSync(
            manifestPath,
            JSON.stringify({
              runtime_bundle: {
                index_path: "runtime-bundle-index.json",
                sha256: new Bun.CryptoHasher("sha256").update(badBytes).digest("hex"),
              },
            }),
          );
          let caught: unknown;
          try {
            // A stale expectation too, so the demotion branch is live: this is
            // the conjunction, not the malformed field alone.
            captureDevelopmentResolver(manifestPath, root, "b".repeat(40), readGitBlob);
          } catch (error) {
            caught = error;
          }
          expect(caught).not.toBeInstanceOf(OwnedSeatStaleBindingError);
          expect((caught as Error).message).toBe(
            "runtime bundle index source commit is invalid",
          );
        } finally {
          rmSync(root, { force: true, recursive: true });
        }
      }
    });

    it("test 3 (D3 over-closure): a matching, valid bundle admits the owned seat unchanged -- no typed error, no throw", () => {
      const root = mkdtempSync(join(tmpdir(), "ember-matching-bundle-test-"));
      try {
        const { sourceCommit, manifestPath, readGitBlob } = buildFixture(root);
        const captured = captureDevelopmentResolver(manifestPath, root, sourceCommit, readGitBlob);
        expect(captured.manifestSha256).toMatch(/^[0-9a-f]{64}$/);
        captured.cleanup();
      } finally {
        rmSync(root, { force: true, recursive: true });
      }
    });

    it("test 4 (mandatory, section 5): a plain Error with a byte-identical message to line 209's string is NOT the typed class", () => {
      // This is the test that makes the substring shortcut impossible to reintroduce.
      // If a future refactor demotes on message text instead of `instanceof`, this proves
      // the class boundary is still what the catch must key on -- a same-text plain Error
      // is a different failure than the one the map allows to demote.
      const impostor = new Error(
        "runtime bundle is not bound to the exact compiled cockpit commit; the owned seat is " +
        "refused and the cockpit continues OFFLINE. Use --reference-seat for explicit " +
        "REFERENCE_ONLY parity testing or EMBER_GPU_FREE=1 for offline observation.",
      );
      expect(impostor).not.toBeInstanceOf(OwnedSeatStaleBindingError);
      expect(impostor.message).toBe(
        new OwnedSeatStaleBindingError(impostor.message).message,
      );
    });
  });

  it("snapshots the owned development runtime under EMBER_HOME regardless of %TEMP% casing/validity (NO-TEMP regression)", () => {
    // Regression for the launch-blocker: the snapshot used to live at
    // mkdtempSync(join(tmpdir(), ...)), i.e. inside the OS-managed system
    // temp directory, whose casing on Windows does not match the real
    // filesystem case and broke case-sensitive path comparisons. The fix
    // routes the snapshot through
    // emberScratchDir(), which never touches system temp at all. Prove that
    // by pointing TEMP/TMP at a differently-cased, nonexistent path before
    // exercising the loader — the snapshot must still land under EMBER_HOME.
    const emberHome = join(process.cwd(), ".ember-home-owned-seat-loader-test");
    const previousEmberHome = process.env.EMBER_HOME;
    const previousTemp = process.env.TEMP;
    const previousTmp = process.env.TMP;
    rmSync(emberHome, { force: true, recursive: true });
    process.env.EMBER_HOME = emberHome;
    process.env.TEMP = "C:\\NONEXISTENT-BOGUS-TEMP-CASING-PROBE";
    process.env.TMP = "C:\\NONEXISTENT-BOGUS-TEMP-CASING-PROBE";
    const root = join(emberScratchDir("test-fixture-bundle"), "bundle");
    mkdirSync(root, { recursive: true });
    const sourceCommit = "a".repeat(40);
    const trustedSources = [
      "configs/ember-restart-3b.json",
      "src/ember/governance/scripts/ember_restart/development_cli_seat.py",
      "src/ember/governance/scripts/ember_restart/prediction_contract.py",
      "scripts/ember_restart_eval_checkpoint_consumer.py",
      "scripts/ember_restart_eval_raw_forward.py",
      "domains/model/tokenizer/tokenizer.json",
      "tools/ember-restart-3b/batch.py",
      "tools/ember-restart-3b/checkpoint_artifacts.py",
      "tools/ember-restart-3b/infer.py",
      "tools/ember-restart-3b/model.py",
      "tools/ember-restart-3b/parameter_counter.py",
      "tools/ember-restart-3b/serve_owned_openai.py",
    ];
    const runtimeFiles = [
      ...trustedSources,
      "parameter-evidence/parameter_counter.py",
      "parameter-evidence/step2-realization-receipt.json",
      "parameter-evidence/trusted-verifiers.json",
    ];
    try {
      for (const relativePath of runtimeFiles) {
        const path = join(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, relativePath === "src/ember/governance/scripts/ember_restart/development_cli_seat.py"
          ? "# exact resolver\n"
          : "exact:" + relativePath + "\n");
      }
      const files = Object.fromEntries(runtimeFiles.map((relativePath) => {
        const payload = readFileSync(join(root, relativePath));
        return [relativePath, {
          bytes: payload.byteLength,
          sha256: new Bun.CryptoHasher("sha256").update(payload).digest("hex"),
        }];
      }));
      const index = {
        schema_version: "ember-owned-runtime-bundle-v1",
        source_commit: sourceCommit,
        files,
      };
      const indexBytes = new TextEncoder().encode(JSON.stringify(index));
      writeFileSync(join(root, "runtime-bundle-index.json"), indexBytes);
      const manifest = {
        runtime_bundle: {
          index_path: "runtime-bundle-index.json",
          sha256: new Bun.CryptoHasher("sha256").update(indexBytes).digest("hex"),
        },
      };
      const manifestPath = join(root, "development.json");
      writeFileSync(manifestPath, JSON.stringify(manifest));
      const readGitBlob = (_repoRoot: string, _commit: string, relativePath: string) =>
        readFileSync(join(root, relativePath));

      const captured = captureDevelopmentResolver(manifestPath, root, sourceCommit, readGitBlob);
      const canonicalEmberHome = realpathSync.native(emberHome);
      expect(captured.resolverPath.startsWith(canonicalEmberHome)).toBe(true);
      expect(captured.resolverPath.toLowerCase().includes("bogus")).toBe(false);
      expect(existsSync(captured.resolverPath)).toBe(true);
      captured.cleanup();
      expect(existsSync(captured.resolverPath)).toBe(false);
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

  it("returns unavailable when the default pointer does not exist", () => {
    let executed = false;
    const identity = loadOwnedModelIdentity(
      { repoRoot: "C:/repo", configHome: "C:/home" },
      {
        exists: () => false,
        execute: () => {
          executed = true;
          return { status: 0, stdout: "{}", stderr: "" };
        },
      },
    );
    expect(identity).toBeUndefined();
    expect(executed).toBe(false);
  });

  it("fails closed when an explicitly selected manifest is missing", () => {
    expect(() =>
      loadOwnedModelIdentity(
        {
          repoRoot: "C:/repo",
          configHome: "C:/home",
          manifestPath: "C:/missing.json",
        },
        { exists: () => false },
      ),
    ).toThrow("owned rung manifest does not exist");
  });

  it("executes the central resolver and derives the admitted identity", () => {
    let observedArgs: string[] = [];
    const identity = loadOwnedModelIdentity(
      {
        repoRoot: "C:/repo",
        configHome: "C:/home",
        manifestPath: resolve("C:/run.json"),
        verifierRegistryPath: resolve("C:/trusted.json"),
        verifierRegistryApprovalPath: resolve("C:/trusted-approval.json"),
        pythonExecutable: "python-owned",
      },
      {
        exists: () => true,
        execute: (executable, args) => {
          observedArgs = [executable, ...args];
          return {
            status: 0,
            stderr: "",
            stdout: JSON.stringify({
              valid: true,
              seat: "OWNED_ADMITTED",
              checkpoint_sha256: CHECKPOINT,
              endpoint_url: "http://127.0.0.1:8083",
              identity_url: "http://127.0.0.1:8083/v1/models",
              model_config_sha256: "b".repeat(64),
              model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
              model_format: "safetensors",
              server_source_sha256: "a".repeat(64),
              tokenizer_sha256: "c".repeat(64),
              launch: {
                checkpoint_dir: resolve("C:/owned/checkpoint"),
                mode: "INTERACTIVE",
                model_config_path: resolve("C:/owned/model-config.json"),
                run_manifest_path: resolve("C:/run.json"),
                server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
                tokenizer_path: resolve("C:/owned/tokenizer.json"),
                trusted_verifier_registry_path: resolve("C:/trusted.json"),
                trusted_verifier_registry_sha256: "d".repeat(64),
                trusted_verifier_registry_approval_path: resolve("C:/trusted-approval.json"),
                trusted_verifier_registry_approval_sha256: "e".repeat(64),
              },
            }),
          };
        },
      },
    );

    expect(identity).toEqual({
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      modelFormat: "safetensors",
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
      launch: {
        authorityKind: "ADMISSION",
        checkpointDir: resolve("C:/owned/checkpoint"),
        mode: "INTERACTIVE",
      modelConfigPath: "C:\\owned\\model-config.json",
        pythonExecutable: "python-owned",
        runManifestPath: resolve("C:/run.json"),
        serverPath: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
        tokenizerPath: resolve("C:/owned/tokenizer.json"),
        trustedVerifierRegistryPath: resolve("C:/trusted.json"),
        trustedVerifierRegistrySha256: "d".repeat(64),
        trustedVerifierRegistryApprovalPath: resolve("C:/trusted-approval.json"),
        trustedVerifierRegistryApprovalSha256: "e".repeat(64),
      },
    });
    expect(observedArgs).toEqual([
      "python-owned",
      "C:\\repo\\scripts\\ember_restart\\cli_seat.py",
      "C:\\run.json",
      "--trusted-verifier-registry",
      "C:\\trusted.json",
      "--trusted-verifier-registry-approval",
      "C:\\trusted-approval.json",
    ]);
  });

  it("parses model_config_capabilities from a real seat payload end-to-end through the real loader", () => {
    const configSha = "b".repeat(64);
    const seatPayload = {
      valid: true,
      seat: "OWNED_ADMITTED",
      checkpoint_sha256: CHECKPOINT,
      endpoint_url: "http://127.0.0.1:8083",
      identity_url: "http://127.0.0.1:8083/v1/models",
      model_config_sha256: configSha,
      model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
      model_format: "safetensors",
      server_source_sha256: "a".repeat(64),
      tokenizer_sha256: "c".repeat(64),
      model_config_capabilities: {
        model_config_sha256: configSha,
        structured_outputs: true,
      },
      launch: {
        checkpoint_dir: resolve("C:/owned/checkpoint"),
        mode: "INTERACTIVE",
        model_config_path: resolve("C:/owned/model-config.json"),
        run_manifest_path: resolve("C:/run.json"),
        server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
        tokenizer_path: resolve("C:/owned/tokenizer.json"),
        trusted_verifier_registry_path: resolve("C:/trusted.json"),
        trusted_verifier_registry_sha256: "d".repeat(64),
        trusted_verifier_registry_approval_path: resolve("C:/trusted-approval.json"),
        trusted_verifier_registry_approval_sha256: "e".repeat(64),
      },
    };
    const identity = loadOwnedModelIdentity(
      {
        repoRoot: "C:/repo",
        configHome: "C:/home",
        manifestPath: resolve("C:/run.json"),
        verifierRegistryPath: resolve("C:/trusted.json"),
        verifierRegistryApprovalPath: resolve("C:/trusted-approval.json"),
        pythonExecutable: "python-owned",
      },
      {
        exists: () => true,
        execute: () => ({ status: 0, stderr: "", stdout: JSON.stringify(seatPayload) }),
      },
    );
    expect(identity?.modelConfigCapabilities).toEqual({
      modelConfigSha256: configSha,
      structuredOutputs: true,
    });
  });

  it("rejects a capability declaration whose hash does not match the served model config", () => {
    const seatPayload = {
      valid: true,
      seat: "OWNED_ADMITTED",
      checkpoint_sha256: CHECKPOINT,
      endpoint_url: "http://127.0.0.1:8083",
      identity_url: "http://127.0.0.1:8083/v1/models",
      model_config_sha256: "b".repeat(64),
      model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
      model_format: "safetensors",
      server_source_sha256: "a".repeat(64),
      tokenizer_sha256: "c".repeat(64),
      model_config_capabilities: {
        model_config_sha256: "e".repeat(64),
        structured_outputs: true,
      },
      launch: {
        checkpoint_dir: resolve("C:/owned/checkpoint"),
        mode: "INTERACTIVE",
        model_config_path: resolve("C:/owned/model-config.json"),
        run_manifest_path: resolve("C:/run.json"),
        server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
        tokenizer_path: resolve("C:/owned/tokenizer.json"),
        trusted_verifier_registry_path: resolve("C:/trusted.json"),
        trusted_verifier_registry_sha256: "d".repeat(64),
      },
    };
    expect(() =>
      loadOwnedModelIdentity(
        {
          repoRoot: "C:/repo",
          configHome: "C:/home",
          manifestPath: resolve("C:/run.json"),
          verifierRegistryPath: resolve("C:/trusted.json"),
          pythonExecutable: "python-owned",
        },
        {
          exists: () => true,
          execute: () => ({ status: 0, stderr: "", stdout: JSON.stringify(seatPayload) }),
        },
      ),
    ).toThrow("capability declaration");
  });

  it("loads a closed development identity through the separate non-claiming resolver", () => {
    let observedArgs: string[] = [];
    let cleanupCalls = 0;
    const identity = loadOwnedDevelopmentIdentity(
      {
        repoRoot: "C:/repo",
        configHome: "C:/home",
        manifestPath: resolve("C:/development.json"),
        pythonExecutable: "python-owned",
      },
      {
        exists: () => true,
        resolveBuildCommit: () => "a".repeat(40),
        captureDevelopmentResolver: () => ({
          cleanup: () => { cleanupCalls += 1; },
          manifestPath: resolve("C:/snapshot/development.json"),
          manifestSha256: "e".repeat(64),
          resolverPath: resolve("C:/snapshot/development_cli_seat.py"),
          runtimeIndexPath: resolve("C:/snapshot/runtime-bundle-index.json"),
          runtimeIndexSha256: "f".repeat(64),
        }),
        execute: (executable, args) => {
          observedArgs = [executable, ...args];
          return {
            status: 0,
            stderr: "",
            stdout: JSON.stringify({
              valid: true,
              seat: "OWNED_DEVELOPMENT",
              claim_status: "NON_ADMISSIBLE",
              checkpoint_sha256: CHECKPOINT,
              endpoint_url: "http://127.0.0.1:8083",
              identity_url: "http://127.0.0.1:8083/v1/models",
              model_config_sha256: "b".repeat(64),
              model_name: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
              model_format: "pytorch-checkpoint-v3",
              server_source_sha256: "a".repeat(64),
              tokenizer_sha256: "c".repeat(64),
              tokens_seen: 2048,
              allocated_parameters: 3_839_161_856,
              active_parameters: 1_020_589_568,
              launch: {
                checkpoint_dir: resolve("C:/owned/checkpoint"),
                development_manifest_path: resolve("C:/snapshot/development.json"),
                mode: "INTERACTIVE",
                model_config_path: resolve("C:/owned/model-config.json"),
                server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
                tokenizer_path: resolve("C:/owned/tokenizer.json"),
              },
            }),
          };
        },
      },
    );

    expect(identity?.seat).toBe("OWNED_DEVELOPMENT");
    expect(identity?.claimStatus).toBe("NON_ADMISSIBLE");
    expect(identity?.tokensSeen).toBe(2048);
    expect(identity?.allocatedParameters).toBe(3_839_161_856);
    expect(identity?.launch).toEqual({
      authorityKind: "DEVELOPMENT",
      checkpointDir: resolve("C:/owned/checkpoint"),
      cleanupRuntimeSnapshot: expect.any(Function),
      developmentManifestSha256: "e".repeat(64),
      developmentManifestPath: resolve("C:/snapshot/development.json"),
      mode: "INTERACTIVE",
      modelConfigPath: resolve("C:/owned/model-config.json"),
      pythonExecutable: "python-owned",
      runtimeIndexPath: resolve("C:/snapshot/runtime-bundle-index.json"),
      runtimeIndexSha256: "f".repeat(64),
      serverPath: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
      tokenizerPath: resolve("C:/owned/tokenizer.json"),
    });
    expect(observedArgs).toEqual([
      "python-owned",
      "C:\\snapshot\\development_cli_seat.py",
      "C:\\snapshot\\development.json",
      "--expected-manifest-sha256",
      "e".repeat(64),
      "--expected-runtime-index-sha256",
      "f".repeat(64),
    ]);
    expect(cleanupCalls).toBe(0);
    if (identity?.launch?.authorityKind !== "DEVELOPMENT") throw new Error("missing development launch");
    identity.launch.cleanupRuntimeSnapshot();
    expect(cleanupCalls).toBe(1);
  });

  it("validates a development launch when the resolver echoes a differently-cased manifest path, and still rejects a genuinely different file", () => {
    // Regression for the owned-seat launch blocker: the %TEMP% environment
    // value on Windows can differ in letter-case from the real on-disk case of
    // the same directory, so the snapshot path handed to the Python resolver
    // and the Path.resolve()'d path it echoes back could differ only in case.
    // A raw case-sensitive `!==` on those two paths killed every owned-seat
    // development launch with "invalid launch descriptor". The compare is now
    // case-correct (sameResolvedPath) WITHOUT weakening the trust binding:
    // prove BOTH directions here.
    const caseInsensitiveFs = process.platform === "win32" || process.platform === "darwin";
    const build = (echoedManifestPath: string) =>
      loadOwnedDevelopmentIdentity(
        {
          repoRoot: "C:/repo",
          configHome: "C:/home",
          manifestPath: resolve("C:/development.json"),
          pythonExecutable: "python-owned",
        },
        {
          exists: () => true,
          resolveBuildCommit: () => "a".repeat(40),
          captureDevelopmentResolver: () => ({
            cleanup: () => {},
            // Snapshot manifest recorded with one casing ...
            manifestPath: resolve("C:/Snapshot/Development.json"),
            manifestSha256: "e".repeat(64),
            resolverPath: resolve("C:/snapshot/development_cli_seat.py"),
            runtimeIndexPath: resolve("C:/snapshot/runtime-bundle-index.json"),
            runtimeIndexSha256: "f".repeat(64),
          }),
          execute: () => ({
            status: 0,
            stderr: "",
            stdout: JSON.stringify({
              valid: true,
              seat: "OWNED_DEVELOPMENT",
              claim_status: "NON_ADMISSIBLE",
              checkpoint_sha256: CHECKPOINT,
              endpoint_url: "http://127.0.0.1:8083",
              identity_url: "http://127.0.0.1:8083/v1/models",
              model_config_sha256: "b".repeat(64),
              model_name: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
              model_format: "pytorch-checkpoint-v3",
              server_source_sha256: "a".repeat(64),
              tokenizer_sha256: "c".repeat(64),
              tokens_seen: 2048,
              allocated_parameters: 3_839_161_856,
              active_parameters: 1_020_589_568,
              launch: {
                checkpoint_dir: resolve("C:/owned/checkpoint"),
                // ... and echoed back with whatever casing the resolver used.
                development_manifest_path: echoedManifestPath,
                mode: "INTERACTIVE",
                model_config_path: resolve("C:/owned/model-config.json"),
                server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
                tokenizer_path: resolve("C:/owned/tokenizer.json"),
              },
            }),
          }),
        },
      );

    // POSITIVE (case-insensitive FS): a differently-cased spelling of the SAME
    // snapshot manifest still validates the launch. On case-sensitive FS the
    // temp-casing failure mode does not exist, so this branch is Windows/macOS.
    if (caseInsensitiveFs) {
      const identity = build(resolve("c:/snapshot/development.json"));
      expect(identity?.seat).toBe("OWNED_DEVELOPMENT");
    }

    // NEGATIVE (all platforms): a genuinely DIFFERENT file — not merely a
    // different case — is STILL rejected. The trust binding is not weakened.
    expect(() => build(resolve("C:/snapshot/development-IMPOSTER.json"))).toThrow(
      "invalid launch descriptor",
    );
  });

  it("validates an admitted (owned) launch when the resolver echoes differently-cased manifest/registry paths, and still rejects a genuinely different file", () => {
    // Class-closure of the development-seat case-correctness fix above: the
    // ADMITTED-seat compare in parseOwnedLaunch had the identical raw
    // case-sensitive `!==` on runManifestPath/trustedVerifierRegistryPath.
    // Now case-correct via the same sameResolvedPath helper — prove BOTH
    // directions here too, without weakening the trust binding.
    const caseInsensitiveFs = process.platform === "win32" || process.platform === "darwin";
    const build = (
      echoedManifestPath: string,
      echoedRegistryPath: string,
      echoedRegistryApprovalPath: string,
    ) =>
      loadOwnedModelIdentity(
        {
          repoRoot: "C:/repo",
          configHome: "C:/home",
          // Expected paths recorded with one casing ...
          manifestPath: resolve("C:/Run/Manifest.json"),
          verifierRegistryPath: resolve("C:/Trusted/Verifiers.json"),
          verifierRegistryApprovalPath: resolve("C:/Trusted/Approval.json"),
          pythonExecutable: "python-owned",
        },
        {
          exists: () => true,
          execute: () => ({
            status: 0,
            stderr: "",
            stdout: JSON.stringify({
              valid: true,
              seat: "OWNED_ADMITTED",
              checkpoint_sha256: CHECKPOINT,
              endpoint_url: "http://127.0.0.1:8083",
              identity_url: "http://127.0.0.1:8083/v1/models",
              model_config_sha256: "b".repeat(64),
              model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
              model_format: "safetensors",
              server_source_sha256: "a".repeat(64),
              tokenizer_sha256: "c".repeat(64),
              launch: {
                checkpoint_dir: resolve("C:/owned/checkpoint"),
                mode: "INTERACTIVE",
                model_config_path: resolve("C:/owned/model-config.json"),
                // ... and echoed back with whatever casing the resolver used.
                run_manifest_path: echoedManifestPath,
                server_path: resolve("C:/repo/tools/ember-restart-3b/serve_owned_openai.py"),
                tokenizer_path: resolve("C:/owned/tokenizer.json"),
                trusted_verifier_registry_path: echoedRegistryPath,
                trusted_verifier_registry_sha256: "d".repeat(64),
                trusted_verifier_registry_approval_path: echoedRegistryApprovalPath,
                trusted_verifier_registry_approval_sha256: "e".repeat(64),
              },
            }),
          }),
        },
      );

    // POSITIVE (case-insensitive FS): differently-cased spellings of the SAME
    // manifest and registry files still validate the admitted seat. On
    // case-sensitive FS the casing failure mode does not exist, so this
    // branch is Windows/macOS.
    if (caseInsensitiveFs) {
      const identity = build(
        resolve("c:/run/manifest.json"),
        resolve("c:/trusted/verifiers.json"),
        resolve("c:/trusted/approval.json"),
      );
      expect(identity?.launch?.authorityKind).toBe("ADMISSION");
    }

    // NEGATIVE (all platforms): a genuinely DIFFERENT file for either path —
    // not merely a different case — is STILL rejected. The trust binding is
    // not weakened.
    expect(() =>
      build(resolve("C:/run/manifest-IMPOSTER.json"), resolve("C:/Trusted/Verifiers.json"), resolve("C:/Trusted/Approval.json")),
    ).toThrow("invalid launch descriptor");
    expect(() =>
      build(resolve("C:/Run/Manifest.json"), resolve("C:/trusted/verifiers-IMPOSTER.json"), resolve("C:/Trusted/Approval.json")),
    ).toThrow("invalid launch descriptor");
    expect(() =>
      build(resolve("C:/Run/Manifest.json"), resolve("C:/Trusted/Verifiers.json"), resolve("C:/trusted/approval-IMPOSTER.json")),
    ).toThrow("invalid launch descriptor");
  });

  it("verifies a live development endpoint without upgrading its claim status", async () => {
    const identity = {
      seat: "OWNED_DEVELOPMENT" as const,
      claimStatus: "NON_ADMISSIBLE" as const,
      tokensSeen: 2048,
      allocatedParameters: 3_839_161_856,
      activeParameters: 1_020_589_568,
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned-development:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await verifyOwnedEndpointIdentity(identity, async () =>
      Response.json({
        seat: "OWNED_DEVELOPMENT",
        mode: "INTERACTIVE",
        claim_status: "NON_ADMISSIBLE",
        tokens_seen: 2048,
        allocated_parameters: 3_839_161_856,
        active_parameters: 1_020_589_568,
        checkpoint_sha256: CHECKPOINT,
        model_name: identity.modelName,
        model_config_sha256: identity.modelConfigSha256,
        server_source_sha256: identity.serverSourceSha256,
        tokenizer_sha256: identity.tokenizerSha256,
        vram_bytes: 987_654_321,
      }),
    );
  });
  it("surfaces admission errors and rejects malformed successful output", () => {
    const common = {
      repoRoot: "C:/repo",
      configHome: "C:/home",
      manifestPath: resolve("C:/run.json"),
      verifierRegistryPath: resolve("C:/trusted.json"),
    };
    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 1,
          stdout: JSON.stringify({ errors: ["stage is not OWNED_ADMITTED"] }),
          stderr: "",
        }),
      }),
    ).toThrow("stage is not OWNED_ADMITTED");

    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 0,
          stdout: JSON.stringify({
            valid: true,
            seat: "OWNED_ADMITTED",
            checkpoint_sha256: CHECKPOINT,
            endpoint_url: "http://127.0.0.1:8083",
            identity_url: "http://127.0.0.1:8083/v1/models",
            model_name: "qwen3.6-27b",
          }),
          stderr: "",
        }),
      }),
    ).toThrow("invalid admitted identity");

    expect(() =>
      loadOwnedModelIdentity(common, {
        exists: () => true,
        execute: () => ({
          status: 0,
          stdout: JSON.stringify({
            valid: true,
            seat: "OWNED_ADMITTED",
            checkpoint_sha256: CHECKPOINT,
            endpoint_url: "",
            identity_url: "/v1/models",
            model_name: "ember-owned:" + CHECKPOINT.slice(0, 12),
          }),
          stderr: "",
        }),
      }),
    ).toThrow("invalid admitted identity");
  });

  it("accepts only a live endpoint bound to the admitted checkpoint", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    let requested = "";
    const resident = await verifyOwnedEndpointIdentity(identity, async (input) => {
      requested = String(input);
      return Response.json({
        seat: "OWNED_ADMITTED",
        mode: "INTERACTIVE",
        checkpoint_sha256: CHECKPOINT,
        model_name: identity.modelName,
        model_config_sha256: identity.modelConfigSha256,
        server_source_sha256: identity.serverSourceSha256,
        tokenizer_sha256: identity.tokenizerSha256,
        vram_bytes: 123_456_789,
      });
    });
    expect(requested).toBe(identity.identityUrl);
    expect(resident.vramBytes).toBe(123_456_789);
  });

  it("rejects a matching resident identity without integer VRAM custody", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    const payload = {
      seat: "OWNED_ADMITTED",
      mode: "INTERACTIVE",
      checkpoint_sha256: CHECKPOINT,
      model_name: identity.modelName,
      model_config_sha256: identity.modelConfigSha256,
      server_source_sha256: identity.serverSourceSha256,
      tokenizer_sha256: identity.tokenizerSha256,
    };
    for (const vram_bytes of [undefined, -1, 1.5, true]) {
      await expect(verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({ ...payload, vram_bytes }),
      )).rejects.toThrow("valid resident VRAM measurement");
    }
  });

  it("rejects a frozen-eval endpoint when the CLI requested interactive mode", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          mode: "FROZEN_EVAL",
          checkpoint_sha256: CHECKPOINT,
          model_name: identity.modelName,
          model_config_sha256: identity.modelConfigSha256,
          server_source_sha256: identity.serverSourceSha256,
          tokenizer_sha256: identity.tokenizerSha256,
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
  });
  it("rejects a live endpoint that reports another checkpoint or identity", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          checkpoint_sha256: "f".repeat(64),
          model_name: identity.modelName,
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
    expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        new Response("unavailable", { status: 503 }),
      ),
    ).rejects.toThrow("identity request failed with HTTP 503");
  });

  it("fails closed when the owned endpoint is unreachable (connection refused / network error)", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await expect(
      verifyOwnedEndpointIdentity(identity, async () => {
        throw new Error("connect ECONNREFUSED 127.0.0.1:8083");
      }),
    ).rejects.toThrow("owned endpoint identity request failed: connect ECONNREFUSED 127.0.0.1:8083");
  });

  it("rejects a live endpoint whose runtime bytes differ from the admitted identity", async () => {
    const identity = {
      checkpointSha256: CHECKPOINT,
      endpointUrl: "http://127.0.0.1:8083",
      identityUrl: "http://127.0.0.1:8083/v1/models",
      modelConfigSha256: "b".repeat(64),
      modelName: "ember-owned:" + CHECKPOINT.slice(0, 12),
      serverSourceSha256: "a".repeat(64),
      tokenizerSha256: "c".repeat(64),
    };
    await expect(
      verifyOwnedEndpointIdentity(identity, async () =>
        Response.json({
          seat: "OWNED_ADMITTED",
          checkpoint_sha256: CHECKPOINT,
          model_name: identity.modelName,
          model_config_sha256: identity.modelConfigSha256,
          tokenizer_sha256: identity.tokenizerSha256,
          server_source_sha256: "f".repeat(64),
        }),
      ),
    ).rejects.toThrow("does not match admitted checkpoint");
  });
});

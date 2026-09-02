// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { existsSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "fs";
import { createHash, randomBytes } from "crypto";
import { dirname, isAbsolute, join, relative, resolve, sep } from "path";
import { spawnSync } from "child_process";

import { emberScratchDir } from "../utils/ember-scratch.ts";

import type {
  ModelConfigCapabilities,
  OwnedModelIdentity,
  OwnedResidentIdentity,
  OwnedServerLaunch,
} from "./model-seat.ts";

interface ResolverResult {
  status: number | null;
  stdout: string;
  stderr: string;
}

export interface DevelopmentResolverBootstrap {
  checkpointDir?: string;
  cleanup: () => void;
  manifestPath: string;
  manifestSha256: string;
  resolverPath: string;
  runtimeIndexPath: string;
  runtimeIndexSha256: string;
}

type ReadGitBlob = (repoRoot: string, commit: string, relativePath: string) => Uint8Array;

const TRUSTED_DEVELOPMENT_SOURCE_FILES = [
  "configs/ember-restart-3b.json",
  "src/ember/governance/scripts/ember_restart/development_cli_seat.py",
  "src/ember/governance/scripts/ember_restart/prediction_contract.py",
  "scripts/ember_restart_eval_checkpoint_consumer.py",
  "scripts/ember_restart_eval_raw_forward.py",
  "domains/model/tokenizer/tokenizer.json",
  "src/ember/infrastructure/tools/ember-restart-3b/batch.py",
  "src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py",
  "tools/ember-restart-3b/infer.py",
  "src/ember/infrastructure/tools/ember-restart-3b/model.py",
  "tools/ember-restart-3b/parameter_counter.py",
  "tools/ember-restart-3b/serve_owned_openai.py",
] as const;

const DEVELOPMENT_RUNTIME_FILES = [
  ...TRUSTED_DEVELOPMENT_SOURCE_FILES,
  "parameter-evidence/parameter_counter.py",
  "parameter-evidence/step2-realization-receipt.json",
  "parameter-evidence/trusted-verifiers.json",
] as const;

export interface OwnedSeatLoaderInput {
  repoRoot: string;
  configHome: string;
  manifestPath?: string;
  verifierRegistryPath?: string;
  verifierRegistryApprovalPath?: string;
  pythonExecutable?: string;
}

export interface OwnedDevelopmentSeatLoaderInput {
  repoRoot: string;
  configHome: string;
  manifestPath?: string;
  pythonExecutable?: string;
}

export interface OwnedSeatLoaderDeps {
  captureDevelopmentResolver?: (
    manifestPath: string,
    repoRoot: string,
    expectedSourceCommit: string,
    readGitBlob: ReadGitBlob,
  ) => DevelopmentResolverBootstrap;
  exists?: (path: string) => boolean;
  execute?: (executable: string, args: string[]) => ResolverResult;
  readGitBlob?: ReadGitBlob;
  resolveBuildCommit?: () => string;
}

function defaultExecute(executable: string, args: string[]): ResolverResult {
  const result = spawnSync(executable, args, {
    encoding: "utf8",
    windowsHide: true,
    timeout: 120_000,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

function sha256(payload: Uint8Array): string {
  return createHash("sha256").update(payload).digest("hex");
}

function requireObject(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(label + " must be an object");
  }
  return value as Record<string, unknown>;
}

function requireExactFields(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (
    actual.length !== wanted.length ||
    actual.some((field, index) => field !== wanted[index])
  ) {
    throw new Error(label + " fields are not closed");
  }
}

function parseJsonObject(payload: Uint8Array, label: string): Record<string, unknown> {
  try {
    return requireObject(JSON.parse(new TextDecoder().decode(payload)), label);
  } catch (error) {
    if (error instanceof Error && error.message.endsWith("must be an object")) throw error;
    throw new Error(label + " is not valid JSON");
  }
}

function resolveContainedFile(root: string, relativePath: unknown, label: string): string {
  if (
    typeof relativePath !== "string" ||
    relativePath.length === 0 ||
    isAbsolute(relativePath)
  ) {
    throw new Error(label + " must be bundle-relative");
  }
  const candidate = resolve(root, relativePath);
  const fromRoot = relative(root, candidate);
  if (fromRoot === ".." || fromRoot.startsWith(".." + sep)) {
    throw new Error(label + " escapes the bundle");
  }
  return candidate;
}

function defaultResolveBuildCommit(): string {
  const value = (globalThis as typeof globalThis & {
    __EMBER_BUILD_COMMIT__?: unknown;
  }).__EMBER_BUILD_COMMIT__;
  if (typeof value !== "string" || !/^[0-9a-f]{40}$/.test(value)) {
    throw new Error("compiled cockpit lacks an exact source-commit trust root");
  }
  return value;
}

function defaultReadGitBlob(
  repoRoot: string,
  commit: string,
  relativePath: string,
): Uint8Array {
  const result = spawnSync(
    "git",
    ["-C", repoRoot, "show", commit + ":" + relativePath],
    { encoding: "buffer", maxBuffer: 64 * 1024 * 1024, windowsHide: true, timeout: 30_000 },
  );
  if (result.status !== 0 || !(result.stdout instanceof Uint8Array)) {
    throw new Error("cannot read trusted runtime source from embedded Git commit: " + relativePath);
  }
  return result.stdout;
}

/** Thrown ONLY when an owned-development runtime bundle is otherwise honest and
 *  self-consistent but was built at a source commit that is not the compiled
 *  cockpit's own commit (state/specs/cockpit-stale-binding-demotion-acceptance-map-2026-07-25.md
 *  section 3). This is the single case process-entry.ts's catch demotes to the
 *  offline/reference seat instead of exiting the process -- gated on
 *  `instanceof`, never on this class's message text. Every other failure in
 *  this file (tamper, malformed manifest, missing files, resolver failure)
 *  throws a plain Error and stays fatal. */
export class OwnedSeatStaleBindingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OwnedSeatStaleBindingError";
  }
}

export function captureDevelopmentResolver(
  manifestPath: string,
  repoRoot: string,
  expectedSourceCommit: string,
  readGitBlob: ReadGitBlob = defaultReadGitBlob,
): DevelopmentResolverBootstrap {
  if (!/^[0-9a-f]{40}$/.test(expectedSourceCommit)) {
    throw new Error("owned development source commit is invalid");
  }
  const manifestBytes = readFileSync(manifestPath);
  const manifest = parseJsonObject(manifestBytes, "owned development manifest");
  const runtimeBinding = requireObject(manifest["runtime_bundle"], "runtime_bundle");
  requireExactFields(runtimeBinding, ["index_path", "sha256"], "runtime_bundle");
  const expectedIndexSha256 = runtimeBinding["sha256"];
  if (typeof expectedIndexSha256 !== "string" || !/^[0-9a-f]{64}$/.test(expectedIndexSha256)) {
    throw new Error("runtime bundle index sha256 is invalid");
  }
  const bundleRoot = dirname(resolve(manifestPath));
  const indexPath = resolveContainedFile(
    bundleRoot,
    runtimeBinding["index_path"],
    "runtime bundle index",
  );
  const indexBytes = readFileSync(indexPath);
  if (sha256(indexBytes) !== expectedIndexSha256) {
    throw new Error("runtime bundle index content hash mismatch");
  }
  const index = parseJsonObject(indexBytes, "runtime bundle index");
  requireExactFields(index, ["schema_version", "source_commit", "files"], "runtime bundle index");
  if (index["schema_version"] !== "ember-owned-runtime-bundle-v1") {
    // Split out of the former compound condition deliberately: a wrong/unrecognised
    // schema is a structurally different defect from a stale-but-honest commit binding,
    // and only the latter may demote (acceptance map section 3 requires the typed error
    // to be thrown ONLY for the stale-commit case -- lumping schema validity in with it
    // would let a malformed index ride the same demotion path).
    throw new Error("runtime bundle index schema is not recognised");
  }
  // The demotion branch below is the ONLY lenient outcome in this function, and
  // it is reachable only for an index that is otherwise honest and
  // self-consistent -- a bundle that is truthfully bound to a DIFFERENT but
  // well-formed commit. So the shape of source_commit has to be established
  // first: without this, `source_commit: null`, an object, an uppercase or
  // non-hex string, or arbitrary garbage all simply fail the equality test and
  // ride the demotion path, because "malformed" and "different" are the same
  // answer to `!==`. The comment on the schema check above states exactly this
  // intent and the equality check immediately undid it for a sibling field.
  //
  // The general form, and the reason this was missed: enumerating one traversal
  // (schema-vs-stale) does not enumerate its siblings. Every field the lenient
  // branch reads needs its own strict check ahead of that branch.
  const indexSourceCommit = index["source_commit"];
  if (typeof indexSourceCommit !== "string" || !/^[0-9a-f]{40}$/.test(indexSourceCommit)) {
    throw new Error("runtime bundle index source commit is invalid");
  }
  if (indexSourceCommit !== expectedSourceCommit) {
    throw new OwnedSeatStaleBindingError(
      "runtime bundle is not bound to the exact compiled cockpit commit; the owned seat is " +
      "refused and the cockpit continues OFFLINE. Use --reference-seat for explicit " +
      "REFERENCE_ONLY parity testing or EMBER_GPU_FREE=1 for offline observation.",
    );
  }
  const files = requireObject(index["files"], "runtime bundle files");
  const capturedFiles = new Map<string, Uint8Array>();
  for (const relativePath of DEVELOPMENT_RUNTIME_FILES) {
    const binding = requireObject(files[relativePath], "trusted runtime source binding");
    requireExactFields(binding, ["bytes", "sha256"], "trusted runtime source binding");
    const expectedSha256 = binding["sha256"];
    const expectedBytes = binding["bytes"];
    if (
      typeof expectedSha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(expectedSha256) ||
      !Number.isSafeInteger(expectedBytes) ||
      (expectedBytes as number) < 1
    ) {
      throw new Error("trusted runtime source binding is invalid: " + relativePath);
    }
    const bundlePath = resolveContainedFile(bundleRoot, relativePath, "trusted runtime source");
    const bundleBytes = readFileSync(bundlePath);
    const gitBytes = (TRUSTED_DEVELOPMENT_SOURCE_FILES as readonly string[]).includes(relativePath)
      ? readGitBlob(repoRoot, expectedSourceCommit, relativePath)
      : undefined;
    if (
      bundleBytes.byteLength !== expectedBytes ||
      sha256(bundleBytes) !== expectedSha256 ||
      (gitBytes !== undefined && (
        gitBytes.byteLength !== expectedBytes ||
        sha256(gitBytes) !== expectedSha256
      ))
    ) {
      throw new Error("runtime source does not match the embedded Git commit: " + relativePath);
    }
    capturedFiles.set(relativePath, bundleBytes);
  }
  const resolverRelative = "src/ember/governance/scripts/ember_restart/development_cli_seat.py";
  const resolverBytes = capturedFiles.get(resolverRelative);
  if (resolverBytes === undefined) {
    throw new Error("trusted runtime resolver was not captured");
  }
  const snapshotRoot = join(
    emberScratchDir("development-runtime"),
    `${process.pid}-${randomBytes(6).toString("hex")}`,
  );
  mkdirSync(snapshotRoot, { recursive: true });
  for (const [relativePath, payload] of capturedFiles) {
    const snapshotFile = join(snapshotRoot, relativePath);
    mkdirSync(dirname(snapshotFile), { recursive: true });
    writeFileSync(snapshotFile, payload, { flag: "wx" });
  }
  const snapshotIndexPath = resolveContainedFile(
    snapshotRoot,
    runtimeBinding["index_path"],
    "runtime bundle index snapshot",
  );
  mkdirSync(dirname(snapshotIndexPath), { recursive: true });
  writeFileSync(snapshotIndexPath, indexBytes, { flag: "wx" });
  const snapshotManifestPath = join(snapshotRoot, "development.json");
  writeFileSync(snapshotManifestPath, manifestBytes, { flag: "wx" });
  const checkpointBinding = manifest["checkpoint"];
  let checkpointDir: string | undefined;
  if (checkpointBinding !== null && typeof checkpointBinding === "object" && !Array.isArray(checkpointBinding)) {
    const checkpointManifest = (checkpointBinding as Record<string, unknown>)["manifest_path"];
    if (typeof checkpointManifest === "string") {
      const checkpointManifestPath = isAbsolute(checkpointManifest)
        ? resolve(checkpointManifest)
        : resolveContainedFile(bundleRoot, checkpointManifest, "checkpoint manifest");
      checkpointDir = dirname(checkpointManifestPath);
      if (!isAbsolute(checkpointManifest)) {
        const snapshotCheckpointPath = resolveContainedFile(
          snapshotRoot,
          checkpointManifest,
          "checkpoint manifest snapshot",
        );
        mkdirSync(dirname(snapshotCheckpointPath), { recursive: true });
        writeFileSync(snapshotCheckpointPath, readFileSync(checkpointManifestPath), { flag: "wx" });
      }
    }
  }
  return {
    checkpointDir,
    cleanup: () => rmSync(snapshotRoot, { force: true, recursive: true }),
    manifestPath: snapshotManifestPath,
    manifestSha256: sha256(manifestBytes),
    resolverPath: join(snapshotRoot, resolverRelative),
    runtimeIndexPath: snapshotIndexPath,
    runtimeIndexSha256: expectedIndexSha256,
  };
}

/**
 * Parses the optional `model_config_capabilities` declaration from a seat
 * resolver payload. Absent → undefined (no capability). Present → must be a
 * closed object whose `model_config_sha256` equals EXACTLY the served
 * identity's `model_config_sha256`; anything else fails closed.
 */
function parseModelConfigCapabilities(
  payload: Record<string, unknown>,
  servedModelConfigSha256: string,
): ModelConfigCapabilities | undefined {
  const raw = payload["model_config_capabilities"];
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("owned seat capability declaration is invalid");
  }
  const record = raw as Record<string, unknown>;
  requireExactFields(
    record,
    ["model_config_sha256", "structured_outputs"],
    "owned seat capability declaration",
  );
  const sha = record["model_config_sha256"];
  const structuredOutputs = record["structured_outputs"];
  if (
    typeof sha !== "string" ||
    !/^[0-9a-f]{64}$/.test(sha) ||
    sha !== servedModelConfigSha256 ||
    typeof structuredOutputs !== "boolean"
  ) {
    throw new Error(
      "owned seat capability declaration is not bound to the served model config",
    );
  }
  return { modelConfigSha256: sha, structuredOutputs };
}

function resolverError(result: ResolverResult): string {
  try {
    const payload = JSON.parse(result.stdout) as { errors?: unknown };
    if (Array.isArray(payload.errors) && payload.errors.length > 0) {
      return payload.errors.map(String).join("; ");
    }
  } catch {
    // Fall through to bounded stderr/stdout disclosure.
  }
  return (result.stderr || result.stdout || "owned seat resolver failed").trim();
}

const OWNED_LAUNCH_FIELDS = [
  "checkpoint_dir",
  "mode",
  "model_config_path",
  "run_manifest_path",
  "server_path",
  "tokenizer_path",
  "trusted_verifier_registry_path",
  "trusted_verifier_registry_sha256",
  "trusted_verifier_registry_approval_path",
  "trusted_verifier_registry_approval_sha256",
] as const;

function parseOwnedLaunch(
  value: unknown,
  expected: { manifestPath: string; registryPath: string; registryApprovalPath: string; pythonExecutable: string },
  exists: (path: string) => boolean,
): OwnedServerLaunch {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
  }
  const payload = value as Record<string, unknown>;
  const fields = Object.keys(payload).sort();
  const expectedFields = [...OWNED_LAUNCH_FIELDS].sort();
  if (
    fields.length !== expectedFields.length ||
    fields.some((field, index) => field !== expectedFields[index]) ||
    payload["mode"] !== "INTERACTIVE"
  ) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
  }
  const requireAbsolutePath = (field: string): string => {
    const candidate = payload[field];
    if (typeof candidate !== "string" || !isAbsolute(candidate)) {
      throw new Error("owned seat resolver returned an invalid launch descriptor");
    }
    return resolve(candidate);
  };
  const launch: OwnedServerLaunch = {
    authorityKind: "ADMISSION",
    checkpointDir: requireAbsolutePath("checkpoint_dir"),
    mode: "INTERACTIVE",
    modelConfigPath: requireAbsolutePath("model_config_path"),
    pythonExecutable: expected.pythonExecutable,
    runManifestPath: requireAbsolutePath("run_manifest_path"),
    serverPath: requireAbsolutePath("server_path"),
    tokenizerPath: requireAbsolutePath("tokenizer_path"),
    trustedVerifierRegistryPath: requireAbsolutePath("trusted_verifier_registry_path"),
    trustedVerifierRegistrySha256: typeof payload["trusted_verifier_registry_sha256"] === "string" && /^[0-9a-f]{64}$/.test(payload["trusted_verifier_registry_sha256"]) ? payload["trusted_verifier_registry_sha256"] : (() => { throw new Error("owned seat resolver returned an invalid launch descriptor"); })(),
    trustedVerifierRegistryApprovalPath: requireAbsolutePath("trusted_verifier_registry_approval_path"),
    trustedVerifierRegistryApprovalSha256: typeof payload["trusted_verifier_registry_approval_sha256"] === "string" && /^[0-9a-f]{64}$/.test(payload["trusted_verifier_registry_approval_sha256"]) ? payload["trusted_verifier_registry_approval_sha256"] : (() => { throw new Error("owned seat resolver returned an invalid launch descriptor"); })(),
  };
  if (
    !sameResolvedPath(launch.runManifestPath, expected.manifestPath) ||
    !sameResolvedPath(launch.trustedVerifierRegistryPath, expected.registryPath) ||
    !sameResolvedPath(launch.trustedVerifierRegistryApprovalPath, expected.registryApprovalPath) ||
    [launch.checkpointDir, launch.modelConfigPath, launch.runManifestPath, launch.serverPath, launch.tokenizerPath, launch.trustedVerifierRegistryPath, launch.trustedVerifierRegistryApprovalPath]
      .some((path) => !exists(path))
  ) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
  }
  return launch;
}

/**
 * True iff `a` and `b` denote the SAME real file. Trust-critical path compare:
 * the runtime snapshot dir is canonicalized at creation (emberScratchDir ->
 * realpathSync.native) and the Python resolver echoes Path.resolve()'d paths,
 * so a raw `===` normally holds. This makes the compare self-sufficiently
 * case-correct instead of depending on that invariant being maintained
 * elsewhere: canonicalize BOTH via realpathSync.native (also resolves 8.3
 * short names and symlinks). If either path is not present on disk (e.g. an
 * injected test mock, or a not-yet-created path), fall back to a
 * case-insensitive compare on case-insensitive filesystems (win32/darwin) and
 * an exact compare elsewhere. The binding is never RELAXED: two genuinely
 * different files differ under realpath AND under the case-folded fallback.
 */
function sameResolvedPath(a: string, b: string): boolean {
  try {
    return realpathSync.native(a) === realpathSync.native(b);
  } catch {
    const caseInsensitiveFs = process.platform === "win32" || process.platform === "darwin";
    return caseInsensitiveFs ? a.toLowerCase() === b.toLowerCase() : a === b;
  }
}

const DEVELOPMENT_LAUNCH_FIELDS = [
  "checkpoint_dir",
  "development_manifest_path",
  "mode",
  "model_config_path",
  "server_path",
  "tokenizer_path",
] as const;

function parseDevelopmentLaunch(
  value: unknown,
  expected: {
    checkpointDir?: string;
    cleanupRuntimeSnapshot: () => void;
    manifestPath: string;
    manifestSha256: string;
    pythonExecutable: string;
    runtimeIndexPath: string;
    runtimeIndexSha256: string;
  },
  exists: (path: string) => boolean,
): OwnedServerLaunch {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("development seat resolver returned an invalid launch descriptor");
  }
  const payload = value as Record<string, unknown>;
  const fields = Object.keys(payload).sort();
  const expectedFields = [...DEVELOPMENT_LAUNCH_FIELDS].sort();
  if (
    fields.length !== expectedFields.length ||
    fields.some((field, index) => field !== expectedFields[index]) ||
    payload["mode"] !== "INTERACTIVE"
  ) {
    throw new Error("development seat resolver returned an invalid launch descriptor");
  }
  const requireAbsolutePath = (field: string): string => {
    const candidate = payload[field];
    if (typeof candidate !== "string" || !isAbsolute(candidate)) {
      throw new Error("development seat resolver returned an invalid launch descriptor");
    }
    return resolve(candidate);
  };
  const launch: OwnedServerLaunch = {
    authorityKind: "DEVELOPMENT",
    checkpointDir: expected.checkpointDir ?? requireAbsolutePath("checkpoint_dir"),
    cleanupRuntimeSnapshot: expected.cleanupRuntimeSnapshot,
    developmentManifestSha256: expected.manifestSha256,
    developmentManifestPath: requireAbsolutePath("development_manifest_path"),
    mode: "INTERACTIVE",
    modelConfigPath: requireAbsolutePath("model_config_path"),
    pythonExecutable: expected.pythonExecutable,
    runtimeIndexPath: expected.runtimeIndexPath,
    runtimeIndexSha256: expected.runtimeIndexSha256,
    serverPath: requireAbsolutePath("server_path"),
    tokenizerPath: requireAbsolutePath("tokenizer_path"),
  };
  if (
    !sameResolvedPath(launch.developmentManifestPath, expected.manifestPath) ||
    [launch.checkpointDir, launch.developmentManifestPath, launch.modelConfigPath, launch.serverPath, launch.tokenizerPath]
      .some((path) => !exists(path))
  ) {
    throw new Error("development seat resolver returned an invalid launch descriptor");
  }
  return launch;
}

export function loadOwnedModelIdentity(
  input: OwnedSeatLoaderInput,
  deps: OwnedSeatLoaderDeps = {},
): OwnedModelIdentity | undefined {
  const exists = deps.exists ?? existsSync;
  const execute = deps.execute ?? defaultExecute;
  const explicitManifest = input.manifestPath !== undefined;
  const manifestPath = resolve(
    input.manifestPath ?? join(input.configHome, "owned", "current.json"),
  );
  if (!exists(manifestPath)) {
    if (explicitManifest) {
      throw new Error("owned rung manifest does not exist: " + manifestPath);
    }
    return undefined;
  }

  const registryPath = resolve(
    input.verifierRegistryPath ??
      join(input.configHome, "owned", "trusted-verifiers.json"),
  );
  if (!exists(registryPath)) {
    throw new Error("trusted verifier registry does not exist: " + registryPath);
  }

  const registryApprovalPath = resolve(
    input.verifierRegistryApprovalPath ??
      join(input.configHome, "owned", "trusted-registry-approval.json"),
  );
  if (!exists(registryApprovalPath)) {
    throw new Error("trusted verifier registry approval does not exist: " + registryApprovalPath);
  }

  const resolverPath = resolve(
    input.repoRoot,
    "scripts",
    "ember_restart",
    "cli_seat.py",
  );
  if (!exists(resolverPath)) {
    throw new Error("owned seat resolver does not exist: " + resolverPath);
  }

  const result = execute(input.pythonExecutable ?? "python", [
    resolverPath,
    manifestPath,
    "--trusted-verifier-registry",
    registryPath,
    "--trusted-verifier-registry-approval",
    registryApprovalPath,
  ]);
  if (result.status !== 0) {
    throw new Error("owned admission rejected: " + resolverError(result));
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(result.stdout) as Record<string, unknown>;
  } catch {
    throw new Error("owned seat resolver returned invalid JSON");
  }
  const checkpointSha256 = payload["checkpoint_sha256"];
  const endpointUrl = payload["endpoint_url"];
  const identityUrl = payload["identity_url"];
  const modelName = payload["model_name"];
  if (
    payload["valid"] !== true ||
    payload["seat"] !== "OWNED_ADMITTED" ||
    typeof checkpointSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(checkpointSha256) ||
    typeof endpointUrl !== "string" ||
    endpointUrl.trim() === "" ||
    typeof identityUrl !== "string" ||
    identityUrl.trim() === "" ||
    identityUrl !== endpointUrl.replace(/\/$/, "") + "/v1/models" ||
    typeof modelName !== "string" ||
    modelName !== "ember-owned:" + checkpointSha256.slice(0, 12)
  ) {
    throw new Error("owned seat resolver returned an invalid admitted identity");
  }

  const modelConfigSha256 = payload["model_config_sha256"];
  const modelFormat = payload["model_format"];
  const serverSourceSha256 = payload["server_source_sha256"];
  const tokenizerSha256 = payload["tokenizer_sha256"];
  if (
    typeof modelConfigSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(modelConfigSha256) ||
    typeof modelFormat !== "string" ||
    modelFormat.trim() === "" ||
    typeof serverSourceSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(serverSourceSha256) ||
    typeof tokenizerSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(tokenizerSha256)
  ) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
  }
  const modelConfigCapabilities = parseModelConfigCapabilities(payload, modelConfigSha256);
  const launch = parseOwnedLaunch(
    payload["launch"],
    { manifestPath, registryPath, registryApprovalPath, pythonExecutable: input.pythonExecutable ?? "python" },
    exists,
  );
  return {
    checkpointSha256,
    endpointUrl,
    identityUrl,
    launch,
    modelConfigSha256,
    modelFormat,
    modelName,
    serverSourceSha256,
    tokenizerSha256,
    ...(modelConfigCapabilities !== undefined ? { modelConfigCapabilities } : {}),
  };
}

export function loadOwnedDevelopmentIdentity(
  input: OwnedDevelopmentSeatLoaderInput,
  deps: OwnedSeatLoaderDeps = {},
): OwnedModelIdentity | undefined {
  const exists = deps.exists ?? existsSync;
  const execute = deps.execute ?? defaultExecute;
  const explicitManifest = input.manifestPath !== undefined;
  const manifestPath = resolve(
    input.manifestPath ?? join(input.configHome, "owned", "development.json"),
  );
  if (!exists(manifestPath)) {
    if (explicitManifest) {
      throw new Error("owned development manifest does not exist: " + manifestPath);
    }
    return undefined;
  }

  const expectedSourceCommit = (deps.resolveBuildCommit ?? defaultResolveBuildCommit)();
  const bootstrap = (deps.captureDevelopmentResolver ?? captureDevelopmentResolver)(
    manifestPath,
    input.repoRoot,
    expectedSourceCommit,
    deps.readGitBlob ?? defaultReadGitBlob,
  );
  const pythonExecutable = input.pythonExecutable ?? "python";
  let result: ResolverResult;
  try {
    result = execute(pythonExecutable, [
      bootstrap.resolverPath,
      bootstrap.manifestPath,
      "--expected-manifest-sha256",
      bootstrap.manifestSha256,
      "--expected-runtime-index-sha256",
      bootstrap.runtimeIndexSha256,
    ]);
  } catch (error) {
    bootstrap.cleanup();
    throw error;
  }
  if (result.status !== 0) {
    bootstrap.cleanup();
    throw new Error("owned development seat rejected: " + resolverError(result));
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(result.stdout) as Record<string, unknown>;
  } catch {
    bootstrap.cleanup();
    throw new Error("development seat resolver returned invalid JSON");
  }
  const checkpointSha256 = payload["checkpoint_sha256"];
  const endpointUrl = payload["endpoint_url"];
  const identityUrl = payload["identity_url"];
  const modelName = payload["model_name"];
  const modelConfigSha256 = payload["model_config_sha256"];
  const modelFormat = payload["model_format"];
  const serverSourceSha256 = payload["server_source_sha256"];
  const tokenizerSha256 = payload["tokenizer_sha256"];
  const tokensSeen = payload["tokens_seen"];
  const allocatedParameters = payload["allocated_parameters"];
  const activeParameters = payload["active_parameters"];
  if (
    payload["valid"] !== true ||
    payload["seat"] !== "OWNED_DEVELOPMENT" ||
    payload["claim_status"] !== "NON_ADMISSIBLE" ||
    typeof checkpointSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(checkpointSha256) ||
    typeof endpointUrl !== "string" ||
    endpointUrl.trim() === "" ||
    typeof identityUrl !== "string" ||
    identityUrl !== endpointUrl.replace(/\/$/, "") + "/v1/models" ||
    typeof modelName !== "string" ||
    modelName !== "ember-owned-development:" + checkpointSha256.slice(0, 12) ||
    typeof modelConfigSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(modelConfigSha256) ||
    typeof modelFormat !== "string" ||
    modelFormat !== "pytorch-checkpoint-v3" ||
    typeof serverSourceSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(serverSourceSha256) ||
    typeof tokenizerSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(tokenizerSha256) ||
    !Number.isSafeInteger(tokensSeen) ||
    (tokensSeen as number) < 0 ||
    !Number.isSafeInteger(allocatedParameters) ||
    (allocatedParameters as number) < 3_000_000_000 ||
    !Number.isSafeInteger(activeParameters) ||
    (activeParameters as number) <= 0 ||
    (activeParameters as number) > (allocatedParameters as number)
  ) {
    bootstrap.cleanup();
    throw new Error("development seat resolver returned an invalid non-claiming identity");
  }
  let modelConfigCapabilities: ModelConfigCapabilities | undefined;
  try {
    modelConfigCapabilities = parseModelConfigCapabilities(payload, modelConfigSha256);
  } catch (error) {
    bootstrap.cleanup();
    throw error;
  }
  let launch: OwnedServerLaunch;
  try {
    launch = parseDevelopmentLaunch(
      payload["launch"],
      {
        checkpointDir: bootstrap.checkpointDir,
        cleanupRuntimeSnapshot: bootstrap.cleanup,
        manifestPath: bootstrap.manifestPath,
        manifestSha256: bootstrap.manifestSha256,
        pythonExecutable,
        runtimeIndexPath: bootstrap.runtimeIndexPath,
        runtimeIndexSha256: bootstrap.runtimeIndexSha256,
      },
      exists,
    );
  } catch (error) {
    bootstrap.cleanup();
    throw error;
  }
  return {
    seat: "OWNED_DEVELOPMENT",
    claimStatus: "NON_ADMISSIBLE",
    tokensSeen: tokensSeen as number,
    allocatedParameters: allocatedParameters as number,
    activeParameters: activeParameters as number,
    checkpointSha256,
    endpointUrl,
    identityUrl,
    launch,
    modelConfigSha256,
    modelFormat,
    modelName,
    serverSourceSha256,
    tokenizerSha256,
    ...(modelConfigCapabilities !== undefined ? { modelConfigCapabilities } : {}),
  };
}

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export async function verifyOwnedEndpointIdentity(
  identity: OwnedModelIdentity,
  fetchFn: FetchLike = fetch,
): Promise<OwnedResidentIdentity> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5_000);
  let response: Response;
  try {
    response = await fetchFn(identity.identityUrl, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error("owned endpoint identity request failed: " + message);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(
      "owned endpoint identity request failed with HTTP " + response.status,
    );
  }

  let payload: Record<string, unknown>;
  try {
    payload = (await response.json()) as Record<string, unknown>;
  } catch {
    throw new Error("owned endpoint identity returned invalid JSON");
  }
  const expectedSeat = identity.seat ?? "OWNED_ADMITTED";
  const developmentMismatch = expectedSeat === "OWNED_DEVELOPMENT" && (
    identity.claimStatus !== "NON_ADMISSIBLE" ||
    payload["claim_status"] !== "NON_ADMISSIBLE" ||
    payload["tokens_seen"] !== identity.tokensSeen ||
    payload["allocated_parameters"] !== identity.allocatedParameters ||
    payload["active_parameters"] !== identity.activeParameters
  );
  if (
    payload["seat"] !== expectedSeat ||
    payload["mode"] !== "INTERACTIVE" ||
    payload["checkpoint_sha256"] !== identity.checkpointSha256 ||
    payload["model_name"] !== identity.modelName ||
    payload["model_config_sha256"] !== identity.modelConfigSha256 ||
    payload["server_source_sha256"] !== identity.serverSourceSha256 ||
    payload["tokenizer_sha256"] !== identity.tokenizerSha256 ||
    developmentMismatch
  ) {
    throw new Error("owned endpoint identity does not match admitted checkpoint or bound development seat");
  }
  const vramBytes = payload["vram_bytes"];
  if (typeof vramBytes !== "number" || !Number.isSafeInteger(vramBytes) || vramBytes < 0) {
    throw new Error("owned endpoint identity lacks a valid resident VRAM measurement");
  }
  return { ...identity, vramBytes };
}

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { createHash } from "crypto";
import { tmpdir } from "os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "path";
import { spawnSync } from "child_process";

import type { OwnedModelIdentity, OwnedServerLaunch } from "./model-seat.ts";

interface ResolverResult {
  status: number | null;
  stdout: string;
  stderr: string;
}

export interface DevelopmentResolverBootstrap {
  cleanup: () => void;
  manifestSha256: string;
  resolverPath: string;
  runtimeIndexSha256: string;
}

export interface OwnedSeatLoaderInput {
  repoRoot: string;
  configHome: string;
  manifestPath?: string;
  verifierRegistryPath?: string;
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
    expectedSourceCommit: string,
  ) => DevelopmentResolverBootstrap;
  exists?: (path: string) => boolean;
  execute?: (executable: string, args: string[]) => ResolverResult;
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

export function captureDevelopmentResolver(
  manifestPath: string,
  expectedSourceCommit: string,
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
  if (
    index["schema_version"] !== "ember-owned-runtime-bundle-v1" ||
    index["source_commit"] !== expectedSourceCommit
  ) {
    throw new Error("runtime bundle is not bound to the exact compiled cockpit commit");
  }
  const files = requireObject(index["files"], "runtime bundle files");
  const resolverRelative = "scripts/ember_restart/development_cli_seat.py";
  const resolverBinding = requireObject(files[resolverRelative], "runtime resolver binding");
  requireExactFields(resolverBinding, ["bytes", "sha256"], "runtime resolver binding");
  const expectedResolverSha256 = resolverBinding["sha256"];
  const expectedResolverBytes = resolverBinding["bytes"];
  if (
    typeof expectedResolverSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(expectedResolverSha256) ||
    !Number.isSafeInteger(expectedResolverBytes) ||
    (expectedResolverBytes as number) < 1
  ) {
    throw new Error("runtime resolver binding is invalid");
  }
  const resolverPath = resolveContainedFile(bundleRoot, resolverRelative, "runtime resolver");
  const resolverBytes = readFileSync(resolverPath);
  if (
    resolverBytes.byteLength !== expectedResolverBytes ||
    sha256(resolverBytes) !== expectedResolverSha256
  ) {
    throw new Error("runtime resolver bytes do not match the bundle index");
  }
  const snapshotRoot = mkdtempSync(join(tmpdir(), "ember-development-resolver-"));
  const snapshotPath = join(snapshotRoot, "development_cli_seat.py");
  writeFileSync(snapshotPath, resolverBytes, { flag: "wx" });
  return {
    cleanup: () => rmSync(snapshotRoot, { force: true, recursive: true }),
    manifestSha256: sha256(manifestBytes),
    resolverPath: snapshotPath,
    runtimeIndexSha256: expectedIndexSha256,
  };
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
] as const;

function parseOwnedLaunch(
  value: unknown,
  expected: { manifestPath: string; registryPath: string; pythonExecutable: string },
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
  };
  if (
    launch.runManifestPath !== expected.manifestPath ||
    launch.trustedVerifierRegistryPath !== expected.registryPath ||
    [launch.checkpointDir, launch.modelConfigPath, launch.runManifestPath, launch.serverPath, launch.tokenizerPath, launch.trustedVerifierRegistryPath]
      .some((path) => !exists(path))
  ) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
  }
  return launch;
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
  expected: { manifestPath: string; pythonExecutable: string },
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
    checkpointDir: requireAbsolutePath("checkpoint_dir"),
    developmentManifestPath: requireAbsolutePath("development_manifest_path"),
    mode: "INTERACTIVE",
    modelConfigPath: requireAbsolutePath("model_config_path"),
    pythonExecutable: expected.pythonExecutable,
    serverPath: requireAbsolutePath("server_path"),
    tokenizerPath: requireAbsolutePath("tokenizer_path"),
  };
  if (
    launch.developmentManifestPath !== expected.manifestPath ||
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
  const launch = parseOwnedLaunch(
    payload["launch"],
    { manifestPath, registryPath, pythonExecutable: input.pythonExecutable ?? "python" },
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
    expectedSourceCommit,
  );
  const pythonExecutable = input.pythonExecutable ?? "python";
  let result: ResolverResult;
  try {
    result = execute(pythonExecutable, [
      bootstrap.resolverPath,
      manifestPath,
      "--expected-manifest-sha256",
      bootstrap.manifestSha256,
      "--expected-runtime-index-sha256",
      bootstrap.runtimeIndexSha256,
    ]);
  } finally {
    bootstrap.cleanup();
  }
  if (result.status !== 0) {
    throw new Error("owned development seat rejected: " + resolverError(result));
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(result.stdout) as Record<string, unknown>;
  } catch {
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
    throw new Error("development seat resolver returned an invalid non-claiming identity");
  }
  const launch = parseDevelopmentLaunch(
    payload["launch"],
    { manifestPath, pythonExecutable },
    exists,
  );
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
  };
}

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export async function verifyOwnedEndpointIdentity(
  identity: OwnedModelIdentity,
  fetchFn: FetchLike = fetch,
): Promise<void> {
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
}

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { existsSync } from "fs";
import { isAbsolute, join, resolve } from "path";
import { spawnSync } from "child_process";

import type { OwnedModelIdentity, OwnedServerLaunch } from "./model-seat.ts";

interface ResolverResult {
  status: number | null;
  stdout: string;
  stderr: string;
}

export interface OwnedSeatLoaderInput {
  repoRoot: string;
  configHome: string;
  manifestPath?: string;
  verifierRegistryPath?: string;
  pythonExecutable?: string;
}

export interface OwnedSeatLoaderDeps {
  exists?: (path: string) => boolean;
  execute?: (executable: string, args: string[]) => ResolverResult;
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
    checkpointDir: requireAbsolutePath("checkpoint_dir"),
    mode: "INTERACTIVE",
    pythonExecutable: expected.pythonExecutable,
    runManifestPath: requireAbsolutePath("run_manifest_path"),
    serverPath: requireAbsolutePath("server_path"),
    tokenizerPath: requireAbsolutePath("tokenizer_path"),
    trustedVerifierRegistryPath: requireAbsolutePath("trusted_verifier_registry_path"),
  };
  if (
    launch.runManifestPath !== expected.manifestPath ||
    launch.trustedVerifierRegistryPath !== expected.registryPath ||
    [launch.checkpointDir, launch.runManifestPath, launch.serverPath, launch.tokenizerPath, launch.trustedVerifierRegistryPath]
      .some((path) => !exists(path))
  ) {
    throw new Error("owned seat resolver returned an invalid launch descriptor");
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
  if (
    payload["seat"] !== "OWNED_ADMITTED" ||
    payload["mode"] !== "INTERACTIVE" ||
    payload["checkpoint_sha256"] !== identity.checkpointSha256 ||
    payload["model_name"] !== identity.modelName ||
    payload["model_config_sha256"] !== identity.modelConfigSha256 ||
    payload["server_source_sha256"] !== identity.serverSourceSha256 ||
    payload["tokenizer_sha256"] !== identity.tokenizerSha256
  ) {
    throw new Error("owned endpoint identity does not match admitted checkpoint");
  }
}

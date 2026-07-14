// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { existsSync } from "fs";
import { join, resolve } from "path";
import { spawnSync } from "child_process";

import type { OwnedModelIdentity } from "./model-seat.ts";

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
    typeof identityUrl !== "string" ||
    identityUrl !== endpointUrl.replace(/\/$/, "") + "/v1/models" ||
    typeof modelName !== "string" ||
    modelName !== "ember-owned:" + checkpointSha256.slice(0, 12)
  ) {
    throw new Error("owned seat resolver returned an invalid admitted identity");
  }

  return { checkpointSha256, endpointUrl, identityUrl, modelName };
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
    payload["checkpoint_sha256"] !== identity.checkpointSha256 ||
    payload["model_name"] !== identity.modelName
  ) {
    throw new Error("owned endpoint identity does not match admitted checkpoint");
  }
}

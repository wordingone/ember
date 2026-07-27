// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "crypto";
import { spawn, type ChildProcess } from "child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { isAbsolute, join, relative, resolve } from "path";
import { createConnection } from "node:net";

import type { OwnedModelIdentity } from "./model-seat.ts";
import { verifyOwnedEndpointIdentity } from "./owned-seat-loader.ts";
import { callEmberLab, configuredEmberLabPipe } from "../services/ember-lab-rpc.ts";

export type OwnedServerDevice = "cpu" | "cuda";
export type OwnedEndpointPresence = "absent" | "present";

export interface OwnedServerCommand {
  executable: string;
  args: string[];
  port: number;
}

const DEVELOPMENT_RUNTIME_BOOTSTRAP = [
  "import hashlib",
  "import json",
  "import runpy",
  "import site",
  "import sys",
  "from pathlib import Path",
  "index_path = Path(sys.argv[1]).resolve()",
  "expected_index_sha256 = sys.argv[2]",
  "server_path = Path(sys.argv[3]).resolve()",
  "index_bytes = index_path.read_bytes()",
  "if hashlib.sha256(index_bytes).hexdigest() != expected_index_sha256:",
  "    raise SystemExit('runtime bundle index changed before development server import')",
  "index = json.loads(index_bytes)",
  "files = index.get('files')",
  "if not isinstance(files, dict):",
  "    raise SystemExit('runtime bundle index files are invalid')",
  "root = index_path.parent",
  "for relative_path, binding in files.items():",
  "    if not isinstance(relative_path, str) or not isinstance(binding, dict):",
  "        raise SystemExit('runtime bundle binding is invalid')",
  "    path = (root / relative_path).resolve()",
  "    if root != path and root not in path.parents:",
  "        raise SystemExit('runtime bundle path escapes snapshot')",
  "    payload = path.read_bytes()",
  "    if len(payload) != binding.get('bytes') or hashlib.sha256(payload).hexdigest() != binding.get('sha256'):",
  "        raise SystemExit('runtime bundle file changed before development server import: ' + relative_path)",
  "user_site = Path(site.getusersitepackages()).resolve()",
  "if not user_site.is_dir():",
  "    raise SystemExit('owned server Python user site-packages directory is unavailable')",
  "sys.path.append(str(user_site))",
  "sys.path.insert(0, str(server_path.parent))",
  "sys.argv = sys.argv[3:]",
  "runpy.run_path(str(server_path), run_name='__main__')",
].join("\n");

export interface OwnedServerHandle {
  process: ChildProcess;
  port: number;
  startupError?: Error;
  kill(): void;
}

export interface OwnedDaemonDispatch {
  pid: number;
  preflightReceiptPath: string;
  preflightReceiptSha256: string;
}

export type EnsureOwnedServerResult =
  | { outcome: "spawned"; port: number; handle: OwnedServerHandle }
  | { outcome: "dispatched"; port: number; pid: number };

type VerifyEndpoint = (identity: OwnedModelIdentity) => Promise<void>;

export interface EnsureOwnedServerDeps {
  device?: OwnedServerDevice;
  dispatchManifest?: (identity: OwnedModelIdentity) => Promise<OwnedDaemonDispatch>;
  probePresence?: (identity: OwnedModelIdentity) => Promise<OwnedEndpointPresence>;
  registerCleanup?: (handle: OwnedServerHandle) => () => void;
  verifyEndpoint?: VerifyEndpoint;
  spawnServer?: (command: OwnedServerCommand) => OwnedServerHandle;
  waitUntilReady?: (
    identity: OwnedModelIdentity,
    handle: OwnedServerHandle,
    verifyEndpoint: VerifyEndpoint,
  ) => Promise<void>;
  waitForDispatchReady?: (
    identity: OwnedModelIdentity,
    verifyEndpoint: VerifyEndpoint,
  ) => Promise<void>;
}

function endpoint(identity: OwnedModelIdentity): { host: string; port: number } {
  let parsed: URL;
  try {
    parsed = new URL(identity.endpointUrl);
  } catch {
    throw new Error("owned endpoint is not a valid URL");
  }
  const port = Number(parsed.port || "80");
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    (parsed.pathname !== "" && parsed.pathname !== "/") ||
    parsed.search !== "" ||
    parsed.hash !== "" ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65535
  ) {
    throw new Error("owned endpoint must be exact loopback HTTP on 127.0.0.1");
  }
  return { host: parsed.hostname, port };
}

export function buildOwnedServerCommand(
  identity: OwnedModelIdentity,
  device: OwnedServerDevice,
): OwnedServerCommand {
  const launch = identity.launch;
  if (!launch || launch.mode !== "INTERACTIVE") {
    throw new Error("owned identity lacks an interactive launch descriptor");
  }
  const { host, port } = endpoint(identity);
  const authorityArgs = launch.authorityKind === "ADMISSION"
    ? [
        "--config", launch.modelConfigPath,
        "--run-manifest", launch.runManifestPath,
        "--trusted-verifier-registry", launch.trustedVerifierRegistryPath,
        "--expected-registry-root-sha256", launch.trustedVerifierRegistrySha256,
        "--trusted-verifier-registry-approval", launch.trustedVerifierRegistryApprovalPath,
        "--expected-registry-approval-sha256", launch.trustedVerifierRegistryApprovalSha256,
      ]
    : [
        "--config", launch.modelConfigPath,
        "--development-manifest", launch.developmentManifestPath,
        "--expected-development-manifest-sha256", launch.developmentManifestSha256,
        "--expected-runtime-index-sha256", launch.runtimeIndexSha256,
      ];
  const serverArgs = [
    "--checkpoint", launch.checkpointDir,
    "--tokenizer", launch.tokenizerPath,
    ...authorityArgs,
    "--host", host,
    "--port", String(port),
    "--device", device,
    "--parent-pid", String(process.pid),
    "--mode", "INTERACTIVE",
  ];
  return {
    executable: launch.pythonExecutable,
    port,
    args: launch.authorityKind === "DEVELOPMENT"
      ? [
          "-I",
          "-c",
          DEVELOPMENT_RUNTIME_BOOTSTRAP,
          launch.runtimeIndexPath,
          launch.runtimeIndexSha256,
          launch.serverPath,
          ...serverArgs,
        ]
      : [launch.serverPath, ...serverArgs],
  };
}

export async function probeOwnedEndpointPresence(
  identity: OwnedModelIdentity,
): Promise<OwnedEndpointPresence> {
  const { host, port } = endpoint(identity);
  return await new Promise<OwnedEndpointPresence>((resolvePromise) => {
    const socket = createConnection({ host, port });
    let settled = false;
    const finish = (presence: OwnedEndpointPresence): void => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolvePromise(presence);
    };
    socket.once("connect", () => finish("present"));
    socket.once("error", (error: NodeJS.ErrnoException) => {
      finish(error.code === "ECONNREFUSED" ? "absent" : "present");
    });
    socket.setTimeout(1_000, () => finish("present"));
  });
}

export interface OwnedCleanupProcess {
  on(event: string, listener: () => void): unknown;
  exit(code?: number): unknown;
}

export function registerOwnedServerCleanup(
  handle: OwnedServerHandle,
  proc: OwnedCleanupProcess = process,
): () => void {
  let cleaned = false;
  const cleanup = (): void => {
    if (cleaned) return;
    cleaned = true;
    handle.kill();
  };
  proc.on("exit", cleanup);
  proc.on("SIGINT", () => { cleanup(); proc.exit(0); });
  proc.on("SIGTERM", () => { cleanup(); proc.exit(0); });
  return cleanup;
}

function defaultSpawnServer(command: OwnedServerCommand): OwnedServerHandle {
  const child = spawn(command.executable, command.args, {
    windowsHide: true,
    stdio: ["ignore", "ignore", "inherit"],
  });
  const handle: OwnedServerHandle = {
    process: child,
    port: command.port,
    kill: () => { child.kill("SIGTERM"); },
  };
  child.once("error", (error) => { handle.startupError = error; });
  return handle;
}

async function defaultWaitUntilReady(
  identity: OwnedModelIdentity,
  handle: OwnedServerHandle,
  verifyEndpoint: VerifyEndpoint,
): Promise<void> {
  const deadline = Date.now() + 240_000;
  let lastError = "owned endpoint did not become ready";
  while (Date.now() < deadline) {
    if (handle.startupError) {
      throw new Error("owned server failed to start: " + handle.startupError.message);
    }
    if (handle.process.exitCode !== null) {
      throw new Error(
        `owned server exited before verified readiness (exit code ${handle.process.exitCode})`,
      );
    }
    try {
      await verifyEndpoint(identity);
      return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("owned server readiness timed out: " + lastError);
}

function manifestObject(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(label + " must be an object");
  return value as Record<string, unknown>;
}

function requireDispatchBinding(bindings: unknown, kind: string, path: string, sha256: string, label: string): void {
  if (!Array.isArray(bindings)) throw new Error("dispatch manifest " + label + " binding does not match owned identity");
  const samePath = bindings.filter((value) => value !== null && typeof value === "object" && !Array.isArray(value) && (value as Record<string, unknown>)["path"] === path);
  if (samePath.length !== 1) throw new Error("dispatch manifest " + label + " binding path is not unique");
  const matches = bindings.filter((value) => {
    if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
    const binding = value as Record<string, unknown>;
    return binding["kind"] === kind && binding["path"] === path && binding["sha256"] === sha256;
  });
  if (matches.length !== 1) throw new Error("dispatch manifest " + label + " binding does not match owned identity");
}

export function validateOwnedDispatchManifest(identity: OwnedModelIdentity, value: unknown, expectedSourceCommit: string): void {
  const manifest = manifestObject(value, "dispatch manifest");
  const fields = [
    "schema_version", "job_id", "source_commit", "not_before_ms", "expires_at_ms",
    "resource_lease", "program", "args", "env", "bindings", "custody_root",
    "storage_reserves", "minimum_free_vram_bytes", "required_available_maximum_commit_bytes",
    "maximum_job_memory_bytes", "simulated_peak_commit_bytes", "preflight_receipt",
  ].sort();
  const actualFields = Object.keys(manifest).sort();
  if (actualFields.length !== fields.length || actualFields.some((field, index) => field !== fields[index])) {
    throw new Error("dispatch manifest fields are not closed");
  }
  if (manifest["schema_version"] !== "ember-lab-dispatch-manifest-v2") throw new Error("dispatch manifest schema is not ember-lab-dispatch-manifest-v2");
  if (!/^[0-9a-f]{40}$/.test(expectedSourceCommit) || manifest["source_commit"] !== expectedSourceCommit) throw new Error("dispatch manifest source commit does not match the installed Ember CLI");
  const launch = identity.launch;
  if (!launch) throw new Error("owned identity lacks an interactive launch descriptor");
  const program = manifestObject(manifest["program"], "dispatch manifest program");
  if (program["path"] !== launch.pythonExecutable || typeof program["sha256"] !== "string" || !/^[0-9a-f]{64}$/.test(program["sha256"] as string)) throw new Error("dispatch manifest program does not match owned launch");
  const expectedCommand = buildOwnedServerCommand(identity, process.env["EMBER_OWNED_DEVICE"] === "cpu" ? "cpu" : "cuda");
  if (!Array.isArray(manifest["args"]) || JSON.stringify(manifest["args"]) !== JSON.stringify(expectedCommand.args)) throw new Error("dispatch manifest argv does not match owned launch");
  requireDispatchBinding(manifest["bindings"], "config", launch.modelConfigPath, identity.modelConfigSha256, "model config");
  requireDispatchBinding(manifest["bindings"], "manifest", launch.tokenizerPath, identity.tokenizerSha256, "tokenizer");
  requireDispatchBinding(manifest["bindings"], "manifest", launch.serverPath, identity.serverSourceSha256, "server source");
  requireDispatchBinding(manifest["bindings"], "manifest", join(launch.checkpointDir, "checkpoint-manifest.json"), identity.checkpointSha256, "checkpoint");
  if (typeof manifest["custody_root"] !== "string" || !isAbsolute(manifest["custody_root"])) throw new Error("dispatch manifest custody root must be absolute");
  if (!Array.isArray(manifest["storage_reserves"]) || manifest["storage_reserves"].length === 0) throw new Error("dispatch manifest storage reserves are required");
}


export function verifyDispatchReceiptCustody(path: unknown, sha256: unknown, custodyRoot: unknown): { path: string; sha256: string } {
  if (typeof path !== "string" || !isAbsolute(path) || typeof sha256 !== "string" || !/^[0-9a-f]{64}$/.test(sha256) || typeof custodyRoot !== "string" || !isAbsolute(custodyRoot)) throw new Error("ember-lab dispatch result lacks preflight receipt custody");
  const root = resolve(custodyRoot); const receipt = resolve(path); const inside = relative(root, receipt);
  if (inside === "" || inside === ".." || inside.startsWith("..\\") || inside.startsWith("../")) throw new Error("ember-lab dispatch receipt escapes authorized custody");
  const bytes = readFileSync(receipt); if (createHash("sha256").update(bytes).digest("hex") !== sha256) throw new Error("ember-lab dispatch receipt hash does not match custody bytes");
  return { path: receipt, sha256 };
}

export function dispatchManifestParams(manifestBytes: Buffer): { manifest_utf8: string; manifest_sha256: string } {
  let manifestUtf8: string;
  try {
    manifestUtf8 = new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes);
  } catch {
    throw new Error("dispatch manifest is not valid UTF-8");
  }
  return {
    manifest_utf8: manifestUtf8,
    manifest_sha256: createHash("sha256").update(manifestBytes).digest("hex"),
  };
}
async function defaultDispatchManifest(identity: OwnedModelIdentity): Promise<OwnedDaemonDispatch> {
  const manifest = process.env["EMBER_LAB_DISPATCH_MANIFEST"];
  const sourceCommit = (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
  if (!manifest) throw new Error("connected owned seats require EMBER_LAB_DISPATCH_MANIFEST");
  if (typeof sourceCommit !== "string" || !/^[0-9a-f]{40}$/.test(sourceCommit)) {
    throw new Error("compiled cockpit lacks an exact source-commit trust root");
  }
  let manifestBytes: Buffer;
  let manifestParams: { manifest_utf8: string; manifest_sha256: string };
  let manifestPayload: unknown;
  try {
    manifestBytes = readFileSync(manifest);
    manifestParams = dispatchManifestParams(manifestBytes);
    manifestPayload = JSON.parse(manifestParams.manifest_utf8);
  } catch (error) { throw new Error("cannot read dispatch manifest: " + (error instanceof Error ? error.message : String(error))); }
  validateOwnedDispatchManifest(identity, manifestPayload, sourceCommit);
  const result = await callEmberLab({
    pipeName: configuredEmberLabPipe(),
    method: "dispatch_manifest",
    params: {
      ...manifestParams,
    },
  });
  const pid = result["pid"];
  const preflightReceiptPath = result["preflight_receipt_path"];
  const preflightReceiptSha256 = result["preflight_receipt_sha256"];
  if (!Number.isSafeInteger(pid) || (pid as number) < 1) {
    throw new Error("ember-lab dispatch result lacks a positive process id");
  }
  const receipt = verifyDispatchReceiptCustody(preflightReceiptPath, preflightReceiptSha256, manifestObject(manifestPayload, "dispatch manifest")["custody_root"]);
  return { pid: pid as number, preflightReceiptPath: receipt.path, preflightReceiptSha256: receipt.sha256 };
}

async function defaultWaitForDispatchReady(
  identity: OwnedModelIdentity,
  verifyEndpoint: VerifyEndpoint,
): Promise<void> {
  const deadline = Date.now() + 240_000;
  let lastError = "owned endpoint did not become ready";
  while (Date.now() < deadline) {
    try { await verifyEndpoint(identity); return; }
    catch (error) { lastError = error instanceof Error ? error.message : String(error); }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("daemon-dispatched owned server readiness timed out: " + lastError);
}
export async function ensureOwnedServer(
  identity: OwnedModelIdentity,
  deps: EnsureOwnedServerDeps = {},
): Promise<EnsureOwnedServerResult> {
  const { port } = endpoint(identity);
  const probePresence = deps.probePresence ?? probeOwnedEndpointPresence;
  const verifyEndpoint = deps.verifyEndpoint ?? verifyOwnedEndpointIdentity;
  const presence = await probePresence(identity);
  if (presence === "present") {
    throw new Error(
      "owned endpoint has a pre-existing listener; loaded-weight identity cannot be independently verified",
    );
  }
  if (!identity.launch) {
    throw new Error("owned identity lacks a launch descriptor");
  }
  if (process.env["EMBER_LAB_PIPE"] !== undefined) {
    const dispatch = deps.dispatchManifest ?? defaultDispatchManifest;
    const dispatched = await dispatch(identity);
    if (typeof dispatched.preflightReceiptPath !== "string" || !isAbsolute(dispatched.preflightReceiptPath) ||
        typeof dispatched.preflightReceiptSha256 !== "string" || !/^[0-9a-f]{64}$/.test(dispatched.preflightReceiptSha256)) {
      throw new Error("ember-lab dispatch result lacks preflight receipt custody");
    }
    await (deps.waitForDispatchReady ?? defaultWaitForDispatchReady)(identity, verifyEndpoint);
    return { outcome: "dispatched", port, pid: dispatched.pid };
  }
  const device = deps.device ?? (process.env["EMBER_OWNED_DEVICE"] === "cpu" ? "cpu" : "cuda");
  const command = buildOwnedServerCommand(identity, device);
  const handle = (deps.spawnServer ?? defaultSpawnServer)(command);
  const cleanupServer = (deps.registerCleanup ?? registerOwnedServerCleanup)(handle);
  let cleaned = false;
  const cleanup = (): void => {
    if (cleaned) return;
    cleaned = true;
    cleanupServer();
    if (identity.launch?.authorityKind === "DEVELOPMENT") {
      identity.launch.cleanupRuntimeSnapshot();
    }
  };
  if (typeof handle.process.once === "function") {
    handle.process.once("exit", cleanup);
  }
  try {
    await (deps.waitUntilReady ?? defaultWaitUntilReady)(identity, handle, verifyEndpoint);
  } catch (error) {
    cleanup();
    throw error;
  }
  return { outcome: "spawned", port, handle };
}

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { spawn, type ChildProcess } from "child_process";
import { createConnection } from "node:net";

import type { OwnedModelIdentity } from "./model-seat.ts";
import { verifyOwnedEndpointIdentity } from "./owned-seat-loader.ts";

export type OwnedServerDevice = "cpu" | "cuda";
export type OwnedEndpointPresence = "absent" | "present";

export interface OwnedServerCommand {
  executable: string;
  args: string[];
  port: number;
}

export interface OwnedServerHandle {
  process: ChildProcess;
  port: number;
  startupError?: Error;
  kill(): void;
}

export type EnsureOwnedServerResult =
  { outcome: "spawned"; port: number; handle: OwnedServerHandle };

type VerifyEndpoint = (identity: OwnedModelIdentity) => Promise<void>;

export interface EnsureOwnedServerDeps {
  device?: OwnedServerDevice;
  probePresence?: (identity: OwnedModelIdentity) => Promise<OwnedEndpointPresence>;
  registerCleanup?: (handle: OwnedServerHandle) => () => void;
  verifyEndpoint?: VerifyEndpoint;
  spawnServer?: (command: OwnedServerCommand) => OwnedServerHandle;
  waitUntilReady?: (
    identity: OwnedModelIdentity,
    handle: OwnedServerHandle,
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
    throw new Error("admitted owned identity lacks an interactive launch descriptor");
  }
  const { host, port } = endpoint(identity);
  return {
    executable: launch.pythonExecutable,
    port,
    args: [
      launch.serverPath,
      "--checkpoint", launch.checkpointDir,
      "--tokenizer", launch.tokenizerPath,
      "--run-manifest", launch.runManifestPath,
      "--trusted-verifier-registry", launch.trustedVerifierRegistryPath,
      "--host", host,
      "--port", String(port),
      "--device", device,
      "--parent-pid", String(process.pid),
      "--mode", "INTERACTIVE",
    ],
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
    throw new Error("admitted owned identity lacks a launch descriptor");
  }
  const device = deps.device ?? (process.env["EMBER_OWNED_DEVICE"] === "cpu" ? "cpu" : "cuda");
  const command = buildOwnedServerCommand(identity, device);
  const handle = (deps.spawnServer ?? defaultSpawnServer)(command);
  const cleanup = (deps.registerCleanup ?? registerOwnedServerCleanup)(handle);
  try {
    await (deps.waitUntilReady ?? defaultWaitUntilReady)(identity, handle, verifyEndpoint);
  } catch (error) {
    cleanup();
    throw error;
  }
  return { outcome: "spawned", port, handle };
}

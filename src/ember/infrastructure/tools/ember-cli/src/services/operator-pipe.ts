// operator-pipe.ts — Windows named-pipe transport for the operator input channel
// (ember issue #165 / #154). Reads newline-delimited lines from
// \\.\pipe\ember-operator-<pid> and hands complete lines to a callback.
//
// Deliberately does NOT touch window focus in any way — no foreground-window
// APIs, no synthetic-keystroke injection, no window-handle APIs at all. This
// module only ever talks to a local TCP-shaped named pipe via Node's `net`
// module. Never crashes or delays the CLI — any failure (unsupported platform,
// pipe creation error, socket error) fails open to keyboard-only operation,
// surfaced as a single warning.

import net from "node:net";

export type OperatorPipeEventKind = "pipe_connected" | "pipe_error";

export interface OperatorPipeEvent {
  kind: OperatorPipeEventKind;
  detail?: string;
}

export interface OperatorPipeOptions {
  /** Overrides process.pid — used by tests to pick a collision-free pipe name. */
  pid?: number;
  /** Fired once per accepted client connection, and on transport-level errors. */
  onEvent?: (event: OperatorPipeEvent) => void;
  /** Fired when the pipe cannot be created at all (platform unsupported, bind failure). */
  onWarning?: (message: string) => void;
}

export interface OperatorPipeHandle {
  /** The pipe path this handle is listening on (or would have, on win32). */
  readonly pipeName: string;
  /** Whether a real server is actually listening (false = no-op handle). */
  readonly active: boolean;
  stop: () => void;
}

/** Computes the well-known pipe name for a given process id. */
export function operatorPipeName(pid: number = process.pid): string {
  return `\\\\.\\pipe\\ember-operator-${pid}`;
}

const NOOP_HANDLE = (pipeName: string): OperatorPipeHandle => ({
  pipeName,
  active: false,
  stop: () => {},
});

/**
 * Starts listening on the operator named pipe and delivers each complete
 * newline-delimited line to `onLine`. No-ops cleanly (returns an inactive
 * handle) on non-Windows platforms or if the pipe cannot be bound.
 */
export function startOperatorPipe(
  onLine: (line: string) => void,
  options: OperatorPipeOptions = {},
): OperatorPipeHandle {
  const pipeName = operatorPipeName(options.pid);

  if (process.platform !== "win32") {
    return NOOP_HANDLE(pipeName);
  }

  let server: net.Server;
  try {
    server = net.createServer((socket) => {
      options.onEvent?.({ kind: "pipe_connected" });
      let buffer = "";
      socket.setEncoding("utf8");

      socket.on("data", (chunk: string) => {
        buffer += chunk;
        let idx: number;
        while ((idx = buffer.indexOf("\n")) >= 0) {
          const rawLine = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 1);
          const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
          if (line.length > 0) onLine(line);
        }
      });

      // A misbehaving client must never take the CLI down with it.
      socket.on("error", (err) => {
        options.onEvent?.({ kind: "pipe_error", detail: err instanceof Error ? err.message : String(err) });
      });
    });
  } catch (err) {
    options.onWarning?.(
      `operator pipe unavailable: ${err instanceof Error ? err.message : String(err)}`,
    );
    return NOOP_HANDLE(pipeName);
  }

  server.on("error", (err) => {
    options.onWarning?.(
      `operator pipe error: ${err instanceof Error ? err.message : String(err)}`,
    );
  });

  try {
    server.listen(pipeName);
  } catch (err) {
    options.onWarning?.(
      `operator pipe listen failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return NOOP_HANDLE(pipeName);
  }

  let stopped = false;
  return {
    pipeName,
    active: true,
    stop: () => {
      if (stopped) return;
      stopped = true;
      try {
        server.close();
      } catch {
        /* ignore — process is tearing down anyway */
      }
    },
  };
}

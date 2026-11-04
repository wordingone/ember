// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/tool-progress.ts -- what the screen may know about a tool call that is running.
//
// Blind test S24: while a long command ran, the spinner said "Thinking…" with no tool name and no
// output, because nothing told the screen a tool was running or what it printed. The query loop
// announces the start and end of each executed tool call; a tool that streams output reports the
// tail of what it has printed so far. The screen subscribes. This is a plain in-process seam (the
// same shape as session-control.ts): no tool imports the screen and the screen imports no tool.

export interface ToolProgressStart {
  kind: "start";
  toolUseId: string;
  toolName: string;
  /** The call's input; the screen summarises it (the command line of a Bash call, a file path). */
  input: unknown;
  startedAt: number;
}
export interface ToolProgressOutput {
  kind: "output";
  toolUseId: string;
  /** The last line of output so far, trimmed for display. */
  tail: string;
}
export interface ToolProgressEnd {
  kind: "end";
  toolUseId: string;
}
export type ToolProgressEvent = ToolProgressStart | ToolProgressOutput | ToolProgressEnd;

type Listener = (event: ToolProgressEvent) => void;

const listeners = new Set<Listener>();

/** Subscribes to progress events; returns the unsubscribe function. */
export function onToolProgress(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function emit(event: ToolProgressEvent): void {
  for (const listener of [...listeners]) {
    try { listener(event); } catch { /* a screen bug must never fail a tool call */ }
  }
}

export function reportToolStart(toolUseId: string, toolName: string, input: unknown): void {
  emit({ kind: "start", toolUseId, toolName, input, startedAt: Date.now() });
}

export function reportToolEnd(toolUseId: string): void {
  emit({ kind: "end", toolUseId });
}

/** Reports the last line of a tool's output so far. No-op without a tool-use id. */
export function reportToolOutput(toolUseId: string | undefined, tail: string): void {
  if (!toolUseId) return;
  emit({ kind: "output", toolUseId, tail });
}

// ---------------------------------------------------------------------------
// Tail extraction
// ---------------------------------------------------------------------------

const ANSI_RE = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;

/**
 * Keeps the last `max` characters of what a command has printed, for the live tail. Output
 * arrives in arbitrary chunks, so this holds a small window and answers with the last non-empty
 * line.
 */
export class OutputTail {
  private window = "";
  constructor(private readonly max = 2048) {}

  push(chunk: string): void {
    this.window = (this.window + chunk).slice(-this.max);
  }

  lastLine(): string {
    const lines = this.window.replace(ANSI_RE, "").split(/\r?\n/);
    for (let i = lines.length - 1; i >= 0; i--) {
      // A carriage return rewrites the line (progress bars): the visible text is what follows it.
      const visible = (lines[i] ?? "").split("\r").filter((part) => part.trim() !== "").pop() ?? "";
      if (visible.trim() !== "") return visible.trim();
    }
    return "";
  }
}

export interface TailReporter {
  push(chunk: Buffer | string): void;
  /** Stops any pending report; the tool call is over. */
  stop(): void;
}

/**
 * A tool's output tap: feed it every chunk and it reports the last line at most once per
 * `intervalMs`, with a trailing report so the final line of a burst is not lost. Without a
 * tool-use id (a tool run outside the query loop) it does nothing.
 */
export function createTailReporter(toolUseId: string | undefined, intervalMs = 120): TailReporter {
  if (!toolUseId) return { push() {}, stop() {} };
  const tail = new OutputTail();
  let lastEmit = 0;
  let pending = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = (): void => {
    timer = null;
    if (!pending) return;
    pending = false;
    lastEmit = Date.now();
    reportToolOutput(toolUseId, tail.lastLine());
  };
  return {
    push(chunk) {
      tail.push(typeof chunk === "string" ? chunk : chunk.toString("utf-8"));
      pending = true;
      const wait = lastEmit + intervalMs - Date.now();
      if (wait <= 0) flush();
      else if (timer === null) timer = setTimeout(flush, wait);
    },
    stop() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending = false;
    },
  };
}

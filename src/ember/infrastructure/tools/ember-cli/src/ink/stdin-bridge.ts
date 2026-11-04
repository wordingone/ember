// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// stdin-bridge — wires Node.js stdin keypress events into the hooks layer.
// Call startStdinBridge() once at process startup; the returned function
// tears down raw-mode and removes the listener.

import readline from "readline";
import { PassThrough } from "node:stream";
import { _deliverKeyEvent, _deliverMouseEvent } from "./hooks.ts";
import { createSgrMouseDecoder } from "./termio.ts";

/** Modifier flags delivered by Node's keypress events. */
interface NodeKey {
  name?:  string;
  ctrl?:  boolean;
  meta?:  boolean;
  shift?: boolean;
}

type StdinLike = NodeJS.ReadableStream & {
  isTTY?: boolean;
  setRawMode?: (mode: boolean) => void;
};

/**
 * How long a lone ESC is held before it counts as the Escape key. A terminal normally sends a whole
 * escape sequence in one read, but a busy process (a long reply being rendered, mouse tracking on)
 * can see one split, with the ESC alone in the first read. Delivering it at once fired a spurious
 * Escape (which interrupts a running turn) and typed the rest of the mouse report into the prompt.
 * An Escape press is still delivered, this much later.
 */
export const ESCAPE_HOLD_MS = 30;

/**
 * How long the front of a mouse report may sit unfinished before it is thrown away. Left in the
 * decoder indefinitely it ate or prefixed whatever the user typed next, minutes later.
 */
export const STALE_PARTIAL_MS = 100;

const NO_MODS = { ctrl: false, alt: false, shift: false, meta: false };

export interface StdinBridgeOptions {
  stdin?: StdinLike;
  emitKeypressEvents?: (stream: NodeJS.ReadableStream) => void;
}

/**
 * Puts stdin into raw mode, enables keypress events via readline, and routes
 * each keypress into the ink hooks layer via `_deliverKeyEvent`.
 *
 * Returns a cleanup function that restores cooked mode and pauses stdin.
 * If stdin is not a TTY (e.g. piped input / CI), returns a no-op cleanup.
 */
export function startStdinBridge(options: StdinBridgeOptions = {}): () => void {
  const stdin = options.stdin ?? process.stdin;
  const emitKeypressEvents = options.emitKeypressEvents ??
    ((stream: NodeJS.ReadableStream) => readline.emitKeypressEvents(stream));

  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    return () => {};
  }
  const rawInput = stdin as NodeJS.ReadableStream;
  const setRawMode = stdin.setRawMode.bind(stdin);

  try {
    setRawMode(true);
  } catch {
    return () => {};
  }

  stdin.resume();

  const mouseDecoder = createSgrMouseDecoder();
  const keyboardStream = new PassThrough();

  // A lone ESC chunk is an Escape keypress (terminals send an escape sequence in one chunk). Both
  // the mouse decoder (ESC is a prefix of an SGR mouse report) and readline hold it waiting for
  // more bytes, so it is delivered here, after a short wait to see whether it is the front of a
  // sequence that was split across reads.
  let heldEscape: string | null = null;
  let escapeTimer: ReturnType<typeof setTimeout> | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;

  const clearEscapeTimer = (): void => {
    if (escapeTimer !== null) { clearTimeout(escapeTimer); escapeTimer = null; }
  };
  const deliverEscape = (): void => {
    _deliverKeyEvent("escape", NO_MODS);
  };
  const releaseHeldEscape = (): void => {
    escapeTimer = null;
    if (heldEscape === null) return;
    heldEscape = null;
    deliverEscape();
    // If this was the front of a mouse report whose rest arrives late, drop that rest.
    mouseDecoder.noteOrphanedEscape();
  };
  const watchPartialMouseReport = (): void => {
    if (staleTimer !== null) { clearTimeout(staleTimer); staleTimer = null; }
    if (!mouseDecoder.hasPending()) return;
    staleTimer = setTimeout(() => {
      staleTimer = null;
      mouseDecoder.discardPending();
    }, STALE_PARTIAL_MS);
  };

  const onData = (chunk: string | Buffer): void => {
    let text = typeof chunk === "string" ? chunk : chunk.toString("utf8");
    if (heldEscape !== null) {
      clearEscapeTimer();
      if (text.startsWith("[") || text.startsWith("O")) {
        // The rest of an escape sequence (CSI "[", SS3 "O") that was split across reads.
        text = heldEscape + text;
        heldEscape = null;
      } else {
        // Anything else after it: the held ESC was a real Escape press.
        heldEscape = null;
        deliverEscape();
      }
    }
    if (text === "\x1b" || text === "\x1b\x1b") {
      heldEscape = text;
      escapeTimer = setTimeout(releaseHeldEscape, ESCAPE_HOLD_MS);
      return;
    }
    // A paste arrives as one chunk; its interior line breaks must not submit the
    // prompt. Turn them into LF (delivered as a typed newline); a single trailing
    // CR stays Enter.
    if (!text.startsWith("\x1b") && text.length > 1 && /[\r\n]./s.test(text)) {
      const trailingCr = text.endsWith("\r") && !text.endsWith("\n\r");
      const body = (trailingCr ? text.slice(0, -1) : text).replace(/\r\n?/g, "\n");
      text = body + (trailingCr ? "\r" : "");
    }
    const decoded = mouseDecoder.push(text);
    for (const event of decoded.events) {
      _deliverMouseEvent(event);
    }
    if (decoded.passthrough.length > 0) keyboardStream.write(decoded.passthrough);
    watchPartialMouseReport();
  };

  const onKeypress = (str: string | undefined, key: NodeKey | undefined) => {
    if (!key) return;

    const mods = {
      ctrl:  key.ctrl  ?? false,
      alt:   key.meta  ?? false,
      shift: key.shift ?? false,
      meta:  key.meta  ?? false,
    };

    const isPrintable =
      str !== undefined &&
      // One code point, not one UTF-16 unit: emoji are surrogate pairs.
      [...str].length === 1 &&
      str.charCodeAt(0) >= 32 &&
      str.charCodeAt(0) !== 127 &&
      !key.ctrl &&
      !key.meta;

    if (isPrintable) {
      _deliverKeyEvent(str, mods);
    } else if (key.name) {
      _deliverKeyEvent(key.name, mods);
    }
  };

  try {
    emitKeypressEvents(keyboardStream);
  } catch {
    try { setRawMode(false); } catch { /* ignore */ }
    stdin.pause();
    keyboardStream.end();
    return () => {};
  }

  rawInput.on("data", onData);
  keyboardStream.on("keypress", onKeypress);

  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    clearEscapeTimer();
    heldEscape = null;
    if (staleTimer !== null) { clearTimeout(staleTimer); staleTimer = null; }
    rawInput.off("data", onData);
    keyboardStream.off("keypress", onKeypress);
    mouseDecoder.reset();
    keyboardStream.end();
    try { setRawMode(false); } catch { /* ignore */ }
    stdin.pause();
  };
}

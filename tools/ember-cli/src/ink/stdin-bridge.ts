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
  const onData = (chunk: string | Buffer): void => {
    const decoded = mouseDecoder.push(chunk);
    for (const event of decoded.events) {
      _deliverMouseEvent(event);
    }
    if (decoded.passthrough.length > 0) keyboardStream.write(decoded.passthrough);
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
      str.length === 1 &&
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
    rawInput.off("data", onData);
    keyboardStream.off("keypress", onKeypress);
    mouseDecoder.reset();
    keyboardStream.end();
    try { setRawMode(false); } catch { /* ignore */ }
    stdin.pause();
  };
}

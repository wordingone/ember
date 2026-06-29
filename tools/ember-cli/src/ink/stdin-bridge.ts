// stdin-bridge — wires Node.js stdin keypress events into the hooks layer.
// Call startStdinBridge() once at process startup; the returned function
// tears down raw-mode and removes the listener.

import readline from "readline";
import { _deliverKeyEvent } from "./hooks.ts";

/** Modifier flags delivered by Node's keypress events. */
interface NodeKey {
  name?:  string;
  ctrl?:  boolean;
  meta?:  boolean;
  shift?: boolean;
}

/**
 * Puts stdin into raw mode, enables keypress events via readline, and routes
 * each keypress into the ink hooks layer via `_deliverKeyEvent`.
 *
 * Returns a cleanup function that restores cooked mode and pauses stdin.
 * If stdin is not a TTY (e.g. piped input / CI), returns a no-op cleanup.
 */
export function startStdinBridge(): () => void {
  if (!process.stdin.isTTY) {
    return () => {};
  }

  try {
    process.stdin.setRawMode(true);
  } catch {
    return () => {};
  }

  process.stdin.resume();

  try {
    readline.emitKeypressEvents(process.stdin);
  } catch {
    try { process.stdin.setRawMode(false); } catch { /* ignore */ }
    process.stdin.pause();
    return () => {};
  }

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

  process.stdin.on("keypress", onKeypress);

  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    process.stdin.off("keypress", onKeypress);
    try { process.stdin.setRawMode(false); } catch { /* ignore */ }
    process.stdin.pause();
  };
}

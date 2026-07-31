// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import {
  DISABLE_MOUSE_TRACKING,
  ENABLE_MOUSE_TRACKING,
  ENTER_ALT_SCREEN,
  EXIT_ALT_SCREEN,
  HIDE_CURSOR,
  SHOW_CURSOR,
} from "./termio.ts";

export interface TerminalSessionStream {
  write(value: string): unknown;
}

export interface TerminalSessionController {
  readonly active: boolean;
  enter(): void;
  exit(): void;
}

/**
 * Owns the terminal modes needed by the full-screen Ember cockpit. The
 * controller deliberately writes each transition as one atomic string and is
 * idempotent so normal teardown and process-exit teardown can safely race.
 */
export function createTerminalSessionController(
  stream: TerminalSessionStream,
): TerminalSessionController {
  let active = false;

  return {
    get active(): boolean { return active; },
    enter(): void {
      if (active) return;
      active = true;
      try {
        stream.write(ENTER_ALT_SCREEN + HIDE_CURSOR + ENABLE_MOUSE_TRACKING);
      } catch (error) {
        active = false;
        try {
          stream.write(DISABLE_MOUSE_TRACKING + SHOW_CURSOR + EXIT_ALT_SCREEN);
        } catch { /* preserve the acquisition error */ }
        throw error;
      }
    },
    exit(): void {
      if (!active) return;
      active = false;
      stream.write(DISABLE_MOUSE_TRACKING + SHOW_CURSOR + EXIT_ALT_SCREEN);
    },
  };
}

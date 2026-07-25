// termio — terminal I/O primitives: ANSI sequence builders, color type system,
// and style application from raw SGR codes.

// ---------------------------------------------------------------------------
// Color value types
// ---------------------------------------------------------------------------

export type ColorValue =
  | { type: "named";   index: number }
  | { type: "indexed"; index: number }
  | { type: "rgb";     r: number; g: number; b: number };

// ---------------------------------------------------------------------------
// Style — per-cell visual decoration applied by the renderer.
// ---------------------------------------------------------------------------

export interface Style {
  bold?:          boolean;
  dim?:           boolean;
  italic?:        boolean;
  underline?:     boolean;
  inverse?:       boolean;
  strikethrough?: boolean;
  fg?: ColorValue;
  bg?: ColorValue;
}

// ---------------------------------------------------------------------------
// ANSI terminal control sequences
// ---------------------------------------------------------------------------

/** Switch to the alternate screen buffer. */
export const ENTER_ALT_SCREEN     = "\x1b[?1049h";
/** Switch back to the primary screen buffer. */
export const EXIT_ALT_SCREEN      = "\x1b[?1049l";
/** Enable mouse tracking (button events, SGR extended). */
export const ENABLE_MOUSE_TRACKING  = "\x1b[?1000h\x1b[?1006h";
/** Disable mouse tracking. */
export const DISABLE_MOUSE_TRACKING = "\x1b[?1000l\x1b[?1006l";

export interface SgrMousePress {
  col: number;
  row: number;
  button: number;
  modifiers: {
    ctrl: boolean;
    shift: boolean;
    alt: boolean;
    meta: boolean;
  };
}

export interface SgrMouseDecodeResult {
  events: SgrMousePress[];
  passthrough: string;
}

export interface SgrMouseDecoder {
  push(chunk: string | Buffer): SgrMouseDecodeResult;
  reset(): void;
}

const SGR_MOUSE_PREFIX = "\x1b[<";
const SGR_MOUSE_SEQUENCE = /^\x1b\[<(\d+);(\d+);(\d+)([Mm])/;

function retainedPrefixLength(value: string): number {
  const max = Math.min(value.length, SGR_MOUSE_PREFIX.length - 1);
  for (let length = max; length > 0; length--) {
    if (SGR_MOUSE_PREFIX.startsWith(value.slice(-length))) return length;
  }
  return 0;
}

/**
 * Incrementally decodes xterm SGR extended mouse input. Only a left-button
 * press is actionable; release, motion, wheel, extra-button, malformed, and
 * non-positive-coordinate sequences are consumed or passed through without
 * producing an activation.
 */
export function createSgrMouseDecoder(): SgrMouseDecoder {
  let pending = "";

  return {
    push(chunk: string | Buffer): SgrMouseDecodeResult {
      pending += typeof chunk === "string" ? chunk : chunk.toString("utf8");
      const events: SgrMousePress[] = [];
      let passthrough = "";
      let cursor = 0;

      while (cursor < pending.length) {
        const start = pending.indexOf(SGR_MOUSE_PREFIX, cursor);
        if (start < 0) {
          const remainder = pending.slice(cursor);
          const retained = retainedPrefixLength(remainder);
          passthrough += remainder.slice(0, remainder.length - retained);
          pending = retained > 0 ? remainder.slice(-retained) : "";
          return { events, passthrough };
        }

        passthrough += pending.slice(cursor, start);
        const candidate = pending.slice(start);
        const match = SGR_MOUSE_SEQUENCE.exec(candidate);
        if (!match) {
          if (/^\x1b\[<[\d;]*$/.test(candidate)) {
            pending = candidate;
            return { events, passthrough };
          }
          passthrough += pending[start]!;
          cursor = start + 1;
          continue;
        }

        cursor = start + match[0].length;
        const code = Number(match[1]);
        const terminalCol = Number(match[2]);
        const terminalRow = Number(match[3]);
        const terminator = match[4];
        const unsupportedBits = code & ~(1 | 2 | 4 | 8 | 16 | 32 | 64);
        const isLeftPress =
          terminator === "M" &&
          Number.isSafeInteger(code) &&
          code >= 0 && code <= 31 &&
          Number.isSafeInteger(terminalCol) &&
          Number.isSafeInteger(terminalRow) &&
          terminalCol > 0 &&
          terminalRow > 0 &&
          (code & 3) === 0 &&
          (code & (32 | 64)) === 0 &&
          unsupportedBits === 0;

        if (isLeftPress) {
          events.push({
            col: terminalCol - 1,
            row: terminalRow - 1,
            button: 0,
            modifiers: {
              shift: (code & 4) !== 0,
              alt: (code & 8) !== 0,
              ctrl: (code & 16) !== 0,
              meta: false,
            },
          });
        }
      }

      pending = "";
      return { events, passthrough };
    },
    reset(): void {
      pending = "";
    },
  };
}

// SGR code range starts (ANSI / xterm)
const NAMED_FG_START  = 30;
const NAMED_BG_START  = 40;
const BRIGHT_FG_START = 90;
const BRIGHT_BG_START = 100;

/** The empty (default) style singleton. */
export const DEFAULT_STYLE: Style = Object.freeze({});

// ---------------------------------------------------------------------------
// ANSI sequence builders
// ---------------------------------------------------------------------------

/** Returns an absolute cursor-position sequence (1-based row, col). */
export function cursorPosition(row: number, col: number): string {
  return `\x1b[${row};${col}H`;
}

/**
 * Returns an OSC (Operating System Command) sequence.
 * Format: `ESC ] n ; p1 ; p2 … ST`
 */
export function osc(n: number, ...params: string[]): string {
  return `\x1b]${n};${params.join(";")}` + "\x1b\\";
}

// ---------------------------------------------------------------------------
// applyAnsiCodes — fold SGR integer codes into a Style
// ---------------------------------------------------------------------------

/**
 * Interprets an array of SGR integer codes and returns a new Style derived
 * from `current`. Handles reset, intensity, decoration, named/indexed/RGB
 * foreground and background colors.
 */
export function applyAnsiCodes(codes: number[], current: Style): Style {
  const s: Style = { ...current };
  let i = 0;
  while (i < codes.length) {
    const code = codes[i] ?? 0;
    switch (code) {
      case 0:
        delete s.bold; delete s.dim; delete s.italic;
        delete s.underline; delete s.inverse; delete s.strikethrough;
        delete s.fg; delete s.bg;
        break;
      case 1:  s.bold          = true; break;
      case 2:  s.dim           = true; break;
      case 3:  s.italic        = true; break;
      case 4:  s.underline     = true; break;
      case 7:  s.inverse       = true; break;
      case 9:  s.strikethrough = true; break;
      case 22: delete s.bold; delete s.dim; break;
      case 23: delete s.italic;       break;
      case 24: delete s.underline;    break;
      case 27: delete s.inverse;      break;
      case 29: delete s.strikethrough; break;
      default: {
        if (code >= NAMED_FG_START && code <= NAMED_FG_START + 7) {
          s.fg = { type: "named", index: code - NAMED_FG_START };
        } else if (code >= BRIGHT_FG_START && code <= BRIGHT_FG_START + 7) {
          s.fg = { type: "named", index: code - BRIGHT_FG_START + 8 };
        } else if (code >= NAMED_BG_START && code <= NAMED_BG_START + 7) {
          s.bg = { type: "named", index: code - NAMED_BG_START };
        } else if (code >= BRIGHT_BG_START && code <= BRIGHT_BG_START + 7) {
          s.bg = { type: "named", index: code - BRIGHT_BG_START + 8 };
        } else if (code === 39) {
          delete s.fg;
        } else if (code === 49) {
          delete s.bg;
        } else if (code === 38) {
          const sub = codes[i + 1];
          if (sub === 5) {
            s.fg = { type: "indexed", index: codes[i + 2] ?? 0 };
            i += 2;
          } else if (sub === 2) {
            s.fg = { type: "rgb", r: codes[i + 2] ?? 0, g: codes[i + 3] ?? 0, b: codes[i + 4] ?? 0 };
            i += 4;
          }
        } else if (code === 48) {
          const sub = codes[i + 1];
          if (sub === 5) {
            s.bg = { type: "indexed", index: codes[i + 2] ?? 0 };
            i += 2;
          } else if (sub === 2) {
            s.bg = { type: "rgb", r: codes[i + 2] ?? 0, g: codes[i + 3] ?? 0, b: codes[i + 4] ?? 0 };
            i += 4;
          }
        }
      }
    }
    i++;
  }
  return s;
}

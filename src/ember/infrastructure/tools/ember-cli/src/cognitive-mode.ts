// cognitive-mode.ts — pure module: CognitiveMode/LoopPhase types, derivation, and glyph table.
// No intra-project imports (L2 leaf). No side effects at module load.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CognitiveMode =
  | "observe"      // idle / awaiting operator input (ready state)
  | "orient"       // model streaming reasoning text, no tool yet
  | "act"          // a tool call is executing (Bash/Edit/etc.)
  | "verify"       // processing a tool result
  | "consolidate"  // compaction / summary in progress
  | "ask"          // awaiting an operator decision mid-turn
  | "report"       // final assistant response being emitted
  | "rollback";    // an error/abort is being recovered

/** Observable loop phase the cockpit can witness without model introspection. */
export type LoopPhase =
  | "idle" | "streaming_text" | "tool_call" | "tool_result"
  | "compacting" | "awaiting_input" | "final_response" | "error";

// ---------------------------------------------------------------------------
// Phase → mode derivation
// ---------------------------------------------------------------------------

/**
 * Pure mapping. Total over LoopPhase (no default-throw).
 * Any unrecognised phase value maps to "observe" (fail-safe).
 */
export function deriveCognitiveMode(phase: LoopPhase): CognitiveMode {
  switch (phase) {
    case "idle":           return "observe";
    case "streaming_text": return "orient";
    case "tool_call":      return "act";
    case "tool_result":    return "verify";
    case "compacting":     return "consolidate";
    case "awaiting_input": return "ask";
    case "final_response": return "report";
    case "error":          return "rollback";
    default:               return "observe";
  }
}

// ---------------------------------------------------------------------------
// Glyph table
// ---------------------------------------------------------------------------

/** Glyph + label + ANSI color hint for a mode. The "fireball" is the glyph for active modes. */
export interface ModeGlyph {
  glyph: string;
  label: string;
  color: "red" | "yellow" | "green" | "cyan" | "magenta" | "gray";
}

const FIREBALL_UNICODE = "🔥";
const FIREBALL_ASCII   = "*";

interface GlyphEntry {
  unicode: string;
  ascii: string;
  label: string;
  color: ModeGlyph["color"];
}

const GLYPH_TABLE: Record<CognitiveMode, GlyphEntry> = {
  observe:     { unicode: "○", ascii: "o", label: "observe",     color: "gray"    },
  orient:      { unicode: FIREBALL_UNICODE, ascii: FIREBALL_ASCII, label: "orient",      color: "yellow"  },
  act:         { unicode: FIREBALL_UNICODE, ascii: FIREBALL_ASCII, label: "act",         color: "red"     },
  verify:      { unicode: FIREBALL_UNICODE, ascii: FIREBALL_ASCII, label: "verify",      color: "cyan"    },
  consolidate: { unicode: FIREBALL_UNICODE, ascii: FIREBALL_ASCII, label: "consolidate", color: "magenta" },
  ask:         { unicode: "?",  ascii: "?",  label: "ask",         color: "magenta" },
  report:      { unicode: "✓",  ascii: "v",  label: "report",      color: "green"   },
  rollback:    { unicode: "⚠",  ascii: "!",  label: "rollback",    color: "red"     },
};

/**
 * Returns the glyph + label + color for a mode.
 * Reads EMBER_ASCII at call time so tests can set it per-call without module reload.
 */
export function modeGlyph(mode: CognitiveMode): ModeGlyph {
  const entry = GLYPH_TABLE[mode];
  const ascii = process.env["EMBER_ASCII"] === "1";
  return {
    glyph: ascii ? entry.ascii : entry.unicode,
    label: entry.label,
    color: entry.color,
  };
}

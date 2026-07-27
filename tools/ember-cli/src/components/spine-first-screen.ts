// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// spine-first-screen.ts — the six spine functions, named on the home screen, each bound to the
// command that drives it.
//
// WHY THIS EXISTS. The hard pre-training gate says the operator must be able to DRIVE, from
// ember-cli, every spine function. An operator pass on 2026-07-25 launched the cockpit and looked:
// the first screen showed a logo, a status line, a tips box and a prompt. None of custody, model,
// checkpoint, benchmark or train appeared anywhere. Each command exists and is well described, and
// you reach it only by already knowing its name — which is exactly what "has read no source file"
// rules out. A no-source harness passing 6/6 and this observation are both honest: the harness asks
// whether each function is DESCRIBED, this asks whether it is FOUND.
//
// WHAT THIS IS NOT. `components/spine-panel.ts` renders "B5.5 Operator Spine" — seven elements of
// EMBER-01 CERTIFICATION evidence (authority binding, custody leg, launch packet, failure-class
// ledger, claim scope). That is a different question from the six spine FUNCTIONS below, and I
// first mis-read one for the other because both are called "spine". They overlap only at seat and
// benchmark; lineage, checkpoint save/load and the training launch are absent from B5.5 entirely.
// Do not source this module's status from that panel: it would put a confident-looking wrong number
// on the first screen.

import type { RegistryCommand } from '../types/command-types.ts';

/** What a row can say about a spine function. Mirrors spine-panel.ts's vocabulary deliberately —
 *  the words mean the same thing to an operator even though the resolvers differ. */
export type SpineRowStatus = 'BOUND' | 'OFFLINE' | 'BLOCKED';

export interface SpineFunctionDef {
  /** The function in the operator's words. Not an internal noun. */
  label: string;
  /** Registry name of the command that drives it. Resolved against the live registry, never
   *  rendered from this literal — see buildSpineRows. */
  command: string;
  /** The sub-verb an operator types after the command, when the function is one verb of several.
   *  Rendered as part of the hint, never resolved. */
  verb?: string;
}

export interface SpineRow {
  label: string;
  /** The command text to show. Empty when the command did not resolve — a row NEVER prints a
   *  command name that does not exist, because the first screen's whole job is to be typeable. */
  command: string;
  /** The command WITHOUT its sub-verb — `/model` for `/model manifest inspect`. Same emptiness rule
   *  as `command`. Kept so a narrow width can drop the verb instead of clipping the command name
   *  itself: `/model` is shorter, still true, and still typeable, whereas `/model mani…` is a name
   *  that resolves to nothing. */
  commandBase: string;
  status: SpineRowStatus;
  /** Why, when the status is not BOUND. Empty when BOUND. */
  reason: string;
}

/**
 * The six spine functions named by the pre-training gate, in the order an operator meets them.
 *
 * This list is the CLAIM. If the gate's wording changes, this changes; it is not a convenience
 * grouping. Keep it at six — a seventh row here means someone widened the gate's sentence without
 * saying so.
 */
export const SPINE_FUNCTIONS: readonly SpineFunctionDef[] = [
  { label: 'custody + identity manifest',      command: 'custody' },
  { label: 'data + tokenizer lineage',         command: 'model', verb: 'manifest inspect' },
  { label: 'checkpoint save / load',           command: 'model', verb: 'checkpoint' },
  { label: 'owned serving path',               command: 'model', verb: 'status' },
  { label: 'benchmarking',                      command: 'benchmark' },
  { label: '3B training launch',               command: 'train' },
] as const;

/**
 * Resolve one function against the live command list.
 *
 * Three states, and each says something different to an operator:
 *   BOUND   — the command is registered and enabled. You can type it right now.
 *   OFFLINE — registered but its own isEnabled() says no in this context. It exists; not today.
 *   BLOCKED — not in the registry at all. The function is not drivable from ember-cli, full stop.
 *
 * WHAT THIS MEASURES, stated plainly because an honest limit beats a flattering number: this is
 * DRIVABILITY — can the operator reach the function — and not the function's internal state. It
 * does not know whether a model is bound, a checkpoint exists, or a benchmark has run. Those are
 * what the commands themselves show when you run them, which is the correct division: the first
 * screen's job is to get you to the command, and the command's job is to tell you the truth about
 * its subject. A row saying BOUND means "typeable", never "healthy".
 */
function resolveOne(
  def: SpineFunctionDef,
  commands: readonly RegistryCommand[],
): SpineRow {
  const found = commands.find(
    (c) => c.name === def.command || (c.aliases ?? []).includes(def.command),
  );

  if (!found) {
    // Fail closed: no command text at all. Printing def.command here would teach the operator to
    // type a name that does not resolve, which is worse than admitting the gap.
    return {
      label: def.label,
      command: '',
      commandBase: '',
      status: 'BLOCKED',
      reason: 'no command registered for this function',
    };
  }

  // The registry's own name wins over our literal. A renamed command must surface as its new name
  // or as BLOCKED — never as the stale string in SPINE_FUNCTIONS above.
  const base = `/${found.name}`;
  const text = def.verb ? `${base} ${def.verb}` : base;

  let enabled = false;
  try {
    enabled = found.isEnabled();
  } catch {
    // A command whose own enablement check throws is not something to advertise as ready.
    return {
      label: def.label,
      command: text,
      commandBase: base,
      status: 'OFFLINE',
      reason: 'availability check failed',
    };
  }

  if (!enabled) {
    return {
      label: def.label, command: text, commandBase: base,
      status: 'OFFLINE', reason: 'not available here',
    };
  }

  return { label: def.label, command: text, commandBase: base, status: 'BOUND', reason: '' };
}

/**
 * Build exactly six rows, always.
 *
 * The count is structural, not measured: it is SPINE_FUNCTIONS.length by construction, so a caller
 * that passes no commands, an empty list, or a garbage list gets six BLOCKED rows rather than a
 * shorter block. A block that silently shrinks when its input degrades is how a missing spine
 * function comes to look like a tidy screen.
 */
export function buildSpineRows(commands?: readonly RegistryCommand[] | null): SpineRow[] {
  const list = Array.isArray(commands) ? commands : [];
  return SPINE_FUNCTIONS.map((def) => resolveOne(def, list));
}

/** Width of the status glyph column. Fixed so the block's shape cannot vary with content. */
const STATUS_WIDTH = 7; // 'BLOCKED'.length, the longest of the three

/**
 * Render one row as a single line, truncated so it CANNOT wrap.
 *
 * Structurally one row per function is the whole constraint: the block's height is six by
 * construction and not by measurement. A compact bar that wraps at the narrowest supported width
 * is one row everywhere the test looked and two rows in production, and that shape has cost us
 * before. Truncation here is deliberate and lossy at the tail; the label leads because the label
 * is what an operator scans for.
 */
export function renderSpineRow(row: SpineRow, width: number): string {
  const status = row.status.padEnd(STATUS_WIDTH, ' ');
  // Command BEFORE label, deliberately. Truncation eats the tail, so whatever is last is what an
  // operator loses at a narrow width — and the command is the only text on this row they are meant
  // to type. Measured, not assumed: a live launch rendered "BOUND custody and the identity
  // manifest  /…", which names a function and then hides how to reach it, i.e. exactly the gap this
  // whole block exists to close, reproduced inside the fix.
  const max = Math.max(1, Math.floor(width));
  // Putting the command first stops the LABEL from eating it, but it does not stop the WIDTH from
  // eating it: at any width below the status column plus the command, the command itself clipped
  // mid-word — `BOUND   /model mani…` at width 20, a width this module's own tests declare
  // supported. A clipped command teaches a name that resolves to nothing, which is the precise harm
  // the reordering was meant to remove; the reordering fixed one cause of it and left the other.
  // Caught by an independent review rather than by me.
  //
  // So when the full command does not fit, drop the VERB and keep the command name. `/model` is
  // true, typeable, and gets the operator to a surface that lists its own verbs. Only if even the
  // bare name cannot fit do we fall back to clipping — at that width nothing legible fits anyway.
  // The `+ 1` reserves the ellipsis column. Without it, a command that measures exactly `max` is
  // judged to fit, the LINE then overflows because of the label after it, and truncation takes the
  // command's own last character — `/model manifest inspec…` at width 31. Measured: the first
  // version of this fix passed at widths 20 and 32 and failed at 31, because "the command fits"
  // and "the command survives the clip" are different claims.
  const fits = (head: string) => STATUS_WIDTH + 1 + head.length + 1 <= max;
  const head = row.command === '' ? ''
    : fits(row.command) ? row.command
    : fits(row.commandBase) ? row.commandBase
    : row.command;
  const line = head
    ? `${status} ${head}  ${row.label}`
    : `${status} ${row.label}  ${row.reason}`;
  if (line.length <= max) return line;
  if (max <= 1) return line.slice(0, max);
  return `${line.slice(0, max - 1)}…`;
}

/** Render the whole block. Always SPINE_FUNCTIONS.length lines, at every width. */
export function renderSpineBlock(rows: readonly SpineRow[], width: number): string[] {
  return rows.map((r) => renderSpineRow(r, width));
}

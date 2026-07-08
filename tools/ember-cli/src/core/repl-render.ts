// core/repl-render.ts — pure rendering helpers for cockpit REPL surface text (prompt, banner,
// word-wrap): "how does a line of cockpit text become terminal-safe output" -- no I/O, no
// process.stdout, no console.log; every function here takes data in and returns strings.
//
// Originally extracted out of core/ember-world-state-repl.ts, a standalone proof-pack REPL that
// no longer exists (see commands/world-state.ts's header for where that logic lives now). Note
// for whoever touches this next: a repo-wide search turned up no current importer of this file's
// exports outside its own test -- worth confirming with whoever owns #412 before assuming it's
// still wired to a live caller.
//
// Fixes two visual defects found from a real capture of the operator's window:
//   1. No prompt was ever rendered -- the REPL only ever called rl.on("line", ...) and never
//      rl.prompt(), so a real interactive session looked hung even though it was silently
//      accepting keystrokes. renderPrompt() is the string the REPL now feeds rl.setPrompt() and
//      re-emits via rl.prompt() after boot and after every handled line.
//   2. Long banner/monitor/evidence lines were left to the terminal's own naive column wrap,
//      which cuts mid-word. wrapAnsi()/wrapForDisplay() do word-boundary wrapping ourselves,
//      ANSI-escape-aware (a color code is never split, and a color that's still open when a
//      line breaks is reset at the break and reopened on the continuation so it can never bleed
//      into unrelated terminal output).

import { ANSI } from "./monitor-render.ts";

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------

export const PROMPT_TEXT = "ember> ";

/** The literal prompt string fed to readline's setPrompt()/prompt(). */
export function renderPrompt(colorEnabled: boolean): string {
  return colorEnabled ? `${ANSI.cyan}${PROMPT_TEXT}${ANSI.reset}` : PROMPT_TEXT;
}

// ---------------------------------------------------------------------------
// ANSI-aware word wrap
// ---------------------------------------------------------------------------

const ANSI_CODE_RE = /\x1b\[[0-9;]*m/g;

// A "space" token carries its FULL original run (e.g. the multi-space column-alignment padding
// monitor rows use), not a single collapsed space -- otherwise reflowing a padded row would
// silently destroy its column alignment even on the (common) case where it fits on one line.
type Token =
  | { kind: "ansi"; text: string }
  | { kind: "word"; text: string }
  | { kind: "space"; text: string };

function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  const plainAndAnsi: Array<{ text: string; isAnsi: boolean }> = [];
  ANSI_CODE_RE.lastIndex = 0;
  while ((m = ANSI_CODE_RE.exec(input)) !== null) {
    if (m.index > lastIndex) plainAndAnsi.push({ text: input.slice(lastIndex, m.index), isAnsi: false });
    plainAndAnsi.push({ text: m[0], isAnsi: true });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < input.length) plainAndAnsi.push({ text: input.slice(lastIndex), isAnsi: false });

  for (const part of plainAndAnsi) {
    if (part.isAnsi) {
      tokens.push({ kind: "ansi", text: part.text });
      continue;
    }
    for (const piece of part.text.split(/(\s+)/).filter((p) => p.length > 0)) {
      tokens.push(/^\s+$/.test(piece) ? { kind: "space", text: piece } : { kind: "word", text: piece });
    }
  }
  return tokens;
}

/**
 * Word-boundary wrap of a single logical line to `width` visible columns. ANSI escape codes
 * never count toward width and are never split; if a color is still open ("activeColor") when a
 * line breaks, that line gets a trailing reset (so it can never bleed past the break) and the
 * next line reopens the same color (so it visually continues). A single word longer than `width`
 * is placed on its own line rather than being cut mid-word.
 */
export function wrapAnsi(text: string, width: number): string[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const tokens = tokenize(text);
  const lines: string[] = [];
  let line = "";
  let lineVisible = 0;
  let activeColor = "";
  let atLineStart = true;

  const pushLine = () => {
    lines.push(activeColor && line.length > 0 ? `${line}${ANSI.reset}` : line);
    line = activeColor;
    lineVisible = 0;
    atLineStart = true;
  };

  for (const tok of tokens) {
    if (tok.kind === "ansi") {
      line += tok.text;
      activeColor = tok.text === ANSI.reset ? "" : tok.text;
      continue;
    }
    if (tok.kind === "space") {
      if (atLineStart) continue; // never leading whitespace on a wrapped continuation line
      if (lineVisible + tok.text.length > safeWidth) {
        pushLine();
      } else {
        line += tok.text; // preserve the full run -- this is what keeps padded columns aligned
        lineVisible += tok.text.length;
      }
      continue;
    }
    // word
    if (!atLineStart && lineVisible + tok.text.length > safeWidth) {
      pushLine();
    }
    line += tok.text;
    lineVisible += tok.text.length;
    atLineStart = false;
  }
  lines.push(line);

  // Drop a trailing line that carries no visible characters (can happen when the text ends
  // exactly on a break, leaving only a carried-over color code on the final line).
  while (lines.length > 1 && lines[lines.length - 1]!.replace(ANSI_CODE_RE, "") === "") {
    lines.pop();
  }
  return lines;
}

/**
 * wrapAnsi() plus indentation of continuation lines. Once a line needs to wrap at all, ALL of
 * its lines (including the first) are re-wrapped at `width - indent.length` so an indented
 * continuation line can never itself exceed `width`.
 */
export function wrapForDisplay(text: string, width: number, indent: string = "  "): string[] {
  const atFullWidth = wrapAnsi(text, width);
  if (atFullWidth.length <= 1) return atFullWidth;
  const narrowed = wrapAnsi(text, Math.max(1, width - indent.length));
  return narrowed.map((line, i) => (i === 0 ? line : `${indent}${line}`));
}

// ---------------------------------------------------------------------------
// Banner (compact, boxed-header style) + relocated proof-pack prose
// ---------------------------------------------------------------------------

const COMMAND_LIST_LINE =
  "commands: monitor | understand | interact | evidence <surface> <n> | act <surface> <n> | confirm <offerId> | decline <offerId> | quit";

export interface BannerCounts {
  red: number;
  green: number;
}

/**
 * The new compact boot banner: title, the command list, a "try:" nudge, and the not-green
 * count -- 4 lines total, replacing the previous 7 dense paragraph lines. Each returned line is
 * still wrapped by the caller's print choke point (wrapForDisplay), never pre-wrapped here.
 */
export function renderBanner(counts: BannerCounts, colorEnabled: boolean): string[] {
  const title = "=== Ember Observatory: C-OBS cockpit ===";
  const notGreenLine = `board: ${counts.red} not-green of ${counts.green + counts.red} - type monitor`;
  return [
    colorEnabled ? `${ANSI.cyan}${title}${ANSI.reset}` : title,
    COMMAND_LIST_LINE,
    "try: monitor | evidence monitor 0",
    notGreenLine,
  ];
}

/**
 * The membrane/click-to-evidence/proof-pack prose that used to open the boot banner --
 * relocated (not deleted) behind the `understand` verb per the redesign. Printed ahead of the
 * existing UNDERSTAND topology listing.
 */
export const UNDERSTAND_PROSE_LINES: string[] = [
  "click-to-evidence: every rendered claim resolves to its receipt path on interaction -- try: evidence monitor 0",
  "confirm-only encounter membrane: no silent-steer path -- an offered action executes only after the exact confirm token is typed back for that offer; declining, a wrong id, or anything else never auto-acts",
  "observatory proof-pack: this command sequence -- monitor, understand, interact, evidence, act, confirm -- IS the proof-pack the operator runs himself",
];

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/headless-capture.ts — one signal with one meaning: THIS PROCESS IS AN INSTRUMENT,
// NOT THE OPERATOR'S COCKPIT, so it must publish nothing that another mechanism will act on.
//
// Why a shared module rather than a check inside each writer: a capture harness drives the real
// compiled binary, so it inherits EVERY side effect the product has — not one. Two are known
// today (the liveness heartbeat and the activity-feed watermark) and both converge on the MAIN
// repo root by design, so worktree isolation does not contain either. A per-writer flag would
// have to be discovered and named again for each one, and a harness that set only the flags that
// existed when it was written would look correct while corrupting whatever landed since.
//
// The detection question this answers, for any future writer: for every process a harness starts,
// name every path, port and registry the production code derives from a ROOT RESOLVER or a FIXED
// CONSTANT rather than from a parameter the harness controls. Each such derivation is a write the
// harness cannot redirect and some other process may be polling. Those are the writes that belong
// behind this predicate.

/** Env var a harness sets when it drives the compiled binary as a test instrument. Exact "1". */
export const HEADLESS_CAPTURE_ENV = "EMBER_CLI_HEADLESS_CAPTURE";

/**
 * The env fragment every instrument launcher spreads into the child it spawns.
 *
 * A fragment rather than a literal at each call site, for the reason the predicate is shared: the
 * defect is not that one writer was missed, it is that the set of writers is not enumerable by
 * inspection. The same is true of launchers. One exported name gives the enumeration test something
 * to require at every `spawnPty` site, so a launcher added later fails loudly instead of quietly
 * running as the cockpit.
 *
 * Spread it AFTER `...process.env` — an instrument forces the value rather than inheriting it.
 */
export function headlessCaptureEnv(): Record<string, string> {
  return { [HEADLESS_CAPTURE_ENV]: "1" };
}

/**
 * True when this process is a headless capture harness rather than the operator's cockpit.
 *
 * Exactly `"1"` enables it. A non-empty value that is not `"1"` is a typo, not an intent, so it
 * warns loudly and changes nothing — silently suppressing on a garbled value would take a real
 * cockpit's published state away, which is the failure these guards exist to prevent, arriving
 * by the other door.
 */
export function isHeadlessCapture(
  env: Record<string, string | undefined> = process.env,
): boolean {
  const raw = env[HEADLESS_CAPTURE_ENV];
  if (raw === undefined || raw === "") return false;
  if (raw === "1") return true;
  console.warn(
    `[headless-capture] ${HEADLESS_CAPTURE_ENV}=${JSON.stringify(raw)} is not the exact value ` +
      `"1" -- ignoring it and behaving as the cockpit. Set it to "1" to suppress.`,
  );
  return false;
}

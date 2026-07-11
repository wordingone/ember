# issue #242 rung-1 — issue cross-link + status seed (2026-07-11)

This is a dated addendum to the canonical live-verification board
(`docs/verification/ember-cli-live-board-20260706.md`, PR #249) — not a replacement, and not a
second competing board. #242 asks for the board to live in-repo with default-BROKEN grading and a
receipt or open issue per row; the 2026-07-06 board already satisfies that shape for its 90-row
inventory, but its BROKEN rows predate issues #251 and #252 (both of which were *filed from* that
board's own findings, so it never linked back to them). This file closes that gap: every relevant
row gets an explicit issue link, and the current source-level status (as of this branch,
`fix/cockpit-ux-240-243-242`) is disclosed honestly — including what this PR does **not** fix.

## Cross-link table — 2026-07-06 board rows → filed issues

Per the companion PR (`fix/cockpit-ux-240-243-242`, refs #240 #242 #243): these rows stay
**BROKEN**. This PR does not touch input-race or dead-control wiring; only the issue links are
added here.

| 2026-07-06 board row | Finding | Issue | Status after this PR |
|---|---|---|---|
| BROKEN #2 | Slash-command autocomplete dropdown never renders live | #252 | **BROKEN** (unchanged) |
| BROKEN #4 | Esc-to-interrupt is a no-op | #252 | **BROKEN** (unchanged) |
| BROKEN #8 | Full line + Enter in one synchronous burst is silently dropped | #251 | **BROKEN** (unchanged) |
| BROKEN #9 | Ctrl+E "open editor" is a no-op | #252 | **BROKEN** (unchanged) |
| BROKEN #10 | Alt+P "open model picker" is a no-op | #252 | **BROKEN** (unchanged) |
| BROKEN #11 | Alt+O "toggle fast mode" has no visible effect | #252 | **BROKEN** (unchanged) |
| BROKEN #12 | Ctrl+G "open editor" (second impl) is a no-op | #252 | **BROKEN** (unchanged) |
| BROKEN #13 | Three unreconciled permission-mode state machines | #252 | **BROKEN** (unchanged) |

Seeded honestly, per the mission that produced this file: #251 and #252 rows say BROKEN, with
their issue links, and nothing here claims otherwise.

## Rows this companion PR *does* change (source-level; not yet live-redriven)

The 2026-07-06 board did not flag raw tool_result JSON or the `tryGenerate: too_few_turns` debug
leak as live-observed defects on `ember-cockpit-195.exe` (issue #240 was filed the same day,
against separate operator observation, likely of an older running process). Source-level status
after this PR:

| Concern | Source cure (this PR) | Live-redrive receipt |
|---|---|---|
| #240: raw tool_result JSON reaching the transcript | `formatToolResultForDisplay` (pre-existing, #173) plus a new digest layer (`summarizeToolResultLine` in `tool-result-renderers.ts`) — unrecognized JSON shapes never surface `{`/`[` as the compact digest; full text sits behind Ctrl+O expand | **Not captured live in this pass** — needs a fresh ConPTY drive against a newly compiled binary (out of scope here; see tenancy note below) |
| #240: internal debug object leak (`tryGenerate: too_few_turns`) | Already gated behind `EMBER_SUGGESTION_DEBUG` (`services/prompt-suggestion.ts`, landed in #199, 2026-07-05) — confirmed still gated, unit-verified, no regression | Same as above |
| #243: bare `>` prompt with no bordered container | `components/prompt-input.ts` now renders a real `PANEL_BORDER_STYLE` (round) box on the cyan interaction accent, containing the glyph, input text, queue preview, and the mode/status line (anchored inside the same box) | Verified with a **real terminal-paint** test (`prompt-input-border-check.test.ts`, `mountInk`) at three widths (80/40/80, live-resize probe) — closed border painted at every width; not yet captured against a compiled `.exe` under ConPTY |

## Tenancy note (why no fresh compiled-binary receipt in this pass)

Per this mission's rails, a timed board render may be executing on this box concurrently with
this lane. This pass did the **source + unit/mount-render half only** and is reporting
READY-FOR-LIVE-DEMO rather than capturing against a freshly compiled `.exe` or the live deployed
process. A future rung-1 re-drive (same harness as PR #249: ConPTY + `@xterm/headless`, isolated
working directory, never the operator's window) should re-run the full 90-row inventory against a
binary built from this branch and flip the #240/#243 rows to VERIFIED-LIVE with a captured-buffer
receipt, per #242's own acceptance bar ("re-verification runs on every deployed-binary change").

## What this file is not

Not a second live-verification board, not a re-grading of the full 90-row inventory, and not a
claim that #251 or #252 are fixed. It is the narrow issue-cross-link + honest-status seed this
mission asked for, layered on top of the existing canonical artifact rather than duplicating it.

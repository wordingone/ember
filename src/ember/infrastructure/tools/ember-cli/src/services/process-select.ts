// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// services/process-select.ts — the click-first SELECT PROCESS run-control model (#1475).
//
// The operator's one obvious path is SELECT PROCESS -> pick -> START. This module decides,
// purely, three things: WHICH registry commands are processes (the dropdown's contents), what
// stage the START control is in (unarmed / armed / confirm), and what text a START activation
// dispatches. Rendering lives in components/operator-surface-pane.ts; the dispatch itself is
// executed by screens/repl.ts through the SAME injector/submitPrompt path every command button
// and every typed slash command already uses — this module only produces the activation, never
// performs it.
//
// There is deliberately no process list here. A process is defined by the registry grouping
// that already exists (services/command-buttons.ts): everything in the `launch` group plus the
// `more` catch-all — i.e. every executable command that is not an `inspect` (read state) or
// `govern` (change authority) surface. A newly registered command therefore lands in the
// dropdown with zero edits here; a hand-maintained list is the banned shape (#1370/#1399).
//
// The /train confirm membrane is PRESERVED, not re-implemented: when the selected process has
// an outstanding offer (minted by the command's own green preflight, held in commands/train.ts's
// session-bound single-use store), START's activation is the exact `/<process> confirm <id>`
// text the offer told the operator to type. The membrane's own validation (single-use,
// session-bound, fail-closed) still runs on dispatch — this module reads the offer store, it
// never spends it.

import type { RegistryCommand } from "../types/command-types.ts";
import {
  buildCommandButtons,
  commandButtonActivation,
  commandButtonGroupId,
  resolveCommandBarPage,
  type CommandButton,
  type CommandButtonActivation,
} from "./command-buttons.ts";
import { outstandingTrainOfferForSession } from "../../../../../../../tools/ember-cli/src/commands/train.ts";

// ---------------------------------------------------------------------------
// Process / subordinate split
// ---------------------------------------------------------------------------

/**
 * A process is anything the operator can EXECUTE through START: the `launch` group plus the
 * `more` catch-all. `inspect` and `govern` are the subordinate surfaces — reachable, but never
 * competing with the one obvious path.
 */
export function isProcessCommand(name: string): boolean {
  const group = commandButtonGroupId(name);
  return group === "launch" || group === "more";
}

/** The registry slice the SELECT PROCESS dropdown lists. */
export function processCommands(commands: readonly RegistryCommand[]): RegistryCommand[] {
  return commands.filter((cmd) => cmd && typeof cmd.name === "string" && isProcessCommand(cmd.name));
}

/** The registry slice the (subordinate) command bar keeps: inspect + govern. Together with
 *  `processCommands` this partitions the registry exactly — no command loses its click surface. */
export function subordinateCommands(commands: readonly RegistryCommand[]): RegistryCommand[] {
  return commands.filter((cmd) => cmd && typeof cmd.name === "string" && !isProcessCommand(cmd.name));
}

/** Dropdown options, derived through the SAME button model the command bar uses (enablement,
 *  needs-argument, disabled reason all included) — never a second, hand-shaped list. */
export function buildProcessOptions(commands: readonly RegistryCommand[]): CommandButton[] {
  return buildCommandButtons(processCommands(commands));
}

// ---------------------------------------------------------------------------
// Outstanding membrane offer
// ---------------------------------------------------------------------------

/** An outstanding confirm-only offer for a process, read from the process's own membrane store. */
export interface ProcessOffer {
  readonly process: string;
  readonly offerId: string;
  /** Exact run-spec path already captured by the process's own offer authority. */
  readonly runSpecPath?: string;
}

export type StartReviewCapture =
  | {
      readonly kind: "captured";
      readonly activation: CommandButtonActivation;
      readonly process: string;
      readonly offerId?: string;
      readonly runSpecPath: string;
    }
  | { readonly kind: "rejected"; readonly reason: string };

/**
 * The newest outstanding offer minted by THIS session, if any. Today /train is the only command
 * with a confirm-only membrane, so this is a thin, read-only view over its store; a second
 * membrane-bearing process would be added here, not in the screen. Reading never spends the
 * offer — only dispatching `/<process> confirm <id>` through the command itself can.
 */
export function outstandingProcessOffer(sessionId: string): ProcessOffer | undefined {
  const trainOffer = outstandingTrainOfferForSession(sessionId);
  return trainOffer
    ? { process: "train", offerId: trainOffer.offerId, runSpecPath: trainOffer.runSpec }
    : undefined;
}

// ---------------------------------------------------------------------------
// START stage machine
// ---------------------------------------------------------------------------

/**
 * unarmed — no process selected; START renders muted and a click surfaces the reason.
 * armed   — a process is selected; START HIGHLIGHTS and a click activates it.
 * confirm — the selected process has an outstanding offer from its own preflight; START reads
 *           [CONFIRM START] and the click is the explicit confirm act. The stage NEVER advances
 *           by itself: armed -> confirm only because the dispatched command's own membrane
 *           minted an offer, and confirm -> armed only because the membrane spent or refused it.
 */
export type StartStage = "unarmed" | "armed" | "confirm";

export function startStage(
  selectedProcess: string | undefined,
  offer: ProcessOffer | undefined,
): StartStage {
  if (selectedProcess === undefined) return "unarmed";
  return offer !== undefined && offer.process === selectedProcess ? "confirm" : "armed";
}

/** Surfaced when START is activated with nothing selected — a control that does nothing and
 *  says nothing is the defect class the operator controls already killed once (R2). */
export const START_NEEDS_SELECTION_REASON = "select a process first (SELECT PROCESS, above)";

/**
 * What a START activation MEANS, in the same activation vocabulary every command button uses:
 *
 *  - nothing selected      -> rejected, with the named reason;
 *  - offer outstanding for the selected process -> dispatch `/<process> confirm <id>` — the
 *    byte-identical text the offer told the operator to type, so the membrane's own validation
 *    is what decides, exactly as on the typed path;
 *  - otherwise             -> the button's ordinary activation (dispatch, or prefill when the
 *    command needs arguments — START never blind-executes a command whose arguments are missing,
 *    and a disabled command rejects with its own named reason).
 */
export function startActivation(
  selected: CommandButton | undefined,
  offer: ProcessOffer | undefined,
): CommandButtonActivation {
  if (!selected) {
    return { kind: "rejected", reason: START_NEEDS_SELECTION_REASON };
  }
  if (offer !== undefined && offer.process === selected.name) {
    return { kind: "dispatch", text: `/${offer.process} confirm ${offer.offerId}` };
  }
  return commandButtonActivation(selected);
}

/** Freeze the exact activation and run-spec identity the dialog reviews. */
export function captureStartReview(
  selected: CommandButton | undefined,
  offer: ProcessOffer | undefined,
  fallbackRunSpecPath: string,
): StartReviewCapture {
  const activation = startActivation(selected, offer);
  if (activation.kind === "rejected") return activation;
  if (!selected) return { kind: "rejected", reason: START_NEEDS_SELECTION_REASON };
  const matchingOffer = offer !== undefined && offer.process === selected.name ? offer : undefined;
  const runSpecPath = matchingOffer?.runSpecPath ?? fallbackRunSpecPath;
  if (runSpecPath.trim() === "") {
    return { kind: "rejected", reason: "launch review has no authority-bound run-spec path" };
  }
  return {
    kind: "captured",
    activation,
    process: selected.name,
    ...(matchingOffer ? { offerId: matchingOffer.offerId } : {}),
    runSpecPath,
  };
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

export const SELECT_PROCESS_LABEL = "[SELECT PROCESS ▾]";

/** The dropdown toggle's label: the affordance name when nothing is selected, the selection
 *  itself (still with the toggle caret) once one is — the armed START right below must never
 *  leave the operator guessing WHAT it would start. */
export function selectProcessButtonLabel(selectedProcess: string | undefined): string {
  return selectedProcess === undefined
    ? SELECT_PROCESS_LABEL
    : `[PROCESS: ${selectedProcess} ▾]`;
}

/** START's rendered label per stage. The confirm stage changes the label ON the button — the
 *  membrane never silently steers, so the click that will confirm must SAY it confirms. */
export function startControlLabel(stage: StartStage): string {
  return stage === "confirm" ? "[CONFIRM START]" : "[START]";
}

// ---------------------------------------------------------------------------
// Dropdown layout
// ---------------------------------------------------------------------------

/** Option-row budget for a pane `paneHeight` rows tall — same height-tier shape as
 *  `commandBarMaxRows`. The menu is transient (open only while choosing), so it may borrow chart
 *  rows; the chart cards already disclose their own hidden count. */
export function processMenuRowBudget(paneHeight: number): number {
  if (paneHeight >= 40) return 10;
  if (paneHeight >= 30) return 8;
  if (paneHeight >= 24) return 6;
  return 4;
}

export interface ProcessMenuLayout {
  readonly visible: CommandButton[];
  /** Options not on this page — the count the pager row discloses and PAGES to. */
  readonly hiddenCount: number;
  readonly page: number;
  readonly pageCount: number;
}

/**
 * One page of the dropdown. When everything fits there is no pager; otherwise each page reserves
 * one row for a clickable `+N more` pager that WRAPS past the last page, so every process is
 * mouse-reachable at every height in a bounded number of clicks (#1370's guarantee, kept).
 */
export function processMenuLayout(
  options: readonly CommandButton[],
  maxRows: number,
  pageIndex: number,
): ProcessMenuLayout {
  const rows = Math.max(1, Math.floor(maxRows));
  if (options.length <= rows) {
    return { visible: [...options], hiddenCount: 0, page: 0, pageCount: 1 };
  }
  const perPage = Math.max(1, rows - 1);
  const pageCount = Math.ceil(options.length / perPage);
  const page = resolveCommandBarPage(pageIndex, pageCount);
  const visible = options.slice(page * perPage, page * perPage + perPage);
  return { visible, hiddenCount: options.length - visible.length, page, pageCount };
}

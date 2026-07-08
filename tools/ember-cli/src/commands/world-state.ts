// commands/world-state.ts — /cockpit (alias /board, /world, /cobs) slash command (gh issue #10,
// C-OBS).
//
// Wires the real adapter (core/ember-world-state.ts) and the confirm-only encounter membrane
// (core/encounter-membrane.ts) into the ember-cli command surface. This command IS the current
// home of that logic -- the original standalone `node core/ember-world-state-repl.ts` proof-pack
// this was split out of no longer exists (its rendering rules live on in core/monitor-render.ts
// and core/repl-render.ts, extracted for unit-testability); this is the only way to exercise the
// adapter today. It renders exactly one MONITOR/UNDERSTAND/INTERACT turn per invocation (a REPL
// turn, not a persistent session) and keeps state (outstanding offers, the last-rendered board) in
// module scope across invocations within one running cockpit process.
//
// Registered in command-registry.ts's builtins list. Reaching a running compiled cockpit requires
// whatever binary is currently launched to have been built AFTER this file last changed -- run
// `bun build ./entrypoints/main.ts --compile --outfile ember.exe` from tools/ember-cli/src/ to
// pick up the current source.

import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";
import { buildEmberWorldState, GOALFORGE_ROOT } from "../core/ember-world-state.ts";
import type { EmberWorldState, Claim } from "../core/ember-world-state.ts";
import { validateConfirmation, logEncounter, CONFIRM_TOKEN } from "../core/encounter-membrane.ts";
import type { EncounterOffer } from "../core/encounter-membrane.ts";
import { renderMonitor, renderMonitorPanel, sortMonitorConditions, colorEnabledFor } from "../core/monitor-render.ts";
import { findNewestReceipts, renderReceiptsTail } from "../core/watch-render.ts";

const ENCOUNTER_LOG = process.env.EMBER_COBS_ENCOUNTER_LOG || "encounters.jsonl";

const outstandingOffers = new Map<string, EncounterOffer>();
let offerCounter = 0;
let cachedState: EmberWorldState | null = null;

function nowIso(): string {
  return new Date().toISOString();
}

function surfaceClaims(state: EmberWorldState, surface: string): Claim[] | undefined {
  // "monitor" resolves against the SAME not-green-first order the `monitor` turn renders below
  // (core/monitor-render.ts's sortMonitorConditions), so a printed [n] here always resolves to
  // the row the operator just saw -- understand/interact untouched.
  if (surface === "monitor") return sortMonitorConditions(state.monitor.conditions);
  if (surface === "understand") return state.understand.topology;
  if (surface === "interact") return state.interact.ledgerRows;
  return undefined;
}

function resolveClaim(state: EmberWorldState, surface: string, idxStr: string): Claim | undefined {
  const claims = surfaceClaims(state, surface);
  if (!claims) return undefined;
  const idx = Number(idxStr);
  if (!Number.isInteger(idx)) return undefined;
  return claims[idx];
}

/**
 * Renders one MONITOR/UNDERSTAND/INTERACT/evidence/act/confirm/decline turn against a fresh (or
 * cached-this-invocation) EmberWorldState. Exported standalone so it is unit-testable without a
 * running cockpit process.
 *
 * "monitor" (and the bare /cockpit default) ALWAYS rebuilds a fresh snapshot and overwrites the
 * cache: a long-running TUI session must show the CURRENT board on repeat invocation, never a
 * permanently-frozen first-call snapshot. Every other subcommand (understand/interact/evidence/
 * act/confirm/decline) resolves against whatever "monitor" last rendered, so evidence/act indices
 * stay consistent with the exact board the operator just saw (falls back to one fresh build if
 * called before "monitor" has ever run).
 */
export async function runWorldStateTurn(argsLine: string): Promise<string> {
  // Honest, visible status (never a throw, never a phantom-path read attempt) when the operator
  // hasn't pointed this command at a contract tree -- see core/ember-world-state.ts's
  // GOALFORGE_ROOT contract.
  if (!GOALFORGE_ROOT) {
    return "world-state source not configured -- set EMBER_GOALFORGE_ROOT to the goalforge contract tree's path to enable /cockpit (monitor/understand/interact over GOAL.md, the debt ledger, and totality-board receipts).";
  }

  const [cmd, ...rest] = argsLine.trim().split(/\s+/);
  const args = rest;

  if (!cmd || cmd === "monitor") {
    cachedState = await buildEmberWorldState();
    // Same renderer the standalone REPL proof-pack uses (core/monitor-render.ts): not-green-first
    // sort, per-condition glyph/truncation, and the pct_complete field-read fix all come for free
    // -- no separate/duplicated MONITOR rendering logic to drift out of sync. Color now matches
    // the same isTTY/NO_COLOR convention every other surface uses (screens/repl.ts's fireball),
    // and the board renders inside renderMonitorPanel()'s bordered container -- the compiled
    // cockpit's message renderer now interprets embedded ANSI via RawAnsi (message-renderers.ts),
    // so a colored panel here reaches the screen intact instead of as a plain-text board.
    const colorEnabled = colorEnabledFor(process.stdout.isTTY, process.env);
    const receipts = await findNewestReceipts(GOALFORGE_ROOT, 3);
    const width = process.stdout.columns || 80;
    return [
      ...renderMonitorPanel(cachedState, { colorEnabled, width, boardTs: cachedState.monitor.boardTs, nowMs: Date.now() }),
      ...renderReceiptsTail(receipts, Date.now()),
    ].join("\n");
  }

  const state = cachedState ?? (cachedState = await buildEmberWorldState());

  if (cmd === "understand") {
    return [
      `UNDERSTAND: goal="${state.understand.goalTitle}" -- organ anatomy + loop topology:`,
      ...state.understand.topology.map((c) => `  ${c.label}`),
    ].join("\n");
  }
  if (cmd === "interact") {
    return [
      "INTERACT: drive/inspect cycles, query receipts/ledger -- active rows:",
      ...state.interact.ledgerRows.map((c) => `  ${c.label}: ${c.detail}`),
    ].join("\n");
  }
  if (cmd === "evidence") {
    const [surface, idx] = args;
    const claim = surface && idx ? resolveClaim(state, surface, idx) : undefined;
    if (!claim) return `EVIDENCE: no claim at ${surface ?? "?"} ${idx ?? "?"}`;
    return `EVIDENCE PATH: ${claim.evidence.path} sha256=${claim.evidence.sha256}`;
  }
  if (cmd === "act") {
    const [surface, idx] = args;
    const claim = surface && idx ? resolveClaim(state, surface, idx) : undefined;
    if (!claim) return `OFFER: no claim at ${surface ?? "?"} ${idx ?? "?"} to act on`;
    offerCounter += 1;
    const offerId = `off-${offerCounter}`;
    const offer: EncounterOffer = { offerId, ts: nowIso(), action: `inspect:${claim.id}`, detail: claim.detail };
    outstandingOffers.set(offerId, offer);
    await logEncounter({ ts: offer.ts, kind: "offer", offerId, action: offer.action }, ENCOUNTER_LOG);
    return `OFFER ${offerId} action=${offer.action} -- type "confirm ${offerId}" to proceed. Declining, a typo, or anything else takes no action; the confirm-only membrane never silently steers.`;
  }
  if (cmd === "confirm" || cmd === "decline") {
    const offerId = args[0] ?? "";
    const offer = outstandingOffers.get(offerId);
    if (cmd === "decline") {
      await logEncounter({ ts: nowIso(), kind: "outcome", offerId, decision: "declined" }, ENCOUNTER_LOG);
      outstandingOffers.delete(offerId);
      return `DECLINED ${offerId} -- no action taken.`;
    }
    const result = validateConfirmation(offer, offerId, CONFIRM_TOKEN);
    if (!result.ok) {
      await logEncounter(
        { ts: nowIso(), kind: "outcome", offerId, decision: "rejected", reason: result.reason },
        ENCOUNTER_LOG,
      );
      return `REJECTED ${offerId}: ${result.reason}`;
    }
    await logEncounter(
      { ts: nowIso(), kind: "outcome", offerId, decision: "confirmed", action: offer!.action },
      ENCOUNTER_LOG,
    );
    outstandingOffers.delete(offerId);
    return `CONFIRMED ${offerId} action=${offer!.action} executed: ${offer!.detail}`;
  }
  return `unknown /cockpit subcommand: ${cmd} (try: monitor | understand | interact | evidence <surface> <n> | act <surface> <n> | confirm <id> | decline <id>)`;
}

export function createWorldStateCommand(): RegistryCommand {
  return {
    name: "cockpit",
    aliases: ["world", "cobs", "board"],
    description:
      "C-OBS observatory: MONITOR/UNDERSTAND/INTERACT over the real GOAL/ledger/receipts world-state adapter, with click-to-evidence and a confirm-only encounter membrane",
    isEnabled(): boolean {
      return true;
    },
    async execute(argsArg: string, _ctx: CommandContext): Promise<CommandResult> {
      const message = await runWorldStateTurn(argsArg);
      return { type: "message", message };
    },
  };
}

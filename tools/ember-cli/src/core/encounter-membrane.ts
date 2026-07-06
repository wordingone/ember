// core/encounter-membrane.ts — confirm-only encounter membrane (gh issue #10, C-OBS clause (c)).
//
// The membrane guarantees no silent-steer path: any action a cockpit surface OFFERS the operator
// requires an explicit confirm token, matched to the exact outstanding offer, before it executes.
// Every offer and every outcome (confirmed / declined / rejected) is logged, append-only, to an
// encounter channel -- mirroring services/finetune-control.ts's pure-validate-then-append pattern.

import { appendFile } from "fs/promises";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EncounterOffer {
  offerId: string;
  ts: string;
  action: string;
  detail: string;
}

export type EncounterDecision = "confirmed" | "declined" | "rejected";

export interface EncounterEvent {
  ts: string;
  kind: "offer" | "outcome";
  offerId: string;
  action?: string;
  decision?: EncounterDecision;
  reason?: string;
}

// The one token that authorizes an offered action. Nothing else -- a decline, a typo, a bare
// Enter, an unrelated command, or a timeout -- ever reaches the "ok:true" branch below.
export const CONFIRM_TOKEN = "confirm";

// ---------------------------------------------------------------------------
// Validation (pure function, no I/O)
// ---------------------------------------------------------------------------

/**
 * Validates a confirmation attempt against an outstanding offer.
 *
 * Returns {ok:true} ONLY when `offer` is defined, `suppliedOfferId` matches its offerId exactly,
 * and `suppliedToken` is exactly CONFIRM_TOKEN. Every other combination -- no outstanding offer,
 * a mismatched id, any token other than the literal confirm token -- returns {ok:false} with a
 * reason, and {ok:false} must never be treated as authorization to act. This is the confirm-only
 * membrane's no-silent-steer guarantee: there is no default/fallback branch that executes an
 * action without this function having first returned {ok:true} for that exact offer.
 */
export function validateConfirmation(
  offer: EncounterOffer | undefined,
  suppliedOfferId: string,
  suppliedToken: string,
): { ok: boolean; reason?: string } {
  if (!offer) {
    return { ok: false, reason: "no outstanding offer -- nothing to confirm, never auto-acted" };
  }
  if (offer.offerId !== suppliedOfferId) {
    return { ok: false, reason: "offerId mismatch -- never auto-acted on the wrong offer" };
  }
  if (suppliedToken !== CONFIRM_TOKEN) {
    return {
      ok: false,
      reason: `confirmation token must be exactly "${CONFIRM_TOKEN}" -- never silent, never assumed`,
    };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Append-only encounter logging
// ---------------------------------------------------------------------------

export async function logEncounter(event: EncounterEvent, logPath: string): Promise<void> {
  await appendFile(logPath, `${JSON.stringify(event)}\n`);
}

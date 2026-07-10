# issue #485 rung-1 reverification (2026-07-10)

This lane (`body485b`) was dispatched to build rung-1 of #485 (real-event activity feed) as if
from scratch. Before writing any feature code, this report verifies rung-1 against current
`master` and the live operator cockpit — the finding is that **rung-1 is already fully built,
merged, and running**, across four prior PRs, and no functional code change is needed here.
This report exists so a future lane does not re-open the same question.

## What already shipped (verified against `origin/master @ dcc79f4`)

- **#491** "ember-cli: real-event activity feed (issue #485 rung 1)" — merged 2026-07-08. Built
  `services/activity-feed.ts` + `components/activity-feed-pane.ts`: real fs-watch on
  `receipts/**`, board renders, outage marker, watchdog restart/kill rows, all traced to a
  ring-buffer + persisted `state/activity-ledger.jsonl`.
- **#574** "P0-B activity-feed watermark/exclusion/coalescing" — merged 2026-07-09. Killed the
  flood source (path+mtime watermark, content-hash fallback, path exclusion, 60ms burst
  coalescing). Flagged a *separate* flood source (watchdog tail-poll) as out of its scope —
  tracked as #576 (still open, not part of rung-1's own acceptance bar).
- **#598** "goal receipts feed the activity surface" — merged 2026-07-09. Added the `"goal"`
  event source (goal-session transitions/continuations) to the same engine.
- **#635** "summarizer renders only real actor/target on kill rows (refs #616)" — merged
  2026-07-09/10, commit `46a2951`. Fixed the fabricated-attribution defect (issue #616: the NL
  summarizer had invented an actor/target on a kill-receipt row it couldn't map). This closes
  the last open item that was actually a rung-1 acceptance-bar violation ("fabricated/synthetic
  events are banned by the P-C text itself").
- **#597** "cockpit: planned-outage status banner" — merged 2026-07-09. Its own PR body records
  an independent re-verification pass: "#485 (activity feed must exist)... already merged...
  confirmed still live and green — no regressions, no partial rollback, no re-implementation
  needed." This is the second independent confirmation rung-1 is done, before today's third.

Issue #485 stays OPEN only because of **rung-2** (a full agentic session's choose→act→verify→
continue cycle rendering live inside ember-cli, riding the `/goal` organ) — explicitly disclosed
as a separately-scoped, substantially larger deliverable by #597's own PR body, tracked via
#211/#154/#98/#92/#483. Rung-2 was not attempted here; it is out of scope for a rung-1 lane.

## Independent reverification performed today

1. **Live production ledger, read from the actual running cockpit**
   (`ember-cockpit-93c7877.exe`, PID 46224 — the operator's deployed keeper, not touched by this
   lane): `tools/ember-cli/state/activity-ledger.jsonl` is 140,647 lines as of
   `2026-07-10T12:53:06.010Z`, actively growing (was 138,830 lines as of #574's forensics on
   2026-07-09). The tail shows genuine receipt-landing lines and a correctly-coalesced watchdog
   burst (`"865 watchdog events collapsed (tail-poll anomaly)"`) — direct evidence the P0-B
   coalescing fix is live in the deployed binary, not just in source. Commit `93c7877` is 11
   commits behind current master but is confirmed to already include both the rung-1 engine
   (#491/#574) and the #616 fabrication fix (`46a2951` is an ancestor of `93c7877`).

2. **Full ember-cli suite**, fresh worktree off `origin/master @ dcc79f4`, `bun install` + `bun
   test`: **3265 pass / 0 fail**, 6473 `expect()` calls, 184 files (53.3s). This is better than
   the 8-pre-existing-failure baseline every earlier PR in this chain reported — #601 ("master
   test-debt") cleared those 8 between #598 and now.
   - Activity-feed-scoped subset (`services/activity-feed.test.ts`,
     `components/activity-feed-pane.test.ts`,
     `screens/activity-flood-render-integrity.test.ts`): **95 pass / 0 fail**.

3. **`bun run typecheck`**: 1 error, `entrypoints/session-init.ts(417,7): error TS2554:
   Expected 2 arguments, but got 3` — pre-existing (introduced 2026-07-09 by commit `a8ecaa42`,
   unrelated to activity-feed; touches an error-constructor call in the model-offline path).
   Out of scope for #485 rung-1 and not fixed here; flagged to the coordinator separately since
   it means "typecheck exit-0" is not currently true of master despite #601's claim.

4. **Live-fire proof against the real production entry point** (not a synthetic demo path —
   `activity-feed.ts` has none; this drives the exact `startActivityFeed()` function the
   compiled cockpit calls, against a scratch state dir):
   - A real receipt file written to `receipts/acceptance/rung1-reverify-proof.json` rendered as
     `"receipt landed [acceptance] rung1-reverify-proof.json — GREEN"` within 1.2s, and the
     ledger file received a matching real-time write.
   - A watchdog restart-log row whose `cmdline` names an unrelated process (not the serving
     binary) correctly produced **no** `"server killed by watchdog"` line — proving the #616
     fix's no-fabrication guarantee holds against a fresh adversarial input, not just the two
     historical rows the original bug report cited.
   - Script: `tools/ember-cli/src/scratchpad/rung1-reverify-20260710.ts` (verification-only,
     scratch-scoped, not part of the shipped feature).

## Conclusion

Rung-1 of #485 is complete, deployed, and independently reverified three times now (#597,
2026-07-09; this report, 2026-07-10; plus the original #491/#574 acceptance legs). No further
lane should be dispatched against rung-1 specifically. The remaining, genuinely open scope
under #485 is rung-2 only. A separate, small, unrelated typecheck regression
(`entrypoints/session-init.ts`) was found during this pass and is flagged, not fixed, here.

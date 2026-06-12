# c04 pick decision table v1 — pre-written verdict logic (2026-06-12, ~4:55 PM LA)

Dress-rehearsal artifact (ledger class): the c04 pick becomes MECHANICAL the
moment the two pending receipts land. Both axes receipted-in-advance here so
no judgment happens post-hoc under deadline pressure. Anchors: production
ceiling 19,228 tok/s (fp39b, B16+ckpt+compile) → 1.66B tok/governed-day;
Muon wall-share 36.01%; criterion = pretrain ≤ 1 governed day (program §3).

## Axis 1 — L10 optimizer swap (#363, receipt pending)

| outcome | optimizer wall | proj tok/s | tokens/day |
|---|---|---|---|
| L10-FULL (≤15% wall, loss-equiv PASS) | ≤15% | ~25.6–28.8k | 2.2–2.5B |
| L10-PART (15–25%) | ~25% | ~22.3k | 1.93B |
| L10-FAIL (no equiv candidate) | 36% | 19.2k | 1.66B |

## Axis 2 — density A/B (4 cells, manifests v1.1, receipt pending)

- **D-CONF:** curated arm clears MDE (3.85pp, n=400 class) both seeds → the
  curated-budget cut is licensed; c03-class budget ≈ 2.0–2.5B tokens.
- **D-BELOW:** delta under MDE both seeds → power statement, NOT a null; the
  curated cut is UNLICENSED — budget stays bulk-class (≥5.7B Chinchilla-
  default at c03-class P).

## The table (pick = row · column)

| | D-CONF | D-BELOW |
|---|---|---|
| **L10-FULL** | **PASS:** c03-class (h1024 d20, ckpt+compile+swap) × ~2.2–2.5B curated ≈ **1.0 governed day** → §3 receipt → gate-9 → pretrain dispatches | FAIL by ~2.3× (5.7B ÷ 2.5B/day) → §4.5 residual |
| **L10-PART** | MARGINAL: 2.0B ÷ 1.93B/day ≈ 1.04–1.3 d → present the fraction to the user — only he relaxes ≤1-day | FAIL ~3× → §4.5 |
| **L10-FAIL** | 2.0–2.5B ÷ 1.66B/day ≈ 1.2–1.5 d → user fraction call | FAIL ~3.4× → §4.5 |

Wider candidates (h2048+) appear in NO pass cell: density requirement 9–21×
(fp-38) exceeds any plausible D-CONF magnitude — they re-enter only if the
density receipt itself measures a multiplier ≥9× (not expected; recorded so
the re-entry condition is explicit, not vibes).

## §4.5 residual (pre-priced so the FAIL cells aren't dead ends)

Local exhausted = every cell above lands FAIL/MARGINAL and the user holds
the ≤1-day bar. The priced residual presented: (a) second 24GB-class GPU ≈
halves wall-days (1.66→3.3B/day class) — hardware, user-owned; (b) cloud
burst for the ONE pretrain (≈4.2 governed-day-equivalents at current
ceiling) — leaves-PC, user-owned; (c) accept 2-day pretrain as a USER
waiver priced per gate-9 (wall-days written down, not silent). The program
never picks among these — it presents the row.

## Bindings

- Verdicts enter via receipts ONLY (L10 cells + density cells, jude pass on
  both); this table's cell text is quoted in the §3 gate receipt.
- Any outcome outside the enumerated axes (e.g. loss-equiv FAIL on every
  L10 candidate but a NEW optimizer idea) = new lever issue, not an edit to
  this table post-receipt.

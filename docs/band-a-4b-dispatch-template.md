# Band-A 4B-leg dispatch template (ledger row 4 — fp-36 Band-A pre-stage)

Pre-staged 2026-06-12 so the 4B retry leg is launchable the moment fp-24
returns RETRY-AT-4B on the real 2B probe — zero design work inside the window.
Plumbing half of row 4 is already DISCHARGED by #336 (chains B and E exercised
RETRY-AT-4B end-to-end, incl. the prior_2b_verdict string contract). This doc
is the remaining half: the exact dispatch.

## Trigger condition (verbatim from the protocol)

`fp24_verdict.py --checkpoint 2B --receipt <real-2B-probe>.json` →
`RETRY-AT-4B`. Per fp-23: 1B (~step 244k) is INFO-only; 2B is the floor
(≥1.0 verified L1 ep/governed-min); 4B is the retry point.

## Dispatch (the command, governed)

```
python scripts/checkpoint_probe.py \
  --checkpoint <ckpt-dir>/step-<4B-step> \
  --probe-set frozen          # 105fd370... — comparability set, NEVER seed23
  --governed                  # VRAM frac 0.80 cap, 1.5GiB margin assert, 0.05s pacer
  --ticket FP24-4B-RETRY \
  --out receipts/fp24-4b-retry-probe-<UTCts>Z.json
```

Then the verdict, carrying the 2B verdict STRING (the #336 wiring guidance —
`.get("verdict")`, never the dict):

```
python scripts/fp24_verdict.py --checkpoint 4B \
  --receipt receipts/fp24-4b-retry-probe-<UTCts>Z.json \
  --prior-2b-verdict RETRY-AT-4B
```

## Bound constraints

- Probe set: checkpoint_probe frozen set (105fd370…) for trajectory
  comparability; the seed23 set (91170123…) rides ONLY as the separate
  fp28_v0_coverage --emit pass (#338 decision) — never substituted here.
- Receipt fields: protocol_sha (40-hex) + harness_sha (64-hex) bound at
  emit; harness_sha "uncommitted" → INVALID-RECEIPT (PR #318 rule, rehearsed
  in #336 and jude's fp24-rehearsal).
- KILL at 4B requires a receipted synthesis attempt first (fp-29;
  episodes_manifest_sha256 from the #333 generator) — KILL without it is
  refused by the gate (KILL-REFUSED-SYNTHESIS-UNRECEIPTED, proven in #336
  chain B).
- Governor floors are non-negotiable (0.80 / 1.5GiB / 0.05s); fix-forward on
  a headroom violation is banned — kill, relaunch governed.

## Receipt naming

`receipts/fp24-4b-retry-probe-<ts>Z.json` (probe) →
`receipts/fp24-4b-verdict-<ts>Z.json` (verdict). Both feed C24/C28 manifest
rows; the tally credits them once the pointers resolve.

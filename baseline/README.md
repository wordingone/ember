# Ember Baseline Staging Packet

Status: STAGING ONLY. This directory does not complete the goal.
Created: 2026-06-29.
Target promotion path: top-level `baseline/` in both `wordingone/ember` and `wordingone/ember-backup`.

2026-07-01 default-branch governance update: `master` is allowed to carry this staging packet only while it remains explicitly NOT COMPLETE. A completed baseline requires the shipping discipline contract, strict verifier, publication-surface verifier, line-ending verifier, remote proof receipts, and operator acceptance to agree. An unmerged PR or staging branch is not delivery.

## Purpose

This packet builds the outside ruler Ember must face before any field-level claim is allowed. The final achievement is not this staging directory. The final achievement is a cited, data-backed, recreatable `/baseline` directory committed or PR-visible in both Ember repos.

## Current Verdict

NOT COMPLETE.

Reasons:

- no dual-repo `/baseline` tree has been verified;
- no remote refs or PR URLs have been recorded;
- no governed Ember-vs-baseline trial has run under the locked protocol;
- exact source pins now exist for the first external anchors, and a first self-improvement zero-spend subset has a static PASS receipt, but baseline receipts, locked thresholds, governed trials, and dual-repo promotion are still missing.
- the active shipping discipline contract forbids treating this staging packet or any unmerged PR as final baseline delivery.

## Layout

- `anchors.md`: external anchor inventory.
- `claim-map-v0.md`: current Ember claim families mapped to external comparators.
- `4090-ceiling-v0.md`: single-4090 >=1B feasibility ceiling.
- `self-improvement-baseline-v0.md`: autonomous ML loop baseline protocol.
- `cli-goal-mode-baseline-v0.md`: CLI and goal-mode baseline protocol.
- `compute-governance-v0.md`: short-job, long-job, and no-recompute rules.
- `contracts/`: uncheatable X/Y/Z/T/C/B/V contracts.
- `protocols/`: locked evaluation protocol.
- `schemas/`: receipt and verdict schemas.
- `scripts/`: deterministic verification helpers, source-ledger validator, manifest generator, external-reference extractor, and promotion-readiness checker.
- `line-endings/`: CRLF/LF policy and verifier notes.
- `reports/`: publication packet draft.

## Recreate Or Verify

1. Refresh external source pins and access dates.
2. Run schema and parser checks:

   ```powershell
   python state\ember-baseline\scripts\emit_verdict.py --help
   python state\ember-baseline\scripts\check_line_endings.py --root state\ember-baseline --mode report
   python state\ember-baseline\scripts\validate_sources.py --sources state\ember-baseline\sources.jsonl --pretty
   python state\ember-baseline\scripts\check_promotion_readiness.py --root state\ember-baseline --pretty
   ```

3. Promote the perfected packet into `baseline/` in both repo checkouts.
4. Verify manifest hashes, line endings, public/private parity, and schema validity in both repos.
5. Commit or open PRs for both repos and record remote refs or PR URLs.

## Non-Substitution Rule

A BabyLM, Modded-NanoGPT, smoke, mock, CLI, or goal-mode result proves only its own contract. No result in this packet transfers to another Ember claim family without its own locked protocol and verdict.

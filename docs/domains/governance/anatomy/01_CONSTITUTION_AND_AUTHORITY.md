# 01 — Constitution and Authority

## Source of truth

`INVARIANT.md` is Ember's sole unamendable identity surface. `GOAL.md` is the
highest amendable authority beneath it: "Lower-precedence files may implement
and test it; they cannot reduce, defer, replace, or reinterpret it" (GOAL.md
line 4-5). `docs/domains/governance/spec/conditions-v1.md` holds the machine-checkable condition
registry that implements GOAL.md's completion bar.

## The EMBER_AUTHORITY_V1 block

`GOAL.md` opens with an HTML-comment-embedded JSON block (`GOAL.md` lines
7-22 at time of writing):

```json
{
  "allows_new_network": true,
  "active_goal_id": "EMBER-02",
  "active_workstream_ids": ["EMBER-02A", "EMBER-02B", "EMBER-02C"],
  "goal_graph_node_ids": ["EMBER-01", "EMBER-02A", "EMBER-02B", "EMBER-02C", "EMBER-02P"]
}
```

Every PR-bound artifact (a `.json` receipt, a `.md` doc, a `.py`/`.ts` config)
that claims to advance the active goal must declare `goal_id`, `workstream_id`
(one of the active set), and `next_executed_outcome` matching the value in
this block, either as top-level fields or nested under an `"authority"` key.
`scripts/verify_authority_conservation.py` (leg 4, `artifact.goal_binding`)
enforces this at commit/push time via `validate_artifact_binding()`.

## Authority conservation legs

`scripts/verify_authority_conservation.py` runs multiple numbered "legs" of
checks (referenced elsewhere in this repo as leg 4, leg 7, etc.) against
staged/changed files: goal-binding presence and correctness, workstream
uniqueness per artifact, policy invariants (`policy.authority_only` must be
`False` — EMBER-02 must retain model-execution authority — and
`policy.new_network` must be `True`, both asserted at
`scripts/verify_authority_conservation.py` around line 551-552), plus a
conservation matrix documented in `docs/authority/ember-authority-matrix.md`. It exits
`EMBER_AUTHORITY_CONSERVATION PASS` or `FAIL <leg> <finding>` and is invoked
both standalone (`python scripts/verify_authority_conservation.py --root .`)
and as part of the repo-guard pre-commit/pre-push hooks.

## The genesis invariant

A separate, narrower invariant lives in `src/ember/governance/scripts/receipt_check.py`:
`INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"`,
pinned at `GENESIS_TS = "2026-07-06T14:13:23-07:00"` (the committer date of
commit `9c89f7f66`, tag `invariant-genesis`, "genesis: entrench
constitutional invariant (#281)"). Every receipt whose `ts` postdates genesis
must carry a matching `invariant_sha256` field (schema-floor rule R4) — see
10_RECEIPTS_PROVENANCE.md.

## Current gaps

Condition `C-AUTHORITY` (board row, `ember-totality-<ts>.json`) tracks
authority-conservation health directly and was GREEN on the last render
(`ember-totality-20260801T052815Z.json`: "authority conservation passed (7
legs)"). This doc does not track separately — see the live board for current
status.

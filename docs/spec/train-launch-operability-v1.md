# FROZEN SPEC — `/train` launch operability through the panel

Status: frozen 2026-07-26. Authored as a frozen spec per user direction; built in an isolated
worktree against this map without amendment.
Gate item: GATE-1 top blocker — the hard pre-training gate requires the 3B training launch itself
to be drivable from ember-cli by a person who has read no source file.

## The defect, measured

Standing in front of the compiled cockpit as the operator (2026-07-26): typing `/train` runs the
cond7 launch-packet preflight and prints the validated launch command as **text for the operator to
paste**. Actually launching requires typing

```
/train --execute --certificate <path> --declaration-ledger <path> --run-spec <path>
```

— four flags and three filesystem paths the operator has to know. The no-source operability harness
scores interaction cost as "one click / one keystroke, with no typed flags". This fails it, and it
fails it for the one spine function the whole gate exists for.

The fail-closed design is sound and stays: `certified_train_launch.py` validates the certificate,
the declaration ledger and the run spec, and the CLI never executes the named command string. The
safety lives in the consumer. It has never lived in the difficulty of typing three paths, so
removing the typing removes no safety.

## The change

### 1. Canonical launch-authority location

Today the three paths are purely caller-supplied; no convention exists anywhere in the repo
(searched: scripts, manifests, docs). Establish one:

```
receipts/ember-02-launch-authority/certificate.json
receipts/ember-02-launch-authority/declaration-ledger.jsonl
receipts/ember-02-launch-authority/run-spec.json
```

Resolved relative to `repoRoot` exactly as `configPath` and `scriptPath` already are in
`train.ts`, and overridable through the existing `TrainCommandDeps` seam for tests.

### 2. Offer/confirm, in the panel's own idiom

Do not invent a new affordance. `commands/world-state.ts:126` already establishes the cockpit's
confirm-only membrane:

> `OFFER <id> action=<action> -- type "confirm <id>" to proceed.`

`/train` adopts the same shape. With no arguments:

1. run the preflight first, as today — it stays the only subprocess in this path;
2. preflight red → unchanged fail-closed message with the failing rows;
3. preflight green → resolve the three canonical artifacts;
4. any of the three missing or unreadable → fail closed, naming **which** prerequisite is absent and
   its expected path. This is the message the operator sees today, before EMBER-01 certifies, and it
   is the correct one: it tells them what is missing rather than handing them a command to paste;
5. all three present → emit `OFFER <id> action=train-launch` with the resolved paths listed for
   inspection, and no subprocess beyond the preflight;
6. `confirm <id>` invokes exactly the same fixed `certified_train_launch.py` consumer the
   `--execute` path invokes today, with the resolved paths.

Offer ids are single-use and expire with the session. A `confirm` for an unknown, spent or expired
id takes no action and says so — matching the membrane's stated contract that a typo never steers.

### 3. `--execute` stays

Explicit `--execute --certificate ... --declaration-ledger ... --run-spec ...` keeps working
unchanged, so CI, tests and any scripted path are untouched. Explicit flags always beat canonical
resolution.

## Acceptance map — FROZEN

Build against this map. Every row is exercised before the head is offered for review.

### Required / allowed keys

No new schema is introduced. The certified consumer's argument contract is unchanged:
`--root --certificate --declaration-ledger --run-spec`, all four required, all four still passed.
Passing a *different* argument set to that consumer is a defect, not an improvement.

### Order invariants (a lenient outcome is reachable only after every strict check passes)

| # | invariant |
|---|---|
| O1 | the preflight runs before any artifact resolution — resolution never precedes it |
| O2 | an OFFER is emitted only after preflight green AND all three artifacts resolved |
| O3 | `confirm` invokes the consumer only for an id minted by a green preflight in this session |
| O4 | preflight red short-circuits: no resolution, no offer, no consumer invocation |

### Conjunction rows (each lenient outcome against each strict check)

| # | condition | required outcome |
|---|---|---|
| C1 | preflight green + all three artifacts present | OFFER emitted, no consumer invoked yet |
| C2 | preflight green + certificate missing | fail closed naming the certificate |
| C3 | preflight green + ledger missing | fail closed naming the ledger |
| C4 | preflight green + run-spec missing | fail closed naming the run spec |
| C5 | preflight red + all three artifacts present | fail closed on the preflight; no offer |
| C6 | preflight red + artifacts missing | fail closed on the preflight; no offer |
| C7 | preflight green, artifacts present, but the runner throws | fail closed, no offer |
| C8 | `--execute` with explicit paths + preflight green | consumer invoked with the explicit paths, canonical resolution not consulted |

### Skip-path rows (the input class on which a validation is bypassed entirely)

| # | skip path | required outcome |
|---|---|---|
| S1 | `confirm <id>` typed with no prior `/train` this session | no consumer invocation; unknown-offer message |
| S2 | `confirm <id>` for a spent id | no second invocation |
| S3 | `confirm` with a malformed or absent id | no action |
| S4 | an artifact path exists but is an empty file or unparseable | fail closed — existence is not validity, and the check must not be skipped just because the path resolved |
| S5 | `--execute` with only *some* of the three flags | the existing usage error, unchanged |

### Over-closure guard

An unmodified real artifact set at the canonical paths must produce an OFFER rather than a false
failure. A cure that fails closed on everything passes every row above and is still broken.

## Kill criteria

If the offer/confirm membrane cannot be reached from a command result without reinventing panel
rendering, stop and report — do not build a second confirmation mechanism beside the existing one.
The directive is explicit that the panel is not to be reinvented.

## Verification

RED first: the C-rows and S-rows are written as failing tests before the implementation, and their
failure is observed and recorded. An assertion that has never failed proves nothing.

Then, as the last leg and not a substitute for it: drive the compiled binary as the operator through
the headless capture, type `/train`, and read the rendered frame. The frame is the receipt — the
test suite establishes that nothing else broke.

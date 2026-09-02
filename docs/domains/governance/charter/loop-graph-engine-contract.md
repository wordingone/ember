# Engine Contract — Loop/Graph Substrate (issue #1309)

## The invariant

The substrate in `schemas/loop-graph/` and `scripts/loop_graph/` stores
authority graphs, execution graphs, and provenance receipts as plain JSON /
JSONL, and verifies them with plain functions. **No field, schema, or module
in this substrate references any specific driving engine** — not Claude
Code, not codex, not any future Ember-native mind. `command.argv` is an
opaque argv list; `resource_class` is a label a scheduler can key off, not a
lock implementation tied to one runtime; nothing here calls a Claude Code
hook, a Workflow, or a codex primitive.

This is deliberate and load-bearing: gap-matrix.md's strongest finding was
that today's actual loop orchestration (when to run the next tick, how to
detect a dead loop, how to lease a worktree) lives entirely inside
Claude-Code-specific hook scripts and skill descriptions, and none of it
would survive an engine swap. This substrate is the part that must survive
the swap.

## The read/claim/execute/receipt/close loop

Any engine — today's Claude Code session, a codex agent, or a future
Ember-native runtime — drives the substrate by repeating exactly this loop.
Nothing about the loop assumes who or what is running it.

1. **Read.** Scan the execution graph for nodes in `PENDING` state whose
   every `prereqs[]` entry is a node in a `CLOSED_PASS` state (or whatever
   closed states the engine's policy treats as satisfying a prerequisite —
   the schema doesn't decide this; the engine does).
   `src/ember/governance/scripts/loop_graph/lifecycle.py:try_load_node` / a directory scan over
   the node store is all that's needed; no engine-specific API.

2. **Claim.** Call `lifecycle.claim(store_dir, node_id, owner)` to record
   who is taking the node, then `lifecycle.start(store_dir, node_id,
   owner_pid, wall_budget_seconds=...)` to move it to `RUNNING` and record
   the lock (`owner_pid`, `acquired_at`) that `mutex.py` and `stale.py` key
   off. If `resource_class` is exclusive (currently `gpu-exclusive`), call
   `mutex.acquire(locks_dir, resource_class, node_id, owner_pid)` first —
   this is the only place resource contention is enforced, and it works the
   same way regardless of what kind of process is about to run.

3. **Execute.** Run `command.argv` in `command.cwd`. This is the ONLY step
   the substrate does not perform for you — deliberately. The substrate
   never shells out, never spawns a process, never decides what "execute"
   means for a given `type` (canary vs. long-run vs. independent-review).
   That decision, and the actual process invocation, belongs entirely to
   the engine. This is what keeps the schema and the tooling engine-neutral:
   the substrate has no opinion about *how* a command runs, only about what
   gets recorded once it has.

4. **Receipt.** Once execution finishes, hash every declared input and
   output with `hashing.hash_file`, write the outputs, and append a
   provenance row with `receipts.append_receipt(index_path, receipt)` —
   `node_id` is mandatory, so the receipt is joinable back to the execution
   node by construction (`receipts.receipts_for_node`).

5. **Close.** Call `lifecycle.close(store_dir, node_id, verdict,
   outputs=..., receipt_id=...)` to move the node to `CLOSED_PASS` /
   `CLOSED_FLAT` / `CLOSED_REJECTED`. If `resource_class` was exclusive,
   release it with `mutex.release(locks_dir, resource_class, node_id)`.
   `lifecycle.close` is idempotent for a repeated close with the same
   verdict, so a crash between execute and close is always safe to resume
   by re-running this same call.

```
        ┌─────────┐   claim/start   ┌─────────┐  gate check   ┌────────────────┐
PENDING │ (read)  │ ─────────────▶  │ RUNNING │ ────────────▶ │ AWAITING_REVIEW │
        └─────────┘                 └─────────┘  (optional)   └────────────────┘
                                          │                             │
                                          └───────────── close ─────────┘
                                                            │
                                                            ▼
                                          CLOSED_PASS | CLOSED_FLAT | CLOSED_REJECTED
```

## Swapping engines requires zero schema or tool changes

Because every step above is a plain function call over plain JSON files:

- A Claude Code session can drive this loop today by reading node files,
  running `command.argv` via its own tool-execution surface, and calling
  the same `lifecycle`/`mutex`/`receipts` functions.
- A codex agent could drive the identical loop by importing the same
  `scripts/loop_graph` package (stdlib only — no engine-specific dependency
  to strip out) and calling the same five functions in the same order.
- A future Ember-native runtime (the `runtime/ember-lab/` Rust control-plane
  crate already gives Ember a non-Claude-Code compute foothold, per
  audit-v1.md §2h) could reimplement the same five-step loop in Rust against
  the same JSON Schema, without touching a single field name.

None of the three graphs, the six tool modules (`validate`, `lifecycle`,
`mutex`, `stale`, `replay`, `receipts`, `gates`), or the state machine's
transition names encode an assumption about which of those three drives the
loop. That is the contract this document exists to make explicit and to
hold future changes to: **if a change to this substrate would break unless
one particular engine were doing the driving, that change does not belong
here.**

## What this substrate deliberately does not do

- It does not choose what to run next, search a topology, or modify its own
  schema — it records and verifies. Topology/experiment selection is engine
  policy, layered on top, out of scope for #1309.
- It does not execute `command.argv` itself (see step 3 above).
- It does not auto-remediate a stale node (`stale.py` only reports —
  killing or reclaiming a stale node is an engine/operator decision).

goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# Ember CLI root authority

Linked worktrees contain source bytes that may differ from the main checkout.
`resolveEmberSourceRootOrCwd` preserves that selected checkout.
`resolveEmberRepoRootOrCwd` follows a linked worktree to the main checkout so
mutable singleton state converges there (issue #666).

| Production consumer | Authority | Reason |
|---|---|---|
| `commands/train.ts` | exact checkout | Executes and hashes config and training scripts. |
| `commands/benchmark.ts` | exact checkout | Reads the selected benchmark registry. |
| `commands/model.ts` | exact checkout | Loads and validates selected model manifests. |
| `commands/custody.ts` identity fallback | exact checkout | Loads selected owned identity manifests and verifier inputs. |
| `commands/custody.ts` root-binding store | canonical root | Machine-local bindings are shared mutable state. |
| `components/spine-panel.ts` | exact checkout | Displays source-bound authority, custody, benchmark, and claim inputs for the selected tree. |
| `entrypoints/process-entry.ts` identity load | exact checkout | Boot identity must match the executable/source checkout. |
| `entrypoints/process-entry.ts` REPL cwd | exact checkout | Commands launched by the REPL must resolve selected source bytes. |
| `hardening/hardening-receipts.ts` | canonical root | Append-only shared test state must not fork per worktree. |
| `services/activity-feed.ts` | canonical root | Watches the shared receipt, outage, and watchdog state surfaces. |
| `services/brain-server-supervisor.ts` | canonical root | Owns singleton serving registry/outage/event state; callers that execute source must pass an explicit selected source path. |
| `services/github-receipts.ts` | canonical root | Append-only outward-action receipts are shared state. |
| `services/goal-persistence.ts` | canonical root | Session goal state must survive worktree rotation and converge. |
| `services/goal-receipts.ts` | canonical root | Append-only goal transition receipts are shared state. |
| `services/operator-receipts.ts` | canonical root | Operator-session receipts are shared state. |
| `services/outage-banner-poller.ts` | canonical root | Reads the same singleton outage marker as the activity feed. |

Rules:

1. A consumer of config, scripts, manifests, registries, or other claim-bearing
   source bytes uses the exact-checkout resolver.
2. A consumer of mutable singleton runtime state uses the canonical resolver.
3. A mixed consumer must receive separate source and state roots; a single
   ambiguous `repoRoot` must not be extended to new mixed behavior.
4. Every source-bound command needs a linked-worktree regression. A normal
   checkout cannot expose accidental canonicalization.

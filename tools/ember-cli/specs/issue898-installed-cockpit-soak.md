<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Installed cockpit-footprint soak

Status: CURRENT

Issue: #898 packet-2 J

Consumer: `tools/ember-cli/src/services/issue898-installed-cockpit-soak.ts`, `src/ember/infrastructure/tools/ember-cli/src/services/issue898-cockpit-negative-harness.ts`
Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/issue898-renderer-census-evidence.ts`

## Contract

The installed soak runs for at least two hours against the exact installed
cockpit and Ember Lab identities. It appends identity-rich process polls and
read-only VRAM/disk wall snapshots to a create-new durable ledger, then seals a
self-hashed receipt containing cadence, custody, negative-harness, and shared
five-minute OLS window evidence. The receipt remains
`MEASURED_NEEDS_INDEPENDENT_ADJUDICATION`; this component cannot mint its own
plateau, execution PASS, issue closure, or training credit.

The renderer-census evidence consumer first verifies that sealed receipt and
its custody bindings, joins each admitted cockpit census row only to the latest
nonfuture renderer diagnostic row inside the frozen tolerance, derives bounded
full-run and settled-window rates, and writes one self-hashed receipt into an
absent sibling root. It is read-only and cannot mint a runtime cure, execution
PASS, or issue closure.

The negative harness executes the real governor and admission logic against an
injected provider listing. It proves receipt-before-action, below-hard reset,
soft observation without action, and exclusion of a foreign same-named
identity without inducing a destructive above-hard event in the live cockpit.

The soak reads wall observations only through the closed Ember Lab RPC. It
never opens the daemon database directly, controls a foreign process, replaces
an existing durable root, or changes training tenancy.

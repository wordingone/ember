# Certified Ember `/train` Executor Design

Status: approved by delegated operator authority (Leo mail 20733)

Goal-ID: EMBER-02  
Workstream-ID: EMBER-02A  
Next executed outcome: one bounded clean-genesis 3B canary through the canonical Ember CLI

## Problem

The public `/train` command currently runs `launch_packet.py`, then prints a
placeholder-bearing shell command. It never launches training. That behavior is
correct for the EMBER-01 operator-experience gate, but after a real B7
SPINE-CERTIFIED declaration it leaves the only executable training path outside
Ember CLI. Running `run_vertical_slice.py` directly would bypass the canonical
surface and would not prove that the declared certificate authorizes the
requested run.

## Decision

Keep `/train` preflight-only unless the operator supplies all three explicit
execution inputs:

```text
/train --execute \
  --certificate <declared-b7-certificate.json> \
  --declaration-ledger <append-only-declaration-ledger.jsonl> \
  --run-spec <certified-train-run-v1.json>
```

No "latest" discovery is permitted. Explicit paths prevent a stale, rogue,
partial, or superseded certificate directory from winning selection and avoid
a preflight-to-execution TOCTOU change.

## Components

### TypeScript command boundary

`tools/ember-cli/src/commands/train.ts`:

1. Parses a closed argument surface.
2. Runs the existing launch-packet preflight first.
3. Without `--execute`, preserves the current preflight-only B5 behavior.
4. With `--execute`, requires all three explicit paths.
5. Spawns exactly one Python certified-launch consumer with an argv array and
   `shell: false`.
6. Never parses or executes `named_ember02_command.command`.
7. Returns the certified consumer's bounded result or exact fail-closed reason.

### Python authority consumer

`tools/ember-restart-3b/certified_train_launch.py`:

1. Loads closed JSON/JSONL schemas and rejects unknown fields.
2. Canonical-hashes the B7 certificate and proves exact membership in the
   supplied append-only declaration ledger.
3. Resolves and rehashes the linked
   `ember-01-completion-receipt-v1`.
4. Requires `ok:true`, exactly nine resolved-true legs, clean/detached/
   head-unchanged checkout integrity, and unchanged selection.
5. Requires the B7 declaration's three conjuncts:
   RECORD-COHERENT, the exact nine-leg receipt, and every birth-relevant
   failure class either `CLOSED_GUARDED` or explicitly blocking.
6. Rehashes and binds the exact public master, config, CLI binary,
   launch-packet receipt, board receipt, benchmark registry, failure-class
   ledger, subject, seat, and other B7 named evidence.
7. Rejects a certificate whose 40-hex Git object ID in `public_master_sha` is
   not the current checked-out public master or whose `superseded_by` field is
   non-null. Content/evidence fields ending in `_sha256` remain exact
   64-hex SHA-256 digests; the Git object ID is not relabeled or hash-wrapped.
8. Validates that the run request is a subset of the certificate-owned scope.
9. Constructs one fixed `disk_budget_runner.py` argv and one fixed,
   allowlisted `run_vertical_slice.py governed-vertical` child argv.
10. Emits a compact execution receipt and propagates child failure without
    making any capability, admission, sufficient-pretraining, VEA, or
    competitiveness claim.

The first implementation supports only the bounded `governed-vertical` canary.
`semantic` and sustained training remain refused until their corpus, optimizer,
and run-scope authority is explicitly added.

## Certificate-Owned Scope

The B7 declared certificate owns the maximum execution envelope. Its closed
`execution_scope` contains:

- purpose: `BOUNDED_CANARY`;
- allowlisted runner modes;
- exact public-master, config, tokenizer, and input-authority hashes;
- maximum optimizer steps;
- maximum accepted records;
- maximum active expert families;
- maximum GPU VRAM;
- maximum transient checkpoint scratch;
- maximum wall time;
- maximum B: and C: writes;
- exact allowed custody and artifact roots;
- prohibition of a model server, WSL, and persistent workers.

The run spec contains only a requested subset. Every numeric request must be
less than or equal to its certificate ceiling; mode and paths must be members of
the certificate allowlists. A canary certificate therefore cannot authorize
semantic or sustained training, multiple active expert families, or the
projected 7.151 GiB all-expert optimizer-state path.

## Error Handling

- Launch-packet failure: no certified consumer spawn.
- Missing execution input: no certified consumer spawn.
- Certificate/ledger/linked-evidence failure: no disk-runner spawn.
- Stale or superseded certificate: no disk-runner spawn.
- Scope escalation: no disk-runner spawn and a distinct scope error.
- Disk-budget refusal or child failure: preserve the runner receipt path and
  propagate nonzero status.
- Success: report exact run receipt and artifact root only.

No path executes a shell command string.

## Test Strategy

### TypeScript

- preflight-only remains backward compatible;
- `--execute` requires certificate, declaration ledger, and run spec;
- preflight failure prevents the certified consumer;
- successful preflight invokes exactly one Python consumer via fixed argv;
- no spawn contains a shell command or the printed launch command;
- consumer nonzero status propagates.

### Python

- valid declared certificate plus subset run spec produces the exact fixed argv;
- raw B6 receipt substituted as the certificate fails;
- schema-valid certificate absent from the ledger fails;
- malformed, extra-key, wrong-role, wrong-event, tampered, wrong-head, stale,
  or superseded certificates fail;
- every linked B7 hash mismatch fails;
- run mode, expert count, record count, VRAM, checkpoint scratch, wall time,
  B/C write, or path above/outside certificate scope fails before spawn;
- fixed allowlist refuses semantic and arbitrary child arguments;
- disk-runner failure is receipted and propagated.

All implementation verification is CPU-only. This change dispatches no GPU
work and does not itself create a certificate.

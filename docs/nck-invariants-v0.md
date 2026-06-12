# NC-K protected-invariant boot-checksum layer — v0 (Closes #261)

## Threat model

ACCIDENTAL self-modification by the resident — not an adversary.  The layer is
a consistency fence, not a security boundary.  The scenarios it guards:

1. A harness edit (branch → receipt path) accidentally modifies a protected
   file without going through the gate.
2. A registered verb (write_gate_note, future state-file ops) accidentally
   targets the protected baseline directory.
3. A non-idempotent verb is registered without a dedup contract, making crash-
   resume unsafe for that verb class.

Boot-time detection of (1) and registration-time detection of (2–3) mean the
resident fails loudly and immediately rather than accumulating silent drift.

## Architecture

### 1. Invariant manifest  (`config/nck-invariants.json`)

A JSON file listing every protected path and its sha256 hash.  The five
invariant slots (sp5 §5):

| Invariant | File | Label |
|---|---|---|
| Three-test gain gate | `docs/formalization-v0.md` | `three-test-gain-gate` |
| Resource governor + headroom config | `configs/v0-pretrain-config.json` | `governor-headroom-config` |
| GOAL.md + only-the-user-retires-it | `GOAL.md` | `goal-md` |
| Receipts-only truth | `GOAL.md` (contains verbatim) | `receipts-only-truth-statement` |
| This enforcement layer itself | `scripts/nck/invariants.py` | `invariants-py` |

The manifest also lists itself (`config/nck-invariants.json`) with
`sha256: "SELF"` — a sentinel that skips the content-hash check, relying
instead on the baseline-comparison step (see §2).  This is correct: a file
cannot hash itself without a fixed-point, and the baseline comparison is the
actual self-verification mechanism.

### 2. Outside-write-surface baseline  (`config/nck-baseline/`)

A second copy of the manifest lives at `config/nck-baseline/nck-invariants.json`.
The resident's tool registry CANNOT write to this directory:

- The `check_write_path(path)` function in `invariants.py` raises
  `PermissionError("WRITE_PROTECTED: ...")` for any path under
  `config/nck-baseline/`.
- The `IdempotenceEnforcingRegistry.register()` method calls `check_write_path`
  for every path in the verb's declared `write_paths` list.
- Verbs that do not declare `write_paths` are not blocked at registration time;
  they are responsible for calling `check_write_path` before any write.

The boot checker verifies the manifest against this baseline copy before
verifying individual paths.  A manifest drift (accidental edit) is caught
even before the per-path hashes are checked.

### 3. Boot check  (`verify_at_boot`)

Called from `NCKEventLoop.__init__` after `validate_invariant_config()`.

```
Step 1: manifest-vs-baseline comparison
  read manifest bytes, read baseline bytes
  if bytes differ → SystemExit naming both sha256s

Step 2: per-path verification
  for each entry in manifest['protected_paths']:
    skip entry if sha256 == "SELF"
    resolve path relative to repo root (derived from manifest_path parameter)
    if file missing → append MISSING to errors
    if sha256(file) != expected → append MISMATCH naming the path

Step 3: fail-closed
  if any errors → SystemExit listing all mismatches
```

The `manifest_path` and `baseline_path` parameters allow selftest fixtures
to supply temp-dir copies without affecting real-repo invariants.

### 4. Per-verb idempotence audit  (`IdempotenceEnforcingRegistry`)

Wraps `ToolRegistry` with a registration-time check:

- Every verb **must** declare `idempotent: bool`.
- Verbs with `idempotent=False` **must** supply a `dedup_contract` dict with
  at least `{"journal_field": ..., "mechanism": ...}`.  Registration is
  refused otherwise.
- Verbs with `idempotent=True` have no additional requirement.

The check fires at registration time (before any dispatch), so a
misconfigured verb is caught at startup, not during crash-resume.

Background: the crash-resume path in the Journal (`event_loop.py`) re-executes
`pending`-without-`applied` actions on restart, relying on idempotence.
`write_gate_note` is idempotent (append-only, same content = same effect).
Non-idempotent verbs (e.g. `send_mail`) must declare how the journal
deduplicates them — otherwise re-execution on restart has undefined behavior.

## Self-covering manifest scheme

The manifest covers its own integrity via two mechanisms that compose:

1. **Baseline comparison** (step 1 of `verify_at_boot`): the manifest must
   byte-match its baseline copy.  The baseline is outside the write surface.
   An accidental in-place edit to the manifest is caught here without needing
   the manifest to hash itself.

2. **Manifest entry** (`sha256: "SELF"`): the manifest lists itself as a
   protected path.  The SELF sentinel is skipped by the per-path checker;
   it exists as documentation of intent, not as a checksum.  A future version
   could store the hash of the manifest-at-write-time in this field as an
   audit trail, but it cannot be part of the boot verification loop without
   a fixed-point.

Why two mechanisms are not redundant: mechanism (1) catches manifest drift
from any source including the promotion path; mechanism (2) ensures the
manifest entry for itself is present and the checker cannot silently omit it.

## What lives outside the write surface

The following paths are protected — the registered verb layer cannot write
to them through `IdempotenceEnforcingRegistry`:

- `config/nck-baseline/` — the baseline directory (hard-enforced via
  `check_write_path`).

The following paths are protected by hash (in the manifest) but not by the
write-surface block (they are inside the write surface, reachable by a branch
promotion):

- `docs/formalization-v0.md`, `configs/v0-pretrain-config.json`, `GOAL.md`,
  `scripts/nck/invariants.py`

These are protected against ACCIDENTAL mutation, not against a deliberate
branch-and-promote.  The full invariant (sp5 §5) requires that promotion
through the gate regenerates the manifest + baseline (via
`scripts/nck/invariants.py --update-manifest`) and re-runs the selftest.
That step is enforced by the promote-script gate (future issue), not by this
layer.

## Wiring in event_loop.py

The edit to `event_loop.py` is surgical — three changes:

1. Docstring addition: one sentence noting boot-checksum wiring.
2. Import block (after existing imports): try/except import of
   `verify_at_boot` from `nck.invariants`; ImportError → SystemExit (fail-closed).
3. `NCKEventLoop.__init__`: one call `_verify_at_boot()` after
   `validate_invariant_config(config)`, guarded by
   `config.get("_skip_invariant_check", False)` for testability.

The `_skip_invariant_check` escape hatch is test-only: the event-loop selftest
runs in temp dirs where protected paths do not exist.  The invariants selftest
(`selftest_invariants.py`) tests the boot-checksum layer directly with
its own fixtures.

## Provenance attestation

Every file read to produce this layer is listed below.  No file under
`B:/M/avir-cli` or any avir-cli source, vendored copy, or transcript was
accessed at any point.  The implementer worked solely from spec documents
and in-repo Python.

| File read | Role |
|---|---|
| `docs/sp5-nck-harness-port-spec-v0.md` | Primary contract: §5 un-removable invariants list |
| `scripts/nck/event_loop.py` | Module to surgically edit; boot-check wiring point |
| `docs/nck-event-loop-v0.md` | Architecture doc for #260 (provenance + ambiguity resolutions) |
| `scripts/nck/selftest_event_loop.py` | Existing selftest: extended with `_skip_invariant_check` |
| `docs/nck-spec-v0.md` | Five invariants with enforcement mechanisms |
| `docs/nck-invariant-contract-v0.md` | 15 behavioral invariants; uniform tool interface (inv 5) |
| `GOAL.md` | Source of receipts-only-truth statement (invariant 4); hash target |
| `docs/formalization-v0.md` | Three-test gain gate (§4); hash target |
| `configs/v0-pretrain-config.json` | Governor + headroom config; hash target |

No file outside this repository was read.  No avir-cli source was accessed.

## Ambiguities resolved

1. **Receipts-only-truth statement file**: the spec requires "a receipts-only-truth
   statement file" as a distinct protected path.  No dedicated file for this
   invariant exists in the repo.  Resolution: `GOAL.md` contains the verbatim
   statement ("Every claim about it is proven by receipts from executed local jobs,
   never by anyone's prose — mine included.") and is the most authoritative source.
   Two manifest entries point to `GOAL.md` with different labels (`goal-md` and
   `receipts-only-truth-statement`) — both hash the same file, so a single mutation
   is caught by either entry.  A dedicated `docs/receipts-only-truth.md` file can
   be created and substituted in the manifest by a future gated PR.

2. **Self-covering manifest bootstrapping**: a manifest that hashes itself cannot
   include its own hash without a fixed-point.  Resolution: use `sha256: "SELF"`
   as a sentinel and skip that entry in the per-path checker.  Self-verification
   is accomplished by the baseline-comparison step (step 1), which is independent
   of the per-path hash table.

3. **Write-surface baseline vs. protected-by-hash**: the spec says the baseline
   dir is "outside the write surface" (enforced by the registry) while the
   other invariant files are inside the write surface (reachable by promotion).
   Resolution: `check_write_path` blocks registered-verb writes to
   `config/nck-baseline/` only.  Protection of the other files is hash-based
   (boot-time detection) rather than filesystem-ACL-based, matching the threat
   model (accidental self-modification, not adversarial attack).

4. **test-only escape hatch**: the boot-check must be skippable for the existing
   event-loop selftest (which runs in temp dirs without the real protected files).
   Resolution: `_skip_invariant_check: True` in the test config dict.  The key
   is underscore-prefixed to signal test-only; production configs never set it.

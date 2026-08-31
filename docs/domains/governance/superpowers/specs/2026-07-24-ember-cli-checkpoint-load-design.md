# Ember CLI Checkpoint Load Design

Date: 2026-07-24
Status: approved
Task: EMBER-CLI-CHECKPOINT-LOAD-OPERABILITY-009

## Outcome

`/model checkpoint load <dir>` loads a modern Ember checkpoint bundle only
after the CLI proves two independent facts:

1. the bundle is internally intact under the v3/v4/v5 checkpoint-manifest
   contract; and
2. the bundle is the checkpoint already designated by Ember's owned model
   identity.

The command cannot designate a new owned checkpoint and cannot reinterpret the
legacy single-file checkpoint snapshot format as a modern model bundle.

## Authority boundary

The currently authorized checkpoint identity remains
`OwnedModelIdentity.checkpointSha256`, whose launch contract points at
`OwnedModelIdentity.launch.checkpointDir`. The command may verify and consume
that authority, but it may not mutate, replace, or mint it.

A requested bundle is authorized only when the SHA-256 of its exact
`checkpoint-manifest.json` bytes equals the active owned identity's
`checkpointSha256`. A valid bundle with any other manifest digest is refused
before server creation, lifecycle mutation, or model loading.

Authority to designate a different owned checkpoint remains in the governed
owned-model identity/admission workflow, not this CLI command. The refusal must
name that next step for operators who have not read the source.

## Accepted bundle

The command accepts a canonical directory containing
`checkpoint-manifest.json` with a supported Ember checkpoint schema:

- `ember-sparse-checkpoint-v3`
- `ember-sparse-checkpoint-v4`
- `ember-sparse-checkpoint-v5`

The CLI preflight validates the manifest and every named artifact before any
model lifecycle action. Validation includes:

- regular, non-symlink/non-reparse directory and files;
- strict UTF-8 and JSON object parsing;
- supported schema;
- exact closed artifact-path set for that schema;
- v3/v4 artifacts `shared.pt`, `replay-state.pt`, and exactly
  `expert-{vision,audio,reasoning,tool}.pt`;
- v5 artifacts `shared-model.pt`, `optimizer-state.pt`, `replay-state.pt`, and
  exactly `expert-{vision,audio,reasoning,tool}.pt`;
- confined normalized relative paths with no absolute path, traversal,
  duplicate, alias, or separator ambiguity;
- exact non-negative byte size and lowercase 64-hex SHA-256 for each artifact;
- each artifact's current on-disk size and digest;
- manifest SHA-256 computed from the same bytes that were parsed.

The real Python serving path remains the second validation gate and revalidates
the modern checkpoint before mutating model state. The TypeScript preflight is
not a replacement for `checkpoint_artifacts.load_checkpoint_artifacts`; it
prevents an invalid or unauthorized bundle from reaching process or lifecycle
creation.

## Load flow

1. Resolve the current `OwnedModelIdentity`.
2. Canonicalize and validate the requested modern checkpoint directory.
3. Hash and parse `checkpoint-manifest.json` from one consumed byte snapshot.
4. Validate the closed schema and hash every named artifact.
5. Compare the manifest digest with
   `OwnedModelIdentity.checkpointSha256`.
6. Clone only `launch.checkpointDir` in the in-memory identity to the verified
   canonical directory. Do not alter any other authority field.
7. Reuse the existing owned server supervisor and lifecycle load path.
8. The Python server revalidates and loads the same bundle.
9. Report success only after the existing lifecycle health contract succeeds.

No persistent selection file or second authority store is introduced.

## Refusal classes

The operator must be able to distinguish integrity failure from authorization
failure.

### Integrity refusal

Used for malformed manifests, unsupported schema, missing/extra/aliased files,
path escape, symlink/reparse input, byte-size mismatch, or artifact digest
mismatch.

Required meaning:

> This checkpoint bundle is corrupt, incomplete, or tampered. Restore or
> regenerate the bundle and retry; no model process was started.

The message identifies the failing artifact or manifest field without leaking
a host path into durable evidence.

### Authorization refusal

Used only after the bundle is internally valid but its manifest digest differs
from the active owned checkpoint identity.

Required meaning:

> This checkpoint bundle is intact but is not the currently authorized owned
> checkpoint. Designate it through the governed owned-model identity/admission
> workflow, then retry; `/model checkpoint load` cannot grant ownership.

No lifecycle state changes and no process starts in either refusal class.

## Save/load truth correction

The existing `/model checkpoint save <dir>` writes the legacy single-file
identity snapshot (`manifest.json` plus `checkpoint`). It does not produce the
modern v3/v4/v5 bundle consumed by `/model checkpoint load`.

The false pairing comments are removed. User-visible command text must state
that legacy save does not round-trip into modern load. A separate successor
item upgrades save to emit a modern bundle; this task does not silently adapt
or reinterpret the legacy format.

## Discoverability and lineage

The `/model` description enumerates every dispatched family:
`status`, `load`, `unload`, `manifest`, and `checkpoint`.

Checkpoint help distinguishes modern load from legacy save and states the
authorization boundary. The manifest/START-HERE surface explicitly tells the

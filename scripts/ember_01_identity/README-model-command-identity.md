<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
<!--
-->

# ember-cli `/model` <-> `validate_identity.py` subprocess contract (cond3 inc2a)

`src/ember/infrastructure/tools/ember-cli/src/commands/model.ts` binds the operator-facing `/model status` and
`/model load` surfaces to checkpoint identity by spawning
`scripts/ember_01_identity/validate_identity.py` as a subprocess (`_resolveModelIdentity`).
This document is the contract between the two sides.

## Invocation

```
<python> scripts/ember_01_identity/validate_identity.py <manifestPath> [--checkpoint <checkpointPath>]
```

- `<python>` — `EMBER_PYTHON_BIN` env override, default `python` (matches the convention in
  `entrypoints/owned-server-supervisor.ts` / `entrypoints/owned-seat-loader.ts`).
- `<manifestPath>` — the active checkpoint's identity manifest. Resolution order:
  `deps.manifestPath` (test injection) -> `EMBER_MODEL_IDENTITY_MANIFEST` env ->
  `<cwd>/.ember/model-identity.json`.
- `--checkpoint <checkpointPath>` — passed only when a sibling file named `checkpoint`
  exists next to the manifest (`dirname(manifestPath)/checkpoint`). When present, the
  validator re-derives `checkpoint.byte_sha256` from the actual bytes and fails closed on any
  mismatch (`checkpoint.byte_hash_mismatch`).

## Contract (validator stdout, exit code 0 == `ok: true`)

```json
{"ok": true, "schema": "ember-model-experiment-identity-v1", "byte_sha256": "<64-hex>", "disposition": "<string>"}
```

`byte_sha256` and `disposition` are surfaced ONLY inside this success envelope so a consumer
never has to (and never should) read `checkpoint.byte_sha256` / `identity.disposition` directly
out of the manifest file — the value it renders has passed the validator's full schema +
closed-object + hash-format + admission checks first.

On rejection, exit code is `1` and stdout is `{"ok": false, "findings": [...]}` — `_resolveModelIdentity`
does not parse `findings`; any non-zero exit or any output that isn't the well-formed success
envelope collapses to a single `null` return.

## Fail-closed contract (binding)

`_resolveModelIdentity(manifestPath)` returns `null` — never a partial/guessed identity — when
**any** of the following holds:

- the manifest file does not exist at `manifestPath`
- `scripts/ember_01_identity/validate_identity.py` does not exist at the resolved repo root
- the subprocess throws, times out (30s), or exits non-zero
- stdout is not parseable JSON
- the parsed payload's `ok` field is not literally `true`
- `byte_sha256` is missing, not a string, or fails `/^[0-9a-f]{64}$/`
- `disposition` is missing, not a string, or empty after trim

Callers (`/model status`, `/model load`) MUST treat a `null` return as "identity unverified":
`/model status` returns `error: checkpoint identity validation failed` with `exitCode: 1` instead
of rendering a bare model name as though it were checkpoint-identity-bearing; `/model load`
throws before any process is spawned, so a checkpoint that cannot be identity-verified is never
loaded.

## Test fixture

`tools/ember-cli/src/commands/__fixtures__/model-identity/` holds a REAL tiny checkpoint
(`checkpoint`, 35 bytes) and a manifest (`manifest.json`, disposition `OWNED_CANDIDATE`) whose
`checkpoint.byte_sha256` is the actual sha256 of those bytes — not a constant/fixture hash typed
by hand. `model.test.ts` exercises the real round trip through `_resolveModelIdentity` (real
`python`/`validate_identity.py` subprocess, not mocked) and a tamper case (mutated checkpoint
bytes) to prove the fail-closed path.

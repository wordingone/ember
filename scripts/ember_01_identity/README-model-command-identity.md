<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# ember-cli `/model` <-> `validate_identity.py` subprocess contract (cond3 inc2a)

`tools/ember-cli/src/commands/model.ts` binds the operator-facing `/model status` and
`/model load` surfaces to checkpoint identity by spawning
`scripts/ember_01_identity/validate_identity.py` as a subprocess (`_resolveModelIdentity`).
This document is the contract between the two sides.

## Invocation

```
<python> scripts/ember_01_identity/validate_identity.py <manifestPath> [--checkpoint <checkpointPath>]
```

- `<python>` — `EMBER_PYTHON_BIN` env override, default `python` (matches the convention in
  `services/brain-server-supervisor.ts` / `entrypoints/owned-seat-loader.ts`).
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

## cond3 inc2b: serving_runtime identity (`LoadedOwnedRuntime.from_paths`)

`tools/ember-restart-3b/serve_owned_openai.py` is the actual serving process the `/model load`
command above spawns. Its identity-binding entry point is
`LoadedOwnedRuntime.from_paths` — this section documents that contract, distinct from (but
downstream of) the CLI-side `/model` contract above.

### `checkpoint-manifest.json` is immutable at startup

`checkpoint/checkpoint-manifest.json` is read exactly once by `from_paths`: the bytes are
hashed (`checkpoint_sha256 = sha256(manifest_bytes)`) before anything else touches them, and
every downstream binding — the central owned-seat resolver's admitted claim
(`resolve_central_owned_admission`), the model/tokenizer config hashes pinned in the central run
manifest, and the served `/v1/models` identity payload — is checked against that ONE read. The
manifest is never re-read, re-derived, or modified for the lifetime of the server process; a
served identity is exactly the identity validated at that single startup read. Nothing in the
serving path writes to `checkpoint-manifest.json` after publication (writes only happen in
`checkpoint_artifacts.write_checkpoint_artifacts`, at training time, never at serve time).

### Pre-load validation receipt (audit trail)

Immediately after `resolve_central_owned_admission` returns a validated claim (and the central
run manifest is re-checked for in-flight mutation), `from_paths` emits one structured JSON
receipt to stderr via `_emit_pre_load_validation_receipt`:

```json
{"schema_version": "ember-owned-pre-load-validation-receipt-v1", "ts": <float>,
 "manifest_path": "<path>", "manifest_sha256": "<64-hex>",
 "claimed_checkpoint_sha256": "<64-hex>", "actual_checkpoint_sha256": "<64-hex>",
 "validation_status": "PASS"}
```

This is receipted before any `state_dict` load touches the model — the audit trail captures the
moment identity was validated, not merely the moment it was claimed. `emit_validation_receipt`
is an injectable keyword argument on `from_paths` (default: the real stderr emitter) so tests
can capture receipts without touching a real file descriptor.

### Fail-closed surface

`from_paths` raises (never falls back to a partial/guessed identity) when:

- the checkpoint manifest file is missing (`OSError` from the read)
- the checkpoint manifest bytes are not valid JSON or not a JSON object (`ValueError`)
- the central resolver's admitted `checkpoint_sha256` does not match the manifest's actual
  hash — including a tampered/mutated manifest whose freshly re-derived hash no longer matches
  a stale admission claim (`ValueError`, from `resolve_central_owned_admission`)
- the central run manifest changes between its own read and the post-admission integrity
  recheck (`ValueError`)
- the model config or tokenizer bytes do not match the hashes pinned in the central run
  manifest (`ValueError`)
- **post-load identity assert:** after `load_checkpoint_artifacts` returns, the architecture's
  tied-embedding invariant (`model.lm_head.weight is model.token_embedding.weight`, enforced at
  `UnifiedDecoder.__init__`) is re-checked with `torch.equal`; a silent partial/misrouted load
  that desynchronized the tied parameter raises `RuntimeError` rather than serving a checkpoint
  whose loaded weights diverge from the architecture's own identity.

### Test fixture

`tests/ember_restart_model/test_owned_openai_server.py`
(`OwnedServerLoadCheckpointIdentityTests`) builds a REAL tiny `UnifiedDecoder` checkpoint through
the production `checkpoint_artifacts.write_checkpoint_artifacts` publication path (not a
constant/mock checkpoint) and drives it through `LoadedOwnedRuntime.from_paths` end to end: a
valid load renders the real derived `checkpoint_sha256` and a `PASS` receipt; a real byte
mutation of the published manifest against a stale admission claim fails closed with no receipt
emitted; a missing manifest and a corrupted-JSON manifest each fail closed; and an injected
broken tied-embedding load is caught by the post-load identity assert.

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Canonical serving contract

Status: CURRENT

Consumer: `runtime/ember-lab/src/server_supervisor.rs`

The canonical serving configuration is one content-addressed
`ember-lab-serving-contract-v1` JSON object. A supervision queue row binds the
contract's canonical path and raw-byte SHA-256; a dispatch manifest or prior
receipt is not a substitute for that contract.

The same canonical path and raw-byte SHA-256 are bound into the content-addressed
`ServerAuthority`. Live registration and every rebound authority require the
request and queue row to equal that authority binding; a caller cannot replace
the contract by supplying a self-consistent model, manifest, and observation.

The object is closed (`deny_unknown_fields`) and contains exactly:

- `schema_version`: `ember-lab-serving-contract-v1`;
- `contract_id`: a stable, path-free operator identifier;
- `model_name`: the exact identity required from `GET /v1/models`;
- `quantization`: either `none`, requiring no quantization option, or the exact
  value of `--quantization VALUE` / `--quantization=VALUE`;
- `expected_vram_bytes`: the nonzero canonical serving footprint;
- `endpoint`: one exact loopback `http://host:port` endpoint;
- `model_config_path` and `model_config_sha256`: the canonicalized model-config
  bytes whose closed `quantization` value equals the contract;
- `launcher_path` and `launcher_sha256`: the canonicalized launcher identity;
- `launcher_args`: the exact ordered argument vector.

An owned checkpoint therefore receives its own exact contract instance. A
borrowed comparison model is never hardcoded or promoted into the owned seat.

## Restore admission and receipt

Ember Lab is the only restore authority. Before fencing the old job it reopens
the contract and restore manifest, verifies both raw identities, requires the
manifest's config binding, launcher, and ordered arguments to equal the
contract, and requires the supervised endpoint to equal the contract endpoint.

Malformed contract bytes, a raw-SHA mismatch, an endpoint mismatch, or a
launcher/manifest mismatch is recorded through the same operational receipt
authority as `RESTORE_FAILED_CONTRACT` / `server_restore_failed_contract`.
That pre-dispatch failure path does not register or change a queue row, fence a
job, dispatch a process, or rebind authority. If the old job is still alive,
the operational receipt keeps `state: running`; only a failed post-dispatch
contract assertion records the stopped rebound job as `state: stopped`.

After governed dispatch and authority rebind, Ember Lab independently reads
the exact model identity from `/v1/models` and the rebound PID's summed GPU
memory from `nvidia-smi`. The observed byte count is accepted only when it is
inside the inclusive band

`abs(observed - expected) / expected <= 0.15`.

Every assertion and both observed values are persisted in the operational
restore receipt. Missing, malformed, foreign, ambiguous, or mismatched
observations produce `RESTORE_FAILED_CONTRACT`; the exact rebound job is
stopped and receives no `RESTORED` event. A model/config swap is therefore a
RED restore, not a silent health-only success.

The Windows `nvidia-smi` child is launched with `CREATE_NO_WINDOW`. Other
platforms use the same argv and parser without a Windows-only wrapper.

## Queue and rollback

`server_supervisions` stores the contract path and SHA beside the restore
manifest. Every subsequent scheduled cycle reloads that row. An older database
is migrated in place with empty contract columns; those rows fail closed until
the operator remints an exact contract-bound server authority and re-registers
it.

Rollback is `git revert` of the serving-contract carrier. Do not delete bound
contract or receipt bytes while any queue row or terminal audit cites them.

This contract is operational evidence only. It grants no checkpoint quality,
training, GPU-result, capability, sufficient-pretraining, milestone, or issue
completion credit. `NO_NEW_PARALLEL_AUTHORITY`.

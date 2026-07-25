<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Closed-loop owned-server identity (ember-cli supervisor side)

This documents the OUTSIDE half of the owned-model identity check. It complements
`tools/ember-restart-3b/serve_owned_openai.py` (#968), which binds the server process's OWN
served identity to a verified checkpoint from the INSIDE (the process refuses to serve unless the
checkpoint it loaded matches its own launch args). This document is about the supervisor verifying,
from the outside, that what the supervisor actually launched is what actually got served.

## The loop

1. **Launch manifest.** `owned-server-supervisor.ts` resolves an `OwnedModelIdentity` (from
   `owned-seat-loader.ts`) carrying the admitted/development checkpoint's `checkpointSha256`,
   `modelConfigSha256`, `serverSourceSha256`, `tokenizerSha256`, `modelName`, and `seat`. This is
   the trust root: everything the supervisor is *about to launch*.
2. **Launch.** `ensureOwnedServer()` either spawns the server directly
   (`buildOwnedServerCommand` + `spawnServer`) or dispatches it through `ember-lab`
   (`dispatchManifest`), passing the checkpoint/tokenizer/config paths bound to those same
   hashes.
3. **Served identity.** Once the endpoint is up, the server exposes `GET /v1/models`
   (`serve_owned_openai.py`'s `Handler.do_GET`), returning `seat`, `mode`, `checkpoint_sha256`,
   `model_name`, `model_config_sha256`, `server_source_sha256`, `tokenizer_sha256`, and (for the
   development seat) `claim_status` / `tokens_seen` / `allocated_parameters` /
   `active_parameters`.
4. **Closed-loop assertion.** `verifyOwnedEndpointIdentity()` (`owned-seat-loader.ts`) fetches that
   endpoint and asserts every one of those served fields equals the launch manifest's identity
   fields. Any mismatch, any non-200 response, or any unreachable/network-error endpoint throws —
   the endpoint is never treated as identity-bearing on a failed or absent check.
5. **Wiring.** `ensureOwnedServer()` uses `verifyOwnedEndpointIdentity` as the default
   `verifyEndpoint` dependency, called by `defaultWaitUntilReady` (direct spawn path) and
   `defaultWaitForDispatchReady` (daemon dispatch path) on every readiness poll. `ensureOwnedServer`
   only resolves `outcome: "spawned" | "dispatched"` after `verifyEndpoint` has succeeded at least
   once; every earlier poll's throw is retried until the 240s deadline, after which the whole
   launch fails closed (`"owned server readiness timed out: " + lastError` /
   `"daemon-dispatched owned server readiness timed out: " + lastError`).

## Fail-closed guarantee

`verifyOwnedEndpointIdentity` never returns a partial or best-effort result — it either resolves
(all fields matched) or throws (`"owned endpoint identity request failed: ..."` for
transport/network failure, `"...failed with HTTP <status>"` for a non-2xx response, `"...returned
invalid JSON"` for an unparseable body, or `"owned endpoint identity does not match admitted
checkpoint or bound development seat"` for any field mismatch). There is no code path in
`ensureOwnedServer` that returns a `"spawned"`/`"dispatched"` result without this check having
already succeeded.

## Tests

- `owned-seat-loader.test.ts`: unit-level closed-loop assertions — served identity matches launch
  manifest (pass), served checkpoint/model/config/server/tokenizer hash mismatches (fail-closed,
  throws), HTTP error status (fail-closed), and unreachable endpoint / network error (fail-closed).
- `owned-server-supervisor.test.ts`: wiring-level — `ensureOwnedServer` calls the injected
  `verifyEndpoint` before resolving `"spawned"`/`"dispatched"`, and propagates a `verifyEndpoint`
  throw into a readiness-timeout failure that also runs cleanup (kills the spawned process,
  removes any development runtime snapshot).

# Acceptance map — modern checkpoint save (#1056)

goal_id: EMBER-02 / workstream_id: EMBER-02A

Frozen BEFORE implementation, per delegation-gate ENUMERATE-FIRST discipline. Derived from the
actual bytes of `tools/ember-cli/src/services/checkpoint-load.ts` (the production consumer/
verifier `/model checkpoint load` already runs) and from the real Python governed writer
`tools/ember-restart-3b/checkpoint_artifacts.py`. The design decision this map drives: the modern
TS save path does **not** reimplement bundle validation — it reuses the exact production
`verifyCheckpointBundle` (checkpoint-load.ts) against the source (before any write) and again
against the published target (after the atomic rename), so there is exactly one closed-schema
validator in the codebase, never two that could drift.

## (a) Closed key set per manifest version — from `checkpoint-load.ts`

All three supported schema versions share ONE manifest-object shape (`verifyCheckpointBundle`,
lines 344-427):

| key | required? | notes |
|---|---|---|
| `schema_version` | REQUIRED | must be a string in `SUPPORTED_SCHEMAS` = {`ember-sparse-checkpoint-v3`, `-v4`, `-v5`} (line 13-17, 368-373) |
| `shards` | REQUIRED | must be `Array` (line 375-377); anything else (object, string, missing) fails |

No other top-level manifest key is inspected by the loader at all — this is the **over-closure
guard**: the loader does not enumerate/close the top-level manifest object's key set beyond
`schema_version`/`shards`, so a manifest carrying extra top-level fields (e.g. the Python writer's
`architecture`, `launch_seed`, `rng_state_sha256`, `data_cursor`, `optimizer_contract`,
`lineage`, `storage_projection`, `host_commit_preflight`, `expert_genesis_sha256`,
`expert_checkpoint_sha256`, `expert_parameter_sha256`, `shared_model_shard_sha256`,
`optimizer_state_shard_sha256`, `contract_version`, `architecture_revision`) is legal and must
round-trip untouched — those are ALLOWED-BUT-NOT-REQUIRED from the loader's point of view. The
modern save path must therefore copy the manifest **byte-for-byte**, never re-serialize a
subset of it (re-serializing would silently drop those fields and still pass the loader, which
is exactly the over-closure trap this map exists to name).

Per-shard record (`validateShardRecord`, lines 240-292) — CLOSED key set:

| key | required? | notes |
|---|---|---|
| `path` | REQUIRED | must be a non-empty, bundle-relative bare filename (`basename(path) === path`, no `/`, `\`, `.`, `..`) |
| `bytes` | REQUIRED | positive `Number.isSafeInteger` |
| `sha256` | REQUIRED | matches `^[0-9a-f]{64}$` |
| `publication_mode` | ALLOWED, NOT REQUIRED | only when `incremental_bytes` also present (paired) |
| `incremental_bytes` | ALLOWED, NOT REQUIRED | only when `publication_mode` also present (paired) |

Any key outside this exact set on a shard record → `shards[i] has unknown field <key>` (line 253).
This is the over-closure guard at the shard level.

## (b) Closed named shard set + per-artifact byte/hash binding

`expectedPaths(schemaVersion)` (lines 227-238):

- `ember-sparse-checkpoint-v5`: `{shared-model.pt, optimizer-state.pt, replay-state.pt,
  expert-vision.pt, expert-audio.pt, expert-reasoning.pt, expert-tool.pt}` — 7 shards.
- `ember-sparse-checkpoint-v3` / `-v4`: `{shared.pt, replay-state.pt, expert-vision.pt,
  expert-audio.pt, expert-reasoning.pt, expert-tool.pt}` — 6 shards.

Binding rule: `records.size === expected.size` AND every name in `expected` present in
`records` (line 387-393) — closed both directions (no missing, no extra shard *names* in the
manifest). Separately, `readdir(canonicalDir)` must yield **exactly** `{checkpoint-manifest.json}
∪ expected` — no untracked sidecar file, and no manifest-declared shard whose physical file is
absent (dir-listing-count check, line 407-409, backed by the per-artifact `requireRegularPath` at
line 413). Byte binding: each artifact's on-disk size is never separately checked against
`bytes` by the loader (no explicit `stat().size !== bytes` assertion) — size fidelity is
transitively enforced only through the sha256 hash match (`hashArtifactFile`, streamed,
`CHECKPOINT_HASH_CHUNK_BYTES`-chunked) at line 414-417. **This is a save-side responsibility**:
the modern save path binds both `bytes` and `sha256` explicitly on every copy (measuring the
freshly-written bytes, never trusting the source manifest's `bytes` field blindly), because the
loader itself does not independently re-check size.

## (c) Production consumer graph — every entry point reaching the loader, default path

1. `/model checkpoint load <checkpoint-dir>` (`commands/model.ts` `action === "load"`, line 542)
   — DEFAULT invocation path: `doVerifyCheckpointBundle(resolve(ctx.cwd, checkpointDir))`, always
   called, no flag suppresses it. Only entry point that reaches `verifyCheckpointBundle` in
   production `ember-cli` code (confirmed by `grep -rn verifyCheckpointBundle` outside test files
   — the only non-test hit besides the definition itself is `commands/model.ts:424`).
2. `tools/ember-restart-3b/checkpoint_artifacts.py` `load_checkpoint_artifacts` /
   `probe_checkpoint_artifacts` (Python side, real training-restart consumer) — OUT OF SCOPE for
   this TS-side issue; it is a separate, independent Python-side verifier over the same on-disk
   shape, not reachable from ember-cli. This map does not modify it and the save path here does
   not need to satisfy Python-side checks beyond producing files that are byte-identical copies of
   an already-Python-governed bundle (see design note above: source must already be a valid
   modern bundle; save never invents shard content).

The new modern save path (`/model checkpoint save <target-dir> [--source <dir>]`, `action ===
"save"`) is a NEW entry point that PRODUCES bundles for entry-point (1) to consume; it is not
itself a consumer of the manifest schema in the validating sense — it delegates that entirely to
`verifyCheckpointBundle`, called both on the source (pre-write) and on the published target
(post-write, proving the round-trip for real rather than by construction-assumption).

## (d) Control flow before dispositions — ORDER / CONJUNCTION / SKIP-PATH rows

Read from `verifyCheckpointBundle`'s actual statement order (checkpoint-load.ts:344-427):

### ORDER rows (strict-before-lenient; the lenient "verified" return is reachable only after
every row below has passed, in this exact sequence)

1. non-empty `checkpointDir` string (line 349-351)
2. `requireRegularPath` on the dir — real directory, not a symlink/reparse leaf (line 354)
3. `requireNoReparseAncestry` — **every ancestor component**, not just the leaf, is walked and
   checked non-symlink (line 355) — this precedes `realpath()` canonicalization deliberately: a
   reparse point anywhere in the ancestry is refused BEFORE the path is ever canonicalized/trusted.
4. `realpath()` canonicalization (line 361) — only reachable after step 3 proves no ancestor is a
   reparse point, so canonicalization can only fix casing/8.3-short-name, never silently follow a
   symlink to a different directory.
5. `requireRegularPath` on the manifest file (line 364) — real file, not symlink.
6. `readManifestFile` — size bound (`0 < size <= MAX_CHECKPOINT_MANIFEST_BYTES`), stable-snapshot
   read (open→stat→read-loop→stat-after, then a POST-CLOSE `lstat` compared to both in-handle
   stats) — refuses a manifest that changes/symlink-swaps mid-read (line 365, 76-137).
7. `decodeManifest` — strict UTF-8 (fatal decode), then `JSON.parse`, then must be a JSON object
   (line 366, 210-225).
8. `schema_version` must be a string in `SUPPORTED_SCHEMAS` (line 368-373) — **cheapest content
   check runs before the expensive per-shard/per-byte work below**.
9. `shards` must be `Array` (line 375-377).
10. Per-shard shape validation (`validateShardRecord`, closed key set, path confinement,
    bytes/sha256 shape) for every entry (line 378).
11. Duplicate-path rejection while building the `records` map (line 380-385).
12. Shard-set closure against `expectedPaths(schemaVersion)` (line 387-393) — **structural**
    completeness, still no disk I/O on artifact bytes yet.
13. `readdir()` the canonical directory; every entry must be in `{manifest} ∪ expected` (line
    401-406) — **no untracked sidecar**, still structural (filenames only).
14. Entry-count closure (`entries.length === allowedEntries.size`, line 407-409) — catches a
    manifest-listed shard whose physical file is simply absent from the directory listing, purely
    by count, before requesting per-artifact `requireRegularPath`.
15. Per-artifact: `requireRegularPath` (not a symlink, is a regular file) then streamed sha256
    (`hashArtifactFile`, same stable-snapshot + post-lstat discipline as the manifest read) MUST
    equal the manifest's declared `sha256` (line 411-417) — **the single most expensive check runs
    strictly last**, only after every cheaper structural/shape check above has already passed.

No short-circuit found that reaches the "verified" return via any path skipping a row above — the
function is a single linear `async` body with no branch that returns success early. This is
already the correct shape (lenient-only-after-every-strict-check); the modern save path's own
new code (below) is what this map's CONJUNCTION/SKIP-PATH rows are really auditing, because it is
the actually-new surface.

### CONJUNCTION rows — pairing each lenient-outcome check against each strict one

| lenient-outcome check | paired strict check | interaction |
|---|---|---|
| `publication_mode` optional field present | `incremental_bytes` optional field present | `hasPublication = "publication_mode" in record \|\| "incremental_bytes" in record` (line 277) — presence of EITHER triggers strict validation of BOTH as a pair (`Number.isSafeInteger` + enum + hardlink-implies-zero rule, line 278-289). A shard record with only one of the two present still fails (the missing one reads as `undefined`, which fails its own type check) — **no independent-lenient path exists for this pair**; verified directly by `checkpoint-load.test.ts`'s existing coverage plus this save path's own reuse of the same validator. |
| destination `pathExists(targetDir)` returns false (lenient: proceed to write) | published-bundle post-verify (`verifyBundle(targetDir)`) | A TOCTOU race between the pre-check and the atomic `rename` is the one place this save path's own lenient check could be stale. The CONJUNCTION that closes it: even if the pre-check lenient-passes on a stale read, the OS-level `rename` to an existing non-empty directory still fails (POSIX `ENOTEMPTY`/`EEXIST`) and — the residual case, an existing but *empty* directory, which POSIX `rename` would silently replace — is caught because the pre-check is unconditional (any existing entry, including an empty directory, refuses BEFORE staging even begins; see design note above and the Python governed writer's own accepted equivalent, `published_root.exists()` before its own rename). |
| per-artifact copy "landed intact" (lenient: bytes+sha256 match expected) | manifest-copy "landed intact" (bytes+sha256 match) | Manifest is written **last**, strictly after every shard copy has already lenient-passed its own check — so a bundle can never end up in staging with a valid manifest pointing at a not-yet-verified shard. |

### SKIP-PATH rows — input class on which a validation is bypassed entirely

| validation | bypassed on |
|---|---|
| `verifyCheckpointBundle`'s reparse-ancestry check on the **destination** side | Not run pre-write for `targetDir`'s ancestry (the loader's `requireNoReparseAncestry` only runs against a directory that already exists — `targetDir` deliberately does not exist yet, that is the collision guard's whole point). This validation is NOT skipped overall — it is *deferred* to the mandatory post-publish `verifyBundle(targetDir)` call, which runs the identical ancestry check against the now-published directory. **Named residual**: there is a narrow window, between the atomic rename and the post-publish verify throwing, during which bytes exist on disk at a path that will be reported as failed. This mirrors the governed Python writer's own accepted `published_root.exists()`-then-rename TOCTOU tradeoff (`checkpoint_artifacts.py` `_write_checkpoint_artifacts_impl`) rather than introducing a new gap. |
| shard byte-count (`bytes` field) cross-check against real on-disk size | The **loader** (`verifyCheckpointBundle`) never independently asserts `stat(artifactPath).size === artifact.bytes` — only the sha256 hash is checked against the manifest, and only implicitly does the hash comparison also prove the byte length (a sha256 match with a different length is not achievable). The **save path** does not rely on this implicit proof: it asserts `bytes` explicitly on every freshly-measured copy, so this loader-side gap is covered on the producer side without needing a loader change (out of this issue's scope — the loader is #1039/#983 governed code, not touched here). |
| Per-shard `publication_mode`/`incremental_bytes` validation | Bypassed entirely (not evaluated at all) when **neither** key is present on a shard record — this is the common case for a bare `{path, bytes, sha256}` shard the modern save path emits (it does not synthesize a `publication_mode`, since the source Python writer's own shards may or may not carry one, and the save path copies the manifest byte-for-byte rather than re-deriving these optional fields). |

## Rows exercised by tests (filled in Stage 3; see `checkpoint-save-modern.test.ts` /
`checkpoint-save-modern-command.test.ts` for the actual assertions per row above).

## Head-verify addendum (2026-07-25) — the one unexercised row, and what it hid

The map above shipped with a single row disclosed as not covered by an executed test: the
destination's reparse/symlink ancestry, deferred to the post-publish re-verify. The disclosure was
honest and it was also the only row that mattered, because "it would throw" and "it does throw"
diverge exactly where a check runs after the function has already written.

I wrote the test, deliberately two-sided: the save must fail **and** leave nothing behind. The first
half passed. The second failed — the published bundle survived at the aliased destination. Step 6 sat
outside the try/catch that cleans up staging, so a throw there reported failure over a complete,
loadable bundle. A retry would then refuse with "destination already exists", naming bytes the
operator had been told were never written.

Cure is ordering, not detection: `requireNoReparseAncestry` runs against the destination's parent
before any staging write, exported from `checkpoint-load.ts` and reused rather than restated. This is
the map's own ORDER invariant applied to itself — the lenient outcome must be reachable only after
every strict check has passed, and a strict check placed after the publish is not a check.

Platform note: Windows refuses unprivileged directory symlinks (EPERM) but permits junctions, which
are reparse points too, so the row is reachable here. The test skips explicitly where reparse points
cannot be created rather than passing vacuously.

Every row in this map is now exercised by an executed test.

(The SKIP-PATH row above still describes the destination reparse check as deferred to the
post-publish re-verify. That is the pre-cure behaviour; step 2a now refuses it before staging. The
row is left as written because it is the record of what the map claimed when it shipped, and this
addendum is where the correction belongs.)

## Second addendum (2026-07-25) — two defects an independent review found in this PR

Both are the same class, and it is a class this map is otherwise built to catch: **a check whose
name promises one tree while its bytes come from another.**

**1. The copy helper measured the source, not the destination.** The map's SKIP-PATH row for shard
byte-counts says the save path "asserts `bytes` explicitly on every freshly-measured copy", and the
production helper's own doc comment claimed it returned "the bytes actually landed at `dest`". The
implementation hashed the read stream. So the map stated a property the code did not hold, and the
caller's error text ("did not land intact") named a tree it had never read. A write-side corruption
— short write, bad flush, failing disk — passed every staging check and surfaced only at the
post-publish verifier, after publication. Cured by re-reading `dest` after the copy completes.

The reason this survived the map's own enumeration is worth stating, because enumeration is what
this document is for: **the unit tests could not have caught it.** The test fixture supplies its own
`copyFileHashed`, which reads the destination and is correct. Only the production dep was wrong. A
test that supplies its own version of the thing under test verifies the test's version — the same
production-entry-is-a-chain error the map warns about elsewhere, arriving through the dependency
seam instead of through the call stack. An acceptance map that enumerates conditions but not
**which tree each measurement comes from** cannot see this class. Byte provenance — *for every byte
a verdict depends on, who chose it and which tree did it come from* — is now a required column of
thinking for any row in this map that asserts a measurement.

**2. The post-publish re-verify ran outside the cleanup path.** Its failure left the divergent bundle
standing at the target: a save reporting failure while publishing bytes that look load-compatible,
with the no-replace guard then refusing the retry. Structurally identical to the ordering defect the
first addendum cures, one layer further in — which is the tell that the first cure fixed an instance
rather than the shape. The target is now removed before the error propagates, and the error names
expected and read values instead of asserting the state was unreachable outside a race.

Covered by an executed test (`removes the published directory when the post-publish re-verify
diverges`), RED-proven by reverting the disposal.

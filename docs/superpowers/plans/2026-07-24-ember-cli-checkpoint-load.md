# Ember CLI Checkpoint Load Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed `/model checkpoint load <dir>` command that verifies a modern Ember checkpoint bundle and proves it is the currently authorized owned checkpoint before any server or lifecycle action.

**Architecture:** A focused TypeScript service validates one consumed manifest byte snapshot, a closed v3/v4/v5 artifact set, and every named artifact's size/digest. `commands/model.ts` compares the verified manifest digest with `OwnedModelIdentity.checkpointSha256`, clones only the in-memory checkpoint directory for the existing owned-server path, and gives distinct integrity versus authorization refusals.

**Tech Stack:** TypeScript, Bun test runner, Node `fs/promises`, Node `crypto`, existing Ember CLI dependency-injection seams.

## Global Constraints

- Workstream remains `EMBER-02A`; do not modify checkpoint producer/server Python in this PR.
- CPU-only: no model load, GPU operation, or training.
- Modern input schemas are exactly `ember-sparse-checkpoint-v3`, `ember-sparse-checkpoint-v4`, and `ember-sparse-checkpoint-v5`.
- `/model checkpoint load` cannot mint or persist owned checkpoint authority.
- Integrity refusal and authorization refusal must remain distinct and actionable.
- Legacy `/model checkpoint save` writes `manifest.json` plus `checkpoint` and does not round-trip into modern load.
- Tests must prove refusal occurs before `ensureOwnedServer`, lifecycle `loadModel`, and registration.
- Niko, Vera, and subagents remain inactive; execute this plan inline.

---

### Task 1: Modern checkpoint bundle verifier

**Files:**
- Create: `tools/ember-cli/src/services/checkpoint-load.ts`
- Create: `tools/ember-cli/src/services/checkpoint-load.test.ts`

**Interfaces:**
- Produces:
  - `CheckpointBundleIntegrityError extends Error`
  - `VerifiedCheckpointBundle { checkpointDir: string; manifestPath: string; manifestSha256: string; schemaVersion: string; artifacts: readonly VerifiedCheckpointArtifact[] }`
  - `CheckpointLoadFsDeps`
  - `verifyCheckpointBundle(checkpointDir: string, deps?: CheckpointLoadFsDeps): Promise<VerifiedCheckpointBundle>`
- Consumes only Node filesystem/hash primitives; it does not consume owned authority.

- [ ] **Step 1: Write the decisive shard-tamper RED**

Create a real temporary `ember-sparse-checkpoint-v5` bundle with an unchanged
`checkpoint-manifest.json`, then overwrite `expert-audio.pt` after the manifest is written:

```ts
const bundle = await writeV5Bundle(tempRoot);
await writeFile(join(bundle, "expert-audio.pt"), Buffer.from("tampered"));
await expect(verifyCheckpointBundle(bundle)).rejects.toThrow(
  /corrupt, incomplete, or tampered.*expert-audio\.pt/i,
);
```

The fixture's manifest names exactly:
`shared-model.pt`, `optimizer-state.pt`, `replay-state.pt`,
`expert-vision.pt`, `expert-audio.pt`, `expert-reasoning.pt`, and
`expert-tool.pt`, with exact sizes and lowercase SHA-256 digests.

- [ ] **Step 2: Run the RED**

Run:

```powershell
bun test tools/ember-cli/src/services/checkpoint-load.test.ts
```

Expected: FAIL because `verifyCheckpointBundle` does not exist.

- [ ] **Step 3: Implement consumed-byte manifest and closed artifact validation**

Implement:

```ts
export interface CheckpointLoadFsDeps {
  lstat(path: string): Promise<{ isDirectory(): boolean; isFile(): boolean; isSymbolicLink(): boolean }>;
  readFile(path: string): Promise<Buffer>;
  readdir(path: string, options: { recursive: true; withFileTypes: true }): Promise<readonly unknown[]>;
  realpath(path: string): Promise<string>;
}

export async function verifyCheckpointBundle(
  checkpointDir: string,
  deps: CheckpointLoadFsDeps = realCheckpointLoadFsDeps,
): Promise<VerifiedCheckpointBundle> {
  // canonicalize directory; reject symlink/reparse/non-directory
  // read checkpoint-manifest.json once into Buffer
  // hash and strict UTF-8-decode that same Buffer, then JSON.parse
  // validate supported schema and exact manifest/artifact row shapes
  // validate confined POSIX relative paths and exact schema path set
  // read each named file once, reject symlink/non-file, compare bytes+sha256
  // reject extra material files under the bundle
  // return the canonical directory and manifest digest
}
```

Use explicit allowlists for each schema and reject unknown/missing row keys,
duplicates, absolute paths, `..`, backslashes, empty components, aliases,
uppercase/non-64-hex digests, negative/non-integer sizes, malformed JSON, and
invalid UTF-8. Every thrown integrity error begins:

```text
This checkpoint bundle is corrupt, incomplete, or tampered.
```

- [ ] **Step 4: Add the full verifier negative matrix**

Add production-shaped cases for:

```ts
test.each([
  "missing shard",
  "extra shard",
  "size mismatch",
  "digest mismatch",
  "absolute path",
  "path traversal",
  "backslash alias",
  "duplicate row",
  "unsupported schema",
  "legacy manifest.json plus checkpoint",
  "symlinked directory",
  "symlinked shard",
])("%s refuses as integrity failure", async (mutation) => { /* real fixture */ });
```

Add one valid fixture for each v3/v4/v5 schema and assert the returned manifest
digest equals a digest independently computed in the test.

- [ ] **Step 5: Run verifier tests and diff check**

Run:

```powershell
bun test tools/ember-cli/src/services/checkpoint-load.test.ts
git diff --check
```

Expected: all verifier tests PASS and diff check is clean.

- [ ] **Step 6: Commit the verifier**

```powershell
git add tools/ember-cli/src/services/checkpoint-load.ts tools/ember-cli/src/services/checkpoint-load.test.ts
git commit -m "feat: verify modern checkpoint bundles"
```

---

### Task 2: Command authorization and lifecycle wiring

**Files:**
- Modify: `tools/ember-cli/src/commands/model.ts`
- Modify: `tools/ember-cli/src/commands/model.test.ts`

**Interfaces:**
- Consumes `verifyCheckpointBundle()` and `VerifiedCheckpointBundle` from Task 1.
- Adds injectable `verifyCheckpointBundle` to `ModelCommandDeps`.
- Produces `/model checkpoint load <dir>` through the existing
  `loadOwnedIdentity`, `ensureOwnedServer`, `loadModel`, and
  `registerManagedModel` seams.

- [ ] **Step 1: Write command-level tamper and no-spawn RED**

Use a real tampered temporary bundle and spies:

```ts
const ensured: OwnedModelIdentity[] = [];
const cmd = createModelCommand({
  loadOwnedIdentity: () => ownedIdentity,
  ensureOwnedServer: async (identity) => {
    ensured.push(identity);
    return spawnedResult(42);
  },
  loadModel: async () => "loaded",
});
const result = await cmd.execute(`checkpoint load ${bundle}`, mockCtx);
expect(result.exitCode).toBe(1);
expect(result.message).toMatch(/corrupt, incomplete, or tampered/i);
expect(ensured).toEqual([]);
```

- [ ] **Step 2: Run the command RED**

Run:

```powershell
bun test tools/ember-cli/src/commands/model.test.ts --filter "checkpoint load"
```

Expected: FAIL because `checkpoint load` is not dispatched.

- [ ] **Step 3: Implement verified authorized load**

In `ModelCommandDeps`, inject:

```ts
verifyCheckpointBundle?: (
  checkpointDir: string,
) => Promise<VerifiedCheckpointBundle>;
```

The handler performs this exact order:

```ts
const verified = await doVerifyCheckpointBundle(resolve(ctx.cwd, targetDir));
const owned = doLoadOwnedIdentity(ctx.cwd);
if (owned === null) throw new CheckpointAuthorizationError("no owned identity");
if (verified.manifestSha256 !== owned.checkpointSha256) {
  throw new CheckpointAuthorizationError(authorizationMessage);
}
const requestedIdentity: OwnedModelIdentity = {
  ...owned,
  launch: { ...owned.launch, checkpointDir: verified.checkpointDir },
};
const ensured = await doEnsureOwnedServer(requestedIdentity);
// reuse existing lifecycle registration/load sequence
```

The authorization message states:

```text
This checkpoint bundle is intact but is not the currently authorized owned checkpoint. Designate it through the governed owned-model identity/admission workflow, then retry; /model checkpoint load cannot grant ownership.
```

Integrity errors retain the service's tamper wording. Neither refusal calls
`ensureOwnedServer`, `loadModel`, or `registerManagedModel`.

- [ ] **Step 4: Add authorization and success tests**

Add tests proving:

- intact bundle with wrong manifest digest gets only the authorization refusal;
- null owned identity names the governed identity/admission next step;
- valid authorized bundle reaches `ensureOwnedServer` with only
  `launch.checkpointDir` changed;
- original identity object is not mutated;
- successful path reuses lifecycle load and registration;
- integrity refusal and authorization refusal are not equal.

- [ ] **Step 5: Run command and service suites**

```powershell
bun test tools/ember-cli/src/services/checkpoint-load.test.ts tools/ember-cli/src/commands/model.test.ts
```

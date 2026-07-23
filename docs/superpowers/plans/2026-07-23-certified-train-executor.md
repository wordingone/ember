# Certified Ember `/train` Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ember CLI the only post-certificate executor of one bounded 3B canary while preserving the existing preflight-only `/train` behavior before a declared B7 certificate exists.

**Architecture:** TypeScript owns slash-command parsing and the existing launch-packet preflight. One Python consumer owns certificate/declaration verification, scope-subsumption, fixed disk-budget-runner argv construction, and execution receipts. No component parses or executes the launch packet's command string.

**Tech Stack:** Bun/TypeScript, Python 3 standard library, `bun:test`, `unittest`, existing `launch_packet.py`, `disk_budget_runner.py`, and `run_vertical_slice.py`.

## Global Constraints

- No GPU command is executed while implementing or verifying this change.
- `/train` without `--execute` remains preflight-only.
- Execution requires explicit `--certificate`, `--declaration-ledger`, and `--run-spec` paths.
- The B7 declared certificate owns the execution envelope; every run request must be a subset.
- Initial runner mode is exactly `governed-vertical`; `semantic` and arbitrary argv remain refused.
- Spawn subprocesses with argv arrays and `shell: false`; never parse or execute `named_ember02_command.command`.
- A stale, superseded, non-ledger, wrong-head, malformed, tampered, or scope-insufficient certificate fails before any disk-runner spawn.
- Success reports exact receipts and artifact root, never capability, admission, sufficient-pretraining, VEA, or competitiveness.
- The implementation reuses the existing public disk-budget runner and governed vertical slice.

---

### Task 1: Pure declared-certificate and run-scope validator

**Files:**
- Create: `tools/ember-restart-3b/certified_train_launch.py`
- Create: `tests/ember_restart_model/test_certified_train_launch.py`

**Interfaces:**
- Consumes: B7 certificate JSON, declaration-ledger JSONL, linked B6 completion receipt, run-spec JSON, repository root.
- Produces: `validate_certified_request(repo_root, certificate_path, declaration_ledger_path, run_spec_path) -> ValidatedLaunch`.

- [ ] **Step 1: Write the failing certificate-membership and scope tests**

Add helpers and these first tests:

```python
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "ember-restart-3b" / "certified_train_launch.py"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_module():
    spec = importlib.util.spec_from_file_location("certified_train_launch", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CertifiedTrainLaunchTests(unittest.TestCase):
    def test_schema_valid_certificate_absent_from_declaration_ledger_fails(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            paths["ledger"].write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "declaration ledger membership"):
                module.validate_certified_request(
                    paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
                )

    def test_run_spec_above_certificate_scope_fails_before_runner_construction(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            paths = write_valid_bundle(pathlib.Path(directory))
            request = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
            request["requested_scope"]["active_expert_families"] = 2
            paths["run_spec"].write_bytes(canonical_bytes(request))
            with self.assertRaisesRegex(ValueError, "scope exceeds certificate"):
                module.validate_certified_request(
                    paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
                )
```

`write_valid_bundle()` must create a temporary repo whose `HEAD` is represented
by a test-injected `current_master_sha256` field, a valid B6 receipt, a B7
certificate whose `completion_receipt_sha256` matches it, one ledger row whose
`certificate_sha256` matches the canonical certificate bytes, and a subset run
spec. Keep every object closed and use lowercase 64-character SHA-256 strings.

- [ ] **Step 2: Run the two selectors and verify RED**

Run:

```text
python -m unittest \
  tests.ember_restart_model.test_certified_train_launch.CertifiedTrainLaunchTests.test_schema_valid_certificate_absent_from_declaration_ledger_fails \
  tests.ember_restart_model.test_certified_train_launch.CertifiedTrainLaunchTests.test_run_spec_above_certificate_scope_fails_before_runner_construction
```

Expected: both error because `certified_train_launch.py` or
`validate_certified_request` does not exist.

- [ ] **Step 3: Implement the closed contracts and pure validation**

Define:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256_KEYS = {
    "public_master_sha",
    "checkout_sha256",
    "completion_receipt_sha256",
    "config_sha256",
    "tokenizer_sha256",
    "input_authority_sha256",
    "cli_binary_sha256",
    "launch_packet_sha256",
    "board_receipt_sha256",
    "benchmark_registry_sha256",
    "failure_class_ledger_sha256",
}


@dataclass(frozen=True)
class ValidatedLaunch:
    certificate_sha256: str
    public_master_sha: str
    artifact_root: Path
    runner_receipt: Path
    seed: int
    write_budget_bytes: int
    max_records: int
    max_c_write_gib: float
    max_b_write_gib: float


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} schema keys mismatch")


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    int(value, 16)
    return value


def _require_scope_subset(requested: dict[str, Any], authorized: dict[str, Any]) -> None:
    if requested["mode"] not in authorized["allowed_modes"]:
        raise ValueError("run scope exceeds certificate: mode")
    for field in (
        "optimizer_steps",
        "max_records",
        "active_expert_families",
        "gpu_vram_gib",
        "transient_checkpoint_gib",
        "wall_minutes",
        "max_b_write_gib",
        "max_c_write_gib",
    ):
        if requested[field] > authorized[field]:
            raise ValueError(f"run scope exceeds certificate: {field}")
    if requested["artifact_root"] not in authorized["allowed_artifact_roots"]:
        raise ValueError("run scope exceeds certificate: artifact_root")
```

`validate_certified_request()` must:

1. reject non-object JSON and unknown/missing keys;
2. require certificate schema `ember-spine-certified-declaration-v1`, event
   `SPINE_CERTIFIED`, role `EMBER_CERTIFICATE_AUTHORITY`, and
   `superseded_by is None`;
3. hash canonical certificate bytes and require one exact ledger membership row;
4. load the certificate-linked B6 receipt by its explicit relative path, rehash
   it, and require schema `ember-01-completion-receipt-v1`, `ok is True`,
   certificate legs exactly `{"1","2","3","4","5","6","7","8","9"}` with every state
   `RESOLVED_TRUE`, checkout clean/detached/head-unchanged, and unchanged
   selection;
5. require all B7 declaration conjunct booleans true and every named evidence
   hash valid;
6. require certificate public master equal the current checked-out master hash
   returned by a small injectable `read_current_master(repo_root)` helper;
7. validate the closed `ember-certified-train-run-v1` request and call
   `_require_scope_subset`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the exact command from Step 2.

Expected: the output ends with `Ran 2 tests` and `OK`.

- [ ] **Step 5: Add the complete negative matrix**

Add table-driven cases for:

```python
cases = {
    "raw B6 receipt substituted": "certificate schema",
    "certificate missing from ledger": "declaration ledger membership",
    "wrong declaration role": "declaration role",
    "wrong declaration event": "declaration event",
    "superseded certificate": "superseded",
    "wrong current master": "current public master",
    "tampered linked B6 receipt": "completion receipt hash",
    "non-nine legs": "exactly nine",
    "checkout not detached": "checkout integrity",
    "selection changed": "selection integrity",
}
```

Add one loop that raises for each individual scope escalation field, including
mode `semantic`, expert count 2, record count above the certificate maximum,
and every budget ceiling.

- [ ] **Step 6: Run the Python module tests**

Run:

```text
python -m unittest tests.ember_restart_model.test_certified_train_launch
```

Expected: every contract and scope test passes; no subprocess starts.

- [ ] **Step 7: Commit**

```text
git add tools/ember-restart-3b/certified_train_launch.py tests/ember_restart_model/test_certified_train_launch.py
git commit -m "feat: validate declared train certificates"
```

---

### Task 2: Fixed disk-budget-runner execution and receipts

**Files:**
- Modify: `tools/ember-restart-3b/certified_train_launch.py`
- Modify: `tests/ember_restart_model/test_certified_train_launch.py`

**Interfaces:**
- Consumes: `ValidatedLaunch`.
- Produces: `build_runner_argv(repo_root, launch) -> list[str]` and
  `execute_validated_launch(repo_root, launch, run_process=subprocess.run) -> int`.

- [ ] **Step 1: Write the failing fixed-argv and child-failure tests**

```python
def test_valid_request_builds_exact_governed_vertical_disk_runner_argv(self):
    module = load_module()
    directory = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
    paths = write_valid_bundle(directory)
    launch = module.validate_certified_request(
        paths["repo"], paths["certificate"], paths["ledger"], paths["run_spec"]
    )
    argv = module.build_runner_argv(paths["repo"], launch)
    self.assertEqual(argv[0], sys.executable)
    self.assertEqual(argv[1], str(paths["repo"] / "tools/ember-restart-3b/disk_budget_runner.py"))
    self.assertIn("--max-c-write-gib", argv)
    self.assertIn("--max-b-write-gib", argv)
    self.assertIn("governed-vertical", argv)
    self.assertNotIn("semantic", argv)


def test_scope_failure_occurs_before_run_process(self):
    module = load_module()
    calls = []
    with tempfile.TemporaryDirectory() as directory:
        paths = write_valid_bundle(pathlib.Path(directory))
        request = json.loads(paths["run_spec"].read_text(encoding="utf-8"))
        request["requested_scope"]["active_expert_families"] = 2
        paths["run_spec"].write_bytes(canonical_bytes(request))
        with self.assertRaisesRegex(ValueError, "scope exceeds certificate"):
            module.certify_and_execute(
                paths["repo"],
                paths["certificate"],
                paths["ledger"],
                paths["run_spec"],
                run_process=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
    self.assertEqual(calls, [])
```

- [ ] **Step 2: Run selectors and verify RED**

Expected: missing `build_runner_argv` and `certify_and_execute`.

- [ ] **Step 3: Implement fixed argv and execution**

`build_runner_argv()` must construct:

```python
[
    sys.executable,
    str(repo_root / "tools/ember-restart-3b/disk_budget_runner.py"),
    "--max-c-write-gib", str(launch.max_c_write_gib),
    "--max-b-write-gib", str(launch.max_b_write_gib),
    "--receipt", str(launch.runner_receipt),
    "--write-root", f"custody={launch.artifact_root.parent}",
    "--write-root", f"artifacts={launch.artifact_root}",
    "--",
    sys.executable,
    str(repo_root / "tools/ember-restart-3b/run_vertical_slice.py"),
    "governed-vertical",
    "--seed", str(launch.seed),
    "--artifact-root", str(launch.artifact_root),
    "--write-budget-bytes", str(launch.write_budget_bytes),
    "--max-records", str(launch.max_records),
]
```

No field may append arbitrary argv. Call `subprocess.run(argv, shell=False,
check=False, cwd=repo_root)` only after validation. Write an atomic compact
receipt beside the disk-runner receipt containing certificate hash, run-spec
hash, exact argv, exit code, artifact root, runner receipt, and a fixed
non-capability claim scope.

- [ ] **Step 4: Run Python tests and verify GREEN**

Run:

```text
python -m unittest tests.ember_restart_model.test_certified_train_launch
```

Expected: all tests pass with injected process runners; no GPU process starts.

- [ ] **Step 5: Commit**

```text
git add tools/ember-restart-3b/certified_train_launch.py tests/ember_restart_model/test_certified_train_launch.py
git commit -m "feat: execute certified canaries through disk governor"
```

---

### Task 3: `/train` explicit execution mode

**Files:**
- Modify: `tools/ember-cli/src/commands/train.ts`
- Modify: `tools/ember-cli/src/commands/train.test.ts`

**Interfaces:**
- Consumes: raw slash-command args and existing launch-packet result.
- Produces: preflight-only message or one certified-consumer subprocess result.

- [ ] **Step 1: Replace the old one-runner test helper with two injected runners**

Extend `TrainCommandDeps`:

```typescript
interface TrainCommandDeps {
  runLaunchPacket?: (executable: string, args: string[]) => LaunchPacketRunResult;
  runCertifiedLaunch?: (executable: string, args: string[]) => LaunchPacketRunResult;
  pythonBin?: string;
  repoRoot?: string;
  configPath?: string;
  scriptPath?: string;
  certifiedLaunchScriptPath?: string;
}
```

Record launch-packet and certified-consumer spawns separately.

- [ ] **Step 2: Write failing tests for the closed execution surface**

```typescript
it("execute mode requires all three explicit authority paths", async () => {
  const { cmd, certifiedSpawns } = makeCmd({
    preflight: { status: 0, stdout: allGreenStdout() },
    certified: { status: 0, stdout: "{}" },
  });
  const result = await cmd.execute("--execute --certificate c.json", mockCtx);
  expect(result?.exitCode).toBe(1);
  expect(result?.message).toContain("--declaration-ledger");
  expect(certifiedSpawns).toHaveLength(0);
});

it("green preflight and explicit paths invoke exactly one certified consumer with argv", async () => {
  const { cmd, preflightSpawns, certifiedSpawns } = makeCmd({
    preflight: { status: 0, stdout: allGreenStdout() },
    certified: { status: 0, stdout: JSON.stringify({ outcome: "COMPLETED" }) },
  });
  const result = await cmd.execute(
    "--execute --certificate c.json --declaration-ledger d.jsonl --run-spec r.json",
    mockCtx,
  );
  expect(preflightSpawns).toHaveLength(1);
  expect(certifiedSpawns).toHaveLength(1);
  expect(certifiedSpawns[0]!.args).toEqual([
    "/fake/ember/tools/ember-restart-3b/certified_train_launch.py",
    "--root", "/fake/ember",
    "--certificate", "c.json",
    "--declaration-ledger", "d.jsonl",
    "--run-spec", "r.json",
  ]);
});
```

Add a test that launch-packet failure produces zero certified spawns, a test
that certified-consumer nonzero propagates, and a test that unknown/duplicate
flags fail before either execution spawn.

- [ ] **Step 3: Run focused Bun tests and verify RED**

Run:

```text
bun test tools/ember-cli/src/commands/train.test.ts
```

Expected: new execution tests fail because `/train` ignores args and has no
certified runner.

- [ ] **Step 4: Implement the minimal closed parser and dispatch**

Implement:

```typescript
interface TrainArgs {
  execute: boolean;
  certificate?: string;
  declarationLedger?: string;
  runSpec?: string;
}

function parseTrainArgs(raw: string): TrainArgs {
  const tokens = raw.trim() === "" ? [] : raw.trim().split(/\s+/);
  const parsed: TrainArgs = { execute: false };
  const seen = new Set<string>();
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index]!;
    if (seen.has(token)) throw new Error(`duplicate train option: ${token}`);
    seen.add(token);
    if (token === "--execute") {
      parsed.execute = true;
      continue;
    }
    const value = tokens[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`missing value for ${token}`);
    index += 1;
    if (token === "--certificate") parsed.certificate = value;
    else if (token === "--declaration-ledger") parsed.declarationLedger = value;
    else if (token === "--run-spec") parsed.runSpec = value;
    else throw new Error(`unknown train option: ${token}`);
  }
  if (!parsed.execute && (parsed.certificate || parsed.declarationLedger || parsed.runSpec)) {
    throw new Error("authority paths require --execute");
  }
  if (parsed.execute && (!parsed.certificate || !parsed.declarationLedger || !parsed.runSpec)) {
    throw new Error(
      "usage: /train --execute --certificate [path] --declaration-ledger [path] --run-spec [path]",
    );
  }
  return parsed;
}
```

Run the launch-packet preflight before the certified consumer. Preserve the old
message when `execute === false`. When true, call only:

```typescript
runCertifiedLaunch(pythonBin, [
  certifiedLaunchScriptPath,
  "--root", repoRoot,
  "--certificate", parsed.certificate!,
  "--declaration-ledger", parsed.declarationLedger!,
  "--run-spec", parsed.runSpec!,
]);
```

- [ ] **Step 5: Run focused Bun tests and verify GREEN**

Run:

```text
bun test tools/ember-cli/src/commands/train.test.ts
```

Expected: every legacy preflight test and every new execution test passes.

- [ ] **Step 6: Commit**

```text
git add tools/ember-cli/src/commands/train.ts tools/ember-cli/src/commands/train.test.ts
git commit -m "feat: route certified training through ember cli"
```

---

### Task 4: Cross-layer fail-closed replay

**Files:**
- Modify: `tests/ember_restart_model/test_certified_train_launch.py`
- Modify only if a real defect is reproduced:
  `tools/ember-restart-3b/certified_train_launch.py`
  or `tools/ember-cli/src/commands/train.ts`

**Interfaces:**
- Consumes: built Ember CLI command plus Python consumer fixtures.
- Produces: one CPU-only proof that the TS boundary cannot bypass Python
  certificate/scope validation.

- [ ] **Step 1: Add a CLI-process fixture test**

Create a temporary B7/B6/ledger/run-spec bundle and invoke the certified Python
consumer as a subprocess with a fake injected disk runner or a validation-only
flag available only through dependency injection in the test process. Assert:

```python
self.assertEqual(result.returncode, 2)
self.assertIn("scope exceeds certificate", result.stdout + result.stderr)
self.assertFalse(runner_marker.exists())
```

The tested run spec requests two active experts against a one-expert
certificate.

- [ ] **Step 2: Run the Python and Bun focused suites**

```text
python -m unittest tests.ember_restart_model.test_certified_train_launch
bun test tools/ember-cli/src/commands/train.test.ts
```

Expected: both pass; no disk-runner/GPU process starts.

- [ ] **Step 3: Run adjacent runner and CLI registry tests**

```text
python -m unittest tests.ember_restart_model.test_runner_preflight
bun test tools/ember-cli/src/command-registry.test.ts tools/ember-cli/src/services/slash-dispatch.test.ts
```

Expected: pass. If a named file does not exist, use `rg --files` to select the
existing focused registry/dispatch test file; do not broaden to unrelated UI
tests.

- [ ] **Step 4: Commit only a reproduced repair**

If Step 2 or 3 exposes a production defect, add one RED reproducer, make the
smallest fix, rerun the named suite, and commit:

Stage only the exact changed files:

```text
git add tests/ember_restart_model/test_certified_train_launch.py tools/ember-restart-3b/certified_train_launch.py tools/ember-cli/src/commands/train.ts tools/ember-cli/src/commands/train.test.ts
git commit -m "fix: close certified train integration gap"
```

If no defect is exposed, create no empty commit.

---

### Task 5: Independent review and guarded publication

**Files:**
- Verify: all files changed since design commit `5e8fa02`
- Update: `docs/superpowers/specs/2026-07-23-certified-train-executor-design.md`
  only if implementation materially differs.

**Interfaces:**
- Consumes: complete branch diff and focused receipts.
- Produces: reviewable public PR; no merge or GPU launch implied.

- [ ] **Step 1: Verify the exact branch**

Run:

```text
git diff --check 2efc67e1e493b361c4c32817a3f5f9d16caa533c..HEAD
python -m unittest tests.ember_restart_model.test_certified_train_launch
bun test tools/ember-cli/src/commands/train.test.ts
python tools/repo_guard.py
```

Expected: all pass. Record exact counts and command outputs.

- [ ] **Step 2: Run a negative no-certificate CLI smoke**

Invoke `/train --execute` through the existing slash-dispatch test surface with
no certificate inputs.

Expected: nonzero result, exact usage error, zero certified-consumer spawn,
zero disk-runner spawn, and zero GPU process.

- [ ] **Step 3: Request independent schema refutation**

Give the exact immutable head to the delegated authority reviewer. Require review of:

- declaration-ledger membership;
- current-master and supersession checks;
- raw-B6 substitution;
- scope-subsumption across mode, experts, records, and all budgets;
- fixed argv/no shell;
- no capability claim.

Any rejection requires one exact RED and a bounded repair commit.

- [ ] **Step 4: Push and open one narrow PR**

Use the safe GitHub wrappers. PR title:

```text
Make Ember CLI the certified canary executor
```

The body must state:

- executor remains fail-closed until a real B7 declared certificate exists;
- implementation dispatched no GPU work;
- initial scope is bounded canary only;
- semantic/sustained training remains refused;
- exact tests and claim limits.

- [ ] **Step 5: Stop at review-ready**

Do not merge and do not launch the canary from this task increment. Merge
requires exact-head independent review. GPU launch still requires a real B7
declaration, a subset run spec, all CPU/disk/GPU preflights, and a new explicit
delegated-authority launch ruling on those exact bytes.

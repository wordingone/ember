# Issue 1296 Fresh-Genesis Launch Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CPU-only, validated R1 WARM-100 launch packet that is ready for compute without executing compute.

**Architecture:** A new packet builder composes existing R1-entry, text-authority, and certified-launch validators. It stages a canonical external custody packet, asks the certified consumer to reopen it and derive argv, emits a self-hashed PREP-only manifest, then atomically promotes the packet.

**Tech Stack:** Python 3, pytest, existing Ember restart contract and certified launch modules.

**Spec:** `docs/domains/governance/ember-restart/issue1296-fresh-genesis-launch-packet-design.md`

## Global Constraints

- CPU-only preparation: never call `execute_validated_launch` or spawn a training process.
- R1 is exactly WARM-100 from clean genesis; no resume keys are permitted.
- The text authority must be reopened by the existing validator and return `VERIFIED`.
- The emitted packet remains `READY_FOR_COMPUTE`, with execution/result/capability/benchmark credit all false.
- Packet telemetry and generated artifacts stay below the supplied custody root.

---

### Task 1: Packet contract and genuine RED

**Files:**
- Create: `tests/ember_restart/test_r1_launch_packet.py`
- Create: `src/ember/governance/scripts/ember_restart/r1_launch_packet.py`

**Interfaces:**
- Consumes: validated R1 receipt, governed manifest, certified declaration packet inputs, text-lab authority, stream paths, and custody roots.
- Produces: `build_ready_for_compute_packet(...) -> dict[str, Any]` and a canonical five-file launch-authority packet plus self-hashed readiness manifest.

- [ ] **Step 1: Write a positive consumer-level test**

  Construct a hermetic source authority and certified-launch fixture, call the wished-for builder API, then independently call `validate_certified_request` and `build_runner_argv` on the emitted packet. Assert exactly 100 steps, no resume keys, telemetry under custody, current authority hashes, CLI-to-Lab argv, E1-E8 bindings, and false execution/result claims.

- [ ] **Step 2: Run the focused test and verify RED**

  Run `pytest -q tests/ember_restart/test_r1_launch_packet.py` through the repository hidden-Python wrapper. Expected: collection failure because `src.ember.governance.scripts.ember_restart.r1_launch_packet` does not exist.

- [ ] **Step 3: Implement the minimal builder**

  Reuse the existing validator modules and their custody schema constants. Stage, validate, derive argv, self-hash the manifest, and atomically promote. Do not execute the returned launch.

- [ ] **Step 4: Run the focused test and verify GREEN**

  Run the same focused test. Expected: all tests pass and the independent certified consumer returns the same argv stored in the manifest.

### Task 2: Refusal cases

**Files:**
- Modify: `tests/ember_restart/test_r1_launch_packet.py`
- Modify: `src/ember/governance/scripts/ember_restart/r1_launch_packet.py`

**Interfaces:**
- Consumes: the Task 1 builder.
- Produces: fail-closed behavior for authority drift, claim widening, path escape, and continuation attempts.

- [ ] **Step 1: Add one parameterized refusal test**

  Mutate the text authority, R1 result/claim boundary, telemetry root, and run-spec extras independently and assert a stable `ValueError` before promotion.

- [ ] **Step 2: Verify each mutation fails for the named reason**

  Run the parameterized test before each corresponding implementation guard.

- [ ] **Step 3: Add only the minimal guard needed for each RED**

  Prefer the existing downstream validator's refusal. Add local guards only for constraints that must hold before writing or that the downstream consumer does not own.

- [ ] **Step 4: Re-run focused tests**

  Expected: all packet tests pass with no training subprocess invoked.

### Task 3: Verification

**Files:**
- Verify only the four intended design, plan, test, and builder paths.

- [ ] **Step 1: Compile changed Python sources**

  Use the hidden-Python wrapper to compile the builder and test source without writing bytecode.

- [ ] **Step 2: Run focused and adjacent tests**

  Run the packet test, contract tests, and certified-launch semantic-canary tests.

- [ ] **Step 3: Run diff and whitespace checks**

  Confirm the worktree contains only intended paths and `git diff --check` is clean.

- [ ] **Step 4: Report without publication**

  Return exact base, worktree path, file hashes, test counts, and blockers. Do not stage, commit, push, or open a pull request.

# Owned Process Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure local Ember verification cannot leave descendant processes running after timeout, completion, or Windows controller exit.

**Architecture:** A platform-neutral Python runner delegates containment to Windows Job Objects or POSIX process groups. The existing supervision gate and future agents invoke this one boundary with finite timeouts.

**Tech Stack:** Python 3.12 standard library, `ctypes` Win32 API, `subprocess`, `unittest`-style executable selftests.

## Global Constraints

- Fail closed if Windows Job Object creation, configuration, or assignment fails.
- Preserve command output and root exit code on normal completion.
- Terminate descendants on timeout and after root completion.
- Do not claim POSIX controller-crash parity without a host-specific proof.
- No new dependency and no model, training, GPU, checkpoint, capability, or milestone claim.

---

### Task 1: Reproduce descendant survival

**Files:**
- Modify: `src/ember/governance/scripts/ember_gate_process_supervision_selftest.py`

- [ ] Add a child/grandchild fixture and assert the grandchild is gone after timeout.
- [ ] Run `python -B src/ember/governance/scripts/ember_gate_process_supervision_selftest.py` and confirm the assertion fails because the grandchild remains alive.

### Task 2: Implement the owned runner

**Files:**
- Create: `src/ember/governance/scripts/owned_process.py`
- Modify: `src/ember/governance/scripts/ember_gate_process_supervision.py`
- Test: `src/ember/governance/scripts/ember_gate_process_supervision_selftest.py`

- [ ] Implement the closed result and containment-error types.
- [ ] Implement Windows Job Object ownership and POSIX process-group cleanup.
- [ ] Route the existing gate through `OwnedProcessRunner`.
- [ ] Run the focused selftest and confirm it passes.

### Task 3: Bind future automation hygiene

**Files:**
- Modify: `AGENTS.md`
- Modify: `tools/ember-cli/src/package.json`

- [ ] Require finite-timeout owned execution for automated descendant-producing commands.
- [ ] Route the package test script through `src/ember/governance/scripts/owned_process.py`.
- [ ] Run compile, focused tests, relevant gate tests, and repository guard.
- [ ] Commit, push, open PR, self-review the exact diff, and merge only after required checks pass.

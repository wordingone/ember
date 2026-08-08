# Windows Desktop Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a versioned, hash-admitted per-user Windows Ember installation with stable Desktop and Start Menu shortcuts.

**Architecture:** The existing canonical source launcher gains a prepare-only build mode. A Windows deployment script publishes immutable version directories and closed manifests, while a separate stable installed launcher performs read-only hash admission before execution. Windows shortcut mechanics stay isolated behind PowerShell functions.

**Tech Stack:** PowerShell 5.1, WScript.Shell `.lnk` API, Bun compiled executable metadata, Git source identity, JSON manifests, SHA-256.

## Global Constraints

- Exact issue authority: #1578.
- Per-user writes only; no elevation, registry, service, task, or shell-profile mutation.
- All executable paths admitted by closed manifests and SHA-256 before spawn.
- Repository `Ember.cmd` remains the developer launcher.
- Windows adapter must not become a second model/server/process authority.
- `NO_NEW_PARALLEL_AUTHORITY`.

---

### Task 1: Branded canonical executable

**Files:**
- Create: `tools/ember-cli/src/assets/ember.ico`
- Modify: `tools/ember-cli/src/build-tools/build-cockpit.ts`
- Modify: `tools/ember-cli/src/build-tools/build-cockpit.test.ts`

**Interfaces:**
- Produces: canonical `cockpitCompileArgs()` containing exactly one `--windows-icon` argument bound to the tracked icon.

- [ ] Write a failing build-argument test requiring the tracked icon.
- [ ] Run the focused Bun test and capture the missing-argument RED.
- [ ] Add the tracked icon and minimal build argument.
- [ ] Run the focused test GREEN and verify the ICO header/resolutions.

### Task 2: Prepare-only canonical build

**Files:**
- Modify: `scripts/launch-ember-cli.ps1`
- Modify: `tests/test_ember_root_launcher.py`

**Interfaces:**
- Produces: `scripts/launch-ember-cli.ps1 -PrepareApplicationOnly`, which prints one absolute built executable path and never launches a window.

- [ ] Add a failing source/behavior test for prepare-only mode.
- [ ] Run the focused root-launcher selector and capture RED.
- [ ] Extract the minimum build-return boundary and implement the switch.
- [ ] Run the focused and full root-launcher tests GREEN.

### Task 3: Closed installed-launch admission

**Files:**
- Create: `scripts/launch-installed-ember.ps1`
- Create: `scripts/ember-desktop-deployment-selftest.ps1`

**Interfaces:**
- Produces: `Read-EmberInstalledManifest`, `Resolve-EmberInstalledExecutable`, and CLI launch behavior returning the admitted executable's exit code.

- [ ] Write RED cases for absent launcher, unknown/missing manifest keys, traversal, and SHA tampering.
- [ ] Run the selftest and capture RED.
- [ ] Implement closed manifest parsing, contained path resolution, SHA admission, and exact exit propagation.
- [ ] Run launcher selectors GREEN.

### Task 4: Versioned deployment lifecycle

**Files:**
- Create: `scripts/install-ember-desktop.ps1`
- Modify: `scripts/ember-desktop-deployment-selftest.ps1`

**Interfaces:**
- Produces: `Install`, `Repair`, `Rollback`, and `Uninstall` actions; immutable `version.json`; atomic `current.json`; path-free `install-receipt.json`.

- [ ] Add RED cases for missing deployment entrypoint, interrupted publication, idempotence, rollback authentication, and scoped uninstall.
- [ ] Run selftest and capture RED.
- [ ] Implement source cleanliness/identity, prepare-only build invocation, destination-volume staging, immutable publication, atomic manifest switch, rollback, repair, uninstall, and receipts.
- [ ] Run lifecycle selectors GREEN.

### Task 5: Real Windows shortcut adapter

**Files:**
- Modify: `scripts/install-ember-desktop.ps1`
- Modify: `scripts/ember-desktop-deployment-selftest.ps1`

**Interfaces:**
- Produces: idempotent Desktop and Start Menu `Ember.lnk` files targeting the stable installed launcher with exact target, fixed arguments, working directory, description, and current icon.

- [ ] Add a real WScript.Shell `.lnk` RED/readback selector.
- [ ] Run it and capture RED.
- [ ] Implement temporary shortcut creation, readback verification, and atomic replacement.
- [ ] Run shortcut/lifecycle selftests GREEN.

### Task 6: CI, operator docs, and real installation

**Files:**
- Modify: `.github/workflows/ci-pr.yml`
- Create: `docs/operations/windows-desktop-install.md`
- Modify: `scripts/ember-desktop-deployment-selftest.ps1`

**Interfaces:**
- CI runs the deployment selftest on Windows; operators have exact install/repair/rollback/uninstall commands.

- [ ] Add the Windows CI invocation and documentation.
- [ ] Run PowerShell selftests, root launcher tests, build tests, source compile/parser checks, and diff-check.
- [ ] Build and install exact current branch bytes into the real per-user install root.
- [ ] Verify real Desktop/Start Menu shortcut metadata, manifests, binary SHA, and a bounded launcher smoke.

### Task 7: Publish, review, and integrate

**Files:**
- Modify only files required by review findings.

**Interfaces:**
- Produces: draft PR linked to #1578, exact-head self-review verdict, green required checks, merged PR, closed issue.

- [ ] Commit through normal guards and push through safe wrappers.
- [ ] Open a draft PR with exact base/head, evidence, claim boundary, rollback, and `Closes #1578`.
- [ ] Review exact public bytes; record P0/P1 or PASS.
- [ ] Repair and repeat review if rejected; otherwise mark ready.
- [ ] Wait for fresh required CI/guard, merge with an allowed repository method, and verify #1578 closes.

# Installed Authority Marker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make upgraded installed Ember desktops retain exactly one installer-owned authority marker and launch the admitted executable.

**Architecture:** Preserve the strict source-root resolver. Add a fail-closed legacy-marker migration inside the desktop installer's stable-file publication and prove it through the existing end-to-end deployment self-test.

**Tech Stack:** PowerShell 5.1, Git fixture repository, compiled console fixture, Python owned-process wrapper.

## Global Constraints

- Remove only the exact raw historical UTF-8 installer-owned legacy marker.
- Refuse foreign root `GOAL.md` bytes without altering them.
- Refuse every symlink, junction, or reparse component.
- Require the canonical destination to reopen as an exact regular non-reparse file before legacy deletion.
- Preserve a single launchable authority marker across every failure boundary.
- Do not weaken the exactly-one-authority runtime resolver.
- Do not claim #1251 visual or pointer acceptance from the launcher repair alone.

---

### Task 1: Upgrade migration RED and GREEN

**Files:**
- Modify: `scripts/ember-desktop-deployment-selftest.ps1`
- Modify: `scripts/install-ember-desktop.ps1`

**Interfaces:**
- Consumes: `Install-StableFiles([string]$Root)` and the self-test's real `Invoke-Deploy` boundary.
- Produces: an upgraded install containing only `docs/domains/governance/authority/GOAL.md`, or a refused install that preserves foreign root marker bytes.

- [ ] **Step 1: Write the failing upgrade tests**

Before the first install, create the exact legacy root marker and assert a successful install removes it while preserving the canonical marker and launcher exit behavior. Add foreign text, UTF-16 matching text, junction-root, canonical-directory, canonical-parent-junction, later-write failure, and locked-deletion fixtures; each refusal must preserve the original marker bytes, avoid foreign writes, and never leave two markers.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -B src/ember/governance/scripts/owned_process.py --timeout-seconds 180 -- powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/ember-desktop-deployment-selftest.ps1
```

Expected: FAIL because the legacy root marker survives, producing dual authority markers.

- [ ] **Step 3: Implement exact owned-marker migration**

In `Install-StableFiles`, compare root `GOAL.md` as raw bytes against the closed UTF-8 BOM/no-BOM historical set, reject reparse components and non-file canonical destinations, finish other stable writes first, atomically publish and reopen the exact canonical bytes, remove legacy last, and roll back canonical state if deletion fails.

- [ ] **Step 4: Verify GREEN and guards**

Run the focused self-test, root launcher tests, diff check, authority conservation, and base-qualified repository guard. All must pass.

- [ ] **Step 5: Commit the reviewed repair**

Stage only the design/plan, installer, and deployment self-test paths. Create one guarded commit and obtain independent exact-head review before publication.

### Task 2: Installed runtime acceptance

**Files:**
- Generated external installation: `%LOCALAPPDATA%\Programs\Ember`
- Generated issue custody: `scratch/issue1251`

**Interfaces:**
- Consumes: exact reviewed source commit and canonical `install-ember-desktop.ps1` / desktop shortcut.
- Produces: admitted executable identity plus real Windows Terminal window, geometry, pointer, scroll, and screenshot evidence.

- [ ] **Step 1: Install exact reviewed commit**

Run the canonical installer and verify `current.json`, version record, and executable SHA-256 agree.

- [ ] **Step 2: Launch the real desktop shortcut**

Verify exactly one Ember window survives in Windows Terminal with the required left-half/full-height rectangle and no stale Ember process.

- [ ] **Step 3: Exercise non-scientific UI acceptance**

Capture hover, safe control click, wheel/scroll containment, border continuity, cursor ownership, fixed flame, and terminal cleanup evidence without launching a model or claiming scientific credit.

- [ ] **Step 4: Seal and review the receipt**

Bind commit, executable, host/version, rectangle, actions, frame evidence, screenshots, and no-result boundary. Obtain independent review before public issue closure.

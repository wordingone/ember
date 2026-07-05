# CONTINUITY — the succession map

**Purpose:** if every person and session that currently holds context disappears, this file plus
the repositories must be sufficient for any competent agent or human to continue ember without
mutation, degradation, scope reduction, or silent loss. This is the entry point; it POINTS at
ground truth rather than duplicating it. If this file contradicts a spec, the spec wins — then
fix this file.

**Maintenance contract:** every landing that changes a lane's state updates the Lanes table the
same turn (work-loop rail). A citation in this file that no longer resolves is a defect.

Last verified: 2026-07-05T14:10Z.

**Ported 2026-07-05 from the private lineage** (last private touch 33df343) so the succession map
lives on the public workbench; update same-turn with every lane-state change.

---

## 1. What ember is (60 seconds)

Ember is an attempt to build and PROVE a self-improving, self-hosting training system on one
consumer box, governed by an unfakeable receipts-only evidence system. The binding contract is
`GOAL.md` (this tree). The formal core is the two-law frame (§1b: P1 energy law, P2 growth law,
P2 subordinate to P1) and the BOOTSTRAP_PASS criterion (`docs/spec/math-core-v1.md` §5). Truth
enters the system ONLY through receipts of executed local jobs — never any model's self-report.
The scoreboard is the totality board (§4 conditions, run by
`scripts/ember_totality/ember_totality_spec.py`).

**Read-first order for a successor:** (1) this file; (2) `GOAL.md`; (3)
`docs/spec/conditions-v1.md` — THE condition registry, §4.3 is the authoritative count when any
other document disagrees; (4) `docs/spec/math-core-v1.md`; (5) `docs/conventions/` (operational
discipline, incident-derived); (6) the open issues on the public repo.

## 2. Topology (verified by `git remote -v`, 2026-07-04)

| Tree | Role | origin | other remotes |
|---|---|---|---|
| `<private-contract-tree>` (GOAL.md, docs/spec, board runners, receipts; private origin) | contract/spec repository | the private backup mirror (PRIVATE) | `public` = the public workbench repo |
| `<execution-tree>` (ember-cli, runners, licensed config, models) | execution repository | the private backup mirror (PRIVATE) | — |
| The public workbench repo (GitHub; = remote `public` of this tree) | THE public workbench: ALL issues, ALL PRs, all landings via lane-branch → PR → gate → squash-merge | — | — |
| The private backup mirror (GitHub; = remote `origin` of both trees) | private mirror only; refreshed before destructive ops, synced AFTER public landings; NEVER primary | — | — |

Full topology + cross-tree conventions: `docs/conventions/tree-topology.md`. NOTE: `gh` resolves against `origin` (= the PRIVATE backup) by default — `gh repo set-default` is set to the public workbench in both trees; if issue lookups return wrong/missing content, pass `-R` explicitly (succession-trial finding). Licensed-file rules
(which files may never be cross-tree synced or edited without re-licensing):
`docs/conventions/licensing-bindings.md`.

**Stale-path warning:** any document referencing a legacy converter checkout or WSL-mounted board
root describes a RETIRED layout (verified nonexistent 2026-07-04). The board runs NATIVELY on
Windows from the contract tree: `PYTHONIOENCODING=utf-8 python scripts/ember_totality/ember_totality_spec.py`.
Similarly, condition counts other than `conditions-v1.md §4.3`'s are stale.

## 3. The board — how truth is kept

- Run: Clone the private contract tree; `cd <contract-root> && PYTHONIOENCODING=utf-8 python scripts/ember_totality/ember_totality_spec.py`
  (self-stamps UTC ts; never hand-pass a timestamp — one non-UTC hand stamp already pollutes
  lexical ordering, which is why prior-receipt lookups use mtime).
- Semantics: STATE-conditions are GREEN/RED/UNEVALUABLE; C0/C9/C15 are standing PROCESS-INVARIANTS
  (AUDIT-OK / AUDIT-INCIDENT / AUDIT-PENDING-EPOCH) and NEVER count in completion math. Registry
  drift between the runner's ORDER list and `conditions-v1.md` aborts the whole run BY DESIGN.
- Controls: `scripts/ember_totality/chk_controls/run_controls.py` (POS/NEG fixture matrix against
  the real probes; control author must differ from probe author). Fixtures are identified by
  sentinel timestamps (`20990101…`, `…999901Z`) and paths (`fixtures/`, `scratch/`); some
  condition families ALSO carry an explicit `_synthetic_control_fixture: true` marker
  (C-SURFACE2, C-LEGIB) — but exclusion must never RELY on the marker alone, because two probes
  (C-SCALE, C-E2B) hard-reject marked candidates and their controls are deliberately unmarked.
  Exclude by path+sentinel. (Amended from succession-trial-1's Q7 finding, 2026-07-04.)
- Probe contract: one status line, always exit 0, 180s timeout; receipts under
  `scripts/ember_totality/receipts-totality/`.
- State as of 2026-07-04T14:02Z (`receipts-totality/ember-totality-20260704T140249Z.json`):
  **28/31 state-conditions GREEN + 3 AUDIT-OK; RED = C-SCALE, C-E2B, C-TALLY** (C-TALLY is
  derivative: it recomputes from the board receipt and goes GREEN when the board completes).
- Anti-self-deception: numeric claims in receipts are RE-DERIVED by probes (ratio re-derivation,
  1% tolerance); a periodic adversarial board-integrity audit re-verifies GREEN conditions are
  probe-faithful. It caught two manufactured-GREEN attempts on 2026-07-04 alone. Any successor
  MUST keep an adversarial audit loop alive; a green board without one drifts to false-GREEN.

## 4. Lanes — exact in-flight state (UPDATE ON EVERY LANDING)

| Lane | State (2026-07-05T08:19Z) | Next action (exact) |
|---|---|---|
| **operator-seat** | #172 FIXED (PR #178, merge 33fb503); operator session #3 pending one cockpit swap; #165 input channel closed-verified; #154 open (standing practice). | Continue session cockpit swap delivery. |
| **cockpit** | flame build (PR #170) live since 2026-07-05 21:28Z; swap delivering the #172 binary in flight. | Gate binary delivery + flamebuild stability surface. |
| **issue hygiene** | #164/#168/#169 closed with verified dispositions; #176 filed (duplicate logo-homescreen.ts copies). | Sweep duplicates per #176 criteria. |
| **W2 decontam** | DOWN (third memory-class death, silent); #174 forensics lane active (probe-174 receipts under goalforge scratch/w2-heldout-run/). | Diagnose memory-class failure; halt W2 until mechanism known. |
| **research queue #155** | leg-1 attempt REJECTED (PR #177, fabricated receipt); re-dispatch pending under hardened telemetry rails (see #175 amendment). | Gate #175 hardening; queue re-dispatch. |
| **board** | 29-GREEN / 2-AUDIT-OK / 1-AUDIT-INCIDENT / 6-RED per ember-totality-20260705T081932Z; the 15xxZ receipts are port-parity artifacts. | Audit the AUDIT-INCIDENT row; certify parity. |
| **W2 G-arm** | #113 frozen spec filed; CPU dry-run lane pending dispatch. | Dispatch dry-run via builder; scope gate on cost before GPU leg. |

## 5. Pre-registrations and standing rulings that BIND future claims

- **W1 outcomes:** L1 (collapse confirmed) / L2 (budget-exhausted bound, ceiling 2× grow-arm
  bill) / L3 (collapse refuted) all land as publishable truth. The old optimizer/MTP confirmation
  hedges are RESOLVED by the full-production-recipe redirect (#82, 2026-07-04).
- **Borrowed-base trap:** no 27B/borrowed-base result is ever C-SCALE/apex evidence
  (`docs/c-scale-execution-graph.md`).
- **C0 anti-laundering:** board claims need fresh post-epoch gate substance, not June-vintage runs.
- **No board condition may require operator action** (operator directive, via #88). Any
  human-attestation-shaped condition is an illegal shape; re-spec to system properties.
- **Attestation freeze:** verification-claim fields are never rewritten to "correctly recomputed"
  values; broken attestations ship honestly RED with disclosure.
- **BOOTSTRAP_PASS non-equivalence:** average gain, same-surface gain, or a single passing episode
  NEVER imply it (math-core §5c). B0 GREEN grants no capability claim; B1/B2/B3 are ABSENT.
- **Experience gate for user-facing surfaces:** condition-GREEN ≠ delivered; deliverables are
  experienced as the recipient against a FIELD exemplar (never self-authored mocks) at the
  operator's real viewport, with a written wince-list.

## 6. Operational discipline (the codex — each doc carries its incident)

`docs/conventions/`: `tree-topology.md`, `licensing-bindings.md` (more being added; a convention
that exists only as behavior is a defect — write it when you meet it). Until then, the
load-bearing set, compressed:

1. **Interlocks (fail-closed, all required):** `EMBER_GATE_AUTHORIZED=1` env + `--live` flag on
   every real runner; W1 additionally `EMBER_W1_MAINTAINER_WINDOW_CONFIRMED=1`; S3 producer
   additionally `--device cuda`; MC runner additionally `EMBER_S3_MATCHED_CONTINUATION_CONFIRMED=1`;
   `timeshare_pretrain --live` additionally requires ALL G-rows green in
   `v0_pretrain_launch_gate.gate()` (including the config-sha licensing row).
2. **Governor:** VRAM fraction 0.80 + ≥4GB margin asserted BEFORE load; commit-margin preflight
   (`COMMIT_MARGIN_REFUSED`) before any big mmap; box ceiling 79.6GB commit (64GB RAM + 16GB fixed
   pagefile); ONE model resident at a time; orphan-process sweep before >10GB-commit launches;
   fix-forward after a headroom violation is BANNED (kill + relaunch governed).
3. **Gate discipline (maintainer):** never accept a builder's self-report — re-run the producer,
   re-run the selftest TWICE (hermeticity), reject with named defects; any "live GPU leg" claim is
   re-run to its FIRST REAL-INPUT ASSERTION before certification (two falsely-live receipts in one
   day prove why).
4. **Builder protocol:** frozen spec in a public issue → cheap builder (never frontier-class by
   default) → deliverable + receipts back → maintainer gates → maintainer lands via PR. Builders
   never commit; delegation blocks (built_by/verified_by) required in process receipts.
5. **Git:** explicit pathspecs only in shared checkouts (never `add -A`/`-a`); wip-anchor snapshot
   before destructive ops; leak-gate scans added lines (identity/lineage terms) — never
   `--no-verify`; adversarial/red-team agents get read-only tools + sandbox copies ONLY.
6. **Receipts:** sha256 over raw on-disk bytes; citation chains pin path AND content hash — verify
   the hash against current bytes, not path existence; receipt EXISTENCE is proof only when the
   producer writes receipts solely after full assertion pass (r3 pattern).

## 7. The operator interface (what the operator role supplies)

Operator-class decisions: goal/scope/priority changes, retiring or weakening any condition
(§12 amendment protocol + acceptance objects), the safety escalation set (money, cloud, new
hardware, >100GB disk, anything leaving the machine). Everything else is the maintainer's to
derive and execute. Standing operator verdicts a successor inherits: receipts-only truth;
never reduce scope (only the operator does); public repo is the workbench; better-by-wide-margin
(parity with a baseline is a floor, not a target); no personal names in git-tracked or public
artifacts; visible living system (the running product on screen is the deliverable, board rows
are accounting); nothing user-gated may silently rot — when the operator is absent ≥5 minutes,
act as the best version of the operator, date the decision, keep it reversible.

## 8. Environment (verified 2026-07-04)

Windows 11 native (no WSL required for the board or runners). Python 3.10.11; torch 2.10.0+cu126;
transformers 5.8.0.dev0 (DEV pin — behavior may drift on upgrade, re-run controls after ANY bump);
bitsandbytes 0.49.1; peft 0.18.1; bun for `tools/ember-cli`; `gh` authenticated. 24GB-class GPU;
`PYTHONIOENCODING=utf-8` on every board invocation. Model artifacts: Qwen3.6-27B
(bf16, 15 shards) + Qwen3.6-27B-nf4 (prequant, 4 shards + convert receipt) held in local models dir. Corpus:
26 shards, 6.98B tokens, sha-pinned by the corpus-verification receipt, held in local corpus dir.

## 9. Loops that must stay alive (they do NOT survive a session)

The work loop (hourly REVIEW+AUTHOR ticks), the board-integrity audit, and any monitors are
SESSION-STATE — they die with the session and must be re-armed. A successor without the private
operational state can reconstruct them from this section: REVIEW = harvest builder reports,
re-run receipts yourself, gate/reject with named defects, land via PR; AUTHOR = frame → decompose
→ frozen-spec issues on the public repo → dispatch cheap builders; AUDIT = adversarially
re-verify GREEN conditions are probe-faithful, on a cadence. Idle is a defect; status-only ticks
are a defect.

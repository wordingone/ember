# sp-5 — NC-K harness: avir-cli clean-room port spec v0 (Closes #257)

Goal clause (user /goal 2026-06-12, verbatim in GOAL.md): "avir-cli must be
clean room ported as ember's visible harness and interface, and ember must be
resident and fully communicatable with via mailbox and me or you also able to
communicate and interact via computer use."

This spec is the clean-room boundary document: the port is written FRESH
against this spec. It binds WHAT the harness must do; the heartbeat-runner
spec (#254, docs/heartbeat-runner-spec-v0.md) is the execution-side seed for
HOW the inner run-loop breathes.

## 1. Clean-room rule (binding)

- No avir-cli source code enters the port tree — not copied, not adapted, not
  "referenced while writing." The port implementer works from THIS spec only.
- This spec was authored from avir-cli's observable behavior and the goal's
  named invariant classes (process supervision, hooks, tool dispatch, state
  persistence) — it contains no avir-cli code.
- Provenance receipt required at port PR time: tree-level attestation that no
  file derives from `B:/M/avir-cli` (path-disjoint diff base + reviewer
  check; deterministic: grep for avir-cli-unique identifiers = empty).

## 2. Resident form

Ember's harness is an EVENT-DRIVEN PERPETUAL RESIDENT (goal: constant
thinking, episodic depth — never a request-response REPL):

- **Event sources (in):** mailbox signal file; filesystem watches on its own
  state + receipts dirs; job-receipt arrivals from the train daemon; a
  schedule (cron-class timers); console input (CU surface, §4).
- **Emission (out, selective):** mailbox sends; receipts (jsonl, every
  action); state-file transitions; console output. Thinking length ≠ thinking
  quality — effort scales with event difficulty (goal annex).
- **Residency budget:** small footprint, CPU-viable idle loop, GPU only via
  governed bounded bursts. The resident NEVER holds the GPU between bursts
  (governor + headroom rule are un-removable, §5).

## 3. Harness invariants (the port must implement ALL)

1. **Process supervision.** Child jobs (sampling, training, eval) are
   spawned governed, monitored, and reaped — no orphans, no zombie handles
   (the avir-cli Job-Object lesson, generalized: every child runs inside a
   kill-safe supervision boundary; native process creation, never bash-fork
   into WSL2 [cygheap precedent]).
2. **Hook points.** Pre/post tool-dispatch, on-stop, on-session-start —
   deterministic scripts, exit-code blocking semantics (the proven CC hook
   model). Hooks are config, not code edits.
3. **One uniform tool interface.** Every capability implements: name, typed
   input schema, async call, safety predicates (concurrency-safe?,
   read-only?, permission class). Name-based dispatch over ONE registry; no
   special execution paths (nck-invariant-contract-v0 §5 verbatim carry).
4. **State persistence.** Append-only ledgers (episodes, receipts) +
   explicit state files; crash-safe (atomic writes, resume from last good);
   cross-session continuity is a FEATURE REQUIREMENT, not an accident.
5. **Self-edit behind the gate.** The harness is version-controlled; ember
   edits it ONLY via branch → receipts (test suite + invariant checks) →
   promote-on-green; deletion test applies (goal HARNESS=ORGAN annex; DGM
   precedent).

## 4. Communicability (binding — both channels)

- **Mailbox:** ember gets a founders.yaml identity (`ember`). The user and
  Leo mail it; it mails back. Signal-file wiring identical to founders.
  (infra/ change — cross-founder coordination, Eli executes.)
- **Computer use:** ember's visible interface is a console session that
  accepts injected text lines (founder-poke / WriteConsoleInput compatible)
  and renders its output as text — so the user AND Leo can drive it exactly
  like a founder pane. No GUI dependency; text-first per the CU rules.

## 5. Un-removable invariants (OUTSIDE ember's write surface)

Held in protected paths ember cannot write, enforced by boot-time checksum
(port refuses to start on mismatch): (1) three-test gain gate; (2) resource
governor + headroom rule; (3) GOAL.md + only-the-user-retires-it; (4)
receipts-only truth; (5) this enforcement layer itself. (Goal verbatim list.)

## 6. Eval-through-harness (milestone hook)

The founder-likeness leg of the E2B-SURPASS MILESTONE is evaluated THROUGH
this harness: paired protocol swaps the core (ember-core vs local Gemma E2B)
under the IDENTICAL harness, same event stream replay, same budgets —
measures: event-response correctness, initiated-work completion w/ receipts,
mail answer quality, schedule adherence. fp-33 freezes the paired protocol;
this spec fixes the surface it runs on.

## 7. Successor eng issues (mint on merge)

a) ember mailbox identity: founders.yaml + signal wiring [eng, infra-coupled];
b) resident event-loop skeleton implementing §2-§3 with a stub core [eng];
c) protected-invariant boot-checksum layer per §5 [eng+logic];
d) CU console surface per §4 [eng].
Sequenced AFTER fp-33 legs; none take the GPU.

## Selftest

`scripts/sp5_spec_selftest.py` asserts every goal-clause noun maps to a
section: clean-room/port (§1), resident (§2), mailbox (§4), computer use
(§4), harness/interface (§3), invariants-protected (§5), milestone-eval (§6),
successors (§7). Run receipt in the PR body.

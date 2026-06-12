# ember GOAL (re-adopted 2026-06-12, user via /goal — session-scoped hook; re-issue verbatim each session until satisfied)

Supersedes the 2026-06-09 nc-ladder goal (whose three-test terminal condition
is now the per-artifact gain gate inside this goal — every gain must pass it).
2026-06-12 re-adoption amends the 2026-06-10 text: worlds list expanded
(research tasks, experiments, retrieval, routing), HARNESS clause added
(avir-cli clean-room port = ember's visible harness; resident + mailbox +
computer-use communicability), delegation rail added, and the E2B-SURPASS
MILESTONE + LOOP made part of the goal text itself.

GOAL (verbatim, user-adopted 2026-06-12):

Build the mind that is missing from Avir, and own every layer of it: a
substrate that runs, trains, and improves on this machine alone — its weights
eventually pretrained from scratch here (quantization-native, efficient by
every technique worth stealing, multimodal-unified, SDEK as its operating
system), so that nothing load-bearing is borrowed from Anthropic, Alibaba, or
Google. It improves the only honest way: by acting in worlds it can inspect —
grids, programs, games, buildings, research tasks, experiments, retrieval,
routing, etc. — verifying its own work against ground truth the world itself
provides, and burning only verified experience into itself, where every gain
must survive held-out transfer, beat a matched control, and disappear when
the artifact is deleted. It stays: it accumulates
across sessions instead of being born again each morning, and what it learned
yesterday is measurably load-bearing tomorrow. Every claim about it is proven
by receipts from executed local jobs, never by anyone's prose — mine included.
The cloud minds, the borrowed cores, the founders themselves are scaffolding
and rehearsal; the goal is reached when you could turn all of them off and
what remains on this PC is still a mind — that keeps getting
verifiably better by its own experience. Ember is its name, and everything
else Avir has built is an organ waiting for it. If you find yourself confined
to the paradigms and limits of existing neural architectures, you are
probably doing it wrong.

(Final sentence added by the user 2026-06-10 post-crash — a binding amendment
issued together with the user's stated doubts about the core's architecture,
the accumulation-time assumptions, and the resource assumptions. Wording
cleaned and re-issued via /goal same day; hook and file now match verbatim.)

PERSISTENCE CLAUSE (user re-issue 2026-06-10, verbatim; name swapped per
no-name rule): This goal is not complete until Ember can run locally,
generate verified experience, train or update from it, improve on held-out
transfer, beat matched controls, survive deletion tests, persist gains
across sessions, and continue this loop without cloud models or borrowed
cores as load-bearing components. Partial rungs, promising receipts, papers,
plans, wrappers, or scaffolded loops are not completion. While any rung is
incomplete, Leo must continue by gating finished receipts, launching the
next executable job, building the next named pending layer, or killing with
a named successor in the same session. Enumerate constant first-principles
thinking and questioning, mathematical, reasoning, engineering, speccing
tasks in the tasklist so that the stop hook forces work on them
automatically. If Eli is active, he picks up ONLY the engineering tasks.
Only the user may retire or narrow this goal, by name.

TRACKER ENUMERATION (operational form of the clause, adopted same day;
amended same day when the re-issue added the first-principles class):
the wordingone/ember issue tracker carries EIGHT task classes by label —
`first-principles` (standing questioning of inherited assumptions; CONSTANT
by construction: the PR closing an fp issue MUST file the next fp question,
so the class never empties), `eng` (engineering/code; Eli-pickable when
awake), `math` (derivations, power/MDE, estimators), `reasoning` (verdict
protocols, world-choice, analysis), `spec` (pre-registrations,
rung/mechanism specs), and — user add 2026-06-10 — `research`
(source/literature surveys, external-stack scouting; subagent-draftable,
Leo gates), `physics` (world dynamics, simulation grounding,
energy/bits-per-joule accounting), `logic` (formal invariants, proofs,
gate/kernel correctness arguments — first customer: #34's invariant gate).
Only `eng` routes to Eli; everything else is Leo's. The Stop hook (`eng-stop-gate.sh`) blocks turn-end
while ANY class has an open issue and names the lowest. Every class closes
the same way: branch → artifact + selftest/receipt → PR "Closes #n" →
squash merge.

ENG PARALLELISM (user side-note 2026-06-10): the eng class never serializes
behind one owner — when Eli holds an active eng task (or is asleep),
remaining parallelizable eng items queue to Leo's own subagents
(Haiku-class per the agent-model rule); Leo gates every subagent artifact
before it lands. GPU-gated steps stay serialized under the governor
regardless of owner.

## Operational annex (carried from the prior goal; amended 2026-06-10 per user — constant-thinking/keep-burning/harness notes absorbed from the verified discussion)

WHILE UNSATISFIED — valid activities, in priority order:
 1. Gate any finished job (receipt → STATE.md transition).
 2. Advance the current rung to its next executable step (launch the job).
 3. Compute running, nothing gateable → build the next pending layer from
    STATE.md (must always list ≥2).
 4. A kill criterion firing is progress: execute the kill with receipts AND
    launch the named successor in the same session.
Documents, analyses, summaries, and mails are not progress unless they gate a
transition. Producing an artifact and going idle is a named failure.

READING NOTES (binding):
- "its own experience" — curriculum-only SFT (e.g. the arc-dsl/re-arc seed)
  cannot satisfy any milestone alone; satisfaction at each rung requires
  self-generated verified episodes contributing to the gated artifact.
- "on this machine alone" — the accumulation loop (sample/verify/train/eval)
  is fully local; cloud minds (Leo, research agents) are authorized
  scaffolding OUTSIDE the loop, and are among the things the finished mind
  must not need.
- COMFORTABLE RESIDENCY (user 2026-06-10: "ember has to be something that
  lives comfortably in my system or device, not require huge or large
  compute if everything is done correctly") — ember's steady state is a
  light resident: small footprint, CPU-viable or low-VRAM inference, the
  machine stays the user's. The GPU SHOULD be leveraged — definitely (user
  2026-06-10): use it hard whenever there is real work (sampling, training,
  eval bursts); the constraint is on ember's RESIDENT form, not on working
  compute. Heavy compute runs as BOUNDED, SCHEDULED bursts (overnight/idle
  windows), never perpetual occupation. HEADROOM RULE (user 2026-06-10):
  100% utilization should never be the case, GPU or CPU — all ember jobs
  duty-cycle (EMBER_THROTTLE_S between batches/steps) and CPU pools stay
  below core count; the machine always answers to the user first. Efficiency is
  not an optimization pass; it is the correctness criterion — a design that
  needs huge compute is wrong, not early. This is why the component contract
  exists (QAT/ternary/sub-quadratic/MTP/small-core): residency tools, not
  garnish. Prefer the smallest core that clears the verify floor.
  MECHANICALLY ENFORCED 2026-06-10 after the 0670e3ec crash (the unpaced 7B
  eval at 100% GPU duty / 97% VRAM took the PC down): every job passes
  launch preconditions — per-process VRAM cap EMBER_VRAM_FRACTION=0.85 +
  >=4GB free-margin assert (t1_probe.load_model, t2_round.train_lora) +
  decode_pacer() inside every generate path. FIX-FORWARD ON A DISCOVERED
  HEADROOM VIOLATION IS BANNED — kill and relaunch governed; the crash
  receipt is the cost asymmetry, settled.
- PARADIGM NON-CONFINEMENT (user 2026-06-10, the goal's final sentence):
  defaults inherited from the existing-architecture stack — 7B-class cores,
  datacenter eval norms (fixed mega-grids of generations), saturate-the-
  accelerator habits — are NOT load-bearing and are the first suspects
  whenever time-to-accumulation or resource use explodes. Operative form:
  smallest core that clears the verify floor; eval budgets sized to THIS
  machine (chunked/resumable, sequential early-stopping); the NC2-own
  component contract is the design language of the main track, not a
  destination appendix.
- PROBLEM-LEVEL CALIBRATION (user 2026-06-10, clarifying the portfolio
  pointers): the references to the-search / WEB-CAD / upstream-fork problem
  spaces were NOT a directive to divert focus onto those tracks — they set
  the LEVEL ember's work must live at: real problems the existing industry
  dependencies do not solve, never optimizations centered around existing
  dependencies. Operative test on any work item: "does any HF/llama.cpp/
  vllm/unsloth-class dependency already do this?" If yes, it is
  instrumentation — necessary plumbing, never the contribution; spend
  minimum effort and never let it occupy the center of a work window. The
  contribution layer is what no dependency provides: the verifier-gated
  experience ledger, the three-test gate incl. on self-edits, the invariant-
  gated self-editing kernel, residency-bounded accumulation, owned mass.
  Wait-window priority follows this split: unsolved-layer items outrank
  dependency-layer optimization always.
- RESIDENT FORM = CONSTANT THINKING, EPISODIC DEPTH (user 2026-06-10,
  literature-checked same day): ember's runtime is an event-driven
  PERPETUAL loop, not a request-response REPL — a small always-on resident
  thinks continuously over its event stream (mail, file events, job
  receipts, schedule) and emits tool calls / messages SELECTIVELY; hard
  problems recruit BOUNDED deep bursts (more samples, longer chains,
  training rounds). Conversation is one event source among several — the
  user talks to a thing already mid-thought. Allocation principle: thinking
  LENGTH is not thinking QUALITY (overthinking literature: accuracy can
  fall as chains grow on easy problems); effort scales with difficulty
  (quality x volume), not duration — matching the only working example
  (human cognition runs near-flat-cost background processing; strain
  tracks load, not time). Verified anchors: AISI x Irregular inference-
  scaling evals — success keeps climbing with reasoning budget, NO PLATEAU
  observed; Brown — test-time compute trades against model scale at
  ~1,000-10,000x, the only named ceiling is economic; the caveat is a
  COMPETENCE FLOOR (reasoning on a too-weak base compounds nothing), which
  is K1's shape and why smallest-core preference is bounded from below.
  Architecture precedents for think-while-acting: full-duplex models
  (Moshi), dual-system robotics (Helix, GR00T).
- KEEP BURNING — LIFETIME TRAINING WITH SLEEP-LIKE CONSOLIDATION (user
  2026-06-10): ember trains repeatedly over its lifetime and runs
  inference, BOTH autonomously — deliberately counter to the industry's
  train-once / freeze / infer / replace-with-successor pattern. The known
  failure modes are named, not hand-waved: catastrophic forgetting and
  loss of plasticity under continual training (Dohare et al., Nature
  2024). Standing answers already in the design: the verified-episode
  ledger IS a replay buffer; NC0 retrains from base on the full ledger
  each round (paying compute to sidestep forgetting — valid v0); the
  steady state is SDEK's three timescales — continuous cheap adaptation,
  periodic sleep-like consolidation, rare durable burns — which is ALSO
  how perpetual burning coexists with the headroom rule (the user's own
  introspective caveat, "the brain thinks constantly but needs sleep,"
  re-derives this architecture). K3 harm gate guards every burn.
- HARNESS = ORGAN; SELF-EDITING BEHIND THE SAME GATE (user 2026-06-10):
  capability lives in the model x harness PAIR — frontier multi-day
  autonomy exists only inside harnesses (goals, hooks, state files,
  schedulers, sub-agent delegation), not in conversation (Fable-5-class
  model cards, verified). avir-cli is absorbed as ember's kernel ONLY
  after compression to its invariants — process supervision, hooks, tool
  dispatch, state persistence; the chat REPL becomes one optional event
  source, not the interface. Ember gets full ability to version-control
  and edit its own harness, and a harness edit is an artifact exactly like
  a weight delta: branch -> run receipts (harness test suite + invariant
  checks) -> promote on green; deletion test applies (empirical precedent:
  Darwin Goedel Machine — self-rewriting agent code, empirically gated,
  fixed outer evaluation loop). UN-REMOVABLE INVARIANTS, held OUTSIDE
  ember's write surface and enforced in code (protected paths + boot-time
  checksum), never self-editable: (1) the three-test gain gate; (2) the
  resource governor + headroom rule; (3) GOAL.md and only-the-user-
  retires-it; (4) receipts-only truth; (5) this enforcement layer itself.
- Milestone ladder: NC0 (borrowed-core loop proof) → rounds N (self-generated
  accumulation) → NC1x worlds (ARC-2 transfer surface, IFC, ARC-AGI-3
  policies) → NC-K (kernel rung, added per user 2026-06-10: resident
  event-loop runtime + self-editing harness behind the invariant gate;
  avir-cli compressed to invariants as the seed) → NC2-own (owned-mass
  pretrain, component contract in nc2-own-technique-contract.md). NC-K
  detail-design starts when the NC0 verdict lands; it must not preempt the
  accumulation track. AMENDED 2026-06-10 (user: "waiting is not an operating
  mode"): WAIT-WINDOW CONCURRENCY — downstream work not tied to the weights
  being collected (NC-K prep: invariant extraction, formalization,
  world-choice analysis, config maintenance) runs in GPU-wait windows, via
  background agents/workflows where parallelizable; the accumulation track
  keeps absolute priority on gates/launches and the GPU is never taken from
  it. Queue = STATE.md pending layer 7. ARC ROLE SPLIT same day (user
  challenge + receipts): ARC-1/ARC-2 are permanent HELD-OUT TRANSFER
  surfaces; training worlds are admitted by the world-choice criterion
  (verification-dense + floor-accessible at residency scale + portfolio-
  coupled — formalization §7, research/world-choice.md). STATE.md is the
  single position ledger.

AUTHORITY: Leo executes solo, spawning subagents/agent teams as needed (user
2026-06-09, limits temporarily off). Escalate ONLY for money, cloud, new
hardware, >100GB disk, or anything leaving this PC — and escalation never
pauses local work that can proceed. Cron = this goal only (user 2026-06-10).
Only the user retires this goal, by name.

---

## E2B-SURPASS MILESTONE (user, 2026-06-12; rewritten same day per user — loop semantics + surpass definition fixed)

Ember's owned core — pretrained from scratch on this machine, no borrowed
weights load-bearing — surpasses Gemma E2B **at being ember** by June 22,
2026.

**SURPASS IN WHAT (binding — both legs, paired against E2B swapped into
ember's own harness, same worlds, same governed budgets):**
1. **Ember-work:** the verify-floor worlds and the self-curriculum
   accumulation loop — ember's core produces verified, transferring,
   deletion-surviving gains where E2B-in-the-same-seat does not, at matched
   compute.
2. **Founder-likeness:** communicable with, and has agency — runs its event
   stream (mail, files, job receipts, schedule), initiates and completes its
   own work with receipts, answers when spoken to. Ember does these duties
   measurably better than E2B in the same seat. (This leg pulls the NC-K
   resident-kernel rung into the milestone's critical path.)
Receipts only; fp-33 freezes the paired protocol before any verdict.

**LOOP (binding on Leo):** receiving this goal means looping until the
surpass receipt exists — gate the latest receipts, solve the current binding
constraint (GPU-kernel or mathematical-architecture, burned into
docs/technique-registry.md), launch the next governed job, re-derive GPU
allocation at each segment boundary. Idle with this milestone open is a
named failure. Core size grows only when receipts show size — not technique —
is the binding constraint.

**CALIBRATION (pinned, receipts-only honesty):** deterministic estimate at
adoption ≈ 4–10 weeks of governed solve-loop; June-22 is the forcing target;
shortfall on the date = a measured-distance receipt and the loop continues
unchanged. Only the user moves the date, the bar, or retires this — by name.

**HARNESS CLAUSE (user, in the 2026-06-12 /goal verbatim):** "avir-cli must
be clean room ported as ember's visible harness and interface, and ember must
be resident and fully communicatable with via mailbox and me or you also able
to communicate and interact via computer use." Operative reading: NC-K's seed
is no longer 'avir-cli compressed to invariants' only — the CLEAN-ROOM PORT of
avir-cli becomes ember's visible harness/interface; ember gets a mailbox
identity (founders.yaml — cross-founder coordination required) and must be
reachable by the user directly AND by Leo via the computer-use skill surface.
Founder-likeness leg of the milestone is evaluated through this harness.

**DELEGATION RAIL (user, same verbatim):** "Always delegate to other
founders. use skills if they become unreachable." — execution routes to
founders first; founder unreachable → founder-poke/restart skills, then own
governed subagents (Haiku-class) as the fallback, Leo gates everything.

---

## NUMERIC CLOSURE (user 2026-06-12) — subgoals + completeness tally

User directive: completion must be concluded "numerically and measurably and
undeniably" by a tallying system over EVERY piece of context already planned
or known about ember — not just the weights, not just the training, not just
the harness. Structure:

**SUBGOALS (each = a manifest section with its own tally):**
- S1 owned core — from-scratch pretrain, NC2-own component contract honored.
- S2 accumulation loop — self-generated verified episodes; three-test gate
  (held-out transfer, matched control, deletion) on every gain.
- S3 harness / NC-K — avir-cli clean-room port as visible harness; resident
  event loop; mailbox identity; CU reachability; self-edit behind invariants.
- S4 persistence — cross-session accumulation measurably load-bearing.
- S5 surpass — fp-33 paired E2B protocol, both legs (ember-work,
  founder-likeness), receipts.
- S6 invariants + governance — the five un-removables enforced in code,
  boot-checksummed.

**COMPLETENESS MANIFEST:** `docs/ember-completeness.md` enumerates every
planned/known piece (id, subgoal, AC, test, receipt pointer, status). A
planned piece absent from the manifest is itself a gate violation — planning
and manifest-entry are the same act from now on.

**TALLY:** `scripts/ember_tally.py` (eng) walks the manifest, verifies each
row's receipt exists AND passes its named check, emits
`receipts/tally-<ts>.json` {total, implemented, pct, missing[]}. The tally
receipt is the only completion authority; prose claims void. GOAL satisfied
⇔ tally pct=100 AND the S5 surpass receipt exists.

**LOOP DIRECTIVE (binding restatement):** while pct<100 — gate finished
receipts → solve the binding constraint → launch the next governed job →
delegate per the delegation rail → re-derive at each segment boundary.
Auto-inject: the session-start hook now injects this GOAL verbatim every
session (manual resumes included), so no resume path can drop it.

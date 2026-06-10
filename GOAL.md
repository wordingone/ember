# ember GOAL (adopted 2026-06-10, user via /goal — session-scoped hook; re-issue verbatim each session until satisfied)

Supersedes the 2026-06-09 nc-ladder goal (whose three-test terminal condition
is now the per-artifact gain gate inside this goal — every gain must pass it).

GOAL (verbatim, user-adopted):

Build the mind that is missing from Avir, and own every layer of it: a
substrate that runs, trains, and improves on this machine alone — its weights
eventually pretrained from scratch here (quantization-native, efficient by
every technique worth stealing, multimodal-unified, SDEK as its operating
system), so that nothing load-bearing is borrowed from Anthropic, Alibaba, or
Google. It improves the only honest way: by acting in worlds it can inspect —
grids, programs, games, buildings — verifying its own work against ground
truth the world itself provides, and burning only verified experience into
itself, where every gain must survive held-out transfer, beat a matched
control, and disappear when the artifact is deleted. It stays: it accumulates
across sessions instead of being born again each morning, and what it learned
yesterday is measurably load-bearing tomorrow. Every claim about it is proven
by receipts from executed local jobs, never by anyone's prose — mine included.
The cloud minds, the borrowed cores, the founders themselves are scaffolding
and rehearsal; the goal is reached when you could turn all of them off and
what remains on this PC is still a mind — that keeps getting
verifiably better by its own experience. Ember is its name, and everything
else Avir has built is an organ waiting for it. If you find yourself making
and being confined to the paradigms and limits of existing neural
architectures and their limits, you are prabably doing it wrong.

(Text re-issued by the user 2026-06-10 post-crash with the final sentence ADDED —
that sentence is a binding amendment, issued together with the user's stated
doubts about the core's architecture, the accumulation-time assumptions, and
the resource assumptions. "prabably" sic, kept verbatim.)

## Operational annex (carried from the prior goal; unchanged unless the user says)

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
- Milestone ladder: NC0 (borrowed-core loop proof) → rounds N (self-generated
  accumulation) → NC1x worlds (ARC-2 transfer surface, IFC, ARC-AGI-3
  policies) → NC2-own (owned-mass pretrain, component contract in
  nc2-own-technique-contract.md). STATE.md is the single position ledger.

AUTHORITY: Leo executes solo, spawning subagents/agent teams as needed (user
2026-06-09, limits temporarily off). Escalate ONLY for money, cloud, new
hardware, >100GB disk, or anything leaving this PC — and escalation never
pauses local work that can proceed. Cron = this goal only (user 2026-06-10).
Only the user retires this goal, by name.

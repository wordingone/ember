# Hardest-problems register v1 (2026-06-12, compiled from user correction 21:07Z)

User, verbatim class: "long jobs should not launch unless a mathematical or
measured proof already shows the path is near-optimized, because otherwise
the job is using scarce wall-clock to discover avoidable inefficiency."

This register exists because the correction was right and the failure was
mine: the live 1B run is the receipt. Each entry = the problem, its PROOF
OBLIGATION (what must exist on disk before resources commit), and honest
status. Ranked by what binds the goal soonest. Rule: an entry leaves this
register only by receipt, never by prose.

## H0 — The local training compute ceiling (user 21:15Z: NO DEFERRAL)

**Problem:** at the measured ceiling (17,899 tok/s paced live config) a
7B-token c03 pretrain costs 3.4–4.5 wall-days — ember gets ~2 iterations
before 06-22 and zero design-space exploration. Everything downstream,
including ember's nature, is gated on shattering this.

**Proof obligation + program:** `docs/compute-ceiling-program-v1.md` —
roofline MFU math, 8-lever stack (each lands by single-variable A/B
receipt), shatter criterion v1 = pretrain-from-scratch ≤1 governed day
(≥3.3× compound, stretch 5×), no-defer rule: ≥1 lever in flight at every
tick until met or all levers receipted-KILLED.

**Status:** OPEN — program active, eli lane #1, first benches in governed
windows beside the live run tonight; 1B-ckpt boundary (~09:00Z) = first
certified-lever entry point via receipted resume decision (user owns).

## H1 — Pre-commitment optimality (the missed requirement; now a gate class)

**Problem:** scarce-resource commitments (GPU wall-clock, founder token
burn, the June-22 window itself) were gated on correctness and safety but
NEVER on a proof of near-optimality. Efficiency ran as a parallel research
track (fp-32/33) instead of a launch precondition.

**The receipt that proves the miss (live 1B run, 12c050e7):**
- B=24 throughput gain was MEASURED pre-launch: 1.345× vs B=4, single
  variable, governor identical (`fp32-step-econ-20260612...T142831Z` vs
  `fp19-bench` anchor, 06-11 14:28Z) — projected −1.157 wall-days.
- The only missing certification was the E1b loss-match pair. Cost of one
  leg at measured paced throughput: 10,485,760 tok ÷ 18,737 tok/s ≈ 9.3 min
  (B=4 leg) + 10.5M ÷ 24,079 ≈ 7.3 min (B=24 leg) + loads — UNDER ONE HOUR
  total. ~10h passed between launch order and dispatch (~01:28Z). The proof
  would have fit; nothing forced the re-derivation; the run now carries a
  known +1.157 wall-days. Return on the skipped proof ≈ 24×.
- The phase profiler (backward 56.5 / forward 20.2 / QAT 12.0 / optimizer
  11.3 GPU shares; optimizer 45.9% of phase wall) ran 03:27Z — TWO HOURS
  AFTER launch. The diagnosis instrument itself was sequenced behind the
  commitment it should have gated.
- Kernel-route candidates at launch: fp8 (later KILLED 0.45×, receipted),
  fused-muon (harness merged, STILL unbenched, #329) — neither receipted
  nor waived at launch time.

**Proof obligation (binding, all future governed jobs projected >12
GPU-hours):** a LAUNCH EFFICIENCY RECEIPT enumerating every known
throughput lever (batch, kernel routes, precision, packing, optimizer) as
receipted-APPLIED / receipted-KILLED / WAIVED-with-priced-cost (wall-days
the waiver burns, signed). A silent lever = launch gate FAIL. Wired as
gate 9 of `v0_pretrain_launch_gate.py` (eng issue minted this turn).
The autonomy clause stays — but a waiver under urgency must still PRICE
the cost it accepts; urgency changes the decision, never the arithmetic.

**Status:** NOT IDENTIFIED until the user named it (21:07Z). Register +
gate-9 issue are the same-turn compile. Live run NOT restarted: a mid-run
B=24 restart is itself an unproven path (E1b evidence still absent; restart
mechanics uncertified) — exactly the class this entry bans.

## H2 — Verified-signal density above the floor (the loop has never closed)

**Problem:** zero positive gain receipts exist across every round to date
(q15 round-1: 0.0% all four arms; 3B ARC: all-zero; W-code floors: 0-2
successes/100). Kai's standing hypothesis — verified signal per GPU-hour is
the deepest bottleneck — is confirmed by measurement, not displaced.

**Proof obligation:** floor-PASS before round dispatch (exists: fp-23/24)
PLUS the eval-reachability constraint the power work exposed: at n=100 and
p0≈2% the round gate cannot see deltas under ~10.2pp (helper receipts
20260612T2106*). A round whose plausible best-case movement is below the
gate's MDE is unfalsifiable BY DESIGN — task difficulty / n / k must be
chosen so the expected gain clears the visible threshold BEFORE dispatch.
This is a design constraint on curriculum, not a stats footnote.

**Status:** instrument fixed (gate-stats-review-v1, helper #346, grid
receipted today). The design-side obligation (curriculum whose deltas are
visible) is OPEN — first test at the 1B checkpoint round-1.

## H3 — Surpass-path schedule arithmetic (S5 by 06-22)

**Problem:** the terminal chain (v0 terminal ~06-16 at B=4 → floor probe →
round-1 → gain rounds → E2B-surpass receipt) has NEVER had end-to-end
schedule math with measured durations. Each leg is receipted somewhere;
the sum is nowhere. If round-1 is FLAT at n=100 (likely under H2), the
confirm leg needs n≥400 (MDE 3.85pp) — eval cost scales, GPU-serial, and
the window may not close by 06-22.

**Proof obligation (MEASURED REWRITE, 3:50 PM LA 06-12 — the promised
schedule-feasibility note; supersedes the skeleton):** the bench receipts
landed and the ARCH kill FIRED: mechanical stack exhausted at 1.85×
bench-path (@9236963), L9 flash dead at projected batches (fp38-l9), and
the production path measured 2× under every bench anchor (fp37-l7-v2;
proxy anchors banned, C-7). The path to 06-22 is now c04-redesign-serial,
five receipt-gated legs with measured-or-priced durations:

1. **Tonight 06-12:** production-path cell = true F (eli, <1h, GO'd
   15078); L9 completion b16/b8-nockpt-flash (<1h).
2. **06-13 AM:** fp-39 recalibration (Leo, mechanical on leg-1 receipts) +
   activation-model refit; density-A/B mix manifests frozen (eli proposes,
   Leo gates); density A/B = 4 cells ≈ 4 governed hours.
3. **06-13:** c04 design + harness build (flash/SDPA module, optimizer
   ≤15% wall, compile-resident, MTP/CE priced — ENG build, the least
   receipted leg: ~1 eli-day, the honest schedule risk) → #353 design
   benches (<1h/cell) → §3 gate: budget/tok_s ≤ 24h on the PRODUCTION
   path, budget per fp-38 row × density verdict.
4. **06-14/15:** IF §3 passes → ONE gate-9-compliant pretrain (≤1 governed
   day). The 614M paid tokens are dead weight (wrong architecture).
5. **06-15/16 → 06-22:** floor probe → round-1 (n=400 class per
   power-helper MDE) → gain rounds: ~6 round-days — survives IFF legs 2-3
   hold their day. Slip >1 day on the c04 build, or a density-A/B verdict
   that no (P,budget) row passes §3, puts S5-by-06-22 mathematically out
   of LOCAL reach → program §4.5 fires: priced scale-out residual to the
   user, never a silently relaxed criterion.

**Status:** ACTIVE — leg 1 in flight; this entry re-prices at every leg
receipt. Owner: Leo, on eli's receipts.

## H4 — O6: verifier-free judgment (formalization open problem)

**Problem:** every gain ember can certify routes through an external
verifier; judgment without one is the unbridged gap to the goal's "mind"
language (self-inventory 2026-06-10, formalization O6).

**Proof obligation:** none exists — that is the point. Candidate attack
surface: calibration-as-skill from the bits account (resolution component),
where a model's own confidence becomes receipt-checkable against held-out
outcomes. No design yet deserves the word.

**Status:** OPEN, untouched, honestly not on the S5 critical path; it is
on the GOAL path. Not scheduled before 06-22; named so the deferral is a
recorded decision, not drift.

## Register discipline

- New hardest-problem candidates enter by receipt of a miss (like H1) or
  by formalization (like O6) — never by mood.
- Every entry's proof obligation must be mechanically checkable; "be more
  careful" is not an obligation.
- The register is reviewed at every verdict-class event; an obligation
  satisfied moves to the gate/spec that now enforces it, with the receipt
  pointer.

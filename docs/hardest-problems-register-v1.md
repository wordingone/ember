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

**Proof obligation:** a receipted schedule-feasibility note — measured leg
durations summed against the calendar, slack quantified, the
first-leg-that-doesn't-fit named — BEFORE the 09:00Z checkpoint fires the
chain. Owner: Leo, tonight. This is H1 applied to the calendar instead of
the GPU.

**Status:** OPEN — minted as the next wait-window artifact.

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

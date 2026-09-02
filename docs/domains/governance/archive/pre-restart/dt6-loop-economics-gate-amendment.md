# DT-6 — Loop-economics gate, made explicit (prereg amendment)

**Status:** authored 2026-06-14 (the lead). Amends the DT-1 delta-rule diagnostic prereg
(`docs/archive/pre-restart/delta-rule-diagnostic-prereg.md`) and binds **all** DT diagnostics, fp/sp gate
verdicts, and the **pretrain readiness gate**. Origin: an agent flag 15051.

## The defect this closes

A diagnostic "PASS" has been read as *"the run completed / the loss went down."* That is
not a PASS — it is **liveness**. Per the goal's verifier-bits objective (formalization
§3b: `B = verified-bits / GPU-hour`) and the standing efficiency-proof rule (runs are
*measurement*, not checkpoints), a PASS is an **economic** statement: the update produced
**more verified signal per GPU-hour than the equal-wall-clock control**. Without that
denominator, "it ran" launders compute as progress — the exact shape of a "half-assed
readiness."

## Binding amendment

1. **PASS criterion (replaces "loss decreased").** A diagnostic / probe / gate verdict may
   assert PASS **only if** it reports a measured **verified-signal-per-GPU-hour** that
   **exceeds the equal-wall-clock band**. The numerator is the diagnostic's own *verified*
   quantity (next-token-loss delta vs base, verified-bits, exact-layer match, …); the
   denominator is GPU-hours (equivalently, matched wall-clock).

2. **The equal-wall-clock band IS the floor.** Every PASS cites a control arm run at
   **matched wall-clock** — the noise-floor / equal-budget run (e.g. fp-44's seed-42/43
   `noise_floor_run` at identical step budget). Signal that does not exceed that band is
   **not** a PASS; it is "within the equal-wall-clock floor" — a *power statement*
   (gate-stats-review-v1), never an effect.

3. **Verdict-prose requirement (deterministic).** Every PASS verdict's receipt MUST carry
   `signal_per_gpu_hour` (or `signal_per_wallclock`), `equal_wallclock_band`, and
   `exceeds_band: true`. A verdict asserting PASS without all three fields is **malformed
   → auto-REJECT** (not a PASS).

4. **Scope.** Binds (a) every DT diagnostic, (b) every fp/sp gate verdict, and
   (c) — load-bearing — the **pretrain readiness gate**: "ember is ready for the first long
   training" is valid only if the readiness probe reports verified-signal-per-GPU-hour above
   the equal-wall-clock band, **never** "the smoke ran clean."

## Selftest / AC (checker spec — eng successor builds `src/ember/governance/scripts/loop_econ_gate.py`)

- **AC1:** a verdict JSON with `"verdict":"PASS"` but MISSING `signal_per_gpu_hour` →
  checker returns REJECT (exit nonzero).
- **AC2:** a verdict with all three fields AND `exceeds_band:true` → ACCEPT (exit 0).
- **AC3:** a verdict with the fields but `signal_per_gpu_hour <= equal_wallclock_band` →
  REJECT-as-"within-floor" (power statement, not PASS).
- Selftest = pure-function checker over the three fixtures; receipt records 3/3.

## Cross-refs

- Formalization §3b (`B = verified-bits/GPU-hour`); standing efficiency-proof rule
  (runs are measurement; >12 GPU-h needs a lever receipt); gate-stats-review-v1
  (equal-wall-clock band, power-floor); fp-44 `noise_floor_run` — the matched-wall-clock
  control is the template for the band.

Per user direction.

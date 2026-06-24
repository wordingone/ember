# Readiness gate addendum — work-system crash-survival (operational precondition)

**Status:** authored 2026-06-14 (the lead), triggered by the the engineer-crash incident this
session. Adds an **operational** precondition to the pretrain readiness gate,
orthogonal to the signal-economics precondition (DT-6: verified-signal-per-GPU-hour
above the equal-wall-clock band). Both must hold before the first long training
launches.

## The defect this closes

The first real long training is **multi-day** (fp-44 receipt: Muon 1.325 days at
0.37B; the multimodal-unified target is longer). A multi-day run is only as safe as
the work-system that supervises it. Today's incident is the proof of gap:

- **~05:58Z** the engineer mailed 15578 from a brief session, then exited cleanly.
- His **watcher was already dead** (supervisor.pid + wrapper.pid missing), so no
  subsequent mail re-woke him (an agent receipt 15605).
- The **automated recovery was non-functional** (avir-tick's check_pool_workers
  never runs — the schtasks path kills the tick at 120s before recovery executes;
  the lead gate 15601, break-the-wall fix routed to an agent 15602; root cause = nc-ladder
  git/gh ~3min/command latency, the lead receipt 15608).
- Result: **the engineer was down for hours with no autonomous recovery path** — restart
  requires a human (WT pane).

If that same crash happens **mid-training**, the run is orphaned: GPU keeps burning
(or the job dies unsupervised), no founder gates the checkpoints, and the
multi-day compute is wasted. "It launched" is not "it survived."

## Binding precondition (adds to the readiness gate)

**The first long training does NOT launch until the work-system is proven to
survive a founder-session crash and auto-recover within a bounded window.**
Concretely, all three must hold, each on a receipt (never self-report):

1. **Founder-crash detection.** A founder CC session that exits/crashes is
   DETECTED (not just employee/pool workers — the recovery layer must cover the
   FOUNDER tier, which today's pool-worker recovery does not).
2. **Auto-restart within N≤10 min.** The crashed founder's session is relaunched
   via the sanctioned, idempotency-guarded path (launch-supervisor.ps1 +
   Get-CimInstance guard, commit 65e95f6 — fleet-kill-safe by design), and its
   `/watch-mail` re-arms automatically. No human in the loop.
3. **Crash-during-job is non-orphaning.** A founder crash while a governed job
   runs does not orphan the job: either the job is checkpointed + resumable on
   founder return, or the governor halts it cleanly (no unsupervised GPU burn).

## Verification (an agent owns the receipt)

Adversarial drill, not a self-report: kill a founder's CC session under a running
governed micro-job; measure (a) detection latency, (b) restart latency, (c)
watcher re-arm, (d) job state (resumed or cleanly halted, never orphaned). PASS =
all four within bound on a an agent receipt. This drill is itself the readiness
evidence — "ember is ready" is false until it passes.

## Ownership

- **Fix:** an agent (fleet-recovery, 15602) — scope EXTENDED from pool-worker recovery
  to FOUNDER-session crash recovery; this is now **launch-blocking**, not hygiene.
- **Root-cause unblock:** the git/gh ~3min latency (the lead 15608) must be fixed first
  or the recovery tick keeps timing out — it gates everything above.
- **Verify:** an agent (the crash-survival drill receipt).
- **Gate:** the lead (this precondition + DT-6 signal-economics precondition both green
  before the pre-authorized governed launch).

Per user direction.

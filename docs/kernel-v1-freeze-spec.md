# Kernel v1.0 freeze spec — what "finished" means, operationally

*2026-06-10. Operationalizes formalization §9b ("the kernel must be FINISHED
once") and the user's directive-class insight: ember needs to be finished in
some fundamental sense that allows everything else to compound. This spec
enumerates exactly WHAT freezes, the closure condition, the freeze procedure,
and the flywheel demonstration protocol. Registry row 14 governs WHEN it
fires (round-1 verdict + schema stability review); this document makes the
firing executable instead of aspirational.*

---

## 1. The freeze surface — what v1.0 closes

The kernel is the set of components whose meaning may not drift while
everything above them churns. Six members:

1. **Verifier semantics (`V`).** Per world: ARC-1 = sandboxed program
   execution against held-back train-pair outputs, byte-exact; W-code/MBPP =
   the task's own asserts in the same sandbox. Frozen: timeout, determinism
   posture (fixed seeds where sampling enters V — none today), and the
   definition `verified := V(artifact, task) = 1`. A change to what counts
   as verified invalidates every ledger entry before it — this is the axiom.
2. **Gate semantics (G1–G3).** G1 held-out transfer (eval split never
   sampled, never trained); G2 matched-control beat (equal-volume
   unverified/failed-program control, identical train budget); G3 deletion
   test (gain disappears when the artifact is deleted — recompile-from-base).
   Frozen: the statistical procedure — paired bootstrap, CI95 excluding 0,
   per-task pairing — not the n or the surfaces, which scale freely.
3. **Ledger contract.** Append-only; entry key `task:sha16(src)`; every entry
   carries an execution receipt reference; identity = the ledger (recompile
   from base + ledger reproduces the artifact — demonstrated 3×: 7B/1.5B/3B
   from one ledger). Frozen: append-only + key schema + receipt-reference
   requirement. Open: field ADDITIONS (additive-only, never reinterpreting
   existing fields).
4. **Receipt schema.** Required: ticket, ts (UTC compact), args fingerprint,
   measured quantities with CIs where statistical. A receipt that cannot be
   replayed against its args is not a receipt.
5. **Invariant set + write surface.** The invariants live OUTSIDE the
   system's write surface (mine and ember's); amendment is user-only. v1.0
   freezes the enforcement mechanism, not the list (the user may extend it).
6. **Resource governor.** VRAM fraction cap + margin assert + decode pacer +
   inter-batch throttle as a kernel obligation on every load/generate path —
   today implemented in `t1_probe.load_model`; freeze-eligible once extracted
   to a module every entry point demonstrably routes through.

## 2. Closure condition

Kernel v1.0 is **closed under reachable actions**: every action the loop can
take — sample, verify, ingest, train, eval, gate, recompile — reaches the
ledger and the verdict surfaces ONLY through the six frozen interfaces. No
script writes episodes except through `V`; no verdict is claimed except
through G1–G3 receipts; no model loads except through the governor. Closure
is checked by audit (grep the call graph), not by trust.

## 3. What is deliberately NOT frozen

Worlds, cores, adapters, harness prompts (δ_H, gated), teacher components,
eval task counts, chunk sizes, schedulers. The kernel is what makes swapping
all of these MEANINGFUL — a new world plugs in a new `V` implementation but
inherits the verified-definition, gate, ledger, receipt, and governor
contracts unchanged.

## 4. Pre-freeze gap list (close before the row-14 fire condition is met)

- **Episode schema unification:** W-code episodes carry `prompt` + `sampler`
  provenance (w2); ARC episodes predate both fields. Additive backfill or
  documented absence — one schema, one renderer (`build_dataset` currently
  branches three ways).
- **Args-fingerprint universality:** chunked harnesses carry it; t2/t5
  receipts don't yet.
- **Governor extraction:** from `t1_probe` into a module with a single
  choke-point import, so closure (§2) is greppable.
- **Replay test:** a `kernel_replay.py` that re-derives one ledger entry's
  verified bit and one gate verdict from raw receipts — the executable
  definition of "replayable."

## 5. Freeze procedure

On fire (registry row 14): (a) tag the kernel files at a commit SHA +
sha256 manifest (`kernel-v1.0.manifest`); (b) any post-freeze kernel change =
version bump (v1.1) requiring user sign-off + a replay test proving old
ledger entries re-verify identically under the new kernel; (c) silent kernel
drift detected by manifest checksum in the Kai audit sweep = gate violation.

## 6. Flywheel demonstration protocol (the completion condition)

§9b: one demonstrated turn, **dF/dround > 0 under frozen kernel**, where
`F` = verified-episodes-per-GPU-hour on the active world's train pool,
measured per round with matched sampling budgets (same task count, k, seeds
across rounds; CI by task-level bootstrap). The control for the turn itself:
round-N adapter must beat round-(N−1) adapter on F under identical budget —
not merely add ledger mass. One such receipt, under a tagged kernel manifest,
is the milestone the whole project's "finished" inversion points at: the
kernel finished once, so that improvement never has to finish.

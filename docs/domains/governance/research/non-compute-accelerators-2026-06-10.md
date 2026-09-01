# Non-compute accelerators (user list, 2026-06-10) — status map + registrations

User named five non-compute accelerators attacking signal quality, iteration
speed, and de-risking the owned core. Verdict per item: what is already live
(with receipts), what is genuinely new, what gets registered.

## 1. Denser verification worlds — LIVE + one NEW registration

Live: the W-code pivot IS this move (feed 86.67%→90% full-pool vs ARC's
≤3% floor — ~2 orders of magnitude more verified episodes per GPU-hour);
MBPP+ extended tests landed tonight (eng #7).

NEW (registered as an ARM of contract row 9, consolidation rule — not a new
row): **per-assert partial credit**. MBPP tasks carry 3+ asserts; the sandbox
currently returns binary verify. Scoring assert-pass FRACTION gives GRPO a
dense reward gradient on exactly the frontier/dead tasks where binary reward
is ~always 0 — the cheapest densification available (sandbox change only,
no new world). Caveat carried: partial credit is a TRAINING signal only;
the gate stays binary verify (G1/feed numbers never soften).

NC1c (IFC world, judge-style checks) stays where the ladder put it: build
on NC0 verdict.

## 2. Mature small-scale pretraining + replay stack — PREP ITEM (wait-window)

BitNet/QAT/Muon/MTP recipe stack for NC2-own. MTP-aux: built tonight
(eng #4, scaffold-head design). Muon: strongest candidate (documented
2× data-efficiency at small scale in public speedruns) — but the
"proven-recipe" discipline from the 7B crash applies: a recipe is proven
only by a LOCAL receipt at the SCALE it claims (the spec-forge recipe was
proven at 3B, imported blind to 7B, crashed the PC). Registered as a
wait-window item: assemble + pin (URL+commit) candidate implementations
(Muon optimizer, BitNet b1.58 training loop, QAT schedule, replay/
consolidation buffer), each with a smoke-scale local validation plan.
No build before the W-code round-1 verdict.

## 3. Hardened verifier + eval suite — LIVE AS OF TONIGHT

eng #7 (MBPP+ ~35× extended tests, local FPR estimator, per-stratum
breakdown, quarantine-by-gate) merged; live FPR run queued behind the
train chain. Verification speed is NOT the bottleneck (CPU sandbox,
parallel); generation is. The FPR receipt closes the V-soundness caveat
with a measured number.

## 4. Parallel non-GPU pipelines — LIVE (standing structures)

Wait-window queue (standing, user-directed), release-scan (registry row
18), eng tracker + stop-gate (10 issues → 8 closed via merged PRs today,
hook-chained), first-principles audit cadence. The accelerant isn't new
machinery — it's that the stop-gate now mechanically prevents idle.

## 5. Reproducible high-leverage recipes — AGREED, with the receipts bar

"Proven implementation" has a project-specific definition: proven = local
receipt at the claimed scale, on this box, under the governor. Anything
short of that is a pinned candidate, not a recipe. Sleep/consolidation
mechanisms route into the round-2 replay-mix arm (anti-forgetting AC);
efficient-multimodal recipes are NC1c/NC2 era — pinned in the prep item
(#2 above), not built now.

## Net registrations from this list

- Row 9 arm: GRPO partial-credit reward variant (per-assert fraction,
  training-only signal).
- Wait-window item: NC2 recipe stack assembly (Muon/BitNet/QAT/replay),
  URL+commit pins + smoke-scale validation plans.
- No new registry rows (consolidation rule held).

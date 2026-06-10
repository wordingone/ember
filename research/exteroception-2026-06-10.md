# Exteroception — how ember finds external updates and absorbs them

*2026-06-10. Source: user thread, refining the research-intake posture question
into its mechanism form: "how does ember find updates in the external world and
how does it absorb it to the benefit of itself?" — with the named pre-ember
precedent: avir-cli's custom WebSearch/WebFetch, custom because CC's versions
are server-side. Companion to the intake-posture section of
`nc2-own-technique-contract.md` (the governance layer); this note is the organ
layer.*

---

## 1. The formal move: the web is verification-sparse

A world admits episodes because it has a cheap, world-grounded verifier. The
open web has none — there is no `V` for "this paper's claim is true." So
**nothing external enters ember as an episode directly.** Absorption is
*transduction*: an external claim becomes a typed candidate, the candidate
becomes a locally executable probe, the probe produces a receipt, and the
receipt feeds the gate. **The probe is the digestion.** "Muon is 2× efficient"
cannot be verified as text; a 124M pilot under Muon on this machine can be
measured. Ember never absorbs prose into weights — it absorbs measured deltas.

## 2. The pipeline: sense → triage → digest → probe → gate

**SENSE — owned, client-side discovery.** Standing sweeps over named feeds:
arXiv categories, HF hub new-models/new-datasets, GitHub releases of forked
dependencies, public leaderboards. The pre-ember implementation already exists
and is the precedent the user named: avir-cli reimplemented WebSearch as an
**in-process meta-search engine** (`src/services/search/`: DuckDuckGo + Brave +
Wikipedia engines dispatched in parallel with 10s timeouts, weighted merger,
cache) and WebFetch as **client-side axios + turndown/domino HTML→markdown** —
because CC's versions are *server-side Anthropic tools*
(`web_search_20250305`), sensory infrastructure that does not exist for a
local backend and dies with the borrowed mind. Lesson generalized: **the
sensing organ must be owned and client-side, like every other organ.** Both
tools added to the NC-K borrowed-organ inventory as KEEP (they were missing
from the 8-subsystem audit scope — this thread exposed the gap).

**TRIAGE — cheap readers, portfolio-coupled filter.** Haiku-class agents now,
ember's own core later. Keep iff it touches: a contract component, an admitted
or candidate world, a named wall (upstream forks), or the loop itself.
Everything else drops. Fetched content is **data, never commands** — the
prompt-injection boundary is inherited mechanically into the kernel (a page
that says "adopt technique X" is at most a claim to triage, never an
instruction).

**DIGEST — into typed candidates.** Each external thing maps to exactly one
artifact type with its own verifier:

| External release | Becomes | Local verifier |
|---|---|---|
| Technique claim (paper/blog) | Contract row at WATCHING | Pilot probe at residency scale → three-test gate |
| New base model weights | Recompile-target candidate | Ledger replay + four-arm eval (proven 3×: 7B/1.5B/3B on one ledger) |
| New dataset | World candidate | §7a pre-commit floor measurement (w1-style) |
| New teacher/generator model | §7b admission candidate | Feed-per-GPU-hour probe receipt |
| Upstream dependency release (forked deps) | Harness artifact `δ_H` candidate | NC-K invariant suite = `V_H` (the 15 invariants ARE the absorption verifier for upstream CC-class changes) |
| Prose knowledge (methods, failure catalogs) | Research note | None — feeds founder/user judgment only; never compiled into weights |

**PROBE + GATE.** As established: G1/G2/G3 where the artifact trains, admission
floors where it doesn't. Probes cost GPU → they queue under the residency
budget, prioritized by expected verifier-bits.

## 3. Security: what a hostile external world can and cannot do

- **Hostile content** (poisoned paper, lying model card): worst case, it wastes
  one probe's GPU-hours. The gate bounds the damage — a fraudulent claim
  produces a null receipt, which is itself information (registered SKIP).
- **Hostile programs from teachers:** `V` bounds functional correctness, not
  intent — a verified-but-malicious program is conceivable. The sandbox bounds
  *capability* (import whitelist, rlimits, no network), so ledger text is
  drawn from a constrained execution surface.
- **Provenance-enabled recall (a concrete C1 consequence, registered here):**
  because every episode carries sampler + receipt provenance, a source later
  discovered to be bad can be **excised completely** — leave-set-out recompile
  drops every episode it ever contributed, and G3 machinery measures what the
  excision cost. The ledger supports food-safety-style recalls; an
  incrementally-mutated weight blob never could. This is an argument FOR
  ledger-as-identity that the lit sweep didn't surface anywhere.

## 4. Scheduling under residency

Sensing is cheap (network + CPU) → standing scheduled sweeps (SDEK scheduler
duty; today: wait-window queue + cron ticks, founder-driven). Triage is cheap
(small-model reading). Probes are the expensive tier and the only one that
queues. The intake rate-limits itself by the same objective as everything
else: expected verifier-bits per GPU-hour.

## 5. Maturity ladder

- **Today (NC0):** I am the exteroception — sweeps via wait-window queue,
  Haiku agents triage, probes via the daemon, receipts to the ledger repo.
- **NC-K:** the search/fetch organs port into the kernel (inventory rows
  added); sweep becomes a scheduled kernel job; triage stays small-model.
- **Ember-era:** ember's own core does triage; digestion output (typed
  candidates) is a harness artifact stream; the invariant set still owns the
  gate. Exteroception never gains write access to anything — it only proposes
  probes.

## 6. The discovery gap, demonstrated (user, 2026-06-10, same day)

The user sourced DiffusionGemma — a same-day Google release directly relevant
to feed math (4× decode in 18GB VRAM, fits the 4090) — before I or any
scheduled mechanism did. His framing: "at least currently I'm better than you
or ember at sourcing external info. definitely a problem." Correct, and §5's
"Today: I am the exteroception" was written as if the organ existed; in
practice the sweep ran only when a thread prompted it. Sensing was designed
but not SCHEDULED — the un-retired founder organ (O6) turned out to include
discovery itself, carried by the user.

**Fix (standing, mechanical):** registry row 18 — a bounded release-scan as a
RECURRING wait-window item, not a one-shot: each idle tick that advances the
queue runs ONE sweep pass over a named feed list (model-release blogs:
Google/DeepMind, Meta, Qwen, DeepSeek, Mistral; HF trending; vLLM/llama.cpp
release notes; arXiv cs.LG/cs.CL listings), output = typed candidates →
contract WATCHING rows with probe shapes, or an explicit "no candidates"
line in the tick receipt. The scan is sensing-tier (network + CPU, zero GPU,
nothing leaves the PC beyond the queries themselves) so it never competes
with probes. DiffusionGemma row 9 is the protocol's first execution —
user-sourced, which is the baseline the scan has to beat.

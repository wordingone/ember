# sp-1 — the-search → ember component mapping (#117)

User pointer (via Kai 14482): "the search's experiment steps have
valuable insights for ember … eigenvectors, codebooks, graphs, ssms,
families … the-search also had a component catalog."

Source read: `B:/M/the-search/docs/COMPONENT_CATALOG.md` (14+ killed
families, C1–C33, anti-collapse table, budget audit). Regime note up
front: the-search ran R1-constrained (no external labels, no gradient
descent on the substrate); ember runs the OPPOSITE regime (gradient
training on execution-verified labels). So the strongest ports are the
METHOD layer; component-level mechanisms port selectively. Every row
names an ember CONSUMER or REJECTS with the receipt that justifies it.

## 1. Method-layer ports (strongest — already partially adopted; this doc makes lineage explicit)

| the-search practice | ember consumer | status |
|---|---|---|
| Family framing + kill-with-receipts (a kill is data; successor pre-registered) | the NC ladder (NC0/NC1a–d) + rung-kill rules in STATE | ADOPTED (lineage now cited) |
| Extraction protocol (one component, one variable, test against the killing finding) | round arm design: matched-budget control + single-variable arms (sft/mtp/grpo deltas) | ADOPTED |
| Component catalog as contract form | `nc2-own-technique-contract.md` (8 components, directed-path gate) | ADOPTED — same form |
| Budget audit per family ("killed too fast?" column) | round verdicts: every kill quotes experiments+budget; under-explored flag before a family dies | ADOPT NOW (add to round-3 verdict template) |
| PRISM enforcement gap (186 experiments bypassed the enforced runner) | the daemon + interlock + receipt_check stack — ember's version of "all experiments through the runner" | ADOPTED (the gap lesson is WHY the interlock is fail-closed) |

## 2. Named pointer classes

**Codebooks (Era-1 LVQ; FSQ in the anti-collapse table).**
- CONSUMER (strong): v0 QAT-native pretrain. FSQ's receipt-backed
  insight — bounded discrete latents + straight-through estimator make
  collapse architecturally impossible vs regularizer-patched — is the
  same STE mechanism as our int8-grid fake-quant (fp19_bench measured
  it at ~5% cost). EXTERNAL-CITED.
- CONSUMER (staged): any learned visual tokenizer for the
  unified-multimodal component (contract #8) IS a codebook; the-search's
  codebook-collapse history + FSQ are the design priors. HYPOTHESIS —
  discharge: v1 tokenizer ablation, not v0.
- REJECT for the adaptation loop: LVQ attract dynamics (C10) — that IS
  the banned mechanism in its home regime and has no gradient-regime
  consumer.

**Eigenvectors (eigenform self-observation C22; spectral structure).**
- CONSUMER: checkpoint-probe diagnostics — rank/spectral collapse
  detection on weight updates (LoRA deltas, QAT grids) is cheap and
  receipt-able; the-search's rank-1 Hebbian collapse (Step 439) is the
  failure shape to watch. Rides fp-23's probe receipt schema (#135) as
  an INFORMATION-ONLY field (never a bar — no receipt yet links
  spectra to our floors). HYPOTHESIS.
- C22's own result (signal present, no performance effect) transfers
  as a caution: self-observation signals are cheap to log and rarely
  load-bearing — log, don't gate.

**Graphs (Era-2; per-(state,action) storage BANNED, negative transfer p<0.0001).**
- CONSUMER (already aligned): the episode LEDGER is append-only and
  TIME-indexed, not state-indexed — exactly the shape that survived
  (C32 append-only trajectory buffer, "graph-ban safe, grows with time
  not state space"). RECEIPTED on the-search side; lineage noted.
- WARNING port: NC1a (context/library accumulation arm) must index by
  episode/time, never by state-key aggregation — the graph family's
  negative-transfer receipt is the strongest prior we own against
  per-state memory stores. Staged into sp-2.
- REJECT: edge-count navigation (C16), per-state visit counts (C17) —
  no ember consumer; their global-aggregate variants are trivially
  what our solve-rate table already is.

**SSMs (reservoir/echo-state C21/C26; Prop 29 architecture-irrelevance; PRISM interference).**
- CONSUMER (staged, v1 only): the SubQ contract component (SSA-class
  sparse/linear-hybrid attention) — the-search's receipt pair is the
  honest prior: recurrent state helps standalone (+8.5% LS20) and
  HURTS under multi-task interference (−14% PRISM). At 0.37B/seq-1024
  the fp-19 bench measured sparse-attn ≈0.98× anyway — v0 stays plain
  attention (RECEIPTED); hybrid goes to a v1 single-variable ablation
  per the extraction protocol. 
- REJECT for v0: any SSM/hybrid block in the owned core now —
  multiplier table says no win at our scale; deviation would violate
  the fp-19 pin.

**Families (the meta-pointer).** The deepest port is the discipline
itself: ember's ladder, pre-registered successors, matched controls,
and the "a ceiling is a door" kill semantics are the-search's method
applied to the gradient regime. §1 table covers the mechanics.

## 3. Anti-collapse table → ember monitoring

SIGReg / Turrigiano / BCM / FSQ all answer "unconstrained dynamics
drift to degenerate fixed points." Ember's exposure: QAT fake-quant
instability (the pre-registered AdamW switch is the response) and
LoRA-delta rank collapse. Consumer: fp-23 probe schema gains
information-only spectral fields (above); the AdamW switch rule stays
the only BINDING response until a receipt links a monitor signal to a
floor failure. No new gates invented from prose.

## 4. Successor

sp-2 (staged, fires if/when NC1a enters): retrieval-arm design spec
consuming C32/C33 — append-only time-indexed buffer + attention
retrieval as the library mechanism, per-state aggregation banned by
the graph-family receipt; bootstrap problem (C33's 0/10) named as the
first design risk.

Evidence classes: the-search rows are RECEIPTED in their own repo
(steps cited in the catalog); every ember-side adoption above is
tagged where it lands (fp-23 fields, v1 ablations, sp-2). Nothing here
modifies a frozen prereg.

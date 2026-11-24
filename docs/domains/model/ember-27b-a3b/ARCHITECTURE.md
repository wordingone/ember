# Ember 27B A3B: architecture

How the model is laid out so that it can meet [PRD.md](PRD.md). Not locked. Each element is marked **decided** (follows directly from a requirement), **established** (measured), or **hypothesis** (with the test that decides it, in [SPEC.md](SPEC.md)).

An earlier architecture (2026-11-15) took the stock 27B model's layer stack as the body and split it in place. That body is the donor's family, so it does not meet EM-07 and is withdrawn. Its measurements stay as facts about that stack as a donor and about the card.

## 1. The contract is the stream, not the block (decided: EM-07, EM-08)

Ember owns five things and nothing else is fixed:

| Part | What it is |
|---|---|
| Stream | the residual stream every block reads and writes: its width and its positions |
| Vocabulary | the token tables at the two ends |
| Router | chooses which modules are active for a segment; has one row per module |
| Core | always on: identity, values, the router's existing rows, norms. Never written by a transplant or by a module's training |
| Module slot | the place a module plugs in: it reads the stream and writes back into it |

A block is anything that reads the stream and writes into it, whatever it computes inside. That is what lets a later architecture become a module: the contract does not name attention, a state-space mixer or any other block kind.

Width, depth and vocabulary are the owner's to set (section 6).

## 2. How a donor enters (decided in principle: EM-08; each route a hypothesis)

A donor is a source. It enters through maps that are measured and recorded, one per axis: width (stream map), depth (which donor layers correspond to which positions in Ember), vocabulary (token map), block kind. An exact copy is the special case where every map is the identity; it is not the design goal.

| Route | What it keeps | Cost | Test |
|---|---|---|---|
| A. Keep the donor's block whole as a module, with a read map and a write map at its edges | everything the block computes; works for any block kind | that block's own run time and memory | D4 |
| B. Map the donor's weights into an Ember block of the same function class | the weights, through a fitted map | the map's loss | D1 (width), D2 (vocabulary and family), D3 (a transplant of record) |
| C. Distill the donor's behaviour into an Ember module | behaviour only; works for any architecture | training tokens | priced by the measured training rate (section 5) |

Recorded in the earlier shape specification: a width map between two small models of one family was measured and came out as a cost, not free. The receipt was not re-read for this document; the number is restated only from its receipt.

## 3. Sparse by residency (decided: EM-14, EM-15, EM-16)

- On the card: the core, the active modules, and the context cache. Everything else is in host memory or on disk.
- The router's choice is the main path for bringing a module in, not an overflow path.
- Training updates one chosen module at a time, with every other tensor's hash checked equal.
- Inference and training share the card; training is slowed while an agent's turn is active and the slowdown is recorded.

What stands in the way, and the method for each:

| Blocker | Evidence | Methods to remove it |
|---|---|---|
| Switching modules off in a model that was trained dense costs more than a step in model size | measured on a 0.8B model of the donor's family (earlier specification, forward-only curve) | sparsity is built in rather than cut out: modules are trained as modules on labelled domain data; or the always-on part is the whole computation at low precision and a module is the full-precision remainder for a group (hypothesis P1); or the routing mechanism of an already sparse open model is transplanted (the owner's question; untested) |
| Host-to-card transfer time when the router changes its choice | not measured | measure the transfer rate and how often the choice changes per segment; prefetch by the router's score |
| A router that is not trained does not route by topic | recorded from published mixtures of experts in the earlier specification | router rows come from each module's domain; an explicit selection by the owner overrides |

## 4. Modules (decided: EM-17 to EM-20)

- A capability module is one file. Adding it writes no existing byte; removing it returns the earlier scores.
- An interest module is a capability module chosen from a library; each owner has a resident list.
- The personal module is a fixed, deliberately chosen part of the parameters that starts empty and holds what the model learns about its user. Replacing it hands the model to another person.
- Modules are never merged into the core.

Partial evidence, inside one family only: copies of a donor's feed-forward weights carried 0.41 and 0.58 of the donor's score gap in two measurements.

## 5. One million tokens (decided: EM-03; hypothesis in every part)

- Measured: for one layer of the donor's stack with random weights, a forward and backward pass completes at 1,000,000 tokens on the card (attention peak 20.19 GiB, state-space mixer 20.38 GiB, under a 22 GiB cap), using tiled attention with per-tile recomputation. A state-space mixer's backward memory was flat from 32,000 to 524,000 tokens.
- Not measured: a whole stack, real weights, serving, recall at length.
- What follows for the body: block kinds whose state does not grow with length are preferred for most of the depth, and the cache of the blocks that attend globally is the quantity that bounds length. Both are Ember's own levers under the contract.
- Measured training rate on the card with the earlier stack: 0.024 to 0.032 billion tokens a day. Any route that needs training tokens is priced with this number until a faster kernel is measured.

## 6. Body: candidate ways to an own-family model (hypothesis; the choice is open)

The body is what fills the contract on day one. No candidate is chosen. Each row is a way to get there and what decides it.

| Candidate | What it is | What it costs or risks | Decided by |
|---|---|---|---|
| 1. Assembled | Ember's own stream; donor blocks from several families kept whole as modules behind maps (route A), with a small trained core and router | run time and memory of foreign blocks; the router must learn to send work to them | D4, then the router test |
| 2. Mapped | Ember's own width, depth and vocabulary; donor weights mapped in block by block (route B) from more than one donor | the maps' loss, measured as a cost for width | D1 to D3 |
| 3. Distilled | Ember's own shape trained to match donors' behaviour (route C) | training tokens at the measured rate; the slowest | the training-rate measurement and a faster kernel |
| 4. Precision split | an always-on low-precision whole plus full-precision remainders as modules (P1) | as first written it splits one donor, so it meets EM-07 only if the whole being split is already Ember's own | P1 forward-only test, after one of 1 to 3 |

A proposal for width, depth and vocabulary, with the cost of each choice under each candidate, is owed to the owner before any is set. Until then the document names no numbers for them.

## 7. Inputs, outputs and the other functions (decided: EM-21, EM-23; not designed)

Vision and audio encoders enter as modules behind maps like any donor. Structured tool calls, working memory, a world model and dreaming are functions the model must have (PRD); none is designed in this document yet. Each gets a section when its first test is specified.

## 8. What is established today

| Fact | Standing |
|---|---|
| One layer's pass at 1,000,000 tokens fits the card | established, random weights, donor's layer kinds |
| Feed-forward copies inside one family carry part of a domain's gap (0.41, 0.58) | established, two measurements |
| A dense model's modules cannot simply be switched off | established on a 0.8B model |
| Training rate 0.024 to 0.032 billion tokens a day | established for the earlier stack |
| Anything across families, any own-family body, residency off the card, simultaneous training and inference on this model | hypothesis |

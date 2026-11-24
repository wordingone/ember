# Ember 27B A3B: product requirements

What the model must be. How it is laid out is in [ARCHITECTURE.md](ARCHITECTURE.md); counting rules, gates and tests are in [SPEC.md](SPEC.md).

Every requirement comes from a statement by the project owner, with its date. Where the owner's wording decides the meaning, it is quoted. A requirement is met only when its acceptance criterion passes on the named weights (EM-30). Open for change; nothing here is frozen.

The transformation from open models to Ember 27B A3B is a research and engineering pathway, not a shown capability. The State column says **established** (runs or measured), **partial**, **hypothesis** (with its test in SPEC.md), or **not started**.

## Terms

| Term | Meaning |
|---|---|
| Ember 27B A3B | the project's own model: about 27 billion parameters in total, about 3 billion in use for any one token |
| in use | parameters that take part in computing one position, by the counting rule in SPEC.md |
| core | the part that is always on: identity, values, the stream contract and the router's existing rows |
| module | a set of parameters that can be added, removed or swapped as one file without writing the core. "Expert" in the owner's statements means the same |
| stream contract | the model's own interface: the residual stream's width and positions, the vocabulary at both ends, and the router |
| donor, recipient | a transplant moves what a donor model computes into a recipient model |
| map | a measured, recorded transform between a donor's interface and Ember's, per axis: width, depth, vocabulary, block kind |
| family | models sharing an architecture lineage and interface (block kinds, widths, vocabulary) |
| the card | one consumer graphics card with 24 GB, the only accelerator |

## Identity

| Id | Requirement | Acceptance | Source | State |
|---|---|---|---|---|
| EM-01 | About 27 billion parameters in total. | The count by the rule in SPEC.md, read from the model's own configuration, is at least 27.0 billion. | owner, 2026-11-15 | not started for an own-family body |
| EM-02 | About 3 billion parameters in use per token, and that number stays about constant as the total grows ("capacity to grow larger but maintain constant partial number of params that require compute"). The name "A3B" is carried only after this is measured. | The in-use count per token, measured over the evaluation suite, stays under the in-use bar, and scores hold inside frozen bounds against the all-on setting. The bar's exact value is not set. | owner, 2026-11-14, 11-15 | hypothesis |
| EM-03 | A context window of at least 1,000,000 tokens that can grow further. Non-negotiable. | At 1,000,000 positions or more on the card: a retrieval test with no literal match and held-out bits per byte both pass bars frozen before the run. | owner, 2026-11-13 ("Id like at least a mil total"), 11-14, 11-15 | hypothesis; one layer's forward and backward pass at 1,000,000 tokens has been measured (SPEC.md) |
| EM-04 | It is built from open weights, donors and transplants by design; training by gradient is also allowed. | Every component's origin (donor, map, or training run) is in its record. | owner, 2026-11-15 | decided as the route; no measurement is claimed |
| EM-05 | It is built, never left as a plan. | Each report names what was built toward it and the receipt. | owner, 2026-11-15 | partial |

## Its own family

| Id | Requirement | Acceptance | Source | State |
|---|---|---|---|---|
| EM-07 | It is its own family and shape, not any donor's. Width, depth, vocabulary, positions and router are Ember's own. No donor is the frame; every donor, the stock 27B model included, enters through maps. | No interface quantity of the model is defined by reference to a donor's configuration, and the model loads and runs with any single donor's files absent. | owner, 2026-11-13 ("nope on the same shape as qwen"; "the goal isnt to make ember27b a qwen specific recipient, but more of a universal recipient"), 2026-11-24 ("the model cannot be same family as qwen, as thats not the point") | not met; width, depth and vocabulary are the owner's to set (Not set, below) |
| EM-08 | It is a universal recipient: it takes capability from donors of other families, other shapes and other block kinds, including models released later and architectures that do not exist yet. | Transplants pass EM-11 from at least two families, at least two widths, and at least one block kind that is not a transformer block. | owner, 2026-11-13 ("what happens when newer open source models are released?"; "and what happens if different architectures arise in the future?") | hypothesis |
| EM-09 | Transplants are studied in both size directions: a smaller model giving to a larger one, and a larger giving to a smaller. | One transplant of each direction passes or fails EM-11 with its record. | owner, 2026-11-15 | not started |
| EM-10 | A transplant never destroys existing weights. It only adds. | The hash of every tensor that existed before the transplant, and of every existing router row, is equal after it (a transplant appends new router rows and new files only), and removing what was added returns the earlier scores. A mismatch refuses the transplant. | owner, 2026-11-13 ("the transplants should happen without ever destroying those weights") | hypothesis: structural gate specified, not run on this model |
| EM-11 | A transplant raises the recipient to the donor's score on a whole benchmark domain, on held-out items, with other scores inside a frozen bound. | As stated, with bars frozen before the run and the void range named. | owner, 2026-11-13, 11-14 | partial: two earlier measurements inside one family reported 0.41 and 0.58 of a donor's gap; their receipts are re-read before either number is cited as a result (EM-30) |
| EM-12 | It is universal in both directions ("universal donor-able"): Ember takes from any donor (EM-08), and an Ember module, with its recorded interface, can be given to another model. | One Ember module is transplanted into a recipient of another family and passes the bar of EM-11 there. | owner, 2026-11-24 | hypothesis |

The owner's words of 2026-11-24 also say "the point is to make it universal donor-able?". Both readings are carried: receiving from any donor is EM-08, and giving an Ember module to another model is EM-12.

## Sparse, and working while it learns

| Id | Requirement | Acceptance | Source | State |
|---|---|---|---|---|
| EM-14 | It is truly sparse: not every module sits on the card. The core and the active modules are on the card; the rest are in host memory or on disk and are brought in by the router's choice. | With the model serving, a process read shows the card holding no more than the core plus the modules active in that window, and a count of modules never brought to the card during the run is above zero; a module not resident is loaded on the router's choice and the answer is the same as with everything resident, inside a frozen bound. | owner, 2026-11-14 ("every expert must NOT sit on the card") | hypothesis |
| EM-15 | Inference, training and experiments run at the same time on the one card, each side taking more or less as needed. | While the model answers an agent's turn, a training job on one of its modules advances; both are measured; neither is refused or voided; the card's memory cap holds. | owner, 2026-11-14 ("does not, then, allow for simultaneous training/finetuning/gpu-experiments and inference"), 2026-11-24 ("it should allow for the simultaneous inference/training as well") | hypothesis |
| EM-16 | Training touches a chosen part only: the modules in use or one deliberately chosen module, never the whole 27B, and it is faster per token than the earlier 3B sparse design was. | A training step updates only the chosen module's tensors (all other hashes equal) and its tokens per second are recorded against the earlier design's record. | owner, 2026-11-15 ("would 3/27b fit? or whatever selective amount of weights and experts? ... the 27b oine should do the same but better") | hypothesis: one module family of at most 754,974,720 parameters per step fits the card by arithmetic done for the donor-family stack's dimensions; redone when Ember's own shape is set |

## Modules

| Id | Requirement | Acceptance | Source | State |
|---|---|---|---|---|
| EM-17 | Every module is replaceable on its own, not only the personal one. | Any one module is removed or swapped and all other scores stay inside the frozen bound; the core's hashes are unchanged. | owner, 2026-11-15 ("its not JUST the personal module being replaceable") | hypothesis: module split test |
| EM-18 | A personal module: the model learns lasting knowledge of its user in a deliberately chosen part of its parameters, without external memory files; handing the model to another person means replacing that one module. | After learning, the knowledge is recalled with no memory file present; with the module replaced by an empty one it is gone and every other score is unchanged. | owner, 2026-11-15 | hypothesis |
| EM-19 | Interest modules: one user's Ember specializes in, for example, mathematics, physics, logical reasoning and spatial reasoning; another's in other fields. The set is chosen per owner from a library. | Two module sets on one core give two different score profiles, each raised in its chosen domains and inside the bound elsewhere. | owner, 2026-11-15 | not started |
| EM-20 | Capability is added and removed without leaking into other scores. | Module split test: add and remove at zero leakage beyond the frozen bound. | owner, 2026-11-15 | hypothesis; a frozen bar exists |

## What it must be able to do

| Id | Requirement | Acceptance | Source | State |
|---|---|---|---|---|
| EM-21 | All modalities, natively: text, images, audio, with video and documents through them. | Each modality has a held-out score on this model's own weights; none is supplied by an outside model at run time. | owner, 2026-11-13 ("everything that it needs to have the capacity for, including all modalities") | not started |
| EM-22 | Specialization in disciplines. The domains experiments target: machine learning, computer science, software engineering, logic, reasoning, puzzle solving, problem solving, mathematics, physics. | Held-out scores with error bars on each, against the open reference at equal in-use size. | owner, 2026-11-13, 11-16 | not started |
| EM-23 | The same end-goal functions as the numbered Ember milestones planned: reasoning, structured tool use, memory, a world model, dreaming, and autonomous research. | Each has its own test on this model's weights, named in SPEC.md as it is written. | owner, 2026-11-15 ("still supposed to be the same in end goal functionality as was planned ... and the other numnbered ember milestones") | not started |
| EM-24 | It can hold the resident agent's place in the lab, and the research loop runs on its own weights. | The agent requirements of the programs pass with this model loaded; the loop's record names this model's weights by hash. | owner, 2026-11-15, 11-24 | not started; an open-weight model holds the place today |
| EM-25 | The open-weight model that runs the resident agent today exists to give what it has to Ember; the two are scheduled so that the borrowed model is dormant when Ember is active, and the reverse. | A record of each hand-over; no time at which both hold the card for inference. | owner, 2026-11-14 | not started |

## Evidence rules

| Id | Requirement |
|---|---|
| EM-30 | Every result names the weights it was measured on by hash, read from the run's own record. A result without one is "unverified as to model". |
| EM-31 | Every bar is frozen before the run and states what makes the measurement void. |
| EM-32 | Every method names the closest published method, what it showed, the step beyond it, and whether a dead end is known. |
| EM-33 | Every weight read or edit leaves a notebook entry. |
| EM-34 | A hypothesis is never reported as a result. A blocker is reported with the methods that remove it, never as "not viable". |

## Not set

Requirement ids are not contiguous; an unused number is not reused.

| What | State |
|---|---|
| Ember's width, depth and vocabulary | the owner's to set; a proposal with the cost of each choice is owed first (ARCHITECTURE.md, Body) |
| The in-use bar of EM-02 | "about 3 billion"; no exact number |
| The frozen bounds of EM-02, EM-10, EM-11, EM-14, EM-17 | set per test, before its run |
| Whether a sparse model's routing mechanism can itself be transplanted without training (owner's question, 2026-11-14) | a candidate route in ARCHITECTURE.md, untested |

## Supersedes

The milestone contracts EMBER-07, EMBER-08 and EMBER-09 describe size rungs and a clean-genesis lineage. The rungs were retired by the owner on 2026-11-24 and the clean-genesis rule on 2026-11-15; where they differ from this document, this document is the requirement.

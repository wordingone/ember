# Ember 27B A3B: specification

The rules, gates and tests that [PRD.md](PRD.md) and [ARCHITECTURE.md](ARCHITECTURE.md) point to. A section says "not written" where nothing is fixed yet.

## 1. Counting rule

- Total parameters: every stored parameter of the core and of every module in the model's library entry for a release, token tables included.
- In use per token: the parameters that enter a matrix product for one position, the output head counted, a token-table lookup not counted. The context cache is counted separately and named with its length.
- A count is read from the model's own configuration and module list, never from a donor's.

## 2. Gates every transplant and every module addition must pass

| Gate | Rule |
|---|---|
| Structural | the hash of every core tensor is read before and after; unequal refuses the job and restores the core from its pinned copy |
| Behavioural | identity and value tests are re-run after; outside the retention bound removes what was added |
| Removal | removing the addition returns the scores measured before it, inside the bound |
| Record | donor, maps, weights hashes of parent and child, the bar and its void range are written before the run's first number |

## 3. Bars

- A bar is frozen in a file before the run and names: the pass value, the bound on other scores, and the void range.
- Void, for any mixed or edited model: more than 1.0 worse than the worse of its sources on the test's own scale means the model is not functional and the result attributes nothing.
- A verdict a script prints by default is never adopted; a result that fits no named class is reported as unclassified with its residual.

## 4. Tests named by the other documents

| Id | Question | Scale | State |
|---|---|---|---|
| D1 | Does a fitted stream map carry one model's stream into another of a different width, in each direction? | two small models of one family | run once; recorded as a cost; receipt to be re-read before the number is restated |
| D2 | The same across a different vocabulary and family | a second-family model of at most 3B | not run |
| D3 | One module carried from the D2 donor through fitted maps: gain on a held-back source, others inside the band, removal removes it | 0.8B-scale Ember | not run |
| D4 | A block of a different kind kept whole as a module behind read and write maps | 0.8B-scale Ember | not run |
| Router | Do new router rows alone suffice to send work to a new module? | 0.8B scale | not run |
| Module split | Add and remove a module at zero leakage beyond the bound | donor-family stack | a frozen bar exists; result not read for this document |
| P1 | Is "module off = low precision" cheaper than "module off = zero"? Loss at 2, 3 and 4 bits with 0 to 32 remainder groups on | 0.8B, forward only | not run |
| L1 | Retrieval with no literal match and bits per byte at 32,000, 128,000, 512,000 and 1,000,000 tokens | 0.8B | harness built; not run on an Ember body |
| Residency | Transfer rate host to card; how often the router's choice changes per segment; answers equal with a module resident or loaded on demand | the card | not run |
| Together | A module trains while the model answers; both measured, memory cap held (EM-15) | the card | not run |

Each test's own file states its prediction before the first number.

## 5. Measurements carried from earlier work

| Measurement | Value | Conditions |
|---|---|---|
| One layer, forward and backward, 1,000,000 tokens | attention peak 20.19 GiB, state-space mixer 20.38 GiB, cap 22 GiB | random weights, one step, the donor's layer kinds, tiled attention with per-tile recomputation |
| State-space mixer backward memory over the floor | 0.978, 1.099, 1.111, 1.136 GiB at 32,000, 131,000, 262,000, 524,000 tokens | chunk-recurrent exact backward |
| Training rate | 0.024 to 0.032 billion tokens a day | earlier stack, fallback kernel |
| Feed-forward copies' share of a domain gap | 0.41 and 0.58 | inside one family |
| One trainable family per step | at most 754,974,720 parameters at 16 bytes each, 20.46 GiB peak | arithmetic |

Their receipts are in the research records of this repository's custody; a value is restated elsewhere only from its receipt.

## 6. Not written

- Ember's width, depth, vocabulary and position scheme (the owner's to set).
- The module file format and the library entry.
- The router: its inputs, its epoch, how many modules are resident and selected.
- The schedule that shares the card between inference and training.
- Tests for tool use, memory, the world model, dreaming and each modality.
- The in-use bar and every bound marked "not set" in the PRD.

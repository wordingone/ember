# Status: what runs today and what is a hypothesis

This page holds the status detail that the [root README](../README.md) points to. Nothing here has
been upgraded without a receipt. Designed, implemented, executed, measured, independently reproduced,
and admitted are different maturity states, and documentation never upgrades one into another.

## Overall

No current checkpoint is an admitted Ember model. The goal file still sets the target as a sufficiently
trained sparse unified text-image-audio decoder with native reasoning and structured tool use. Ember 27B
A3B is the route now being tried. It is a research and engineering pathway, not an already demonstrated
capability.

## Ember 27B A3B

Established, meaning it runs today or was measured:

- The stock 27B layer stack, 48 DeltaNet layers and 16 attention layers, and its vision encoder.
- Serving with every unit on, which is 27.45B parameters per token. The 3.27B figure is a target
  setting, and it does not carry the name until its first two tests pass their frozen bars.
- The cache arithmetic at 1,000,000 tokens.

Partial evidence only: internal transplant experiments exist, and their results are in the paper's
experiment log. No figure from them is quoted here.

Hypotheses, each with the test that decides it and its planning date:

- Gating DeltaNet head groups: E1, Nov 16.
- Healing the 3.27B setting back to the bars: E3 at 0.8B on Nov 18, and at 27B on Nov 30.
- Adding and removing modules at zero leakage: M1 on Nov 15, gate 5 on Nov 24.
- The domain picker at 27B: Nov 24.
- Compressed attention holding at 1,000,000 tokens: L1 and the latent attention test, Nov 21.
- A comparison with the open A3B model at equal parameters in use: B1, Dec 2.

Dates are planning dates. They move when a receipt says they must. Every page and paper line calls
each of these a hypothesis until its receipt lands.

## The transplant research

The paper is a working draft that states a design and claims no result yet. What moves is a whole
benchmark domain's score. No transplant harness is in this repository, so nothing here reruns a
transplant press today.

## Ember, the agent

The aim is a system drivable solely by Ember. Ember is meant to submit an approved run to ember-lab,
inspect the receipts against a frozen bar when the job ends, recompute the score with a script, and
write the verdict and the paper's experiment log. Today the owner and the AI agents the owner directs
still do most of those steps. The plan counts the share of loop steps Ember did, and that share is meant
to rise.

## Ember Studio

Ember Studio is a desktop program to train, explore and use Ember and open-weight models, and it is a
client of ember-lab. The public face is [wordingone/ember-studio](https://github.com/wordingone/ember-studio)
for the manual and issues. No release build is published yet, and the application source is not in this
repository. The ember-lab control plane, which starts and supervises runs and model servers, is
`runtime/ember-lab` here.

## History

Earlier Ember was a 3B model trained from scratch on this one GPU, with a receipts-gated accumulation
loop. Hours 1 to 43 are a from-scratch, model-free baseline that used no borrowed weights, teacher
models or judge models. Since early November 2026, declared open-weight models may be used, and every
use is recorded per hour. The 3B model is no longer being trained (2026-11-14). Its checkpoints,
receipts and ledgers stay here as an archive, and nothing is deleted. The roadmap and the authority
pages still describe the 3B goal. They have not been revised for the change above. The
[docs map](README.md) says which pages are current and which are archive.

Data exception: an internal audit ([`receipts/genesis/genesis-audit-20260706.md`](../receipts/genesis/genesis-audit-20260706.md))
found earlier training data included FineWeb-Edu, selected by a classifier trained on Llama-3-70B-Instruct
annotations. It was later dropped ([`docs/domains/governance/anatomy/14_MODEL_CARD.md`](domains/governance/anatomy/14_MODEL_CARD.md)).
The lineage is not certified clean. Model-generated data is declared per hour and counted separately
from human-sourced data.

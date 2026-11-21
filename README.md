<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->
<!-- Reading note for the header above: its field names are fixed tokens that authority verification
checks in every governed document. `borrowed_lineage=frozen_reference_only` names the historical
baseline boundary (hours 1-43) and does not forbid declared open-weight use after the baseline hours, which
the text below states and each training hour records. -->


# Ember

<a id="ember.claim.identity"></a>
<a id="ember.claim.problem"></a>
I am now obsessed with training my own foundation model, creating my own harness for the terminal, and experimenting to push the bounds of what is possible with the resources I have. Ember is that work. It runs locally on one home computer with one consumer GPU, and every claim about what it can do points to public evidence anyone can check.

I've also earnestly been reading research papers, trying to understand software, computer science as much as I could by myself using available resources, not just entrusting that the agents would handle everything. The experiments and most of the code are still built and run with AI agents (Claude). Training data is human-sourced first.

## What Ember is now

Ember is four things. The first two are research. The proposed 27B-to-Ember transformation is a research and engineering pathway, not an already demonstrated capability.

**Ember 27B A3B.** Ember 27B can't be built just to allow for the current Qwen 27B transplant. What happens when newer open source models are released? Ember 27B A3B needs to be 1 million context window, so that design of that Ember must consider that. It's not just the personal module being replaceable.

**The transplant research.** Given that the donor model receives score x.xx on MLE-bench, and the recipient model scores x.xx-y.yy, how must the transplant be done in order to then raise the recipient model post transplant to x.xx? The goal isn't one time success or even multiple time success, it's doing enough varied experiments to understand the underlying methods in which how to do it successfully every time, no matter the variable. The goal isn't to make Ember 27B a Qwen specific recipient, but more of a universal recipient. And then the transplants should happen without ever destroying those weights. It wasn't, get better at addition, it was literally getting better at math as a whole.

**Ember, the agent.** We also need to increasingly be moving (ember+ember-lab+ember-studio) from a tool that lets us (Claude agents, me, Ember) conduct experiments to a system drivable solely by Ember that can systematically and continuously conduct and learn from them. Ember should manage/initiate the experiments and then go dormant, as well as inspect the results post.

**Ember Studio.** Make it a research environment in which visual and spatial interaction is the primary way of understanding and manipulating ML systems. A fundamental principle in Ember Studio's tabs and graphics must be that it MUST be a visual interface.

## How the research is run

Don't define a method then figure out the outcome. Define the outcome then figure out the method. Make sure that we aren't digging down the wrong hole where others have already dug and found it to be 100% a dead end.

## History

We will not be training the 3B Ember model anymore. Earlier Ember was a 3B model trained from scratch on this one GPU, and its checkpoints, receipts and ledgers stay here as an archive.

## Status

<a id="ember.claim.maturity"></a>
<a id="ember.claim.target"></a>
- Ember 27B A3B: the stock Qwen3.8-27B layer stack runs today, and about 3.27B parameters used per token is a target with no result yet
- The transplant research: the paper is a working draft that claims no result, and no transplant harness is in this repository
- Ember, the agent: I and the AI agents I direct still do most of the loop steps today
- Ember Studio: [wordingone/ember-studio](https://github.com/wordingone/ember-studio) is the public face, no release build is published yet, and its application source is not in this repository
- Overall: no current checkpoint is an admitted Ember model, and the goal file still sets the target as a sufficiently trained sparse unified text-image-audio decoder with native reasoning and structured tool use
- What runs today and what is a hypothesis, with the test and the date of each: [the status page](docs/STATUS.md)

## Where things are

| Kind | Name | Path | Contents |
|---|---|---|---|
| Domain | Model | `src/ember/model` | The canonical Python model implementation |
| Domain | Data | `src/ember/data` | Dataset custody, synchronization, and data-domain code |
| Domain | Training | `src/ember/training` | The canonical training-loop implementation |
| Domain | Evaluation | `src/ember/evaluation` | Protected and held-out evaluation entry points |
| Domain | Runtime | `src/ember/runtime` | Python inference and runtime entry points |
| Domain | Lab | `domains/lab` | Cross-domain experiments and their declared interfaces |
| Domain | Infrastructure | `src/ember/infrastructure` | Operator tooling, launchers, and execution support |
| Domain | Governance/contracts | `src/ember/governance` | Policy enforcement and receipt-governance code |
| Artifact | Model | `src/ember/model/ember_v0_model.py` | Unified decoder definition |
| Artifact | Training loop | `src/ember/training/pretrain.py` | Owned pretraining loop |
| Artifact | Evaluator | `src/ember/evaluation/cbase_heldout_eval.py` | Held-out evaluation entry point |
| Artifact | Runtime entry | `src/ember/runtime/infer.py` | Inference entry point |
| Artifact | Data pipeline | `src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py` | Current text-lab corpus pipeline |
| Artifact | Governing contracts | `docs/domains/governance/authority` | Canonical goal, continuity, and governance authorities |

## Inspect or install

To inspect Ember, start at this repository-root README and continue through the
[canonical `docs/domains/governance/guides/START-HERE.md` page](docs/domains/governance/guides/START-HERE.md). On Windows, `tools/launchers/Ember.cmd` is
the operator entry.

Python dependency authority: manifests/python-environment-v1.json.

Installation authorities are distinct: Python uses
[`manifests/python-environment-v1.json`](manifests/python-environment-v1.json), the ember-lab daemon is installed from the released build on
[wordingone/ember-studio](https://github.com/wordingone/ember-studio/releases) (its source is in a private repository, so there is no Rust build here), and `ember-cli` uses
[`src/ember/infrastructure/tools/ember-cli/src/package.json`](src/ember/infrastructure/tools/ember-cli/src/package.json). From the repository
root, install the measured direct environment:

```text
python src/ember/infrastructure/tools/ember-restart-3b/python_environment.py install --receipt state\receipts\python-environment-install-v1.json
```

This requires a supported Windows Python environment and network access for dependencies. It does
not require model weights or a GPU. See the [start guide](docs/domains/governance/guides/START-HERE.md) before using
operator or training surfaces.

## Current truth and roadmap

<a id="ember.claim.mutable-state-owner"></a>
Exact mutable state lives in [`docs/domains/governance/authority/CONTINUITY.md`](docs/domains/governance/authority/CONTINUITY.md). Public milestone contracts and certificates live under the [roadmap](docs/domains/governance/roadmap/README.md).

## Documentation routes

- [Docs map](docs/README.md), current versus archive
- [Status](docs/STATUS.md), what runs today and what is a hypothesis
- [First-reader route](docs/domains/governance/guides/START-HERE.md) and the [documentation map](docs/domains/governance/DOCS-README.md)
- [Verification guide](docs/guides/VERIFY.md), the CPU-only checks
- [System overview](docs/architecture/system-overview.md) and [glossary](docs/GLOSSARY.md)
- [Operator documentation](docs/domains/governance/operator/README.md)
- [Generated canonical index](docs/INDEX.md)

## Contributing

Use the [canonical contribution route](docs/contributing.md).

## License

See [LICENSE](LICENSE).

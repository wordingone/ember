<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Ember

<a id="ember.claim.identity"></a>
<a id="ember.claim.problem"></a>
Ember is a complete local foundation-intelligence project: a clean-genesis model-creation
primitive, a continuously improving organism, the ember-cli operator body, and a general local AI
laboratory. It addresses the problem of creating and operating owned foundation intelligence on a
one consumer GPU while making every learned, executed, and evaluated claim traceable to
public evidence. Borrowed learned or evaluative signals do not enter the target lineage.

<a id="ember.claim.maturity"></a>
<a id="ember.claim.target"></a>
Ember has a certified custody and experiment spine, but no current checkpoint is an admitted Ember
model. The governing target remains a sufficiently trained sparse unified text-image-audio decoder
with native reasoning and structured tool use. Designed, implemented, executed, measured,
independently reproduced, and admitted are different maturity states; documentation never upgrades
one into another.

## First-reader facts

- Ember is the complete clean-genesis sovereign foundation-intelligence project: the local
  foundation-model creation primitive, continuously improving organism, `ember-cli` operator body,
  and general local AI laboratory.
- It addresses creating and operating owned local foundation intelligence on one consumer GPU.
  Claims require verified public experience and receipts; borrowed learned or evaluative signals
  are excluded from the target lineage.
- `EMBER-01` is certified but grants no model-training or capability credit. `EMBER-02` is active,
  and no current checkpoint is an admitted Ember model. The target is an approximately 30–35B
  sparse unified text-image-audio decoder with native reasoning and structured-tool use.
- The domains are Model, Data, Training, Evaluation, Runtime, Lab, Infrastructure, and Governance.
  Lab integrates experiments across declared interfaces and does not replace domain authority.
- Inspection starts at this root README and the [canonical start page](docs/domains/governance/guides/START-HERE.md).
  On Windows, `tools/launchers/Ember.cmd` is the operator entry. Python uses
  `manifests/python-environment-v1.json`; Rust uses `runtime/ember-lab/Cargo.toml`; `ember-cli` uses
  `src/ember/infrastructure/tools/ember-cli/src/package.json`.
- The smallest safe executable check is CPU-only authority verification from the repository root:
  `python src/ember/governance/scripts/verify_authority_conservation.py --root .`. Success reports authority
  conservation; it requires no credentials, weights, or GPU and grants no model capability.
- Exact mutable current truth lives only in
  [`docs/domains/governance/authority/CONTINUITY.md`](docs/domains/governance/authority/CONTINUITY.md); this README links rather than
  copying it. Public roadmap certificates, not prose or progress bars, carry completion.
- Contribution and independent reproduction start at
  [`docs/contributing.md`](docs/contributing.md) and the public
  [reproducibility charter](docs/domains/governance/charter/REPRODUCIBILITY.md): bind an exact public source, replay
  documented commands, and verify source identities and receipts without hidden or local evidence.

## Where things are

This map points to the current implementation and authority surfaces. The guard test keeps every
path live and requires every tracked top-level directory to remain explained.

| Kind | Name | Path | What you find there |
|---|---|---|---|
| Domain | Model | `src/ember/model` | The canonical Python model implementation. |
| Domain | Data | `src/ember/data` | Dataset custody, synchronization, and data-domain code. |
| Domain | Training | `src/ember/training` | The canonical training-loop implementation. |
| Domain | Evaluation | `src/ember/evaluation` | Protected and held-out evaluation entry points. |
| Domain | Runtime | `src/ember/runtime` | Python inference and runtime entry points. |
| Domain | Lab | `domains/lab` | Cross-domain experiments and their declared interfaces. |
| Domain | Infrastructure | `src/ember/infrastructure` | Operator tooling, launchers, and execution support. |
| Domain | Governance/contracts | `src/ember/governance` | Policy enforcement and receipt-governance code. |
| Artifact | Model | `src/ember/model/model.py` | Unified decoder definition. |
| Artifact | Training loop | `src/ember/training/pretrain.py` | Owned pretraining loop. |
| Artifact | Evaluator | `src/ember/evaluation/cbase_heldout_eval.py` | Held-out evaluation entry point. |
| Artifact | Runtime entry | `src/ember/runtime/infer.py` | Inference entry point. |
| Artifact | Data pipeline | `src/ember/infrastructure/tools/ember-restart-3b/text_lab_corpus.py` | Current text-lab corpus pipeline. |
| Artifact | Governing contracts | `docs/domains/governance/authority` | Canonical goal, continuity, and governance authorities. |

Start with the [first-reader route](docs/domains/governance/guides/START-HERE.md), or use the
[documentation map](docs/domains/governance/DOCS-README.md) to choose a route by task, audience, or technical domain.

## Architecture

The adopted domains are Model, Data, Training, Evaluation, Runtime, Lab, Infrastructure, and
Governance. Lab integrates experiments across the declared domain interfaces; it does not replace
their authority. Infrastructure and Governance are cross-cutting. The
[system overview](docs/architecture/system-overview.md) explains the boundaries, dependencies, and
implemented-versus-designed state, and the [domain index](docs/domains/governance/DOCS-README.md#technical-domains)
links each canonical overview.

## Inspect or install

To inspect Ember, start at this repository-root README and continue through the
[canonical `docs/domains/governance/guides/START-HERE.md` page](docs/domains/governance/guides/START-HERE.md). On Windows, `tools/launchers/Ember.cmd` is
the operator entry.

Python dependency authority: manifests/python-environment-v1.json.

Installation authorities are distinct: Python uses
[`manifests/python-environment-v1.json`](manifests/python-environment-v1.json), Rust uses
[`runtime/ember-lab/Cargo.toml`](runtime/ember-lab/Cargo.toml), and `ember-cli` uses
[`src/ember/infrastructure/tools/ember-cli/src/package.json`](src/ember/infrastructure/tools/ember-cli/src/package.json). From the repository
root, install the measured direct environment:

```text
python src/ember/infrastructure/tools/ember-restart-3b/python_environment.py install --receipt state\receipts\python-environment-install-v1.json
```

This requires a supported Windows Python environment and network access for dependencies; it does
not require model weights or a GPU. See the [start guide](docs/domains/governance/guides/START-HERE.md) before using
operator or training surfaces.

## Verify safely

The smallest safe default is CPU-only authority verification from the repository root:

```text
python src/ember/governance/scripts/verify_authority_conservation.py --root .
```

For a smaller demonstration of receipt semantics, run:

```text
python src/ember/governance/scripts/receipt_check.py --selftest
```

These checks require no credentials, weights, or GPU and grant no model capability. The
[verification guide](docs/guides/VERIFY.md) records expected results and the complete four-command
public replay set.

## Current truth and roadmap

<a id="ember.claim.mutable-state-owner"></a>
Exact mutable state lives in
[`docs/domains/governance/authority/CONTINUITY.md`](docs/domains/governance/authority/CONTINUITY.md). This README links to that owner and
does not duplicate its rapidly changing identities. Public milestone contracts and certificates
live under the [roadmap](docs/domains/governance/roadmap/README.md); a certificate, not a progress bar, carries a
completion claim.

## Documentation routes

- Understand the project: [system overview](docs/architecture/system-overview.md) and
  [glossary](docs/GLOSSARY.md).
- Use or inspect it: [start guide](docs/domains/governance/guides/START-HERE.md).
- Verify evidence: [verification guide](docs/guides/VERIFY.md) and
  [reproducibility charter](docs/domains/governance/charter/REPRODUCIBILITY.md).
- Operate it: [operator documentation](docs/domains/governance/operator/README.md).
- Audit authority: [continuity](docs/domains/governance/authority/CONTINUITY.md),
  [invariant](docs/authority/INVARIANT.md), and
  [governance](docs/domains/governance/authority/GOVERNANCE.md).
- Browse every current entry document: [generated canonical index](docs/INDEX.md).

## Contributing

Use the [canonical contribution route](docs/contributing.md). Contributions must preserve public
source identity, replay their documented commands, and separate implementation evidence from model
or campaign claims.

## License

See [LICENSE](LICENSE).

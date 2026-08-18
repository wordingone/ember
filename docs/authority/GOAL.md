# EMBER - Constitution

docs/authority/INVARIANT.md is Ember's sole unamendable identity surface. docs/authority/GOAL.md is the
highest amendable authority. Lower-precedence files may implement and test it;
they cannot reduce, defer, replace, or reinterpret it.

<!-- EMBER_AUTHORITY_V1
{
  "allows_new_network": true,
  "active_goal_id": "EMBER-02",
  "active_workstream_ids": [
    "EMBER-02A",
    "EMBER-02B",
    "EMBER-02C"
  ],
  "goal_graph_node_ids": [
    "EMBER-01",
    "EMBER-02A",
    "EMBER-02B",
    "EMBER-02C",
    "EMBER-02P"
  ],
  "workstream_path_scopes": {
    "EMBER-02A": {
      "mode": "all_except",
      "prefixes": [
        "configs/ember-restart-3b.json",
        "docs/ember-restart-3b-",
        "models/ember-restart-3b/",
        "tools/ember-restart-3b/",
        "receipts/ember-restart-3b/",
        "inference/ember-restart-3b/",
        "data/ember-restart-3b/",
        "tests/ember_restart_model/",
        "docs/ember-restart-eval-",
        "docs/ember-restart-terminal-",
        "docs/ember-restart-browser-",
        "docs/ember-restart-audio-",
        "docs/ember-restart-image-",
        "manifests/ember-restart-eval-",
        "scripts/ember_restart_eval",
        "tests/test_ember_restart_eval",
        "docs/ember-restart-sql-",
        "docs/ember-restart-structured-tools-",
        "docs/ember-restart-dynamics-",
        "scripts/ember_restart_measured_receipts",
        "tests/test_ember_restart_measured_receipts"
      ]
    },
    "EMBER-02B": {
      "mode": "only",
      "prefixes": [
        "configs/ember-restart-3b.json",
        "docs/ember-restart-3b-",
        "models/ember-restart-3b/",
        "tools/ember-restart-3b/",
        "receipts/ember-restart-3b/",
        "inference/ember-restart-3b/",
        "data/ember-restart-3b/",
        "tests/ember_restart_model/"
      ]
    },
    "EMBER-02C": {
      "mode": "only",
      "prefixes": [
        "docs/ember-restart-eval-",
        "docs/ember-restart-terminal-",
        "docs/ember-restart-browser-",
        "docs/ember-restart-audio-",
        "docs/ember-restart-image-",
        "manifests/ember-restart-eval-",
        "scripts/ember_restart_eval",
        "tests/test_ember_restart_eval",
        "docs/ember-restart-sql-",
        "docs/ember-restart-structured-tools-",
        "docs/ember-restart-dynamics-",
        "scripts/ember_restart_measured_receipts",
        "tests/test_ember_restart_measured_receipts"
      ]
    }
  },
  "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
  "architecture": {
    "headline_hypothesis": "Verified Expert Accretion",
    "owned_unified_decoder": true,
    "published_family_backbone_allowed": false,
    "sparse_differentiated_capacity": true,
    "task_level_expert_routing": true
  },
  "benchmark_custody": {
    "additional_direct_recovered": [
      "ARC-AGI 1",
      "ARC-AGI 2",
      "ARC-AGI 3"
    ],
    "broader_named_families_minimum": 31,
    "direct_recovered_minimum": 13,
    "no_silent_retirement": true,
    "operator_recollection_minimum": 15,
    "owned_checkpoint_binding_required": true,
    "recovered_operator_mandate": [
      "SWE-Bench Pro",
      "FrontierCode Diamond",
      "GDPval-AA",
      "GDPpdf",
      "Blueprint-Bench 2",
      "AutomationBench",
      "OSWorld-Verified",
      "Legal Agent Benchmark",
      "Humanity's Last Exam",
      "Terminal-Bench 2.1"
    ],
    "unrecovered_direct_names_minimum": 2
  },
  "conservation_hashes": {
    "authority_matrix_sha256": "CACB09B1CD16B3272DBE0EB0D35DC0B5B334B74F791D1ADE4BFC651F93C9F4DB",
    "governing_surfaces_sha256": {
      "docs/authority/CONTINUITY.md": "F406058BBE2B935E1FCCB12D02F620B37989CDA63B05CDF0CB74DEF2CF797D85",
      "docs/authority/GOVERNANCE.md": "186cdc1e2dcbd34f0dea1421e70cc8f70b7e9b906f3d04b2b2befdc5c69e980c",
      "README.md": "120D8D68C9C3D79E1F1D9D9CFA549EAB31A93B059C40394FA5E5B7A7FC5CA01A",
      "docs/authority/ember-authority-matrix.md": "CACB09B1CD16B3272DBE0EB0D35DC0B5B334B74F791D1ADE4BFC651F93C9F4DB",
      "docs/contracts/ember-floor-contract.md": "83816F1DE862F9DC4BBE90E73474F4E50F0E1AEF7C1A191F31C40683D0493AD1",
      "docs/contracts/goal-clear-protocol.md": "6A0A5D8BF04D22B374B197B2C6A380D80C893748BF38FAB706137EC47C33635C",
      "docs/contracts/goal-mode-mechanism.md": "F3D0A29007DB098FCEAEED650BCAE530A442E99598E8A9A092F47945A1C7D300",
      "docs/contracts/nc2-own-technique-contract.md": "A0A12328B2D96F6DF12BD7D51D029F88279436C9E1073835EDBC12E7C8B85B9C",
      "docs/contracts/registry-dispatch-gate-spec-v0.md": "6AC47945BAA555F159F4DE338D3E3241C9119E5684E5370707C3B3C11E90AF0F",
      "docs/spec/autonomy-relinquishment-ladder-v1.md": "36C23511461DA3AD5E988D4ED0C2193340E0F523D25886461D6026442798E0CB",
      "docs/spec/conditions-v1.md": "363B1A0E1D952ECA1B1DD70CC2239685EBC02A67816A3697872171E8D8256B37"
    }
  },
  "authority_only_goal": false,
  "destination": {
    "competitive_reference_parameters": [
      27000000000,
      31000000000
    ],
    "initial_total_parameter_band": [
      30000000000,
      35000000000
    ],
    "minimum_total_parameters_exclusive": 27000000000,
    "single_gpu_vram_gib": 24
  },
  "hard_rungs_total_parameters": [
    3000000000,
    7000000000,
    15000000000,
    27000000001
  ],
  "highest_amendable_authority": "docs/authority/GOAL.md",
  "invariant_sha256": "08A0EB7418C09A8088BE4658E10785107ABBB7507FC2DBCDC789936AA54E02A6",
  "lineage": {
    "borrowed_models_role": "frozen_reference_only",
    "forbidden_model_mediated_signals": [
      "weights",
      "outputs",
      "teachers",
      "judges",
      "filters",
      "ranks",
      "curricula",
      "stopping_decisions",
      "hidden_external_cognition"
    ],
    "published_ideas_allowed": true,
    "transparent_deterministic_tools_allowed": true
  },
  "model_birth": {
    "minimum_total_parameters": 3000000000,
    "parameter_shell_is_model_birth": false,
    "required_native_capabilities": [
      "text",
      "image",
      "audio",
      "reasoning",
      "structured_tool_use"
    ],
    "sufficient_training_required": true
  },
  "mutation_controls_required": [
    "invariant_tamper",
    "missing_discrepancy",
    "sub_3b_network",
    "missing_native_modality",
    "missing_native_reasoning",
    "borrowed_backbone",
    "model_mediated_signal",
    "mechanism_erasure",
    "missing_totality_member",
    "ambiguous_identity",
    "missing_goal_binding",
    "non_authority_completion_claim",
    "benchmark_obligation_erasure",
    "governing_surface_semantic_drift",
    "selection_duplicate_key",
    "selection_path_substitution",
    "historical_execution_reenable"
  ],
  "negative_evidence": {
    "may_delete_required_capability": false,
    "may_erase_research_family": false,
    "may_force_named_successor": false,
    "preserve_synergy_order_scale_modality_substrate_routing_precision_retests": true
  },
  "operator_relationship": {
    "behavior_tested": true,
    "dynamically_configurable": true,
    "explicit": true,
    "operator_retains_final_scope_authority": true,
    "revocable": true
  },
  "reasoning_evidence": {
    "checkpoint_bound": true,
    "forbidden_substitutes": [
      "borrowed_model",
      "search",
      "script",
      "verifier",
      "tool_wrapper",
      "human_intervention"
    ],
    "hidden_trace_disclosure_required": false,
    "required_axes": [
      "multi_step",
      "compositional",
      "counterfactual",
      "causal",
      "action_coherence",
      "component_deletion"
    ],
    "unseen_tasks_required": true
  },
  "required_future_artifact_fields": [
    "goal_id",
    "workstream_id",
    "next_executed_outcome"
  ],
  "required_governing_surfaces": [
    "docs/contracts/goal-clear-protocol.md",
    "docs/contracts/nc2-own-technique-contract.md",
    "docs/contracts/ember-floor-contract.md",
    "docs/contracts/goal-mode-mechanism.md",
    "docs/contracts/registry-dispatch-gate-spec-v0.md",
    "docs/spec/autonomy-relinquishment-ladder-v1.md",
    "docs/spec/conditions-v1.md",
    "docs/authority/ember-authority-matrix.md",
    "docs/authority/GOVERNANCE.md",
    "README.md",
    "docs/authority/CONTINUITY.md"
  ],
  "schema": "ember-authority-v1",
  "totality": [
    "creation_primitive",
    "foundation_model",
    "organism",
    "body",
    "general_local_ai_laboratory",
    "individual_local_ownership",
    "whole_stack_ownership",
    "operational_and_cognitive_self_sufficiency"
  ]
}
-->

## Public roadmap hierarchy

The complete milestone decomposition is published at
[`docs/roadmap/README.md`](../roadmap/README.md). It has exactly four
surfaces: this constitutional goal, twelve version-controlled milestone
contracts, one non-authoritative execution graph, and concrete GitHub
issues/pull requests. The decomposition and tracking surfaces cannot reduce,
defer, replace, or reinterpret this file.

## 1. One project, conserved in full

Ember is one clean-genesis sovereign foundation intelligence and one local AI
laboratory. Its totality is inseparable:

1. the creation primitive that lowers barriers to local foundation-model
   creation and ownership;
2. the sufficiently trained owned foundation model;
3. the organism whose verified experience changes useful neural state;
4. the ember-cli body, typed tools, memory, observation, and action;
5. the general local AI laboratory able to create materially different
   clean-genesis intelligences; and
6. individually owned local operation without mandatory hosted cognition,
   central control, subscription, or data upload.

A checkpoint, CLI, benchmark harness, training runtime, symbolic loop, parameter
shell, or laboratory wrapper cannot substitute for the totality.

## 2. Exact terms

- Ember means the complete project and conserved identity, not whichever
  component is currently visible.
- Ember model means a sufficiently trained clean-genesis checkpoint that meets
  the birth floor. Random weights, a smoke run, or allocated parameters do not.
- Research candidate means an explicitly identified experimental network or
  mechanism with no milestone credit before admission.
- Historical artifact means preserved evidence or implementation denied current
  execution and milestone authority.
- Borrowed reference means a frozen external model used only to measure a
  comparison point and never to supply learned or evaluative lineage signal.
- Parameter count means total unique stored neural parameters. Trainable and
  episode-active parameters are reported separately.
- Trained capacity means useful capacity supported by checkpoint-bound training
  and capability evidence, not allocated storage.
- Active capacity means parameters exercised for a declared episode.
- Checkpoint means exact bytes plus architecture, tokenizer, data, token,
  update/optimizer, parentage, and active-mechanism identity.
- Body means the real operator-facing perception, action, tool, memory, and
  observability surface attached to the owned model.
- Organism means the connected experience, neural update, verification,
  promotion, persistence, rollback, deletion, and non-regression loop.
- Laboratory means the local system in which Ember can design, create, train,
  verify, study, and operate clean-genesis intelligences.

Every current object exposes one unambiguous identity. The unqualified name
Ember cannot label a borrowed backend or unadmitted checkpoint.

## 3. Model birth, hard rungs, and destination

No newly created, trained, fine-tuned, grown, evaluated, or served Ember
research network may contain fewer than 3,000,000,000 total parameters.
Existing smaller artifacts are read-only history.

The first admissible 3B model and every 7B, 15B, and >27B rung are sufficiently
trained native text-image-audio foundation models with native reasoning and
structured tool use. No capability is deferred. Every rung binds to exact
checkpoint bytes, passes each modality, and shows no cross-modality regression.

The destination is an owned model strictly above 27B total parameters,
initially 30-35B, competitive with frozen 27B and 31B open-model references on
one 24 GiB GPU. A 30B model that performs like a 4B model fails.

## 4. Architecture and the headline research hypothesis

The target is an owned sparse unified decoder: a shared core plus independently
trainable differentiated expert banks, with only the episode-required expert
set active. Vision, audio, reasoning, tool, and other domain experts coexist in
the same decoder to limit cross-domain damage.

Raw image patches and audio frames project directly into decoder tokens. The
interface uses soft-token splicing, multimodal-span attention, and
two-dimensional rotary position structure. Published studies may motivate
properties. No published model family, copied implementation, or borrowed
weights become Ember's backbone.

The single headline causal hypothesis is Verified Expert Accretion: repeated
locally verified experience can grow useful persistent capacity beyond 27B
while active memory and episode-level training cost remain nearly constant, and
its advantage over equal-budget dense restarts widens with scale.

Exact-duplicate growth is invalid. Expert upcycling is asymmetric or partially
reinitialized. One candidate expert family trains at a time, while interacting
mechanisms remain available for explicit synergy, order, scale, modality,
substrate, routing, and precision tests.

## 5. Native reasoning is non-negotiable

Reasoning credit requires frozen unseen multi-step, compositional,
counterfactual, causal, and action-coherence tasks across text, mathematics,
code, images, audio, tools, and grounded interaction where applicable. It binds
to owned checkpoint bytes and degrades when responsible learned state is
deleted or rolled back.

Search, scripts, verifiers, tool wrappers, human intervention, and borrowed
models may expose or check behavior but cannot perform the load-bearing
inference and transfer credit to Ember. Correct final answers are insufficient
when memorization, leakage, shortcuts, or harness policy remain plausible.
Hidden internal trace disclosure is not required; behavioral and causal
evidence is.

## 6. Clean genesis and frozen-reference boundary

No borrowed weights, outputs, teachers, judges, filters, ranks, curricula,
stopping decisions, or hidden external cognition may shape an Ember lineage or
any intelligence created by Ember's laboratory. Published ideas and transparent
deterministic tools are allowed research inputs.

Borrowed models occupy explicit frozen reference seats only. Removing them must
not prevent creation, training, verification, or operation. Baseline work is a
bounded instrument and cannot displace owned creation.

## 7. Experience, memory, dreaming, tools, and world models

A local generator creates frontier tasks across code, mathematics, SQL, files,
browser and UI activity, images, audio, and laboratory research. A solver acts
through typed tools. Only independently verified trajectories may update
temporary neural state, create experts, or promote persistent capacity.

KV and context are perception and working memory. Episodic records are
replayable experience. Temporary adapters or fast weights are intermediate
consolidation. Durable parametric burns require transfer, controls,
non-regression, persistence, and deletion or rollback evidence. Predictive
planning, episodic replay consolidation, fast-weight sleep, and durable neural
promotion are distinct operations.

World models may support learned environment prediction, counterfactual task
generation, action simulation, cross-world transfer, and benchmark-world
construction. Symbolic traces and deterministic fixtures receive no learned
world-model credit.

The laboratory also studies transferable self-improvement processes recovered
from historical and modern research journals, laboratory notebooks, letters,
and documented practice across scientific, technical, artistic, and
professional fields. These sources motivate falsifiable process hypotheses;
their prose or authority is not copied into model capability credit.

## 8. Negative evidence preserves the research graph

A negative result constrains its tested mechanism, regime, order, scale,
modality, substrate, routing, precision, data, and budget. It remains evidence.
It does not kill, retire, indefinitely park, exclude, or delete a mechanism,
required capability, benchmark, modality, or research family; force a named
successor; or prohibit later composition tests. Only the operator can reduce
invariant scope.

Deletion and rollback tests establish causal attribution. They do not erase the
research object.

## 9. Whole-stack ownership and the local AI laboratory

Ember progressively owns data and tokenizer custody, training and inference
runtimes, attention and state, kernels, compiler, optimizer and update
computation, numerics, checkpointing, storage, routing, evaluation, deployment,
and the transformation of inference optimizations into training optimizations.

The laboratory lowers time, compute, data, expertise, and infrastructure
barriers to local foundation-model creation. Useful autonomous AI research must
emerge during bootstrap on a weeks-to-months horizon rather than waiting for
the finished >27B model. Transitional agents and the operator may help build
Ember, but none is permanent cognitive life support.

Each operator can own an independent Ember, its weights, memory, tools,
laboratory state, and created intelligences. Shared software and research are
optional; central cognition and control are not.

## 10. Body and operator relationship

ember-cli is Ember's real body and observation surface. Its minimum product
floor is the complete predecessor CLI surface plus goal mode, model and
training observation, typed tools, native multimodal interaction, memory
inspection, laboratory control, and truthful backend identity. The owned model
is the default once admissible. Until then, the interface states that no
admissible Ember model exists. Borrowed models are explicit reference seats.

Operational authority is dynamically configurable by operator, task, scope,
consequence, reversibility, and demonstrated trust. Modes are explicit,
inspectable, behavior-tested, and revocable. Ember may challenge an operator
with evidence and propose a relationship change; it cannot silently grant
itself authority. The operator retains voluntary direction and final scope.

## 11. Executable identity and evidence spine

Every claim joins architecture, checkpoint bytes, total, trainable, and active
parameters, trained tokens, tokenizer and data lineage, parentage, active
mechanisms, backend, benchmark protocol, comparator, capability result, and
deletion-sensitive evidence. The exact object is named at every boundary.

### Conserved benchmark custody

The exact recovered July mandate is: SWE-Bench Pro, FrontierCode Diamond,
GDPval-AA, GDPpdf, Blueprint-Bench 2, AutomationBench, OSWorld-Verified, Legal
Agent Benchmark, Humanity's Last Exam, and Terminal-Bench 2.1. ARC-AGI 1,
ARC-AGI 2, and ARC-AGI 3 raise the stable directly recovered lower bound to
thirteen. The operator's recollection is at least fifteen direct requests, so
at least two still-unrecovered names remain an explicit unresolved obligation;
they are not guessed, dismissed, or silently filled.

The broader named research and governance universe remains above thirty
families with distinct provenance classes. A pivot, blocker, frozen dataset,
harness, smoke, subset, control, borrowed result, or unrelated run never
retires or satisfies a named obligation. Only a result bound to the exact owned
checkpoint and required official/comparable boundary can receive owned-model
benchmark credit. Under the 3B genesis rule, the old 2.2B test subject remains
history; its unexecuted mandate transfers intact to the first admissible Ember
model rather than disappearing.

Every future pull request, experiment, receipt, configuration, and control
artifact names the active goal_id and the next executed model or capability
outcome it directly enables. Reports, wrappers, boards, and preparatory
machinery are not progress without that link.

## 12. Completion and precedence

docs/contracts/goal-clear-protocol.md defines the executable completion audit without
changing this goal. docs/authority/ember-authority-matrix.md maps D-001 through D-062 to
enforcement, historical evidence, and explicit open research. docs/authority/STATE.md resolves
every current model, checkpoint, backend, and benchmark class.

Evidence and historical artifacts never become authority. Subordinate contracts
carry the machine-checked conservation header and fail closed on contradiction.
Precedence is docs/authority/INVARIANT.md, then docs/authority/GOAL.md, then named subordinate contracts,
then implementation and evidence, then history.

No completion claim is valid unless the primitive, model, organism, body, and
laboratory totality and every hard-rung requirement pass together.

This master authority document itself creates, trains, evaluates, and serves
no network and claims no model, training, benchmark, or capability completion.
Any runtime named by a subordinate goal receives credit only through that
goal's own exact execution and evidence contract.

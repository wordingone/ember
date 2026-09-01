<!--
Provenance:
  Pinned to commit: 3d48d3870919bd04cec735f68d0fad45fcfae0b2
  Ingested: 2026-08-01
  Status: research annex — binding by incorporation into the EMBER-02 spec
-->

# Research Transcript and Evidence Audit

## From Experts to Artificial Physiology

*A compressed, source-grounded transcript on mixture-of-experts, cognitive functions, Ember, energy constraints, heterogeneous intelligence, and the closed-boundary one-GPU frontier*

**Participants:** User; OpenAI model  
**Prepared:** 1 August 2026  
**Ember source snapshot:** `wordingone/ember @ 3d48d3870919bd04cec735f68d0fad45fcfae0b2`

## Central questions

1. Should a transformer-centered agent perform every cognitive function internally, or should a more mature intelligence coordinate specialized learned, symbolic, procedural, sensory, memory, and control systems?
2. Under a strict all-inclusive boundary of one RTX 4090-class GPU plus a declared local host, what theoretical resource limits and experimentally demonstrated capability-time-energy Pareto frontier can be defended for a system created from random initialization?

---

# Reader's guide

This is an edited transcript, not a raw call log. Repetitions, backchannels, false starts, and some detours have been compressed. Selected quotations preserve the participants' words; punctuation and paragraph breaks are lightly normalized for readability without changing the quoted wording. The labels are exactly “User” and “OpenAI model,” as requested.

Every substantive scientific or engineering proposition is treated in one of three ways: supported by a primary or official source; qualified where the evidence is narrower than the conversation implied; or marked as an open hypothesis with the closest identifiable research prior. Ember-specific statements are pinned to one repository commit so an external reader can distinguish project intention from demonstrated capability. [E1–E5]

## Evidence-status legend

| **Status**               | **Meaning in this document**                                                                                                                                                                |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **PROJECT FACT**         | A statement about Ember's documented goal, mechanism, or current state at the pinned commit; not an independent scientific validation.                                                      |
| **ESTABLISHED**          | A result, mechanism, or historical fact well supported by primary literature or an official source.                                                                                         |
| **SUPPORTED, QUALIFIED** | The core claim has support, but scope, causality, or generality is narrower than the conversation suggested.                                                                                |
| **OPEN HYPOTHESIS**      | Plausible and connected to research priors, but not demonstrated for the proposed setting.                                                                                                  |
| **CORRECTION**           | A conversational claim was wrong, too broad, or used a term inaccurately.                                                                                                                   |
| **CONCEPTUAL PROPOSAL**  | A useful framework or vocabulary introduced in the conversation, not a field-standard result.                                                                                               |
| **BOUNDARY RESULT**      | A result about what can be bounded or compared after the accounting boundary is fixed. It may establish that the admissible empirical set is empty rather than estimate a capability level. |

## Table of contents

- Reader's guide
  - Evidence-status legend
- Executive synthesis
  - Nine conclusions an external reader should retain
- Part I — Compressed transcript
  - Experts, routers, and emergent specialization
    - A minimal technical model
  - From blank experts to developmental role priors
  - Brain organization and functional biomimicry
  - Memory, prediction, action, and persistent adaptation
  - Value, survival, sociality, and artificial life
  - What Ember actually aims to be
  - The compute ceiling: BF16, one-bit training, and selective precision
  - Sparsity, MoE, MoT, nesting, and global signals
  - Energy, benchmarks, and the invariant question
  - From architecture to physiology
    - Testing the one-word metaphors
  - Human modalities as lossy but structured traces
  - Toward a heterogeneous artificial physiology
- Part II — Claim audit and corrections
  - Corrections to the spoken exchange
  - Major claim ledger
- Part III — Cognitive functions and computational constructs
  - Mapping method: function, algorithm, implementation
  - Functional map
  - What should the transformer do?
  - Why tool-call tags are not themselves tools
  - A three-plane artificial physiology
- Part IV — A research program for Ember
  - The functional-role prior
  - Experimental ladder
  - Measurement contract
  - Failure modes and falsifiers
- Part V — The closed-boundary one-GPU frontier
  - The answer is a boundary result, not a frontier number
  - A valid boundary must separate learned imports from declared priors
  - What theory can actually bound
  - The RTX 4090 gives hard resource ceilings, not intelligence ceilings
    - Residency: ideal storage ceilings are not trainable-model ceilings
    - Roofline and seriality: peak FLOPs are rarely the active constraint
    - Energy is a measured integral, not a TDP multiplication
  - The strict empirical Pareto frontier is currently unpopulated
  - Frontier systems are target envelopes, not comparable creation points
  - A and B require separate Pareto surfaces
    - A — Less training to matched capability
    - B — More useful information processing per second and joule
  - The twelve bottlenecks become an experimental protocol
  - Implications for Ember
  - Falsifiable answer as of 1 August 2026
- Conclusion
  - The distilled hypotheses
- References
  - Ember project sources
  - Research and historical sources

# Executive synthesis

**The conversation's distilled thesis**

A capable local intelligence may be more compute-efficient and more persistent if it is not treated as one homogeneous transformer. A stronger candidate is a heterogeneous, continuously verified system in which broad functional responsibilities exist from the outset, while their capacity, internal representation, routing, and sub-specialization remain plastic.

The discussion began with a terminology problem: in a mixture-of-experts model, an “expert” is normally a learned subnetwork selected by a router, not a human-labeled expert in vision, memory, or planning. From there, the User proposed a narrower and more original hypothesis: predefine only that certain functional roles exist, while allowing their size, wiring, and internal competence to emerge through training.

Biology provides a serious prior for that possibility. Human brains are neither blank homogeneous networks nor rigid collections of isolated organs: development supplies regional, cellular, and circuit-level biases, while activity, plasticity, and neuromodulation refine distributed functions. This is evidence that structured development can produce intelligence; it is not proof that the same decomposition is optimal on silicon. [R9–R14]

The conversation then identified a candidate functional loop: experience must persist; memory must be retrieved; retrieved experience must improve prediction; prediction must guide action; action changes the world and produces new experience. That loop is more complete than “memory” alone, but it remains a scaffold rather than a definition of intelligence. [R13–R23]

The strongest engineering conclusion is already visible in contemporary agents: a coding agent's competence resides in the coupled system of model, context, files, web, tools, shell, programs, compilers, tests, and orchestration—not in weights alone. A `<tool-call>` token has no causal power by itself; an external runtime interprets and executes the protocol. [R17–R19]

For Ember, the repo-grounded question is not merely “Which architecture wins?” It is: under one 24 GiB GPU, what combination of sparse learned capacity, explicit memory, specialized computation, growth, verification, and low-precision execution maximizes durable capability per unit of energy, time, active compute, and memory? Ember's current constitution already names a sparse unified decoder, differentiated expert banks, task-level routing, an energy law, and verified expert accretion—but it explicitly reports that no current checkpoint is an admissible Ember model and that no complete neural self-improvement cycle is proven. [E1–E3]

**Closed-boundary result**

As of 1 August 2026, the tightest defensible answer is not a frontier capability number. Without a fixed task distribution, error target, time horizon, and complete host specification, a 4090 does not imply a nontrivial universal ceiling on general intelligence. It does impose hard state, rate, and energy envelopes. Under the stricter operational boundary posed here, the audited public set of general-purpose systems satisfying every condition is unpopulated: nearby studies demonstrate isolated memory, speed, or narrow-capability points but exempt preprocessing, import learned components, use pretrained agents, or omit all-in energy and information accounting. [R62–R87]

This second thread changes Ember’s burden of proof. Frontier models such as GLM-5.2, Kimi K3, DeepSeek-V4-Flash, and Inkling are capability and systems-engineering comparators, not points on the same creation frontier: their data acquisition, accelerator fleets, curation, teachers, post-training, and evaluation compute are not charged to one local machine. Ember must therefore publish its own matched, all-in Pareto points rather than infer feasibility from model parameter counts or vendor benchmark tables. [E1–E5, R82–R87]

## Nine conclusions an external reader should retain

1. An MoE expert is normally a conditionally activated learned subnetwork; its specialization is induced by routing and gradient updates, and may be messy, redundant, or unstable rather than human-legible.

2. The proposed “functional-role prior” is coherent: require the existence and interface of roles, but let capacity and internal organization develop. It has close priors in modular learning, cognitive architectures, global workspaces, progressive networks, and structure-growing methods; its benefit for general foundation models is unproven.

3. Biological functional specialization is real but distributed and developmental. Biomimicry should copy transferable principles, not anatomy.

4. Persistent intelligence likely requires multiple memory timescales and a loop linking experience, retrieval, prediction, action, feedback, and consolidation. Weights alone are not episodic memory.

5. A transformer is exceptionally strong at semantic representation, translation, synthesis, and open-ended coordination. It is not automatically the cheapest, most exact, or most reliable mechanism for every cognitive function.

6. Specialized systems—solvers, planners, graph models, databases, compilers, programs, kernels, and narrow predictors—can provide exactness, state, inductive bias, or energy efficiency that token generation does not.

7. Low-bit training does not eliminate all high-precision state. Selective high precision in the router has direct precedent, but the broader question is which computations require precision, not merely which named module receives it.

8. The proper experiment is comparative and energy-matched: dense unified model, homogeneous MoE, heterogeneous MoE, predefined-role system, and external heterogeneous runtime—evaluated with matched active FLOPs, wall time, VRAM, energy, data, and verification gates.

9. The strict one-GPU frontier is not currently a demonstrated capability curve. The defensible result is an accounting and resource envelope plus an empty qualifying empirical set. Ember’s first frontier contribution should therefore be a closed-boundary receipt that measures the entire run, including failed runs, local-host work, tools, verification, evaluation, and test-time reasoning.

# Part I — Compressed transcript

The following sections preserve the intellectual sequence of the exchange. Each section combines a short transcript summary, selected verbatim quotations, and a research-grounded adjudication.

## Experts, routers, and emergent specialization

The opening misunderstanding was useful: “experts” could mean researchers, human-defined specialties, or learned subnetworks. In standard sparse MoE transformers, the expert is usually a feed-forward subnetwork. A learned router scores the current token representation against available experts and sends the token to a small top-k subset. The expert and router co-adapt: routing determines what data each expert sees, and expert performance changes future routing gradients. [R2–R4]

**User — verbatim**

*“I never mentioned people.”*  
Editorial note: This correction established that “experts” meant components inside a mixture-of-experts model.

**User — verbatim**

*“What is the sort of technical term for the phenomena or mechanism that allows for or that sort of defines the creation and maintenance of experts within an MoE model”*

**OpenAI model — verbatim**

*“The word you're reaching for is ‘specialization’, or more precisely, ‘emergent specialization through co-adaptation.’”*  
Editorial note: The phrase is descriptively useful, but it is not a canonical field term or a single standardized mechanism.

**SUPPORTED, QUALIFIED:** Specialization can emerge through router–expert co-adaptation, but expert identities are not guaranteed to become clean human-readable domains. Load balancing, capacity limits, routing noise, data order, and optimization can yield redundancy, collapse, or unstable assignments. [R2–R4]

### A minimal technical model

For token representation x, a router commonly computes scores g(x) = Wᵣx, converts them to routing weights, and selects one or several experts. Only selected experts execute. Auxiliary losses or routing constraints are often used to prevent a few experts from receiving nearly all tokens. MoE is therefore one form of conditional computation: total parameter capacity can grow faster than per-token active compute. [R2, R3]

## From blank experts to developmental role priors

The User's central proposal was repeatedly narrowed. It was not to hand-code fixed “memory” or “vision” boxes with fixed budgets. It was to define the existence of broad responsibilities, then let training determine their capacity, connectivity, internal representation, and possibly their subdivision.

**User — verbatim**

*“Why not already predefine these specific functional categories, not necessarily the size”*

**User — verbatim**

*“I don't necessarily mean buckets or budgets, I mean only defining the existence of a role, and then the size and capacity is self-optimized by the router, I guess”*

**OpenAI model — verbatim**

*“The role is innate; the scale and wiring emerge.”*

**CONCEPTUAL PROPOSAL:** This document calls the idea a functional-role prior: the system begins with typed responsibilities or interfaces, while specialization and capacity remain learned. The exact phrase is proposed here, not established nomenclature.

Closest research priors include fixed cognitive modules in ACT-R and Soar; neural module networks; modular deep learning with learned routing; shared global workspaces; progressive networks; and methods that grow or prune network structure under resource constraints. These priors show that predefined interfaces, modularity, and adaptive capacity are technically possible. They do not show that a human-inspired role taxonomy improves a general foundation model under Ember's constraints. [R4–R8, R50–R53]

**OPEN HYPOTHESIS:** A system with predefined functional roles but plastic capacity will outperform a homogeneous transformer or homogeneous MoE at equal energy and active compute. This requires direct ablation; biological analogy is not evidence of machine advantage. [R4–R8, R50–R53]

## Brain organization and functional biomimicry

The discussion used high-level brain functions—perception, memory, action selection, prediction, executive control, salience, and homeostasis—as possible priors. The critical correction is that brain regions are not isolated experts. Functional specialization exists across cortical and subcortical systems, but behavior arises from overlapping, recurrent, and developmentally changing networks. [R9–R14]

**User — verbatim**

*“Doesn't it tell us though what the closest layout to human cognition is”*

**OpenAI model — verbatim**

*“The brain is proof of possibility, not proof of optimality.”*

**OpenAI model — verbatim**

*“Functional biomimicry, not biological mimicry.”*

The distinction is analogous to successful biomimicry in engineering: the 500 Series Shinkansen's nose is widely documented as being inspired by the kingfisher's low-splash water entry—not a falcon's head. The transfer was a functional principle addressing pressure waves and noise, not a literal bird reconstruction. [R57]

**SUPPORTED, QUALIFIED:** Human development supplies nonuniform structure and predispositions before mature learning, and plasticity refines them. That makes developmental priors a legitimate AI hypothesis. It does not identify which brain functions, boundaries, or learning rules transfer to silicon. [R9–R14]

## Memory, prediction, action, and persistent adaptation

The conversation moved from “memory is necessary” to a more operational loop. Parametric memory in weights stores compressed regularities learned during training. Context and caches maintain transient state. External stores can preserve episodes and provenance. But persistence becomes cognitively useful only when retrieval changes prediction or action and the resulting experience updates future behavior. [R13–R21]

**User — verbatim**

*“I think it's memory plus using that memory to improve prediction”*

**OpenAI model — verbatim**

*“Maybe it's not just memory, but memory in use.”*

World-model and reinforcement-learning research provides concrete versions of this loop: learned dynamics predict action-conditioned futures; search or policy selection chooses actions; environmental feedback supplies new data. External-memory systems and retrieval-augmented models show that learned controllers can use memory outside fixed weights. None of these establishes that prediction alone is sufficient for intelligence, value, abstraction, or social cognition. [R15–R23]

**SUPPORTED, QUALIFIED:** Some mechanism for retaining and using information across time is necessary for learning across time. “Memory plus prediction” is a strong organizing scaffold, not a complete or accepted definition of cognition. [R13–R23]

## Value, survival, sociality, and artificial life

The exchange then asked what prediction is for. In organisms, evolutionary fitness, homeostasis, reward learning, and social interaction shape behavior at different explanatory levels. In engineered agents, objectives are designed or learned; continued operation is not automatically equivalent to biological survival, and reward signals are not equivalent to conscious suffering. [R11, R12, R29–R32]

**User — verbatim**

*“There is no documented case of an intelligent system that didn't have any interaction with other intelligent systems. Even the environment or data sets and whatnot are a byproduct of intelligent systems”*

As an empirical statement about human intelligence and today's AI, the observation is strong: humans develop within cultural communities, and frontier models learn from human-created or human-mediated corpora. As a necessity theorem, it is unproven. Artificial-life systems and evolution experiments demonstrate adaptive complexity under non-social selection, but not human-level general intelligence. Social-brain research supports sociality as a major driver of primate cognition without proving that all possible intelligence requires another intelligence. [R29–R32]

**CORRECTION:** Binary hardware does not force binary cognition: modern neural computation uses high-dimensional continuous or quantized numerical states, and the same binary substrate can implement many representational regimes. Likewise, multicellularity is not universally “better” than unicellularity; it is advantageous in some ecological niches, while unicellular life remains extraordinarily successful.

## What Ember actually aims to be

The conversation initially relied too much on remembered descriptions of Ember. A repository-grounded reading changes the level of precision. At the pinned commit, Ember defines itself as a clean-genesis sovereign foundation intelligence, a local foundation-model creation primitive, a continuously improving organism, the ember-cli body, and a general local AI laboratory. The target is an owned 30–35B sparse unified text–image–audio decoder with native reasoning and structured tool use, created and operated on one 24 GiB GPU. [E1, E2]

**User — verbatim**

*“GitHub tell me exactly what the totality of ember aims to be”*

**PROJECT FACT:** Ember's constitution separates model, body, organism, laboratory, and creation primitive. It defines the organism as the connected experience, neural-update, verification, promotion, persistence, rollback, deletion, and non-regression loop; body capability is explicitly not model capability. [E2, E5]

Its architecture section names an owned sparse unified decoder with a shared core, independently trainable differentiated expert banks, task-level expert routing, and only the episode-required expert set active. Its headline causal hypothesis is Verified Expert Accretion: repeated locally verified experience can grow persistent capacity while active memory and episode-level training cost remain nearly constant, outperforming equal-budget dense restarts increasingly with scale. [E2]

The repo also defines an A/B/C evidence loop: act or propose; verify on frozen held-out tasks against an equal-budget control with before/after measurement; then burn in only verified gains, requiring deletion ablation and restart persistence. It separately names an energy law—capability per unit of pinned local compute/energy—and a growth law requiring function preservation and budget accounting. [E3]

**PROJECT FACT:** The target and mechanisms are project commitments, not achieved results. The current candidate has about 3.839B total parameters but only about 1.021B active and episode-trainable parameters, has observed 2,048 tokens, has specialist banks still at random genesis, and is explicitly not admitted. No complete neural verified-experience self-improvement cycle or field-level breakthrough is currently proven. [E1, E5]

## The compute ceiling: BF16, one-bit training, and selective precision

The User's resource concern is valid: naïve full-parameter BF16 training of a 30B model cannot fit within 24 GiB once weights, gradients, optimizer state, activations, and temporary buffers are counted. But “impossible with BF16” is too absolute. Sparse activation, CPU/NVMe offload, sharding, recomputation, low-rank or selective updates, optimizer-state compression, and staged growth can change the memory boundary—often at severe wall-clock cost. [E1–E3, R35, R36]

**User — verbatim**

*“Can we offload the sort of full precision or BF16 level of floating numbers to just the router”*

There is a direct research prior. Switch Transformer introduced “selective precision,” keeping router computations in float32 while training the rest of the model in bfloat16 to improve stability. That supports preferential precision for routing, not the stronger claim that only the router needs high precision. [R3]

BitNet-style training quantizes the forward weights to very low precision, but training generally retains higher-precision latent weights and uses higher-precision gradients, optimizer accumulators, activations, or normalization operations. A “1-bit model” therefore does not imply a one-bit end-to-end training memory footprint. The principal empirical question is where precision is load-bearing for optimization and inference under a complete memory-and-energy audit. [R46, R47]

**OPEN HYPOTHESIS:** Ember could keep routing, normalization, accumulation, or a small shared control core at higher precision while using low-bit expert weights and activations elsewhere. The exact partition must be found experimentally; component names are a weaker guide than numerical sensitivity and error propagation. [R3, R46, R47]

## Sparsity, MoE, MoT, nesting, and global signals

Sparsity is the broader principle: some weights, activations, tokens, attention edges, experts, or time steps are inactive. Sparse MoE is one implementation in which only a subset of experts executes per token or episode. MoE and sparsity are therefore not synonyms. [R2–R4]

Mixture-of-Transformers (MoT) is a multimodal design that decouples non-embedding transformer parameters by modality while retaining global self-attention across modalities. The conversation's earlier description—“several networks with shared global attention”—was directionally useful but too coarse: the proposed pathways remain components of one coupled model rather than independent complete brains. The paper reports substantial training-compute reduction in its tested multimodal settings; it does not establish a universal speed advantage over every unified design. [R48]

**User — verbatim**

*“can an MOE be nested within an MOT”*

Yes as an architectural construction: modality-specific pathways can themselves contain conditional experts, creating sparsity at more than one level. That does not guarantee efficiency. Routing overhead, communication, load imbalance, duplicated capacity, and poor specialization can erase the theoretical advantage. The scientific question becomes where modularity belongs and what information must remain shared. [R4, R48]

Official Gemma 4 documentation provides a useful contrast. The 12B Unified model uses an encoder-free unified decoder in which raw image patches and audio waveforms are projected into the shared sequence. The 26B A4B model uses an MoE configuration with a vision encoder and a large expert bank. These coexistence choices illustrate that “unify versus specialize” is an empirical axis, not a settled doctrine. [R49]

**SUPPORTED, QUALIFIED:** Biological neuromodulation motivates a separate low-bandwidth control or learning plane that changes gain, plasticity, salience, or resource allocation across local circuits. Translating this into shared AI control signals is coherent, but the mapping is functional, not homologous. [R11, R12]

## Energy, benchmarks, and the invariant question

**User — verbatim**

*“what is the relationship between energy and intelligence”*

No accepted scalar law converts joules into intelligence. Physics imposes lower bounds on irreversible computation, brains operate under severe metabolic budgets, and machine-learning scaling laws relate loss to model size, data, and compute over specific regimes. None provides a substrate-independent intelligence-per-energy equation. [R33–R36]

The practical research frame is nonetheless strong: measure useful, persistent capability under explicit budgets of energy, wall time, memory, active FLOPs, data, and interaction. This avoids rewarding a system merely for spending more resources. It also aligns with Ember's documented P1 energy law and matched-control verification requirements. [E2, E3, R33–R37]

The benchmark history required correction. Alfred Binet and Théodore Simon developed early intelligence tests in the first decade of the twentieth century to identify schoolchildren needing educational support. Large-scale military testing came later with the U.S. Army Alpha and Beta tests during World War I. The conversation's “post-war, wars and factories” origin story was therefore inaccurate. [R55, R56]

**SUPPORTED, QUALIFIED:** Many benchmark families become saturated, contaminated, optimized against, or too narrow as models improve, producing a recurring evaluation chase. It is too broad to say the entire 2026 benchmark landscape is saturated. Energy and time are often important deployment metrics but are not formal dimensions of every benchmark. [R37]

## From architecture to physiology

**User — verbatim**

*“One thing I question is Why architecture”*

The canonical computer-science use of “architecture” was formalized at least by the 1964 IBM System/360 paper, which distinguished the programmer-visible conceptual structure and functional behavior of a machine from its implementation. It is safer to call this a canonical early formulation than to claim it was the absolute first use. [R54]

The User's architectural-profession perspective sharpened the metaphor. Architecture no longer means only static form: CAD, BIM, simulation, parametric modeling, occupancy analysis, and lifecycle performance have made the discipline increasingly dynamic. Even so, “architecture” tends to foreground organization; it does not automatically foreground metabolism, learning, regulation, memory consolidation, or continual adaptation.

**User — verbatim**

*“naming things and defining something is extremely important because … the token itself, whatever word is chosen really heavily influences the direction in which something carries forward”*

Terminology and framing can influence the questions researchers notice and the alternatives they compare, but no word deterministically fixes a field's trajectory. The conversation tested one-word candidates and found a grammatical constraint: “organism” names what a thing is, whereas “architecture” names a property it has. “Physiology” can perform the latter job: one may ask what a system's physiology is—how information, control, memory, energy, learning, and action operate over time. [R60]

**OpenAI model — verbatim**

*“Architecture describes the arrangement of the machinery; physiology would describe the recurring processes by which information becomes experience, experience changes prediction, prediction guides action, and action generates the next experience.”*

**CONCEPTUAL PROPOSAL:** Use architecture and physiology as complementary levels. Architecture describes relatively stable organization and interfaces; physiology describes operational dynamics, flows, regulation, learning timescales, and resource use. “Artificial physiology” is not a consensus replacement term for AI architecture.

### Testing the one-word metaphors

| **Word**         | **Grammatical test**      | **What it reveals**                        | **What it hides**                               |
|------------------|---------------------------|--------------------------------------------|-------------------------------------------------|
| **Architecture** | What is its architecture? | Organization, interfaces, flow             | Can imply design-first or relative stability    |
| **Physiology**   | What is its physiology?   | Function over time, regulation, adaptation | May import biological assumptions               |
| **Metabolism**   | What is its metabolism?   | Energy/resource conversion                 | Too narrow for semantics and structure          |
| **Ecology**      | What is its ecology?      | Relations to environments and other agents | Describes context more than internal function   |
| **Development**  | What is its development?  | Growth, plasticity, maturation             | Names a process, not the whole operating system |
| **Constitution** | What is its constitution? | Persistent rules and composition           | Weak on ongoing activity and learning           |

## Human modalities as lossy but structured traces

**User — verbatim**

*“using the output of the origin in order to infer/pattern extract is an extremely lossy way of capturing that intelligence”*

The hypothesis distinguishes cognition from its traces. A sentence is a severe compression of the perception, memory, bodily state, intention, social context, and deliberation that produced it. Static images and audio preserve other information but still do not expose the full learning process or causal sensorimotor loop. Symbol-grounding and embodied-cognition research supplies close theoretical prior for the concern that form alone does not guarantee grounded meaning. [R24–R28]

The claim needs two qualifications. First, not all multimodal training data is simply an output of human cognition: photographs and recordings also capture nonhuman physical structure, although their capture, selection, annotation, and distribution are human-mediated. Second, language is not merely lossy noise. It is an extraordinarily structured cultural distillation containing compressed evidence about causality, social relations, abstraction, values, tools, and the world. [R24–R28, R58, R59]

**OPEN HYPOTHESIS:** A major cause of frontier training cost is inverse reconstruction: inferring the hidden processes of human cognition from compressed artifacts emitted by those processes. Grounding and representation studies make the hypothesis plausible, but there is no established causal result showing that this is the dominant source of scaling cost. [R24–R28, R58, R59]

## Toward a heterogeneous artificial physiology

**OpenAI model — verbatim**

*“A transformer should not be presumed to be the entire cognitive substrate.”*

**OpenAI model — verbatim**

*“The transformer is best cast as a semantic generalist and computational diplomat.”*

The final technical question asked whether a transformer plus a Claude Code– or Codex-like harness should handle every function itself. The evidence favors a qualified division of labor. Transformers are powerful general-purpose semantic models and can approximate many algorithms. But representability is not the same as reliable learnability, energy efficiency, persistence, or formal guarantee. A solver can certify consistency; a database can preserve dated state; a compiler can deterministically translate a program; a CUDA or Triton kernel can execute a repeated primitive efficiently; a graph model can impose relational structure; a planner can search explicit futures. [R17–R19, R38, R40–R45]

Modern coding agents already instantiate a heterogeneous runtime. The model interprets and proposes; context holds temporary state; files store persistent artifacts; retrieval locates information; the web supplies observations; shell and Python perform actions; compilers and interpreters turn procedures into execution; tests, linters, theorem provers, and solvers return structured error signals; orchestration determines what happens next. Capability belongs to the coupled loop. [R17–R19]

**OPEN HYPOTHESIS:** A more evolved general intelligence will benefit from additional specialized computational modules coordinated by a semantic model and an executive control plane. Hybrid systems already outperform monolithic generation in specific domains; the strongest general claim remains unproven and must include interface, routing, and communication costs. [R15–R23, R41–R45]

# Part II — Claim audit and corrections

## Corrections to the spoken exchange

| **Conversational claim**                                                   | **Audit result**              | **Corrected formulation / evidence**                                                                                                                                                                               |
|----------------------------------------------------------------------------|-------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **“Emergent specialization through co-adaptation” is the technical term.** | Too strong.                   | It is a useful descriptive phrase, not a single canonical name. Relevant terms include expert specialization, learned routing, conditional computation, load balancing, and router–expert co-adaptation. [R2–R4] |
| **MoE experts become clean domains such as vision or language.**           | Not generally established.    | Experts may specialize, overlap, duplicate one another, collapse, or remain difficult to label. [R2–R4]                                                                                                          |
| **Brain regions are separate cognitive experts.**                          | Oversimplified.               | Regional biases are real, but cognition is distributed, recurrent, and developmentally plastic. [R9–R14]                                                                                                         |
| **The brain's layout proves the best AI layout.**                          | Invalid inference.            | It proves that one structured, energy-constrained biological route can realize human cognition; optimality and substrate transfer remain open.                                                                     |
| **Memory plus prediction defines intelligence.**                           | Useful but incomplete.        | It omits goals/value, action selection, abstraction, social learning, self-monitoring, and implementation constraints. [R13–R23]                                                                                 |
| **Intelligence requires interaction with other intelligent systems.**      | Unproven necessity claim.     | All known human and frontier-AI cases are socially or culturally entangled, but that observation does not exclude solitary intelligence in principle. [R31, R32]                                                 |
| **Reward and punishment are interchangeable with suffering.**              | Category error.               | Reward is an optimization or learning signal. Suffering is a contested phenomenal and ethical property, not implied by scalar feedback. [R12]                                                                    |
| **Binary substrate implies binary cognition.**                             | False.                        | Binary hardware can implement continuous, probabilistic, symbolic, analog-emulated, or quantized representations.                                                                                                  |
| **Multicellular organisms are fundamentally better at survival.**          | Too broad.                    | Fitness is niche-dependent; unicellular lineages remain dominant and highly successful.                                                                                                                            |
| **Mamba is a transformer variant.**                                        | Incorrect.                    | Mamba is a selective state-space sequence model proposed as an alternative to attention-based transformers. [R39]                                                                                                |
| **Weights provide long-term experiential memory.**                         | Needs distinction.            | Weights hold parametric regularities; episodic, dated, revisable experience usually needs state outside fixed weights or an online-learning mechanism. [R15, R16]                                                |
| **A 30B target is impossible with BF16.**                                  | Too absolute.                 | Naïve full-state BF16 training is incompatible with 24 GiB, but sparsity, offload, recomputation, selective updates, staged growth, and compression alter the boundary—often with major time costs.                |
| **Starting with one-bit weights eliminates high-precision training.**      | Incorrect.                    | BitNet-style forward quantization typically retains higher-precision latent weights and training state. [R46, R47]                                                                                               |
| **Full precision could live only in the router.**                          | Unproven, with a close prior. | Switch used float32 router computation with bfloat16 elsewhere, but other operations and training state may still require precision. [R3]                                                                        |
| **MoT is several independent transformer networks sharing attention.**     | Oversimplified.               | MoT decouples non-embedding parameters by modality while preserving global cross-modal self-attention in one coupled model. [R48]                                                                                |
| **Gemma 4 12B has a unified encoder and decoder.**                         | Incorrect.                    | The official 12B Unified configuration is encoder-free and decoder-only; image patches and audio waveforms are projected into the shared decoder sequence. [R49]                                                 |
| **IQ testing began postwar for wars and factories.**                       | Historically incorrect.       | Binet–Simon testing began before World War I for educational triage; Army Alpha/Beta later scaled group testing in wartime. [R55, R56]                                                                           |
| **IBM invented the word architecture for computing in the late 1950s.**    | Not proven as stated.         | The 1964 System/360 paper is a canonical early formalization of architecture as programmer-visible structure distinct from implementation. [R54]                                                                 |
| **The 2026 benchmark landscape is saturated.**                             | Too broad.                    | Many benchmarks saturate or lose diagnostic value; others remain difficult, and evaluation continues to evolve. [R37]                                                                                            |
| **All AI training modalities are outputs of human cognition.**             | Overbroad.                    | Text and code are largely human-produced; images/audio also encode nonhuman physical structure, though data pipelines remain heavily human-mediated. [R24–R28]                                                   |
| **Scaling cost is caused by reconstructing cognition from its outputs.**   | Open causal hypothesis.       | Grounding and embodiment research provide prior, but no accepted decomposition identifies this as the dominant cost. [R24–R28, R58, R59]                                                                         |

## Major claim ledger

| **Proposition**                                                                             | **Status**                       | **Basis / nearest prior**                                                                                                                                          |
|---------------------------------------------------------------------------------------------|----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **MoE routing enables more total parameters than active per-token compute.**                | ESTABLISHED                      | Conditional expert activation is the core sparse-MoE mechanism. [R2, R3]                                                                                         |
| **Router and experts co-adapt during gradient training.**                                   | ESTABLISHED                      | Routing controls expert data exposure; expert losses shape router gradients. [R2–R4]                                                                             |
| **Experts naturally acquire stable human-readable cognitive roles.**                        | OPEN HYPOTHESIS                  | Not guaranteed; specialization can be entangled or unstable. [R2–R4]                                                                                             |
| **Predefined role interfaces with learned capacity are technically feasible.**              | SUPPORTED, QUALIFIED             | Modular architectures, cognitive architectures, progressive networks, and structure learning provide priors. [R4–R8, R50–R53]                                    |
| **Such roles improve a general foundation model under local-compute constraints.**          | OPEN HYPOTHESIS                  | Requires matched-budget ablation; no general result establishes it.                                                                                                |
| **The developing brain combines prior structure and plastic refinement.**                   | SUPPORTED, QUALIFIED             | Strong developmental-neuroscience support; boundaries are distributed rather than clean modules. [R9–R14]                                                        |
| **Brain-inspired function decomposition is optimal for AI.**                                | OPEN HYPOTHESIS                  | Biology supplies existence proofs and candidate principles, not silicon optimality.                                                                                |
| **Persistent learning needs information retained across time.**                             | ESTABLISHED                      | By definition, adaptation across episodes requires state or parameter change that survives the episode. [R13–R16]                                                |
| **External memory can complement parametric memory.**                                       | ESTABLISHED                      | DNC and RAG are direct examples. [R15, R16]                                                                                                                      |
| **World models connect memory/prediction to action.**                                       | SUPPORTED, QUALIFIED             | Demonstrated in controlled domains; general world modeling remains difficult. [R20–R23]                                                                          |
| **Social and cultural interaction is central to human intelligence.**                       | SUPPORTED, QUALIFIED             | Strong evidence for humans; not a theorem about all possible intelligence. [R31, R32]                                                                            |
| **Language-only learning necessarily cannot yield meaning.**                                | Contested / qualified            | Symbol-grounding critiques are strong, but language models recover substantial conceptual structure; sensorimotor alignment remains weaker. [R24–R28, R58, R59]  |
| **Human artifacts are compressed traces of cognition.**                                     | SUPPORTED, QUALIFIED             | True as an information-loss observation, but artifacts are also rich cultural distillations and multimodal data contains world structure.                          |
| **Inverse reconstruction explains frontier compute requirements.**                          | OPEN HYPOTHESIS                  | No decisive causal evidence; closest priors are grounding, embodiment, and multimodal representation studies. [R24–R28, R58, R59]                                |
| **Selective full precision in the router can stabilize low-precision MoE training.**        | ESTABLISHED in a specific design | Switch Transformer used float32 routing with bfloat16 elsewhere. [R3]                                                                                            |
| **One-bit pretraining removes high-precision state.**                                       | Refuted as a general claim       | Low-bit forward weights coexist with higher-precision latent/training state. [R46, R47]                                                                          |
| **MoE can be nested within modality-specific transformer pathways.**                        | Architecturally feasible         | Straightforward composition; net efficiency and quality are empirical. [R4, R48]                                                                                 |
| **Global low-bandwidth modulation can coordinate local modules.**                           | SUPPORTED as a design prior      | Biological neuromodulation and neural global-workspace work motivate it; AI benefit is setting-dependent. [R5, R11, R12]                                         |
| **Tool-using LLM agents are already system-level rather than model-only.**                  | ESTABLISHED                      | ReAct, Toolformer, and cognitive-architecture analyses explicitly couple models to actions and memory. [R17–R19]                                                 |
| **Specialized computation can dominate an LLM for exact or repeated tasks.**                | ESTABLISHED in many niches       | SAT/SMT, compilers, numerical optimization, kernels, and narrow predictors provide guarantees or efficiency unavailable from unconstrained generation. [R40–R45] |
| **A heterogeneous artificial physiology is the most likely route to general intelligence.** | OPEN HYPOTHESIS                  | Supported by many successful hybrids, but no comparative theorem or decisive general experiment exists.                                                            |
| **Energy-normalized capability is a better Ember objective than parameter count alone.**    | PROJECT PRINCIPLE / OPEN METRIC  | Ember codifies this as an energy law; operationalizing “capability” remains benchmark-dependent. [E2, E3, R33–R37]                                               |
| **Ember currently demonstrates its target organism.**                                       | False as a current-state claim   | The repo explicitly denies model admission and a complete neural verified-experience loop. [E1, E5]                                                              |

# Part III — Cognitive functions and computational constructs

## Mapping method: function, algorithm, implementation

A one-to-one mapping such as “hippocampus = vector database” is a category error. Following Marr's distinction, it is more rigorous to separate: (1) the function or problem being solved; (2) the algorithm and representation used; and (3) the physical or software implementation. The same function may have several implementations, and one implementation may participate in several functions. [R1]

**CONCEPTUAL PROPOSAL:** The table below is a functional engineering map, not a claim of biological homology. “Closest computational constructs” means mechanisms whose inductive biases, state model, guarantees, or resource profile make them plausible participants in that function.

## Functional map

| **Cognitive function**                     | **Candidate constructs**                                                               | **Why this mapping is plausible—and its limit**                                                                                                                                   |
|--------------------------------------------|----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Sensory acquisition and preprocessing**  | CNNs; vision/audio encoders; signal processing; event cameras; spiking neural networks | Exploit locality, frequency, temporal events, or sensor physics before semantic abstraction. SNN energy benefits depend strongly on neuromorphic hardware. [R40, R61]           |
| **Semantic abstraction and language**      | Transformers; multimodal foundation models                                             | Flexible contextual representation, cross-domain translation, synthesis, instruction following, and open-ended generalization. [R38]                                            |
| **Working memory**                         | Context window; KV cache; structured scratch state; blackboard; recurrent state        | Keeps goals, observations, hypotheses, and intermediate results available across steps. Prompt text is one implementation, not the function itself. [R5, R7, R8, R19]           |
| **Global coordination**                    | Shared workspace; broadcast bus; typed event system; executive state                   | Allows specialized processes to expose selected information without sharing all weights or all internal state. [R5]                                                             |
| **Episodic memory**                        | Append-only event log; trajectory store; temporal database; experience replay          | Preserves what happened, when, under what conditions, with provenance and possible counterfactual replay. [R13–R16]                                                             |
| **Semantic memory**                        | Model weights; knowledge graph; database; RAG index                                    | Stores compressed regularities or explicit factual relations. External stores are easier to update, inspect, date, and source than weights. [R15, R16]                          |
| **Associative retrieval**                  | Embedding index; learned retriever; content-addressable memory                         | Finds relevant items from partial cues; must be governed by relevance, confidence, and provenance policies. [R15, R16]                                                          |
| **Relational and spatial representation**  | GNNs; scene graphs; factor graphs; causal graphs; object-centric models                | Makes entities and relations explicit, useful where topology or persistent objects are part of the problem. [R41]                                                               |
| **World dynamics and prediction**          | State-space models; world models; simulators; differentiable physics; causal models    | Predicts how states evolve, ideally conditioned on action. Transformers can participate, but explicit state/dynamics may reduce search. [R20, R21, R39]                         |
| **Formal deduction and consistency**       | SAT/SMT solvers; theorem provers; proof assistants; type systems; model checkers       | Once formalized, these systems provide exact search, contradiction detection, or machine-checkable certificates. [R42, R43]                                                     |
| **Planning and sequential action**         | Model-based RL; tree search; classical planners; MPC; MCTS                             | Compares action-conditioned futures rather than generating only one continuation. [R20–R23]                                                                                     |
| **Resource allocation and scheduling**     | Linear, mixed-integer, quadratic, and constraint programming                           | Exploit known objective and constraint structure; can provide optimality bounds or infeasibility certificates.                                                                    |
| **Procedural memory and reusable skills**  | Python functions; shell scripts; programs; workflows; policy networks                  | Compiles successful behavior into reusable, testable procedures instead of regenerating every step in language.                                                                   |
| **Translation to execution**               | Compiler; interpreter; runtime; type checker                                           | Transforms high-level intent or code into executable operations and supplies deterministic diagnostics.                                                                           |
| **Low-level motor primitives**             | CUDA/Triton kernels; device libraries; RPC calls; OS operations                        | Execute repeated, narrow operations with predictable semantics and high hardware efficiency.                                                                                      |
| **Fast narrow judgment**                   | XGBoost; random forests; linear/GLM models; calibrated classifiers                     | For structured, stable tasks, may be cheaper, more interpretable, and easier to calibrate than a large model. [R44, R45]                                                        |
| **Executive control**                      | Router; scheduler; critic; uncertainty estimator; stopping policy; budget allocator    | Chooses which kind of computation to invoke, how much resource to spend, and when evidence is sufficient. Broader than a token-level MoE router. [R3–R5, R19]                   |
| **Salience, value, and global modulation** | Reward/value models; novelty; risk constraints; confidence; urgency; energy budgets    | Changes attention, routing, learning rate, replay, or exploration without carrying all task content. Functional analogy to neuromodulation, not biological identity. [R11, R12] |
| **Continual learning and consolidation**   | Replay; adapters; parameter isolation; skill synthesis; distillation; network growth   | Balances stability and plasticity over several timescales and turns verified episodes into durable changes. [R13, R14, R50–R53]                                                 |
| **Social and cultural learning**           | Multi-agent protocols; shared artifacts; debate; imitation; curricula; institutions    | Transfers knowledge and norms across agents; central to human development, but not proven necessary for every possible intelligence. [R31, R32]                                 |
| **Metacognition and verification**         | Calibration; critics; tests; audits; provenance; deletion ablations; matched controls  | Estimates what is known, detects error, and binds claims to evidence. Ember's receipt and gate system is a project-specific implementation. [E3, R19]                           |

## What should the transformer do?

The transformer should be favored when the problem is semantically ambiguous, the ontology is incomplete, representations must be invented or translated, and flexible transfer matters more than exact guarantees. It is especially strong as an interface among human language, code, images, plans, tools, memories, and formal systems. [R17–R19, R38]

A specialized mechanism should be favored when the state must persist, the representation is known, a formal guarantee matters, the operation repeats frequently, latency or energy dominates, or isolated online updates are desirable. The practical design question is not “Can a transformer approximate this computation?” but four separate questions:

1. Can it represent the computation?

2. Can training reliably discover and retain it?

3. Can it execute it at the required energy, latency, and memory cost?

4. Can it provide the required correctness, provenance, or safety guarantees?

**OpenAI model — verbatim**

*“Predefine the existence and interface of certain functional roles, but do not predefine their eventual capacity, internal representation, or degree of specialization.”*

## Why tool-call tags are not themselves tools

A modern agent may serialize internal state and actions as text such as \`\<system-prompt\>\`, `<tool-call>`, or \`\<read\>\`. The token sequence is a protocol message. It becomes causally effective only because software outside the transformer parses it, validates permissions and types, invokes a function, changes an environment, and returns an observation. The intelligence is therefore distributed across the language model and the runtime that gives selected symbols operational semantics. [R17–R19]

Text is currently attractive as an inter-module protocol because it is model-friendly, portable, loggable, and human-auditable. It is also verbose and can be lossy. A more mature physiology may exchange typed objects, graphs, tensors, executable plans, or latent messages internally while preserving a textual audit trace for people.

## A three-plane artificial physiology

| **Plane**          | **Examples**                                                                 | **Primary role**                                    |
|--------------------|------------------------------------------------------------------------------|-----------------------------------------------------|
| **Content plane**  | Percepts, concepts, memories, hypotheses, plans, programs, world states      | Carries task-specific information.                  |
| **Control plane**  | Routing, priority, confidence, stopping, permissions, latency/energy budgets | Determines what computation happens where and when. |
| **Learning plane** | Error, reward, novelty, replay, plasticity, consolidation, growth, rollback  | Determines what changes persist after experience.   |

The planes should interact but need not share the same representation, numerical precision, update frequency, or hardware path. This directly develops the User's observation that biological global modulatory signals operate through channels distinct from ordinary fast synaptic signaling. [R11, R12]

# Part IV — A research program for Ember

## The functional-role prior

The proposed research object is neither a rigid hand-engineered cognitive architecture nor a fully homogeneous neural network. It is a developmental system with a small set of typed responsibilities and a large amount of learned freedom.

**CONCEPTUAL PROPOSAL:** Initialize roles such as semantic integration, episodic memory, world modeling, planning, verification, action/skill execution, and consolidation. Predefine interfaces and accountability, not internal algorithms or permanent budgets. Allow roles to grow, split, merge, retire, share subspaces, or delegate to external deterministic systems.

This formulation aligns unusually well with Ember's own constitutional language: shared core, differentiated expert banks, episode-required activation, expert accretion, model/body distinction, explicit memory and tools, and an act–verify–burn-in organism loop. The new contribution would be to make functional responsibility itself an experimental variable rather than assuming homogeneous experts or fixed modality banks. [E2, E3, E5]

## Experimental ladder

| **Experiment**                        | **Arms / mechanism**                                                                                                            | **Question answered**                                                                                                                                     |
|---------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| **E0 — Immutable baseline**           | Dense unified decoder and current harness                                                                                       | Pin data, tokenizer, hardware, wall time, energy method, active FLOPs, peak VRAM, and evals. Establish reproducible baseline.                             |
| **E1 — Precision localization**       | BF16 baseline; float32 router/BF16 body; low-bit experts with higher-precision router/control; alternative precision partitions | Test whether routing or other operations are uniquely precision-sensitive. Include total training-state memory, not only served weights. [R3, R46, R47] |
| **E2 — Low-bit total-cost audit**     | BitNet-style forward quantization with explicit latent-weight, gradient, optimizer, activation, and temporary-buffer accounting | Determine whether low-bit training moves or truly bends the memory/energy frontier.                                                                       |
| **E3 — Modularity ablation**          | A dense unified model; homogeneous MoE; heterogeneous MoE; predefined-role model; external heterogeneous runtime                | Match data, active FLOPs, wall time, energy, and trainable state. Test whether role priors beat emergence or merely add interface cost.                   |
| **E4 — Control-plane separation**     | Shared content representation with distinct routing, confidence, novelty, and budget channels                                   | Test the neuromodulation-inspired hypothesis without claiming biological equivalence. [R5, R11, R12]                                                    |
| **E5 — Multi-timescale memory**       | Working state, episodic log, semantic retrieval, procedural skills, periodic consolidation                                      | Apply deletion and restart gates so every claimed gain has a known storage locus. [E3, R13–R16]                                                         |
| **E6 — Heterogeneous compute router** | Transformer plus SMT/theorem prover, planner, GNN/world state, code execution, compiler, and kernels                            | Route by expected correctness, latency, energy, and uncertainty. Include a model-only arm to measure system contribution. [R17–R23, R41–R45]            |
| **E7 — Verified expert accretion**    | Grow or add experts only after held-out gains clear matched controls; preserve rollback and deletion tests                      | Test Ember's headline hypothesis against equal-budget dense restarts and non-growing sparse controls. [E2, E3, R50–R53]                                 |
| **E8 — Role plasticity**              | Allow roles to split, merge, shrink, or retire under explicit penalties and verification                                        | Test whether predefined roles are useful scaffolds or prisons. Record interface and communication costs.                                                  |

## Measurement contract

Parameter count cannot be the principal success metric. Each experiment should report a capability vector and its resource denominator. At minimum:

- Capability per joule or best available energy proxy, with hardware and measurement method pinned.

- GPU-hours and wall-clock time to reach a declared capability threshold.

- Peak and steady-state VRAM; CPU RAM and storage traffic when offload is used.

- Total, trainable, served, active, and episode-updated parameters reported separately.

- Active FLOPs per token or step, throughput, and model-FLOPs utilization where meaningful.

- Held-out task performance, long-horizon completion, calibration, exact correctness, and failure recovery.

- Retention, forgetting, transfer, data efficiency, and improvement from verified experience.

- Matched-control delta, deletion ablation, restart persistence, reproducibility, and provenance.

- Router balance, expert utilization, communication overhead, and specialization stability.

- System-versus-model attribution: remove tools, memory, or modules and measure what disappears.

Ember's existing receipt discipline, equal-budget controls, before/after evaluation, deletion gate, restart gate, and no-capability-credit boundary provide a strong governance skeleton for this contract. The missing work is empirical: execute the comparisons at credible scale and report negative evidence without silently retiring mechanisms. [E1–E5]

## Failure modes and falsifiers

| **Failure mode**              | **Mechanism**                                                                    | **Decisive falsifier**                                                                                                |
|-------------------------------|----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| **Wrong role ontology**       | Human labels do not match useful machine decomposition.                          | Role-prior arm fails to beat homogeneous MoE; learned routing consistently bypasses predefined interfaces.            |
| **Interface bottleneck**      | Typed boundaries discard useful cross-domain information.                        | Dense/shared arms transfer better at equal active compute; communication dominates runtime.                           |
| **Router collapse**           | A few modules monopolize data or capacity.                                       | Utilization entropy falls, load-balancing loss rises, or inactive roles never acquire competence.                     |
| **Duplicate cognition**       | Multiple modules relearn the same representations.                               | High representational redundancy without improved robustness or efficiency.                                           |
| **Credit-assignment failure** | End-to-end learning cannot identify which module caused success.                 | Learning stalls or modules game shared rewards; verifier attribution is unstable.                                     |
| **Low-bit instability**       | Quantization noise overwhelms early optimization or routing margins.             | Divergence, poor calibration, expert churn, or no net energy gain once master state is counted.                       |
| **Tool illusion**             | Harness competence is falsely credited to the owned model.                       | Model-only deletion ablation removes the claimed capability; benchmark evidence depends on prohibited substitutes.    |
| **Memory illusion**           | Improvement lives only in context or process state.                              | Gain disappears after restart or remains after the claimed artifact is deleted, violating locus attribution.          |
| **Growth without function**   | Parameter accretion adds storage but not useful capacity.                        | Equal-budget dense or fixed-sparse controls match or exceed the grown system; active cost rises with no durable gain. |
| **Benchmark gaming**          | The measurement rewards narrow adaptation rather than transferable intelligence. | Performance fails on frozen variants, counterfactuals, or independently sourced tasks.                                |

# Part V — The closed-boundary one-GPU frontier

**Exact question — User**

What are the tightest defensible theoretical upper bounds and experimentally demonstrated Pareto frontier over externally validated, generalizable capability, wall-clock time, and energy, as of August 1, 2026, for an AI system created from random initialization and operated on one RTX 4090-class GPU plus a declared local host, when every source of information and compute—data collection and curation, synthetic generation, teachers and verifiers, training, tools, and test-time reasoning—is charged to that boundary, no learned weights or unaccounted accelerator work are imported, and progress is decomposed into (A) minimizing the nonredundant training information, FLOPs, and joules required to match peer capability under matched model-capacity and evaluation conditions and (B) maximizing effective training-and-inference information throughput per second and joule against the strongest evidenced open and closed systems, including GLM-5.2, Kimi K3, DeepSeek-V4-Flash-0731, and Inkling?

## The answer is a boundary result, not a frontier number

**Answer as of 1 August 2026.** No nontrivial universal upper bound on general capability follows from the RTX 4090 specification alone. The hardware provides hard limits on instantaneous state, data movement, arithmetic rate, and measured energy over a declared interval. Capability bounds become numerical only after the task distribution, prior information, acceptable error, time horizon, host resources, and evaluation protocol are fixed. Under the operational closed-run boundary defined below, no published general-purpose system found in this audit satisfies all conditions simultaneously; the strict experimentally demonstrated Pareto set is therefore unpopulated, not proven impossible.

A finite benchmark can of course be upper-bounded by its maximum score. That is only a bound on the benchmark vector, not on general capability or transfer beyond the frozen distribution. Likewise, a finite-duration run has a finite work and energy budget, but the User’s question does not specify one duration. With time unbounded, cumulative operations and energy can grow without a hardware-derived semantic ceiling until component reliability, storage, maintenance, or an externally imposed horizon binds. [R37, R62–R66]

The strongest defensible result is consequently conditional: define the boundary, declare the priors, freeze a capability vector and evaluation harness, measure all work and energy, then compare nondominated points. Claims that omit any of those steps may still be useful engineering results, but they do not answer this exact question.

## A valid boundary must separate learned imports from declared priors

“Random initialization” forbids imported learned tensors, but it does not create an intelligence-free starting point. Architecture, optimizer, tokenizer, curricula, handwritten programs, solvers, compilers, CUDA kernels, benchmarks, and human decisions all embody prior structure. A rigorous comparison must therefore distinguish two boundaries.

| **Boundary**                    | **What is charged**                                                                                                                                                                                                                                                                                                                                   | **What it can support**                                                                                              | **Irreducible limitation**                                                                                                       |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| Operational closed-run boundary | Every post-genesis data acquisition and curation step; synthetic generation; teachers, judges and verifiers; CPU, GPU, storage and network work; training; tools; evaluation; test-time reasoning; failures, restarts and checkpoints; full-system wall energy; human interventions. Fixed nonlearned software and hardware are hashed and disclosed. | A reproducible engineering Pareto frontier for a declared machine, software stack, data window and evaluation suite. | It still inherits historical intelligence embedded in algorithms, software, datasets, human knowledge and manufactured hardware. |
| Full-causal boundary            | The operational ledger plus the historical cost of collecting the raw world data, developing algorithms and libraries, producing compilers, designing and fabricating the chip, and training the humans who supplied design choices.                                                                                                                  | A philosophical accounting of the entire causal ancestry of the system.                                              | Not practically measurable or comparable. Treating it as an empirical requirement makes every modern experiment undefined.       |

**The operational boundary is the tightest usable standard.** Its immutable ledger should include:

- zero imported learned weights, embeddings, tokenizers with learned parameters, teacher outputs, learned filters, learned judges, or hidden accelerator services;

- hashes and provenance for all fixed nonlearned code, algorithms, corpora, benchmarks, tools, solvers, compilers, kernels, and configuration;

- human labor and every intervention that changes data, curriculum, stopping, model selection, reward, routing, evaluation, or publication;

- bytes acquired, source identities, deduplication and curation operations, repetitions, synthetic generations, and retained original data;

- CPU, GPU, RAM, storage and network utilization; offload bytes; checkpoint and failure overhead; full-system AC wall energy;

- all training, validation, tool use, environment execution, judging, search, retrieval, rollouts, test-time reasoning, and final evaluation.

This is stricter than most published “single-GPU” studies, which commonly meter only the main accelerator training interval. It is also compatible with Ember’s invariant that borrowed learned or evaluative signals cannot enter the lineage, while making the remaining nonlearned priors and host-side costs explicit. [E2–E4]

## What theory can actually bound

Theory supplies several sharp conditional bounds, but none is a universal conversion from data, FLOPs, time, or joules to intelligence. Each bound becomes informative only after its hypothesis class, task distribution, prior, representation, or physical operation is specified.

| **Result**                     | **Tight defensible statement**                                                                                                                                                             | **What it does not provide**                                                                                                                                                                     |
|--------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| No-Free-Lunch theorems         | Under the theorem’s averaging assumptions over all possible objective functions, no optimizer is uniformly superior; performance gains require a restricted problem distribution or prior. | They do not say learning is futile on structured real-world distributions, and they do not rank current AI architectures. [R62]                                                                |
| Fano-type information bound    | For M equiprobable hypotheses and error probability Pe, the observation must carry enough mutual information to distinguish them: I(H;Z) ≥ log₂M − h₂(Pe) − Pe log₂(M−1).                  | M, the prior and the error target must be defined. It is not a universal bit count for intelligence. [R63]                                                                                     |
| PAC / VC sample bounds         | Sample complexity can be bounded for an explicit hypothesis class, confidence, loss and distributional assumption.                                                                         | Modern foundation-model capability and open-ended agentic work do not supply one agreed hypothesis class or distribution.                                                                        |
| MDL and algorithmic complexity | Learnability can be related to the length of a model or program plus the unexplained data, relative to a description language or universal machine.                                        | Kolmogorov complexity is uncomputable and constant-dependent; MDL is a modeling principle, not an experimentally known minimum for AGI. [R64, R65]                                             |
| Data-processing inequality     | A transformation of existing observations cannot increase mutual information about an external hidden variable in the relevant Markov chain.                                               | Synthetic data can still reorganize evidence, expose implications of priors, improve optimization, or simulate new interactions. The claim is not “synthetic data is useless.” [R63, R71, R72] |
| Landauer limit                 | At 300 K, erasing one logical bit dissipates at least kBT ln2 ≈ 2.87×10⁻²¹ J in the ideal irreversible limit.                                                                              | It is many orders below present system energy and does not determine how many irreversible operations a capability requires. [R33]                                                             |
| Empirical scaling laws         | Within measured model, data, objective and compute regimes, loss follows useful empirical power laws and compute-optimal trade-offs.                                                       | They are not theoretical minima and do not establish the best architecture, data, energy, or general capability attainable on a 4090. [R35, R36, R71]                                          |

F(T) ≤ ∫₀ᵀ R_sust(t) dt ≤ R_peak · T

E_total(T) = ∫₀ᵀ P_wall(t) dt

These are genuine upper envelopes on work and measured energy for a declared interval T. They become capability bounds only through an empirically justified mapping from work and information to a frozen task distribution. No such generally accepted mapping exists. [R37, R62–R66]

## The RTX 4090 gives hard resource ceilings, not intelligence ceilings

For the Founders Edition/reference specification, NVIDIA reports 16,384 CUDA cores, 83 shader TFLOPS, 1,321 vendor-defined AI TOPS, 24 GB GDDR6X on a 384-bit interface, no NVLink, and 450 W total graphics power. A representative board vendor specifies 21 Gbit/s memory and 1,008 GB/s theoretical bandwidth. The 850 W figure is a recommended minimum system-power-supply rating, not measured system draw. [R86, R87]

| **Resource**          | **Declared ceiling or specification**      | **Interpretation**                                                                                                                                                                |
|-----------------------|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GPU memory            | 24 GB GDDR6X                               | Weights, inactive experts, activations, gradients, optimizer state, workspaces and KV state compete for the same residency. Usable allocation is lower than the nominal capacity. |
| Memory interface      | 384-bit; 21 Gbit/s; 1,008 GB/s theoretical | A bandwidth roof, not an application guarantee. Cache behavior, access patterns and host transfers reduce sustained rate.                                                         |
| Advertised arithmetic | 83 shader TFLOPS; 1,321 AI TOPS            | Precision- and workload-specific marketing peaks. AI TOPS is not interchangeable with conventional training FLOPs.                                                                |
| Power                 | 450 W total graphics power                 | A board limit. Full experiment energy requires an AC wall meter for GPU, CPU, RAM, storage, cooling and conversion losses.                                                        |
| Interconnect          | PCIe Gen4; no NVLink                       | Offload and inactive-expert movement must cross a far slower boundary than local VRAM.                                                                                            |

### Residency: ideal storage ceilings are not trainable-model ceilings

Treating 24 GiB as 24×2³⁰ bytes, ignoring every scale, metadata item, embedding, activation, workspace, fragment and KV entry, gives the following raw storage-only maxima. They are deliberately optimistic upper bounds.

| **Representation** | **Nominal bytes / parameter** | **Ideal maximum in 24 GiB** | **Excluded from the number**                         |
|--------------------|-------------------------------|-----------------------------|------------------------------------------------------|
| BF16 / FP16        | 2.0                           | 12.885B parameters          | All runtime and training state                       |
| FP8 / INT8         | 1.0                           | 25.770B                     | Scales, metadata and all runtime state               |
| 4-bit              | 0.5                           | 51.540B                     | Packing overhead, scales and all runtime state       |
| 1.58-bit           | 0.1975                        | 130.480B                    | Codebooks/scales and higher-precision training state |
| 1-bit              | 0.125                         | 206.158B                    | All practical training and execution overhead        |

Standard mixed-precision AdamW is commonly budgeted at roughly 16 bytes per parameter before activations. FlashOptim reports 7 bytes per parameter, or 5 with gradient release, for its optimized state representation. The corresponding ideal 24-GiB state-only ceilings are about 1.611B, 3.681B and 5.154B parameters respectively—again before activations, workspaces and fragmentation. GaLore and Q-GaLore show that alternative gradient-state representations can fit 7B pretraining on 24 GB and 16 GB devices, but residency is not evidence of complete training, broad capability, or all-in energy efficiency. [R77, R78, R80]

### Roofline and seriality: peak FLOPs are rarely the active constraint

R_attain ≤ min(R_peak, B_mem × I_arith)

The roofline model makes arithmetic intensity explicit: low-intensity work is bandwidth-bound even when nominal tensor throughput is enormous. FlashAttention is important precisely because reducing HBM traffic can improve wall-clock time while doing comparable or even additional arithmetic. Irregular expert routing, small kernels, launches, cache misses, offload, and host synchronization can move a sparse model far below its nominal FLOP advantage. [R66–R68]

Autoregressive generation also preserves a serial dependency across accepted output positions. Speculative decoding can verify several proposed tokens in parallel and preserve the target distribution, but its gain depends on acceptance rate and draft cost; tools, environments, verifiers, rollouts, and long-horizon feedback introduce additional serial work that cannot be summarized by model tokens per second. [R69]

| **Idealized 4-bit active weights** | **Weight bytes read / token** | **Bandwidth-only batch-1 ceiling at 1,008 GB/s**    |
|------------------------------------|-------------------------------|-----------------------------------------------------|
| 13B active                         | 6.5 GB                        | ≈155 tokens/s                                       |
| 40B active                         | 20.0 GB                       | ≈50.4 tokens/s                                      |
| 41B active                         | 20.5 GB                       | ≈49.2 tokens/s                                      |
| 104B active                        | 52.0 GB                       | ≈19.4 tokens/s; active subset itself exceeds 24 GiB |

These are not forecasts. They assume each active weight is read exactly once per token at theoretical bandwidth and exclude the shared core, quantization metadata, KV cache, activations, routing, synchronization and host movement. Batching can amortize weight reads; long contexts can shift the bottleneck to KV state and attention kernels.

### Energy is a measured integral, not a TDP multiplication

At the 450 W graphics-power limit, the GPU alone would consume 10.8 kWh per day, 324 kWh per 30-day month, or 3.942 MWh per 365-day year. Those figures are useful envelopes, not experiment measurements. A compliant receipt must integrate full-system AC wall power over the run and separately record idle baseline, CPU/RAM/storage/network work, cooling if dedicated, and failed or repeated runs. MLPerf Power similarly treats system-level AC measurement as the relevant boundary rather than substituting component TDP. [R74, R86]

## The strict empirical Pareto frontier is currently unpopulated

The audit searched for public work combining random initialization, one RTX-4090-class GPU, all-in data and host accounting, zero learned imports, measured wall time and energy, and broad externally validated general capability. No qualifying result was found. The nearest work proves important subclaims, but each relaxes at least one decisive condition. “Unpopulated” means no admissible public point was identified; it is not a proof that one cannot exist.

| **Study or system**                 | **Demonstrated point**                                                                                                                 | **Why it does not answer the exact question**                                                                                                                                                                                | **Strictly admissible?**  |
|-------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------|
| Cramming [R75]                    | A masked-language model trained from scratch on one GPU for 24 hours, approaching BERT on GLUE after downstream fine-tuning.           | The rules exempt raw-data download, CPU preprocessing, tokenizer construction and filtering from the 24-hour budget; downstream fine-tuning is outside the main training interval; energy is not an all-in wall measurement. | No                        |
| Slamming [R76]                    | A one-GPU, one-day speech-language demonstration.                                                                                      | The released model card describes fine-tuning from pretrained Qwen2.5-0.5B and uses pretrained mHuBERT units, a vocoder and synthetic data—learned imports under this boundary.                                              | No                        |
| GaLore [R77]                      | Full-parameter LLaMA-7B pretraining feasibility in 22 GB on a 24 GB consumer GPU; up to 19.7B training tokens in reported experiments. | A memory and optimization result, not a full all-in one-host capability-time-energy frontier; public data and preprocessing are imported.                                                                                    | No                        |
| Q-GaLore [R78]                    | LLaMA-7B from-scratch pretraining residency on a 16 GB RTX 4060 Ti using quantized weights and gradient projections.                   | Demonstrates memory feasibility, not broad externally validated capability or all-in information and energy accounting.                                                                                                      | No                        |
| 1 GPU, 7 Runs, 7 Challenges [R79] | Seven task-specific models developed with 40–120 minute single-GPU runs and strong task results.                                       | The development agents include pretrained Claude, Codex, Qwen and Kimi models; their cognition and compute are imported.                                                                                                     | No                        |
| FlashOptim [R80]                  | AdamW state reduced from 16 to 7 bytes per parameter, or 5 with gradient release, without measured quality loss on its tested tasks.   | A component-level memory result; it does not construct a general random-initialized system or meter the entire boundary.                                                                                                     | No                        |
| Ember at pinned commit [E1–E5]    | A 3.839B allocated candidate with about 1.021B active parameters and a governance system designed for receipts.                        | Only 2,048 tokens observed; specialist banks at random genesis; no admitted model or complete neural verified-experience loop.                                                                                               | No current frontier point |

## Frontier systems are target envelopes, not comparable creation points

GLM-5.2, Kimi K3, DeepSeek-V4-Flash and Inkling are valuable external capability and systems-engineering references. Their public benchmarks, however, mix different harnesses, judges, tools, context limits, reasoning budgets, sandboxes and sometimes different checkpoints. Their training disclosures do not charge the causal production of data, curation, teachers, human labor and accelerator fleets to one 4090 host. They therefore cannot define the one-GPU creation frontier. [R82–R85]

| **System**                | **Public envelope as of 1 Aug 2026**                                                                                                                                                                       | **4090 residency implication**                                                                                                                           | **Boundary and evaluation caveat**                                                                                                                                                                          |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GLM-5.2 [R82]           | 1M context; IndexShare claims 2.9× fewer per-token FLOPs at 1M; MTP acceptance length +20%; reported HLE 40.5 / 54.7 with tools, SWE-bench Pro 62.1, Terminal-Bench 2.1 Terminus-2 81.0, FrontierSWE 74.4. | Official artifacts indicate roughly 753B total and about 40B active. Ideal 4-bit total ≈376.5 GB; active ≈20 GB before shared/core and runtime state.    | Post-training merged \>10 expert models through parallel OPD. Published scores use heterogeneous judges, tools, contexts, CPU/RAM sandboxes and up to multi-hour samples; no all-in energy.                 |
| Kimi K3 [R83]           | 2.8T total / 104B active; 1M context; text and image; MXFP4 weights / MXFP8 activations; reported GPQA 93.5 and HLE 43.5 / 56.0 with tools.                                                                | Ideal 4-bit total ≈1.4 TB; active ≈52 GB, so even the active subset exceeds 24 GiB before runtime state.                                                 | Approximate 2.5× scaling-efficiency improvement over K2 is a provider claim. Evaluations mix Kimi Code, Claude Code, Codex, external judges and H20/H100 environments; no all-in creation energy.           |
| DeepSeek-V4-Flash [R84] | 284B total / 13B active; 1M context; FP4 experts and mostly FP8 other parameters; pretrained on \>32T tokens; domain experts trained by SFT/RL then consolidated by on-policy distillation.                | Ideal 4-bit total ≈142 GB; active ≈6.5 GB, but full weights, shared/core, KV and workspaces exceed the local boundary. Offload would incur host traffic. | No separate official artifact named “DeepSeek-V4-Flash-0731” was found; this report maps the requested label to the official DeepSeek-V4-Flash available by 31 Jul 2026. No all-in training energy.         |
| Inkling [R85]           | 975B total / 41B active; 1M context; text, image and audio; trained from scratch on 45T multimodal tokens; reported broad reasoning, coding and tool-use results.                                          | Ideal 4-bit total ≈487.5 GB; active ≈20.5 GB before shared/core and runtime state.                                                                       | Thinking Machines states the benchmark results were obtained on a different checkpoint from the released one. The training fleet, data-production cost and all-in energy are not reduced to one local host. |

The benchmark numbers above are provider-reported envelope points, not a normalized ranking. A valid matched comparison must freeze the harness, tools, judge, context, output length, effort level, retries, sandbox resources, timeout and complete test-time energy.

## A and B require separate Pareto surfaces

There is no defensible one-number “intelligence efficiency” score. Define a preregistered capability vector, for example C = (reasoning, knowledge, code, agentic execution, multimodal grounding, calibration, transfer, retention), and report nondominated points. A system x Pareto-dominates y only if every frozen capability dimension is at least as good, every charged cost is no greater, and at least one inequality is strict. Scalarization is permissible only when the weights are declared before results are seen.

### A — Less training to matched capability

Choose a target capability vector C\* and match total, active and trainable capacity; tokenizer and architecture declarations; data sources; evaluation; tool access; context; and test-time compute. Then report:

DR(C\*) = unique source data_baseline / unique source data_method

FR(C\*) = charged training FLOPs_baseline / charged training FLOPs_method

ER(C\*) = charged wall joules_baseline / charged wall joules_method

“Nonredundant information” should not be reported as literal Shannon bits unless a task-specific random variable and mutual-information estimator are defined. The practical ledger should instead report unique source bytes or tokens, duplication structure, number of exposures, synthetic ancestry, and an explicitly modeled fresh-information equivalent. Data repetition can be useful for several epochs in tested regimes, but its marginal value eventually decays; recursive generated data can lose tails and amplify approximation errors when original data is not preserved. [R71, R72]

### B — More useful information processing per second and joule

Report both low-level throughput and outcome-level throughput. Hardware utilization cannot substitute for externally validated success, while benchmark success cannot hide unlimited rollouts or tools.

| **Layer**                      | **Required metrics**                                                                                              | **Reason**                                                                                  |
|--------------------------------|-------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Capability attainment          | Time-to-C\*; energy-to-C\*; successful held-out tasks/s and tasks/J; calibrated error; retention and transfer.    | Directly answers whether useful validated capability is reached faster or with less energy. |
| Training throughput            | Tokens/s; charged FLOPs/s; MFU where defined; unique tokens/s; joules/token; optimizer and data-pipeline time.    | Separates arithmetic progress from repeated or low-value exposure.                          |
| Inference and agent throughput | Prefill and decode tokens/s; joules/token; wall time and joules/task; tool, environment, judge and retry counts.  | Captures seriality and external work hidden by model-only throughput.                       |
| Memory and movement            | Peak allocated/reserved VRAM; host RAM; bytes moved over PCIe/storage/network; KV bytes; offload time and energy. | Makes residency and movement costs visible.                                                 |
| Reliability and evidence       | Failed runs; restarts; checkpoint I/O; deletion and restart gates; evaluator variance; provenance completeness.   | Prevents selective reporting and attributes gains to the claimed artifact.                  |

API token rate, dollar price, or vendor-advertised FLOPs are not substitutes for full-system joules. Similarly, a model with lower active parameters can be slower if routing, memory movement, long context, small-batch utilization, or test-time search dominates. [R66–R74]

## The twelve bottlenecks become an experimental protocol

| **Wall**                    | **Required control or measurement**                                                                                                                                                               | **Decisive failure signal**                                                                                             |
|-----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| 1\. Metric                  | Freeze a multidimensional capability vector, external tasks, contamination checks, harness, tools, context, output budget, judge and retries. Report Pareto points rather than a post hoc scalar. | Ranking changes under reasonable metric or harness perturbations; score cannot be attributed to generalization.         |
| 2\. Accounting              | Zero learned imports; hash and disclose fixed priors; meter all data, host, tool, teacher, verifier, evaluation and test-time work plus human interventions.                                      | Unmetered accelerator/service use or undocumented learned signal enters the chain.                                      |
| 3\. Theory / disclosure     | Label every bound as hardware, information-theoretic, empirical or project-specific; publish recipe, negative results and uncertainty.                                                            | An empirical scaling fit or vendor peak is presented as a theoretical minimum or end-to-end measurement.                |
| 4\. Data                    | Record unique sources, bytes/tokens, repetitions, deduplication, synthetic ancestry, retained originals and acquisition/curation cost.                                                            | Gains vanish under source-held-out evaluation, repetition has exhausted marginal value, or recursive data erases tails. |
| 5\. Objective / verifier    | Use deterministic external verification where possible; freeze rubrics; measure learned-judge sensitivity and reward hacking; keep open-ended tasks separate.                                     | Score improves without real task success or changes materially with judge choice.                                       |
| 6\. Transfer / persistence  | Deletion ablation, process restart, retention intervals, continual-learning and non-regression tests; identify the exact state carrying the gain.                                                 | Gain lives only in transient context, disappears after restart, or destroys prior capability.                           |
| 7\. Optimization            | Measure gradient noise, conditioning proxies, update efficiency, interference, routing balance, credit-assignment delay and scale transfer.                                                       | More updates or compute do not improve held-out loss/capability, or gains fail when scaled. [R70]                     |
| 8\. Architecture / capacity | Compare dense, homogeneous sparse, heterogeneous expert and external-module arms at matched total, active and trainable capacity.                                                                 | A claimed architectural gain is explained by more capacity, data, active FLOPs or test-time work.                       |
| 9\. Composition             | Use factorial or staged ablations for quantization, sparsity, growth, optimizer, data and objective changes; measure interactions.                                                                | Individual gains fail to compose or create instability, routing imbalance, regression or movement overhead.             |
| 10\. Residency              | Byte-level state inventory; peak allocator and system measurements; offload traffic, latency and energy; total versus active expert storage.                                                      | The model “fits” only by excluding workspaces, KV, inactive weights, host state or transfer cost.                       |
| 11\. Roofline / numerics    | Measure sustained FLOPs, bandwidth, arithmetic intensity, kernel occupancy, launches, cache behavior, precision error and numerical fallbacks.                                                    | Theoretical FLOP savings do not produce wall-clock or energy gains. [R66–R68]                                         |
| 12\. Seriality / iteration  | Include autoregressive steps, rollouts, tools, environments, verification, thermal throttling, checkpoints, failures, search and evaluation in wall time.                                         | Model tokens/s looks high while end-to-end task time or joules regress. [R69]                                         |

## Implications for Ember

The exact question should become a first-class Ember completion contract, not an informal aspiration. The repo already supplies unusual strengths—clean-genesis lineage, equal-budget controls, deletion and restart gates, separate model/body identities, and an energy law—but the closed boundary requires additional receipts. [E1–E5]

1. Install and calibrate a full-system AC wall-power meter; record idle baseline, sampling cadence, uncertainty and the declared host configuration.

2. Create one append-only all-compute ledger covering CPU, GPU, RAM, storage, network, tools, environments, evaluation, rollouts, failed runs and restarts.

3. Publish a fixed-prior manifest separating learned-state imports—which must be zero—from nonlearned algorithms, software, tools, corpora, benchmarks and human interventions.

4. Bind random initialization, data provenance, tokenizer construction, curriculum, optimizer, stopping, routing and checkpoint lineage to the exact run.

5. Separate model capability from body capability with model-only, body-only, tool-deletion, memory-deletion and verifier-deletion ablations.

6. Compare dense, homogeneous MoE, heterogeneous roles, growth and external specialized modules under matched total, active and trainable capacity plus matched test-time compute.

7. Report unique and repeated data separately, preserve original data, and treat synthetic ancestry as a provenance graph rather than a new-information count.

8. Measure sustained throughput, MFU, arithmetic intensity, bytes moved, offload, KV state, routing balance, wall time and joules—not only theoretical FLOPs or parameter count.

9. Keep GLM-5.2, Kimi K3, DeepSeek-V4-Flash and Inkling in a comparator registry with disclosed harness mismatches; never present their scores as one-GPU creation evidence.

10. Make the first deliverable a closed-boundary frontier receipt for a smaller credible rung. A 30–35B parameter shell is not a frontier point until useful externally validated capability, time and energy are jointly measured.

## Falsifiable answer as of 1 August 2026

**BOUNDARY RESULT.** No nontrivial universal capability upper bound is presently defensible from the RTX 4090 hardware description alone. The tight bounds are conditional resource envelopes and task-specific information/sample bounds. Under the operational all-inclusive boundary posed here, the audited public general-purpose empirical Pareto set is unpopulated. Nearby studies establish valuable isolated feasibility points—single-GPU language training, 7B residency, optimizer-state compression, or task-specific agent-assisted development—but not the complete closed-boundary frontier. Ember’s scientific opportunity is to create the first receipted points on that frontier and allow matched evidence to falsify its efficiency and growth hypotheses.

# Conclusion

## The distilled hypotheses

**Research proposition.** Under a fixed energy, memory, and compute budget, can a heterogeneous system with predefined functional responsibilities, adaptive capacity, explicit memory, routed specialized computation, and verified consolidation achieve greater persistent capability than a monolithic transformer-centered agent?

**Boundary proposition.** Under a strict one-RTX-4090-plus-host boundary, can Ember produce and repeatedly improve nondominated, externally validated capability-time-energy points when all information, computation, tools, verification and test-time reasoning are charged to the same ledger and no learned state is imported?

The conversation did not prove that proposition. It did something more useful: it progressively removed several ambiguities. “Experts” need not mean human-labeled domains. Biological inspiration need not mean copying anatomy. Memory need not mean merely storing text. Architecture need not disappear, but it can be complemented by physiology. And the transformer need not be rejected to cease being treated as the whole mind.

The strongest near-term position is therefore neither “scale the transformer and nothing else” nor “replace transformers with a brain replica.” It is to test a developmental, heterogeneous artificial physiology in which semantic neural models, explicit memory, planners, solvers, graph structures, procedures, kernels, tools, and global control signals are assigned work according to their actual strengths—and every durable claim is tied to matched resource accounting and verified experience.

For Ember specifically, the repo already contains much of the constitutional vocabulary needed to make that test rigorous: clean genesis, sparse differentiated capacity, active-versus-total parameter accounting, model/body separation, energy law, matched controls, deletion ablation, restart persistence, expert accretion, and explicit denial of unearned capability. The next contribution is not another metaphor. It is an experiment that can cause the hypothesis to fail. [E1–E5]

The closed-boundary addendum does not convert the resource constraint into a promised capability level. It clarifies the experiment Ember must perform: establish the first admissible points, publish the denominator as rigorously as the numerator, and let matched controls determine whether sparse expert growth, functional roles, low precision, specialized modules, and verified experience actually bend the frontier.

# References

References are grouped by identifier rather than citation style. Ember documents [E1–E5] are commit-pinned project sources. Research references [R1–R87] prioritize primary papers, official documentation, or canonical historical sources. A citation supports only the qualified statement attached to it; it does not validate broader biological analogies, vendor comparisons, or Ember’s unexecuted hypotheses.

## Ember project sources

**[E1]** Ember repository. README.md at commit 3d48d3870919bd04cec735f68d0fad45fcfae0b2. State as of 1 Aug 2026. github.com/wordingone/ember/blob/3d48d3870919bd04cec735f68d0fad45fcfae0b2/README.md

**[E2]** Ember repository. GOAL.md (Ember Constitution) at commit 3d48d3870919bd04cec735f68d0fad45fcfae0b2. github.com/wordingone/ember/blob/3d48d3870919bd04cec735f68d0fad45fcfae0b2/GOAL.md

**[E3]** Ember repository. docs/domains/governance/guides/START-HERE.md at commit 3d48d3870919bd04cec735f68d0fad45fcfae0b2. github.com/wordingone/ember/blob/3d48d3870919bd04cec735f68d0fad45fcfae0b2/docs/domains/governance/guides/START-HERE.md

**[E4]** Ember repository. INVARIANT.md at commit 3d48d3870919bd04cec735f68d0fad45fcfae0b2. github.com/wordingone/ember/blob/3d48d3870919bd04cec735f68d0fad45fcfae0b2/INVARIANT.md

**[E5]** Ember repository. CONTINUITY.md at commit 3d48d3870919bd04cec735f68d0fad45fcfae0b2. github.com/wordingone/ember/blob/3d48d3870919bd04cec735f68d0fad45fcfae0b2/CONTINUITY.md

## Research and historical sources

**[R1]** Marr, D. Vision: A Computational Investigation into the Human Representation and Processing of Visual Information. W. H. Freeman, 1982.

**[R2]** Shazeer, N., et al. “Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer.” arXiv:1701.06538, 2017.

**[R3]** Fedus, W., Zoph, B., and Shazeer, N. “Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity.” Journal of Machine Learning Research 23(120):1–39, 2022.

**[R4]** Pfeiffer, J., et al. “Modular Deep Learning.” arXiv:2302.11529, 2023.

**[R5]** Goyal, A., et al. “Coordination among Neural Modules through a Shared Global Workspace.” arXiv:2103.01197, 2021.

**[R6]** Andreas, J., Rohrbach, M., Darrell, T., and Klein, D. “Neural Module Networks.” Proceedings of CVPR, 2016; arXiv:1511.02799.

**[R7]** Anderson, J. R., et al. “An Integrated Theory of the Mind.” Psychological Review 111(4):1036–1060, 2004. doi:10.1037/0033-295X.111.4.1036.

**[R8]** Laird, J. E. The Soar Cognitive Architecture. MIT Press, 2012.

**[R9]** Li, et al. Scientific Reports 10:18039, 2020. doi:10.1038/s41598-020-75015-7.

**[R10]** Kubota, et al. Nature Human Behaviour 9:955–970, 2025. doi:10.1038/s41562-025-02116-6.

**[R11]** Marder, E. “Neuromodulation of Neuronal Circuits: Back to the Future.” Neuron 76(1):1–11, 2012. doi:10.1016/j.neuron.2012.09.010.

**[R12]** Schultz, W., Dayan, P., and Montague, P. R. “A Neural Substrate of Prediction and Reward.” Science 275(5306):1593–1599, 1997. doi:10.1126/science.275.5306.1593.

**[R13]** Chaudhuri, R., and Fiete, I. “Computational Principles of Memory.” Nature Neuroscience 19:394–403, 2016. doi:10.1038/nn.4237.

**[R14]** Benna, M. K., and Fusi, S. “Computational Principles of Synaptic Memory Consolidation.” Nature Neuroscience 19:1697–1706, 2016. doi:10.1038/nn.4401.

**[R15]** Graves, A., et al. “Hybrid Computing Using a Neural Network with Dynamic External Memory.” Nature 538:471–476, 2016. doi:10.1038/nature20101.

**[R16]** Lewis, P., et al. “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.” arXiv:2005.11401, 2020.

**[R17]** Yao, S., et al. “ReAct: Synergizing Reasoning and Acting in Language Models.” arXiv:2210.03629, 2022.

**[R18]** Schick, T., et al. “Toolformer: Language Models Can Teach Themselves to Use Tools.” arXiv:2302.04761, 2023.

**[R19]** Sumers, T. R., et al. “Cognitive Architectures for Language Agents.” arXiv:2309.02427, 2023.

**[R20]** Ha, D., and Schmidhuber, J. “World Models.” arXiv:1803.10122, 2018.

**[R21]** Schrittwieser, J., et al. “Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model.” Nature 588:604–609, 2020. doi:10.1038/s41586-020-03051-4.

**[R22]** Silver, D., et al. “Mastering the Game of Go with Deep Neural Networks and Tree Search.” Nature 529:484–489, 2016. doi:10.1038/nature16961.

**[R23]** Mnih, V., et al. “Human-Level Control through Deep Reinforcement Learning.” Nature 518:529–533, 2015. doi:10.1038/nature14236.

**[R24]** Harnad, S. “The Symbol Grounding Problem.” Physica D 42:335–346, 1990. doi:10.1016/0167-2789(90)90087-6.

**[R25]** Bender, E. M., and Koller, A. “Climbing towards NLU: On Meaning, Form, and Understanding in the Age of Data.” Proceedings of ACL, 2020. doi:10.18653/v1/2020.acl-main.463.

**[R26]** Barsalou, L. W. “Grounded Cognition.” Annual Review of Psychology 59:617–645, 2008. doi:10.1146/annurev.psych.59.103006.093639.

**[R27]** Smith, L., and Gasser, M. “The Development of Embodied Cognition: Six Lessons from Babies.” Artificial Life 11(1–2):13–29, 2005.

**[R28]** Lake, B. M., Ullman, T. D., Tenenbaum, J. B., and Gershman, S. J. “Building Machines That Learn and Think Like People.” Behavioral and Brain Sciences 40:e253, 2017.

**[R29]** Lenski, R. E., et al. “The Evolutionary Origin of Complex Features.” Nature 423:139–144, 2003. doi:10.1038/nature01568.

**[R30]** Mordvintsev, A., Randazzo, E., Niklasson, E., and Levin, M. “Growing Neural Cellular Automata.” Distill, 2020. doi:10.23915/distill.00023.

**[R31]** Dunbar, R. I. M. “The Social Brain: Mind, Language, and Society in Evolutionary Perspective.” Annual Review of Anthropology 32:163–181, 2003. doi:10.1146/annurev.anthro.32.061002.093158.

**[R32]** Morgan, T. J. H., and Feldman, M. W. Nature Human Behaviour 9:28–42, 2025. doi:10.1038/s41562-024-02035-y.

**[R33]** Landauer, R. “Irreversibility and Heat Generation in the Computing Process.” IBM Journal of Research and Development 5(3):183–191, 1961. doi:10.1147/rd.53.0183.

**[R34]** Attwell, D., and Laughlin, S. B. “An Energy Budget for Signaling in the Grey Matter of the Brain.” Journal of Cerebral Blood Flow & Metabolism 21:1133–1145, 2001. doi:10.1097/00004647-200110000-00001.

**[R35]** Kaplan, J., et al. “Scaling Laws for Neural Language Models.” arXiv:2001.08361, 2020.

**[R36]** Hoffmann, J., et al. “Training Compute-Optimal Large Language Models.” arXiv:2203.15556, 2022.

**[R37]** Chollet, F. “On the Measure of Intelligence.” arXiv:1911.01547, 2019.

**[R38]** Vaswani, A., et al. “Attention Is All You Need.” arXiv:1706.03762, 2017.

**[R39]** Gu, A., and Dao, T. “Mamba: Linear-Time Sequence Modeling with Selective State Spaces.” arXiv:2312.00752, 2023.

**[R40]** LeCun, Y., Bottou, L., Bengio, Y., and Haffner, P. “Gradient-Based Learning Applied to Document Recognition.” Proceedings of the IEEE 86(11):2278–2324, 1998.

**[R41]** Battaglia, P. W., et al. “Relational Inductive Biases, Deep Learning, and Graph Networks.” arXiv:1806.01261, 2018.

**[R42]** de Moura, L., and Bjørner, N. “Z3: An Efficient SMT Solver.” TACAS 2008. doi:10.1007/978-3-540-78800-3_24.

**[R43]** Trinh, T. H., et al. “Solving Olympiad Geometry without Human Demonstrations.” Nature 625:476–482, 2024. doi:10.1038/s41586-023-06747-5.

**[R44]** Chen, T., and Guestrin, C. “XGBoost: A Scalable Tree Boosting System.” arXiv:1603.02754, 2016.

**[R45]** Breiman, L. “Random Forests.” Machine Learning 45:5–32, 2001. doi:10.1023/A:1010933404324.

**[R46]** Wang, H., et al. “BitNet: 1-bit Pre-training for Large Language Models.” Journal of Machine Learning Research 26(125):1–29, 2025.

**[R47]** Ma, S., et al. “The Era of 1-bit LLMs: All Large Language Models Are in 1.58 Bits.” arXiv:2402.17764, 2024.

**[R48]** Liang, et al. “Mixture-of-Transformers: A Sparse and Scalable Architecture for Multi-Modal Foundation Models.” arXiv:2411.04996, 2024.

**[R49]** Google AI. “Gemma 4 Model Card.” Official Gemma documentation, updated 16 Jul 2026.

**[R50]** Chen, T., Goodfellow, I., and Shlens, J. “Net2Net: Accelerating Learning via Knowledge Transfer.” arXiv:1511.05641, 2015.

**[R51]** Cortes, C., et al. “AdaNet: Adaptive Structural Learning of Artificial Neural Networks.” arXiv:1607.01097, 2016.

**[R52]** Gordon, A., et al. “MorphNet: Fast & Simple Resource-Constrained Structure Learning of Deep Networks.” arXiv:1711.06798, 2017.

**[R53]** Rusu, A. A., et al. “Progressive Neural Networks.” arXiv:1606.04671, 2016.

**[R54]** Amdahl, G. M., Blaauw, G. A., and Brooks, F. P. “Architecture of the IBM System/360.” IBM Journal of Research and Development 8(2):87–101, 1964. doi:10.1147/rd.82.0087.

**[R55]** Smithsonian Institution. “The Measurement of Intelligence: Alfred Binet and the Binet–Simon Scale.” National Museum of American History.

**[R56]** Smithsonian Institution. “Group Examination Alpha.” National Museum of American History; historical documentation of U.S. Army group testing.

**[R57]** Nakatsu, E. “Essence of High Speed Rail Technology, Learning from Nature: Episodes of Developing the 500 Series Shinkansen.” JSME Mechanical Engineering Congress, 2018. doi:10.1299/jsmemecj.2018.W20200.

**[R58]** Marjieh, R., et al. Scientific Reports 14:21445, 2024. doi:10.1038/s41598-024-72071-1.

**[R59]** Xu, et al. Nature Human Behaviour 9:1871–1886, 2025. doi:10.1038/s41562-025-02203-8.

**[R60]** Tversky, A., and Kahneman, D. “The Framing of Decisions and the Psychology of Choice.” Science 211(4481):453–458, 1981. doi:10.1126/science.7455683.

**[R61]** Roy, K., Jaiswal, A., and Panda, P. “Towards Spike-Based Machine Intelligence with Neuromorphic Computing.” Nature 575:607–617, 2019. doi:10.1038/s41586-019-1677-2.

**[R62]** Wolpert, D. H., and Macready, W. G. “No Free Lunch Theorems for Optimization.” IEEE Transactions on Evolutionary Computation 1(1):67–82, 1997. doi:10.1109/4235.585893.

**[R63]** Cover, T. M., and Thomas, J. A. Elements of Information Theory, 2nd ed. Wiley-Interscience, 2006.

**[R64]** Hutter, M. Universal Artificial Intelligence: Sequential Decisions Based on Algorithmic Probability. Springer, 2005.

**[R65]** Grünwald, P. D. The Minimum Description Length Principle. MIT Press, 2007.

**[R66]** Williams, S., Waterman, A., and Patterson, D. “Roofline: An Insightful Visual Performance Model for Multicore Architectures.” Communications of the ACM 52(4):65–76, 2009. doi:10.1145/1498765.1498785.

**[R67]** Dao, T., Fu, D. Y., Ermon, S., Rudra, A., and Ré, C. “FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness.” arXiv:2205.14135, 2022.

**[R68]** Dao, T. “FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning.” arXiv:2307.08691, 2023; ICLR 2024.

**[R69]** Leviathan, Y., Kalman, M., and Matias, Y. “Fast Inference from Transformers via Speculative Decoding.” arXiv:2211.17192, 2022; ICML 2023.

**[R70]** McCandlish, S., Kaplan, J., Amodei, D., and OpenAI Dota Team. “An Empirical Model of Large-Batch Training.” arXiv:1812.06162, 2018.

**[R71]** Muennighoff, N., et al. “Scaling Data-Constrained Language Models.” arXiv:2305.16264, 2023.

**[R72]** Shumailov, I., Shumaylov, Z., Zhao, Y., Papernot, N., Anderson, R., and Gal, Y. “AI Models Collapse When Trained on Recursively Generated Data.” Nature 631:755–759, 2024. doi:10.1038/s41586-024-07566-y.

**[R73]** Dehghani, M., et al. “The Efficiency Misnomer.” arXiv:2110.12894, 2021; ICLR 2022.

**[R74]** MLCommons. “MLPerf Power: Full-System AC Power and Energy Measurement Rules.” Official MLPerf documentation, accessed 1 Aug 2026. mlcommons.org/benchmarks/inference-datacenter/.

**[R75]** Geiping, J., and Goldstein, T. “Cramming: Training a Language Model on a Single GPU in One Day.” arXiv:2212.14034, 2022; ICML 2023.

**[R76]** Maimon, G., Elmakies, A., and Adi, Y. “Slamming: Training a Speech Language Model on One GPU in a Day.” Findings of ACL 2025, pp. 12201–12216. doi:10.18653/v1/2025.findings-acl.631. See also the official SLAM model card.

**[R77]** Zhao, J., Zhang, Z., Chen, B., Wang, Z., Anandkumar, A., and Tian, Y. “GaLore: Memory-Efficient LLM Training by Gradient Low-Rank Projection.” arXiv:2403.03507, 2024; ICML 2024.

**[R78]** Zhang, Z., Jaiswal, A., Yin, L., Liu, S., Zhao, J., Tian, Y., and Wang, Z. “Q-GaLore: Quantized GaLore with INT4 Projection and Layer-Adaptive Low-Rank Gradients.” arXiv:2407.08296, 2024.

**[R79]** Kampa, R.-N., Deuser, F., Bößendörfer, A., Habel, K., and Oswald, N. “1GC-7RC: One Graphic Card — Seven Research Challenges! How Good Are AI Agents at Doing Your Job?” arXiv:2605.17046, 2026.

**[R80]** Gonzalez Ortiz, J. J., Gupta, A., Renard, C., and Blalock, D. “FlashOptim: Optimizers for Memory-Efficient Training.” arXiv:2602.23349, 2026.

**[R81]** DeepSeek-AI. “DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning.” arXiv:2501.12948, 2025; Nature, 2025.

**[R82]** Z.ai. “GLM-5.2: Built for Long-Horizon Tasks.” Official release blog, 16 Jun 2026. z.ai/blog/glm-5.2. See also the official GLM-5.2 model artifacts.

**[R83]** Moonshot AI. “Kimi K3: Open Frontier Intelligence.” Official GitHub repository and technical report, accessed 1 Aug 2026. github.com/MoonshotAI/Kimi-K3.

**[R84]** DeepSeek-AI. “DeepSeek-V4: Towards Highly Efficient Million-Token Context Intelligence.” Official DeepSeek-V4-Flash model card and technical report, 2026. huggingface.co/deepseek-ai/DeepSeek-V4-Flash.

**[R85]** Thinking Machines Lab. “Inkling Model Card” and “Inkling: Our Open-Weights Model.” Official sources, 15 Jul 2026. thinkingmachines.ai/model-card/inkling/ and thinkingmachines.ai/news/introducing-inkling/.

**[R86]** NVIDIA. “GeForce RTX 4090 Specifications.” Official product page, accessed 1 Aug 2026. nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/.

**[R87]** PNY. “GeForce RTX 4090 24GB XLR8 Gaming Product Specifications.” Official product page, accessed 1 Aug 2026. pny.com/pny-geforce-rtx-4090-24gb-xlr8-gaming-revel-epic-x-triple-fan.

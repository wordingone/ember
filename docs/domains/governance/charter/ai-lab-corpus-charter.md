# AI-Lab Corpus Charter

Operator directive, 2026-07-09. Ember functions — atop the trinity — as a closed-loop AI
lab for local/consumer-scale creation. A lab is only as good as its corpus; the operator's
standing assessment at charter time: the current corpus is lacking in both total quality
and diversity. This charter is the corpus floor.

## The domain floor (minimum; a lab corpus includes ALL of these)

- **A. Mathematical Foundations** — analysis, algebra, probability, optimization,
  numerical methods; textbook-to-research grade.
- **B. Statistics / Measurement / Inference** — experimental statistics, estimation,
  uncertainty, causal inference, metrology.
- **C. Physics / Dynamical Systems / Resource Reality** — mechanics, thermodynamics,
  dynamical systems, energy/compute physical constraints.
- **D. Computer Science / Algorithms / Systems** — algorithms, data structures, OS,
  distributed systems, databases, networking.
- **E. ML / AI / Model Science** — architectures, training dynamics, scaling, evaluation,
  interpretability, the research literature itself.
- **F. Training Infrastructure / CUDA / Kernels / Hardware** — GPU architecture, CUDA,
  kernels, compilers, memory systems, quantization, consumer-hardware specifics.
- **G. Formal Logic / Verification / Proof** — logic, type theory, theorem proving,
  program verification, proof corpora.
- **H. Software Engineering / Debugging / Testing** — engineering practice, debugging,
  testing, code review, incident analysis.
- **I. Data / Corpus / Evaluation / Decontamination** — dataset construction, curation,
  dedup, contamination detection, benchmark design.
- **J. Scientific Method / Lab Operation / Receipts** — experimental design,
  pre-registration, reproducibility, lab notebooks, negative results.
- **K. Application Worlds** — code, CAD/BIM, robotics, simulation, architecture, and other
  domains where created models act.

## Bars

- **Quality**: every source is license-clean, provenance-manifested (L4: source →
  generator → verifier chain), deduplicated, and decontaminated against the frozen eval
  suites before any training use. Quality is receipted per acquisition, never asserted.
- **Diversity**: within each domain, multiple independent sources and registers
  (textbook, paper, reference, applied); a domain fed from a single source fails the bar.
- **Anti-distillation (L3, absolute)**: connectors FETCH; no external model authors,
  filters, ranks, scores, or selects a training token in any role. All curation is local.
- **Zero-cost (L5)**: free/public tiers only.

## Programmatic access (first-class lab equipment)

Direct programmatic connectors — CLI, API, or MCP — to at minimum: Hugging Face, Kaggle,
arXiv, and NeurIPS/ICML proceedings (OpenReview). Every acquisition through a connector
emits a receipt (source id, license, bytes, hashes, timestamp, manifest path).

## Status

Acquisition state per domain is tracked in the corpus program issue and its per-domain
sub-issues on the workbench; the board's data conditions consume those receipts.

- Answers: what corpus a closed-loop lab must hold; edited-by: maintainer via PR;
  invalidated-by: a domain standing at zero receipted acquisitions while the charter holds.

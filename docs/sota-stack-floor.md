# Ember SOTA-stack floor v1

**Status:** initial cited gap-table mechanism. **Evidence date:** 2026-07-27.
**Claim boundary:** this table records gaps; it does not claim frontier parity.
The field must be re-surveyed before any contribution claim that depends on a
row whose cited evidence has materially changed.

The translation IDs point to
[`docs/inference-to-training-translation-v1.md`](inference-to-training-translation-v1.md).
`UNMEASURED` and `LAGS` are honest research-queue states.

| Layer | Irreducible job | External frontier evidence | Ember evidence | Gap | Training translation |
|---|---|---|---|---|---|
| Objective and curriculum | Turn fixed tokens into transferable predictive structure | Multi-token prediction adds future-token objectives ([MTP](https://arxiv.org/abs/2404.19737)) | `configs/v0-pretrain-config.json` specifies two MTP heads; isolated value is unreceipted | UNMEASURED | [T02](inference-to-training-translation-v1.md#standing-process) |
| Architecture and conditional compute | Allocate capacity and compute per token | Sparse conditional compute is established by [Switch Transformer](https://arxiv.org/abs/2101.03961) | `tools/ember-restart-3b` contains owned routing, but no residency-sparse training receipt | LAGS | [T04](inference-to-training-translation-v1.md#standing-process) |
| Tokenizer and vocabulary | Encode modalities with stable owned identities | No single universal frontier is asserted; task and language coverage remain empirical | `tokenizer/tokenizer.json` is checked in and custody-bound; comparative efficiency is unmeasured | UNMEASURED | [T16](inference-to-training-translation-v1.md#standing-process) |
| Quantization | Reduce weight bandwidth without losing trainability | Integer QAT is established ([Jacob et al.](https://arxiv.org/abs/1712.05877)); native ternary recipes exist ([BitNet](https://arxiv.org/abs/2402.17764)) | QAT configuration and historical harnesses exist; no current owned native low-bit checkpoint is admitted | LAGS | [T01](inference-to-training-translation-v1.md#standing-process), [T08](inference-to-training-translation-v1.md#standing-process) |
| Optimizer and schedule | Convert gradients into stable progress under bounded memory | [8-bit optimizers](https://arxiv.org/abs/2110.02861) and [GaLore](https://arxiv.org/abs/2403.03507) reduce optimizer/update memory | Current governed path rejects AdamW8bit identity; no GaLore-class receipt | LAGS | [T11](inference-to-training-translation-v1.md#standing-process), [T12](inference-to-training-translation-v1.md#standing-process) |
| Data pipeline | Deliver owned, resumable, correctly mixed examples | The frontier is dataset- and objective-dependent; no universal winner is asserted | Four-domain input identity and shard custody exist; sufficient pretraining remains false | UNMEASURED | [T07](inference-to-training-translation-v1.md#standing-process) |
| Parameter growth | Add capacity without destroying learned function | No cited universal frontier is asserted; Net2Net and expert addition require task-specific controls | Growth harnesses and historical receipts exist; no current 3B birth/growth completion claim | UNMEASURED | [T06](inference-to-training-translation-v1.md#standing-process) |
| Multimodal fusion | Learn native text, image, and audio representations in one foundation model | No single architecture is declared frontier without a frozen comparative suite | Unified-decoder design and modality paths exist; native sufficiently trained checkpoint is absent | LAGS | [T10](inference-to-training-translation-v1.md#standing-process) |
| Long-context state | Preserve useful context with bounded memory and compute | [Mamba](https://arxiv.org/abs/2312.00752) provides a selective linear-time alternative; [GQA](https://arxiv.org/abs/2305.13245) reduces KV heads | GQA is specified; subquadratic architecture and long-context training receipts are absent | LAGS | [T05](inference-to-training-translation-v1.md#standing-process), [T14](inference-to-training-translation-v1.md#standing-process) |
| Inference and decoding | Produce tokens with low latency and memory | [FlashAttention](https://arxiv.org/abs/2205.14135), GQA, and speculative/MTP families are established research directions | Several mechanisms are specified or historically harnessed; current owned checkpoint benefit is unmeasured | UNMEASURED | [T02](inference-to-training-translation-v1.md#standing-process), [T13](inference-to-training-translation-v1.md#standing-process) |
| Serving runtime | Keep owned model execution resident and inspectable | Runtime maturity is implementation- and hardware-specific; no universal external winner is asserted | `runtime/ember-lab` and `tools/ember-cli` are owned surfaces; end-to-end owned-model independence is incomplete | UNMEASURED | [T03](inference-to-training-translation-v1.md#standing-process), [T09](inference-to-training-translation-v1.md#standing-process) |

## Cross-node synthesis boundary

The currently physics-motivated candidate is a quantized frozen majority plus
an owned sparse trainable slice, GQA or subquadratic state, IO-aware attention,
and memory-reduced optimizer/update state. It remains a **candidate**, not a
result. Its missing load-bearing proof is a governed, owned, sufficiently
trained checkpoint with matched controls, external evaluation, resource
receipts, and deletion tests.

## Maintenance

Each contribution proposal must name the affected rows, revalidate their cited
frontier artifacts, and record any delta before freezing its comparator. The
automated frontier-delta alarm required by the specification has not landed;
that absence remains visible rather than being inferred away.

export const meta = {
  name: 'gpu-math-attack',
  description: 'Mine + adversarially refute 4090-scale throughput/efficiency multipliers for the owned-core envelope (fp-19)',
  whenToUse: 'June-22 push: attack the GPU long pole. Re-run when the technique contract changes or a bench receipt lands. args: {benchReceipt?: path} — pass the fp19-bench receipt path to get envelope ratios computed against measured paced tok/s.',
  phases: [
    { title: 'Mine', detail: 'one Haiku agent per technique — 4090-scale multiplier with citations' },
    { title: 'Refute', detail: 'two Haiku refuters per surviving claim' },
    { title: 'Assemble', detail: 'deterministic ranked table; envelope math if bench receipt provided' },
  ],
}
// Constraints (non-negotiable, per user 2026-06-11): model:'haiku' explicit on
// EVERY agent() call; agents NEVER dispatch GPU work / daemon jobs / mail /
// merges — read-only research legs; the verdict is Leo's, from receipts.
const CLAIM = {
  type: 'object',
  properties: {
    technique: { type: 'string' },
    axis: { type: 'string', enum: ['step_throughput', 'data_efficiency', 'sampling_throughput', 'memory_enables_batch'] },
    claimed_multiplier: { type: 'number' },
    baseline: { type: 'string' },
    conditions: { type: 'string' },
    citations: { type: 'array', items: { type: 'string' } },
    fits_4090_24gb: { type: 'boolean' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    notes: { type: 'string' },
  },
  required: ['technique', 'axis', 'claimed_multiplier', 'baseline', 'conditions', 'citations', 'fits_4090_24gb', 'confidence'],
}
const VERDICT = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    adjusted_multiplier: { type: 'number' },
    reasons: { type: 'array', items: { type: 'string' } },
  },
  required: ['refuted', 'adjusted_multiplier', 'reasons'],
}
const TECHNIQUES = [
  { key: 'fp8-ada', q: 'FP8 training on Ada-class GPUs (RTX 4090 has FP8 tensor cores; transformer-engine / torchao paths). Realistic training step-throughput multiplier vs bf16 at 0.1-0.3B params, seq 1024, on ONE 4090. Note software-support caveats on consumer Ada.' },
  { key: 'muon', q: 'Muon optimizer (momentum-orthogonalized) vs AdamW for small-LM pretraining: data-efficiency multiplier (tokens to reach equal loss) at 0.1-0.3B scale. Cite the Keller Jordan speedrun / K2 / Kimi results honestly; separate wall-clock overhead of Newton-Schulz from the data-efficiency gain.' },
  { key: 'mtp', q: 'Multi-token prediction auxiliary heads during pretraining: data-efficiency multiplier (denser supervision per token) at sub-1B scale; cite DeepSeek-V3 MTP, Meta MTP paper; note our own receipt (W-code r1: MTP arm +5.23pp where plain SFT was flat) as local evidence of the densification direction.' },
  { key: 'ternary-bitnet', q: 'BitNet b1.58 ternary from-scratch training on one 4090: what it multiplies is MEMORY/serving and possibly batch size, NOT step throughput (trains with fp shadow weights + STE). Quantify honestly: memory-enables-batch multiplier at 0.1-0.3B, and whether training is SLOWER per step.' },
  { key: 'qat', q: 'Quantization-aware pretraining (fake-quant in the loop) overhead at 0.1-0.3B: step-throughput COST multiplier (expected <1.0) and what it buys (deploy-time int4/int8 with no PTQ loss). Distinguish from BitNet.' },
  { key: 'sparse-attn-short-seq', q: 'Content-dependent sparse / linear-hybrid attention (NSA, MoBA, lightning, gated-deltanet) at seq 1024: honest step-throughput multiplier at SHORT sequence on 0.1-0.3B (expectation: near 1.0 — attention is a small FLOP fraction at seq 1024; say so if true).' },
  { key: 'data-selection', q: 'Data selection / dedup-cap / curriculum for small-LM pretraining (DoReMi, DSIR, dedup results, SlimPajama findings): data-efficiency multiplier (tokens needed to equal-loss vs unfiltered). Note our local receipt: cluster-cap cut 2,321 to 394 SFT steps (~5.9x) at equal evidence mass (eng26-cap receipt) — SFT-side analogue, do not double-count it as pretrain evidence.' },
  { key: 'mla-kv-sampling', q: 'MLA / KV-compression and speculative decoding for the SAMPLING side of the loop (verified-episodes-per-GPU-hour includes sampling cost): generation-throughput multiplier on one 4090 for 1.5-3B-class samplers (our q3/q15). Cite MLA, GQA baselines, speculative/MTP decode.' },
]
phase('Mine')
const results = await pipeline(
  TECHNIQUES,
  t => agent(
    `You are a research leg for a local-pretrain feasibility envelope (RTX 4090, 24GB, one GPU, decoder LMs 0.1-0.3B params, seq 1024, bf16-AdamW-dense baseline). READ-ONLY task: do NOT run GPU work, do NOT dispatch daemon jobs, do NOT send mail, do NOT merge anything.
Mine this technique for its realistic multiplier: ${t.q}
Rules: be conservative; one multiplier number on ONE axis (pick the dominant axis); name the baseline it multiplies; citations = paper/repo identifiers (arXiv IDs, repo names) — no fabricated cites; if the honest answer is ~1.0x at our scale, SAY 1.0 and explain. Local receipts you may cite live under B:\\M\\avir\\leo\\state\\nc-ladder\\receipts\\ (read-only).`,
    { label: `mine:${t.key}`, phase: 'Mine', model: 'haiku', schema: CLAIM }
  ),
  (claim, t) => claim && parallel([0, 1].map(i => () => agent(
    `Adversarial refuter ${i + 1} of 2. READ-ONLY (no GPU, no daemon, no mail). Try to REFUTE or DOWN-ADJUST this multiplier claim before it enters a feasibility envelope for one RTX 4090, 0.1-0.3B decoder pretrain, seq 1024:
${JSON.stringify(claim)}
Attack surfaces: (a) scale mismatch (claim measured at 7B+ or multi-GPU); (b) GPU-class mismatch (H100 features absent on consumer Ada, e.g. TE support); (c) training-vs-inference confusion; (d) double-counting with other stack techniques; (e) citation does not support the number. Output refuted=true ONLY for a concrete checkable flaw; otherwise refuted=false with adjusted_multiplier = your honest 4090-scale number (may equal the claim).`,
    { label: `refute:${t.key}:${i + 1}`, phase: 'Refute', model: 'haiku', schema: VERDICT }
  ))).then(vs => ({ claim, verdicts: vs.filter(Boolean) }))
)
phase('Assemble')
const table = []
const rejected = []
for (const r of results.filter(Boolean)) {
  const { claim, verdicts } = r
  const refutes = verdicts.filter(v => v.refuted).length
  if (refutes >= 2) { rejected.push({ technique: claim.technique, reasons: verdicts.flatMap(v => v.reasons) }); continue }
  const adj = Math.min(claim.claimed_multiplier, ...verdicts.map(v => v.adjusted_multiplier))
  table.push({
    technique: claim.technique, key: claim.technique, axis: claim.axis,
    claimed: claim.claimed_multiplier, surviving_multiplier: adj,
    contested: refutes === 1, conditions: claim.conditions,
    citations: claim.citations, confidence: claim.confidence,
    refuter_reasons: verdicts.flatMap(v => v.reasons).slice(0, 6),
  })
}
table.sort((a, b) => b.surviving_multiplier - a.surviving_multiplier)
let envelope = null
if (args && args.benchReceipt) {
  envelope = { note: 'compute envelope by applying data_efficiency multipliers to needed-tokens and step_throughput multipliers to measured paced tok/s from ' + args.benchReceipt + ' — Leo computes against the receipt, agents never did' }
}
return { multiplier_table: table, rejected, envelope_note: envelope, discipline: 'verdict is Leo\'s from receipts; this table is evidence legs only' }

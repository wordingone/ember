export const meta = {
  name: 'gpu-math-attack-v2',
  description: 'RIGOROUS 4090-scale multiplier mining for the owned-core feasibility envelope (fp-19): Opus miners, 5 perspective-diverse refuter lenses, REAL nested citation verification (WebSearch), an Opus completeness critic with one expansion round, and deterministic envelope math against the receipted fp19-bench numbers. Successor to gpu-math-attack.',
  whenToUse: 'June-22 push, deepened. Pass args:{bench:{...}} with the c03-bf16 (0.37B core) numbers from the fp19-bench receipt so the envelope is computed against measured paced tok/s. Verdict stays Leo\'s, from receipts; agents are read-only research legs.',
  phases: [
    { title: 'Mine', detail: 'one Opus agent per technique — 4090-scale multiplier + real citations' },
    { title: 'Refute', detail: 'five perspective-diverse Sonnet refuters per claim (scale/gpu-class/train-vs-inf/double-count/cite-fidelity)' },
    { title: 'Verify', detail: 'nested citation-verify workflow — WebSearch every surviving citation' },
    { title: 'Complete', detail: 'Opus completeness critic proposes missing techniques; one expansion round' },
    { title: 'Envelope', detail: 'deterministic owned-core feasibility math against the bench receipt' },
  ],
}
// Non-negotiable: read-only research legs. Agents NEVER run GPU work, dispatch
// daemon jobs, send mail, or merge. model is explicit on EVERY agent() call
// (user opt-in to Opus/Sonnet for this run). The verdict is Leo's, from receipts.

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
    lens: { type: 'string' },
    refuted: { type: 'boolean' },
    adjusted_multiplier: { type: 'number' },
    reasons: { type: 'array', items: { type: 'string' } },
  },
  required: ['refuted', 'adjusted_multiplier', 'reasons'],
}
const MISSING = {
  type: 'object',
  properties: {
    missing: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          key: { type: 'string' },
          axis: { type: 'string', enum: ['step_throughput', 'data_efficiency', 'sampling_throughput', 'memory_enables_batch'] },
          q: { type: 'string' },
          why_it_matters: { type: 'string' },
        },
        required: ['key', 'axis', 'q'],
      },
    },
    reasoning: { type: 'string' },
  },
  required: ['missing'],
}

// Five distinct adversarial lenses — perspective-diverse verification, not N
// identical refuters. Each attacks a different failure mode.
const LENSES = [
  { key: 'scale-mismatch', focus: 'Was the multiplier measured at 7B+ params or multi-GPU, then assumed to hold at 0.1-0.4B on ONE 4090? Small-scale numbers are often much weaker. Refute if the evidence is only at large scale.' },
  { key: 'gpu-class', focus: 'Does this need Hopper/H100 features absent or crippled on consumer Ada (RTX 4090)? e.g. FP8 via transformer-engine silently falls back to BF16 on sm89; some kernels are H100-only. Refute if the gain depends on hardware the 4090 lacks.' },
  { key: 'train-vs-inference', focus: 'Is the multiplier an INFERENCE/serving gain being mis-applied to TRAINING step-throughput (or vice-versa)? Pretrain and sampling are different axes. Refute if the axis is confused.' },
  { key: 'double-count', focus: 'Does this gain OVERLAP another technique already in the stack (e.g. flash-attention + torch.compile + a fused kernel all claiming the same attention speedup)? Refute/down-adjust if it would be double-counted in a stacked envelope.' },
  { key: 'cite-fidelity', focus: 'Do the cited sources actually STATE this number, at this scale, on this axis? A plausible-but-uncited number is a fabrication risk. Down-adjust to the honest defensible number; refute if the citation clearly does not support it.' },
]

const TECHNIQUES = [
  { key: 'fp8-ada', axis: 'step_throughput', q: 'FP8 training on RTX 4090 (Ada sm89, has FP8 tensor cores) via transformer-engine / torchao at 0.1-0.4B, seq 1024. Our survey prior: SKIP — TE silently falls back to BF16 on consumer Ada, torchao tensorwise-only on sm89, zero published 4090 FP8 pretrains. Confirm or refute that prior with the most current evidence; give the honest step-throughput multiplier (expectation near 1.0).' },
  { key: 'muon', axis: 'data_efficiency', q: 'Muon optimizer (momentum-orthogonalized, Newton-Schulz) vs AdamW for small-LM pretrain: tokens-to-equal-loss multiplier at 0.1-0.4B. Cite Keller Jordan modded-nanogpt speedrun, Moonlight/Kimi K2, torch.optim Muon. Separate the data-efficiency gain from the per-step Newton-Schulz wall-clock overhead. Our survey prior: ADOPT (~2x, strongest validated item at our scale).' },
  { key: 'mtp-pretrain', axis: 'data_efficiency', q: 'Multi-token-prediction auxiliary heads during PRETRAIN (denser supervision per token) at sub-1B. Cite DeepSeek-V3 MTP, Meta 2404.19737, TOP. Our survey prior: NEGATIVE quality evidence <=1B (Meta "worse on smaller models"); we RE-STAGED MTP to a speculative-decode drafter, not a pretrain quality lever. Give the honest pretrain data-efficiency multiplier at our scale (may be <=1.0).' },
  { key: 'ternary-bitnet', axis: 'memory_enables_batch', q: 'BitNet b1.58 ternary FROM-SCRATCH on one 4090 at 0.1-0.4B: it multiplies MEMORY/residency (and possibly batch size), NOT training step-throughput (trains with fp shadow weights + STE, often slower per step). Cite BitNet b1.58, Falcon-Edge, onebitllms. Quantify the memory-enables-batch multiplier honestly and state whether training is slower per step.' },
  { key: 'qat-int4', axis: 'step_throughput', q: 'Quantization-aware pretraining (fake-quant int4 in the loop, torchao) overhead at 0.1-0.4B: the step-throughput COST multiplier (expected <1.0) and what it buys (deploy-time int4 with no PTQ cliff). Cite torchao QAT. Distinguish from BitNet. Our bench measured ~0.92x (qat vs bf16 paced) as an STE proxy.' },
  { key: 'sparse-attn-short', axis: 'step_throughput', q: 'Content-dependent sparse / linear-hybrid attention (DeepSeek NSA, Moonshot MoBA, MiniMax lightning, Qwen gated-deltanet) at seq 1024 on 0.1-0.4B: honest step-throughput multiplier at SHORT sequence. Expectation: ~1.0 (attention is a small FLOP fraction at seq 1024; NSA attended-token floor ~1.5-2k). Cite NSA, MoBA. Say 1.0 if true.' },
  { key: 'data-selection', axis: 'data_efficiency', q: 'Data selection / dedup-cap / curriculum for small-LM pretrain: tokens-to-equal-loss multiplier vs unfiltered. Cite DoReMi, DSIR, SemDeDup, SlimPajama. Note our LOCAL receipt cluster-cap cut 2,321->394 SFT steps (~5.9x) at equal evidence mass (SFT-side analogue — do NOT double-count as pretrain evidence). Give the honest pretrain data-efficiency multiplier.' },
  { key: 'mla-kv-speculative', axis: 'sampling_throughput', q: 'MLA / KV-compression + speculative (MTP-drafter) decoding for the SAMPLING side of the loop (verified-episodes-per-GPU-hour includes sampling): generation-throughput multiplier on one 4090 for 1.5-3B samplers. Cite DeepSeek MLA, GQA, Medusa/EAGLE speculative decode. This is the SAMPLING axis, separate from pretrain.' },
  { key: 'gradient-checkpointing', axis: 'memory_enables_batch', q: 'Activation/gradient checkpointing at 0.1-0.4B, seq 1024 on a 24GB 4090: the memory it frees (enabling larger batch) vs the recompute step-throughput cost (~20-30%). Our bench already has checkpointing ON. Cite the original gradient-checkpointing work. Give the net memory-enables-batch multiplier honestly (it is a memory-for-compute trade, often net-negative on throughput).' },
  { key: 'flash-attention-3', axis: 'step_throughput', q: 'FlashAttention-2/3 vs a naive attention baseline at 0.1-0.4B, seq 1024 on Ada: step-throughput multiplier. Note FA3 is Hopper-tuned; FA2 is the 4090 reality. At seq 1024 attention is a modest FLOP fraction, so the end-to-end multiplier is much smaller than the attention-kernel multiplier. Cite FlashAttention-2/3. Give the honest END-TO-END number.' },
  { key: 'torch-compile', axis: 'step_throughput', q: 'torch.compile (inductor) end-to-end training step-throughput multiplier for a small decoder LM at 0.1-0.4B on a 4090 vs eager. Cite PyTorch 2.x compile benchmarks. Give the realistic kernel-fusion multiplier (typically modest, 1.1-1.4x end-to-end for small models) and note overlap with flash-attention/fused optimizers (double-count risk).' },
  { key: '8bit-adam', axis: 'memory_enables_batch', q: 'bitsandbytes 8-bit Adam vs 32-bit Adam optimizer state at 0.1-0.4B: the VRAM it frees (optimizer state is ~2x params in fp32) and whether that enables a larger batch on a 24GB card. Cite bitsandbytes / 8-bit optimizers paper. Give the memory-enables-batch multiplier; note near-zero throughput change.' },
  { key: 'sequence-packing', axis: 'data_efficiency', q: 'Sequence packing / no-pad batching (concatenate short docs to fill seq 1024, block-diagonal attention) for small-LM pretrain: the effective tokens-per-step / wasted-compute reduction vs padded batches. Cite packing in T5/GPT pretrain recipes, FlashAttention varlen. Give the honest effective-throughput multiplier (depends on doc-length distribution).' },
]

// ---- helpers (pure JS; no file/network access in the script itself) --------
const mineStage = (t) => agent(
  `You are a research leg for a LOCAL-pretrain feasibility envelope: RTX 4090, 24GB, ONE GPU, decoder LM 0.1-0.4B params, seq 1024, bf16-AdamW-dense baseline (our receipted bench: 0.37B core = 20,201 tok/s paced). READ-ONLY: do NOT run GPU work, dispatch daemon jobs, send mail, or merge.
Mine this technique for its realistic 4090-scale multiplier on its dominant axis: ${t.q}
Rules: be conservative; ONE multiplier number on ONE axis (${t.axis} is the expected axis — override only with justification); name the baseline it multiplies; citations = real paper/repo identifiers (arXiv ids, repo names) you are confident exist — NO fabricated cites; if the honest answer is ~1.0x at our scale, SAY 1.0 and explain why. Treat any "survey prior" in the question as a hypothesis to TEST, not to accept.`,
  { label: `mine:${t.key}`, phase: 'Mine', model: 'opus', schema: CLAIM }
)

const refuteStage = (claim, t) => claim && parallel(LENSES.map(L => () => agent(
  `Adversarial refuter — lens "${L.key}". READ-ONLY (no GPU, no daemon, no mail, no merge). Attack this 4090-scale multiplier claim from ONLY your lens before it enters an owned-core feasibility envelope (0.1-0.4B decoder pretrain, seq 1024, one RTX 4090):
${JSON.stringify(claim)}
YOUR LENS: ${L.focus}
Output refuted=true ONLY for a concrete, checkable flaw visible through your lens; otherwise refuted=false with adjusted_multiplier = your honest 4090-scale number (may equal the claim). Always set lens="${L.key}". Give concrete reasons.`,
  { label: `refute:${t.key || claim.technique}:${L.key}`, phase: 'Refute', model: 'sonnet', schema: VERDICT }
))).then(vs => ({ claim, verdicts: (vs || []).filter(Boolean) }))

const assemble = (rounds) => {
  const survivors = [], rejected = []
  for (const r of (rounds || []).filter(Boolean)) {
    const { claim, verdicts } = r
    const refutes = verdicts.filter(v => v.refuted).length
    if (refutes >= 3) {
      rejected.push({ technique: claim.technique, axis: claim.axis, refutes, reasons: verdicts.flatMap(v => v.reasons).slice(0, 8) })
      continue
    }
    const adj = Math.min(claim.claimed_multiplier, ...verdicts.map(v => v.adjusted_multiplier))
    survivors.push({
      technique: claim.technique, axis: claim.axis,
      claimed: claim.claimed_multiplier, surviving_multiplier: adj,
      contested: refutes >= 1, refutes,
      baseline: claim.baseline, conditions: claim.conditions,
      citations: claim.citations || [], confidence: claim.confidence,
      fits_4090_24gb: claim.fits_4090_24gb,
      refuter_reasons: verdicts.flatMap(v => v.reasons).slice(0, 6),
      citation_verification: null, evidence_class: 'HYPOTHESIS',
    })
  }
  return { survivors, rejected }
}

const mergeVerify = (survivors, verifications) => {
  const byTech = {}
  for (const v of (verifications || [])) byTech[v.technique] = v
  for (const s of survivors) {
    const v = byTech[s.technique]
    if (v) {
      s.citation_verification = { overall: v.overall, evidence_class: v.evidence_class, reasons: (v.reasons || []).slice(0, 4) }
      s.evidence_class = v.evidence_class
    }
  }
}

const toVerifyClaim = (s) => ({ technique: s.technique, axis: s.axis, claimed_multiplier: s.claimed, surviving_multiplier: s.surviving_multiplier, citations: s.citations })

const computeEnvelope = (bench, survivors) => {
  if (!bench || !bench.ratio_7d) return { note: 'no bench numbers passed in args.bench — envelope not computed' }
  const STEP = ['step_throughput', 'memory_enables_batch']
  const stepS = survivors.filter(s => STEP.includes(s.axis) && s.surviving_multiplier > 0)
  const dataS = survivors.filter(s => s.axis === 'data_efficiency' && s.surviving_multiplier > 0)
  const sampS = survivors.filter(s => s.axis === 'sampling_throughput' && s.surviving_multiplier > 0)
  const grounded = (s) => s.evidence_class === 'EXTERNAL-CITED'
  const prod = (arr) => arr.reduce((p, s) => p * s.surviving_multiplier, 1)
  const maxm = (arr) => arr.length ? Math.max(...arr.map(s => s.surviving_multiplier)) : 1
  const round = (x) => Math.round(x * 1000) / 1000
  // Base = receipted bf16 envelope (compute-optimal multiple reachable in N days).
  const mk = (base, label) => {
    const consv = base * maxm(stepS) * maxm(dataS)
    const optim = base * prod(stepS) * prod(dataS)
    const groundedOptim = base * prod(stepS.filter(grounded)) * prod(dataS.filter(grounded))
    return {
      window: label,
      base_ratio_receipted: round(base),
      conservative_ratio: round(consv),
      grounded_optimistic_ratio: round(groundedOptim),
      optimistic_ratio_upper_bound: round(optim),
      days_to_compute_optimal_base: round(7 / base),
      days_to_compute_optimal_grounded: round(7 / groundedOptim),
    }
  }
  return {
    core: bench.core || 'c03-bf16 (0.37B owned-core proxy)',
    tok_s_paced_receipted: bench.tok_s_paced,
    source: bench.source,
    pretrain_envelope: [mk(bench.ratio_7d, '7-day burst'), mk(bench.ratio_8d, '8-day burst')],
    step_multipliers_applied: stepS.map(s => ({ technique: s.technique, m: s.surviving_multiplier, evidence: s.evidence_class })),
    data_multipliers_applied: dataS.map(s => ({ technique: s.technique, m: s.surviving_multiplier, evidence: s.evidence_class })),
    sampling_multipliers_separate: sampS.map(s => ({ technique: s.technique, m: s.surviving_multiplier, evidence: s.evidence_class, note: 'applies to the loop SAMPLING axis (verified-episodes/GPU-hr), NOT the pretrain envelope' })),
    discipline: 'base_ratio is RECEIPTED (fp19-bench, governed 4090). conservative = base x max(step) x max(data). optimistic_upper_bound = base x PRODUCT(step) x PRODUCT(data) and is an UPPER bound only — stacked multipliers overlap and rarely fully compound. grounded_* counts ONLY EXTERNAL-CITED survivors. Any ratio >= 1.0 means the 0.37B core reaches compute-optimal (20 tok/param) inside the window. This is a CONDITIONAL projection feeding fp-19, not a certification.',
  }
}

// ---- run -------------------------------------------------------------------
phase('Mine')
const round1 = await pipeline(TECHNIQUES, mineStage, refuteStage)
const a1 = assemble(round1)
log(`round-1: ${a1.survivors.length} survive, ${a1.rejected.length} rejected (>=3/5 lenses)`)

phase('Verify')
const v1 = await workflow('citation-verify', { claims: a1.survivors.map(toVerifyClaim) })
mergeVerify(a1.survivors, (v1 && v1.verifications) || [])
log(`citation-verify: ${a1.survivors.filter(s => s.evidence_class === 'EXTERNAL-CITED').length}/${a1.survivors.length} EXTERNAL-CITED`)

phase('Complete')
const coveredKeys = [...TECHNIQUES.map(t => t.key)]
const critic = await agent(
  `READ-ONLY completeness critic for a 4090-scale owned-core PRETRAIN feasibility envelope (0.1-0.4B decoder, seq 1024, one RTX 4090). We attacked these technique keys (axes in parens):
${TECHNIQUES.map(t => `${t.key} (${t.axis})`).join(', ')}
Surviving with multipliers: ${a1.survivors.map(s => `${s.technique}=${s.surviving_multiplier}x[${s.axis}]`).join(', ') || 'none'}.
What 4090-scale technique or axis that MATERIALLY affects owned-core pretrain step-throughput, memory-enables-batch, data-efficiency, or loop-sampling throughput is MISSING from this list? Propose only techniques with a real chance of a >1.05x (or, for cost items, a clearly quantifiable) effect at our scale; do NOT repeat covered keys. For each, give a key, the axis, and a precise q an Opus miner can answer with real citations. Be selective — quality over quantity.`,
  { label: 'critic:completeness', phase: 'Complete', model: 'opus', schema: MISSING }
)
let extra = { survivors: [], rejected: [] }
const newTechs = ((critic && critic.missing) || []).filter(m => m.key && !coveredKeys.includes(m.key)).slice(0, 6)
if (newTechs.length) {
  log(`completeness round: mining ${newTechs.length} proposed-missing techniques`)
  const round2 = await pipeline(newTechs, mineStage, refuteStage)
  extra = assemble(round2)
  const v2 = await workflow('citation-verify', { claims: extra.survivors.map(toVerifyClaim) })
  mergeVerify(extra.survivors, (v2 && v2.verifications) || [])
}

phase('Envelope')
const allSurvivors = [...a1.survivors, ...extra.survivors].sort((a, b) => b.surviving_multiplier - a.surviving_multiplier)
const envelope = computeEnvelope(args && args.bench, allSurvivors)

return {
  multiplier_table: allSurvivors,
  rejected: [...a1.rejected, ...extra.rejected],
  completeness_critic: critic,
  envelope,
  discipline: 'Verdict is Leo\'s, from receipts. This table is read-only evidence legs: Opus-mined, refuted through 5 perspective-diverse lenses (kill at >=3/5), and citation-verified against the live web. Every multiplier carries an evidence_class (EXTERNAL-CITED vs HYPOTHESIS); the envelope is a CONDITIONAL projection over the receipted fp19-bench base, feeding fp-19 — not a certification.',
}

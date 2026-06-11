export const meta = {
  name: 'citation-verify',
  description: 'Web-verify each citation behind a 4090-scale multiplier claim (WebSearch/WebFetch): does the cited paper/repo actually state this number at this scale? Grounds claims in real sources instead of model memory.',
  whenToUse: 'Called by gpu-math-attack-v2 as a nested sub-step. args: {claims:[{technique,axis,claimed_multiplier,surviving_multiplier,citations:[...]}]}',
  phases: [
    { title: 'CiteVerify', detail: 'one Sonnet web-research agent per claim — check every citation' },
  ],
}
// Read-only: agents use WebSearch/WebFetch only; NO GPU, NO daemon, NO mail, NO merge.
const VERIFY = {
  type: 'object',
  properties: {
    technique: { type: 'string' },
    citation_results: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          citation: { type: 'string' },
          found_on_web: { type: 'boolean' },
          states_a_number: { type: 'boolean' },
          number_found: { type: 'string' },
          scale_of_measurement: { type: 'string' },
          supports_claimed_multiplier: { type: 'boolean' },
          note: { type: 'string' },
        },
        required: ['citation', 'found_on_web', 'supports_claimed_multiplier'],
      },
    },
    overall: { type: 'string', enum: ['SUPPORTED', 'PARTIAL', 'UNSUPPORTED', 'UNVERIFIABLE'] },
    evidence_class: { type: 'string', enum: ['EXTERNAL-CITED', 'HYPOTHESIS'] },
    reasons: { type: 'array', items: { type: 'string' } },
  },
  required: ['technique', 'overall', 'evidence_class'],
}
const claims = (args && args.claims) || []
phase('CiteVerify')
if (!claims.length) {
  return { verifications: [], note: 'no claims passed to citation-verify' }
}
const out = await parallel(claims.map(c => () => agent(
  `READ-ONLY web verification. Do NOT run GPU work, dispatch daemon jobs, send mail, or merge anything. Use the WebSearch and WebFetch tools to check whether the citations behind this 4090-scale multiplier claim ACTUALLY support it.

CLAIM:
${JSON.stringify(c)}

For EACH citation string (arXiv id, repo name, paper title, author): (1) WebSearch for it; (2) if found, WebFetch the most authoritative hit and read for a number on the SAME axis "${c.axis}"; (3) record the number found and the SCALE it was measured at (param count, GPU class, single-vs-multi-GPU, train-vs-inference). supports_claimed_multiplier = true ONLY when the source reports a comparable number at comparable scale (<=1B params, single consumer GPU, matching axis). If you cannot find the source, set found_on_web=false and do NOT invent a number.

overall: SUPPORTED if >=1 citation concretely supports the claimed/surviving multiplier; PARTIAL if only a related-but-different-scale number; UNSUPPORTED if the citations exist but contradict or omit the number; UNVERIFIABLE if no citation can be located. evidence_class = EXTERNAL-CITED iff overall in {SUPPORTED,PARTIAL}, else HYPOTHESIS. List concrete reasons. Never fabricate a citation or a number.`,
  { label: `verify:${c.technique}`, phase: 'CiteVerify', model: 'sonnet', schema: VERIFY, agentType: 'general-purpose' }
)))
return { verifications: out.filter(Boolean) }

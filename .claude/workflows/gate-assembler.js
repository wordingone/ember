export const meta = {
  name: 'gate-assembler',
  description: 'Parallel mechanical gate legs for an ember PR: scope diff, receipt field-exactness, selftest re-run from head, cross-receipt arithmetic, audit/STATE drafts',
  whenToUse: 'On every Eli PR gate (and self-gates) to compress serial gate minutes. args: {pr: number, claims?: string}. Returns an evidence bundle — the GATE VERDICT AND MERGE REMAIN LEO\'S; this workflow never approves, merges, mails, or dispatches GPU work.',
  phases: [
    { title: 'Evidence', detail: 'four parallel Haiku legs against the PR head' },
    { title: 'Bundle', detail: 'deterministic assembly + draft snippets' },
  ],
}
// Constraints (non-negotiable): model:'haiku' explicit on every agent();
// agents are READ-ONLY + local selftest execution (CPU) — NEVER gh pr merge /
// gh pr comment / mail_send / daemon dispatch / GPU work.
const LEG = {
  type: 'object',
  properties: {
    leg: { type: 'string' },
    pass: { type: 'boolean' },
    findings: { type: 'array', items: { type: 'string' } },
    numbers_checked: { type: 'array', items: { type: 'string' } },
  },
  required: ['leg', 'pass', 'findings', 'numbers_checked'],
}
// Runtime delivers args as a JSON string (verified wf_38f0566c: typeof args === 'string') — parse defensively.
const a = typeof args === 'string' ? JSON.parse(args) : args
const pr = a && a.pr
if (!pr) throw new Error('args.pr required (e.g. {pr: 112})')
const claims = (a && a.claims) || '(no mail-claims text provided — use the PR body as the claims source)'
const REPO = 'wordingone/ember'
const COMMON = `PR #${pr} on ${REPO}. Work READ-ONLY against the PR head: use \`git fetch origin pull/${pr}/head:gatewf${pr}\` in B:\\M\\avir\\leo\\state\\nc-ladder, then \`git show gatewf${pr}:<path>\` / \`git diff $(git merge-base origin/master gatewf${pr})..gatewf${pr}\`. NEVER: merge, comment, push, mail, dispatch daemon/GPU jobs, or modify the working tree (worktrees for selftest runs are OK, clean them up). Claims under test:\n${claims}\nReturn the StructuredOutput verdict; numbers_checked lists every number you actually recomputed.`
phase('Evidence')
const legs = await parallel([
  () => agent(`${COMMON}\nLEG scope: list every changed file vs merge-base; flag anything outside the issue's stated scope, any production data file modified, any deletion. pass=true iff scope is exactly the intended files.`, { label: `scope:#${pr}`, phase: 'Evidence', model: 'haiku', schema: LEG }),
  () => agent(`${COMMON}\nLEG receipts-field-exact: open every receipt JSON added by the PR; verify each numeric/boolean claim in the claims text against an ACTUAL receipt field (name the field); flag any claim with no backing field (the #91/#102 class). Recompute internal consistency (counts reconcile, fractions = numerator/denominator).`, { label: `receipts:#${pr}`, phase: 'Evidence', model: 'haiku', schema: LEG }),
  () => agent(`${COMMON}\nLEG selftest-from-head: create a temp git worktree of the PR head (git worktree add <tmp> gatewf${pr}), run every *selftest* the PR adds or touches (python <script> --selftest, CPU only), capture sentinel lines + exit codes, remove the worktree (git worktree remove -f, then git worktree prune). pass=true iff all selftests PASS with exit 0.`, { label: `selftest:#${pr}`, phase: 'Evidence', model: 'haiku', schema: LEG }),
  () => agent(`${COMMON}\nLEG cross-receipt: check the PR's numbers against PRIOR receipts in receipts/ (read-only) — pins, shas, counts that should match earlier gated receipts (e.g. fp-17 pins, fp-16 census cells, committed view shas). Name each cross-receipt pair checked. pass=true iff no mismatch.`, { label: `crossref:#${pr}`, phase: 'Evidence', model: 'haiku', schema: LEG }),
])
phase('Bundle')
const bundle = legs.filter(Boolean)
const allPass = bundle.length === 4 && bundle.every(l => l.pass)
return {
  pr,
  all_legs_pass: allPass,
  legs: bundle,
  draft_signoff_skeleton: allPass
    ? `Gate evidence bundle complete (4/4 legs pass) — LEO must verify the load-bearing numbers himself from the receipts before posting <!-- leo-signoff:approve --> and merging. This workflow output is evidence, not a verdict.`
    : `One or more legs failed or missing — DO NOT approve. Failed legs carry findings above.`,
  discipline: 'verdict/merge/mail are Leo-only; agents performed read-only legs + CPU selftests',
}

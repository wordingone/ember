# Issue #1413 checkpoint projection repair plan

## Scope

Repair the single-route all-expert optimizer-storage projection exposed by the
governed signature-census run. Preserve the conservative four-expert floor,
but count shared optimizer storage once and multiply only the active expert
storage across the four closed expert routes.

## Steps

1. Add failing assertions for the published storage projection and its failure
   operands: `shared + expert_count * active_expert`, never
   `(shared + active_expert) * expert_count`.
2. Introduce one closed helper for the projection and use it in both producer
   paths so success and quarantine evidence cannot diverge.
3. Replay the focused checkpoint tests, the affected runner tests, authority
   conservation, diff checks, and repository guard through owned finite-time
   processes.
4. Publish as a separate nonclosing defect carrier. Do not reuse or clean the
   failed census custody. Rebase/remint the census producer only after this
   repair is independently reviewed and merged.

## Claim boundary

This repair corrects checkpoint byte-budget projection only. It does not
produce a census, checkpoint, training result, acceleration result, benchmark,
milestone, or issue closure.

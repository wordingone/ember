# Stage-1 Zero-Claude Status

Updated: 2026-06-17

This branch tracks an agent's Zero-Claude-active Stage-1 first-words lane. It is a
work branch, not a completion claim.

## Scope

- Clean code/spec worktree: `<local-path>`
- Dirty execution/data tree: `<local-path>`
- Resume artifact: `<local-path>`
- Detailed handoff: `<local-path>`

The branch should carry source code and small docs. Bulky local execution
artifacts, generated image corpora, run directories, and large receipt sets stay
in `<local-path>` unless a later packaging decision explicitly promotes a small
subset.

## Current Evidence

Best equal-budget arm so far:

- `convstem + latent_refine_steps=2 + contrastive1 + prototype0.10`
- Receipt: `<local-path>`
- Heldout top1: image->word `0.222222`, word->image `0.166667`
- Chance top1: `0.055556`
- Verdict: `FAIL`

Comparison receipt:

`<local-path>`

The near-miss is evidence of signal, not evidence of completion. Do not escalate
to wake-only vs wake+sleep+dream A/B until bidirectional heldout `PASS` is
receipted.

## Next Lever

Run the projection-head arm described in
`<local-path>` when governed GPU execution
is available. The relevant code path is default-off and controlled by
`--stage1-projection-dim`.

Completion for this lane requires a bidirectional heldout `PASS` receipt.

# Governed owned-3B runner

This is the public production entrypoint for the clean-genesis
`ember-sparse-3b-v2` subject. It constructs the real model and optimizer,
consumes the checked-in owned training authority, executes the real training
path, and publishes manifest-last checkpoint bundles through the repository
disk governor.

The runner does not confer sufficient-pretraining, multimodal capability,
reasoning, tool-use, competitiveness, admission, or Verified Expert Accretion
credit. A successful bounded run is execution and restart evidence only.

## CPU-only launch preflight

Run from the repository root in PowerShell after creating an empty bounded
custody directory:

```powershell
$custody = 'B:\ember-runs\owned-3b-canary'
$artifacts = Join-Path $custody 'artifacts'
New-Item -ItemType Directory -Force -Path $artifacts | Out-Null
python -I src\ember\infrastructure\tools\ember-restart-3b\disk_budget_runner.py `
  --max-c-write-gib 0 `
  --max-b-write-gib 16 `
  --receipt (Join-Path $custody 'runner-preflight-receipt.json') `
  --write-root "custody=$custody" `
  --write-root "artifacts=$artifacts" `
  -- `
  python tools\ember-restart-3b\run_vertical_slice.py `
    governed-vertical-preflight `
    --seed 83 `
    --artifact-root $artifacts `
    --write-budget-bytes 17179869184 `
    --max-records 1
```

The child must return `PREFLIGHT_ONLY`. This command does not allocate CUDA or
perform a training update.

## One-record GPU canary

After the CPU preflight receipt passes and the single-GPU lease is available:

```powershell
python -I src\ember\infrastructure\tools\ember-restart-3b\disk_budget_runner.py `
  --max-c-write-gib 0 `
  --max-b-write-gib 16 `
  --receipt (Join-Path $custody 'runner-canary-receipt.json') `
  --write-root "custody=$custody" `
  --write-root "artifacts=$artifacts" `
  -- `
  python tools\ember-restart-3b\run_vertical_slice.py `
    governed-vertical `
    --seed 83 `
    --artifact-root $artifacts `
    --write-budget-bytes 17179869184 `
    --max-records 1
```

The governed checkpoint publication bound is `12,202,530,816` bytes. The
separate transient checkpoint-scratch cap is `4,294,967,296` bytes. New
checkpoints use the closed v5 split:

- `shared-model.pt`
- `optimizer-state.pt`
- `replay-state.pt`
- `expert-vision.pt`
- `expert-audio.pt`
- `expert-reasoning.pt`
- `expert-tool.pt`
- `checkpoint-manifest.json`, written last

The loader, counter, serving path, and model-only optimizer transition retain
explicit read compatibility for historical v3/v4 `shared.pt` bundles. The v5
model-only transition never opens `optimizer-state.pt`.

## Resume

Resume only from a content-addressed published bundle and one matching
counter, realization, or optimizer-transition authority:

```powershell
python -I src\ember\infrastructure\tools\ember-restart-3b\disk_budget_runner.py `
  --max-c-write-gib 0 `
  --max-b-write-gib 16 `
  --receipt (Join-Path $custody 'runner-resume-receipt.json') `
  --write-root "custody=$custody" `
  --write-root "artifacts=$artifacts" `
  -- `
  python tools\ember-restart-3b\run_vertical_slice.py `
    governed-vertical `
    --seed 83 `
    --artifact-root $artifacts `
    --write-budget-bytes 17179869184 `
    --max-records 1 `
    --resume-checkpoint '<published-checkpoint-directory>' `
    --resume-realization-registry '<matching-realization-registry>'
```

The runner rejects an exhausted or mismatched cursor, wrong configuration or
tokenizer identity, wrong checkpoint bytes, missing optimizer authority,
resource-floor breach, write-root escape, and a launch whose retained plus
transient write envelope exceeds the declared budget.

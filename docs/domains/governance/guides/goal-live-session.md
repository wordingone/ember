# Compiled goal-session live receipt

Issue #211's live acceptance path is a model-free, deterministic local-session
probe. It uses the real continuation engine, GoalStore transition boundary,
receipt transition writer, and compiled `ember` entrypoint; it does not claim
model quality or training progress.

From `src/ember/infrastructure/tools/ember-cli/src`, build and run the exact command:

```powershell
$exe = Join-Path $env:TEMP "ember-goal-live.exe"
$commit = (git rev-parse HEAD).Trim()
$define = 'globalThis.__EMBER_BUILD_COMMIT__=\"' + $commit + '\"'
bun build .\entrypoints\main.ts --compile --outfile $exe --define $define
& $exe goal-session-live
Remove-Item -LiteralPath $exe -Force
```

The command emits one path-free JSON object with schema
`ember-goal-live-session-receipt-v1`. The checked-in deterministic fixture is
`src/ember/infrastructure/tools/ember-cli/src/fixtures/goal-live-session-receipt-v1.json`.

The receipt contains three rendered, fixed-dimension frame captures from the compiled session. Each frame binds UTF-8 bytes, width/height, sequence,
receipt range, the exact frame-source SHA, and the compiled executable SHA;
the checked-in test recomputes each hash and rejects a one-byte tamper.

Acceptance evidence is bounded to: at least three autonomous continuation
events after boot with zero user input, refusal of premature `Complete` at
both tool and store boundaries, an evidence-bearing `Complete` transition,
and queued-user-input preemption with zero started turns. A refused or
unavailable external model endpoint is outside this model-free probe and does
not alter the receipt claim boundary.

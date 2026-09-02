# Floor Contract Test Fixture

## What v0 already carries

| Component | v0 surface | Evidence |
|---|---|---|
| Reserved vocab | 8 reserved IDs | tokenizer-freeze.json |
| QAT | int8 fake-quant | precision.qat |

## Deferral rows

| Component | Why deferred | Receipt-producing pilot | Revision trigger | Owner | Status | Kill / promote condition |
|---|---|---|---|---|---|---|
| BitNet 1.58-bit | quality crossover ~3B | ternary pilot | hardware escalation | lead | RE-STAGED | promote on >=3B |
| Sparse attention | NSA floor | 340M pilot | long-context admission | lead | RE-STAGED | promote on parity |
| MoE | trades VRAM | none at scale | multi-GPU evidence | lead | SKIP-with-receipt | re-enter on hardware |

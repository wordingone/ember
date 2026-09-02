# Ember Floor Contract — In-Vehicle Components Only

This fixture has the "What v0 already carries" table but NO "Deferral rows" section.
Used to test the precedence bug fix where partial manifest should be returned with errors.

## What v0 already carries

| Component | v0 surface | Evidence |
|-----------|-----------|----------|
| Reserved vocab | 8 reserved IDs | tokenizer-freeze.json |
| QAT | 8-bit quantization | training/qat.py |

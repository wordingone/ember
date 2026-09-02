# Ember Floor Contract — Unknown Status in Deferral

This fixture has both in-vehicle and deferral tables, but a deferral row with an unknown status.
Used to test the _map_status_to_disposition fix for unmapped status values.

## What v0 already carries

| Component | v0 surface | Evidence |
|-----------|-----------|----------|
| QAT | 8-bit quantization | training/qat.py |

## Deferral rows

| Component | Why deferred | Receipt-producing pilot | Revision trigger | Owner | Status | Kill/promote |
|-----------|-------------|------------------------|------------------|-------|--------|-------------|
| Unrecognized status test | Test case | test.json | on-merge | test-lead | FUTURE_UNKNOWN_STATUS | cannot be removed yet |

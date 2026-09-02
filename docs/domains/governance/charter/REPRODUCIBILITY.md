# Reproducibility Guide

What can be reproduced from this repository, and how.

## Prerequisites

- Python 3.11+
- **For selftests and schema checks:** No external dependencies (stdlib only)
- **For corpus acquisition and full training:** Additional packages required (pinned separately; not in this repo)
- NVIDIA RTX 4090 (24 GB VRAM) required for training runs

## Checks that require no model weights and no GPU

These are the only checks fully reproducible without local hardware or
out-of-tree data:

### Receipt schema validation

```bash
# Self-test (pure-logic; no files on disk needed)
python src/ember/governance/scripts/receipt_check.py --selftest

# Report over every receipt in receipts/
python src/ember/governance/scripts/receipt_check.py --all

# Fail-closed validation of a single receipt file
python src/ember/governance/scripts/receipt_check.py --file receipts/<receipt>.json
```

Expected output on success: `RECEIPT_CHECK_SELFTEST_PASS` (selftest mode) or
a per-file findings table with exit code 0 (report mode).

### Corpus pipeline selftests

```bash
python src/ember/governance/scripts/corpus_acquire_selftest.py
python src/ember/governance/scripts/corpus_mix_selftest.py
```

These test the pipeline logic against constructed fixtures; they do not
download any data.

### Gate component selftests

Each script below tests one gate component using constructed inputs. All
print a `*_SELFTEST_PASS` sentinel on success and exit non-zero on failure.

```bash
python src/ember/governance/scripts/ember_gate_cleanroom_inventory_selftest.py
python src/ember/governance/scripts/ember_gate_cleanroom_legal_boundary_selftest.py
python src/ember/governance/scripts/ember_gate_full_parity_harness_selftest.py
python src/ember/governance/scripts/ember_gate_receipt_store_selftest.py
python src/ember/governance/scripts/ember_gate_state_persistence_selftest.py
python src/ember/governance/scripts/ember_gate_hook_runner_selftest.py
python src/ember/governance/scripts/ember_gate_launch_packaging_selftest.py
python src/ember/governance/scripts/ember_gate_rollback_rewind_selftest.py
python src/ember/governance/scripts/ember_gate_process_supervision_selftest.py
python scripts/ember_gate_tool_dispatch_permissions_selftest.py
python src/ember/governance/scripts/ember_gate_function_slash_commands_selftest.py
python src/ember/governance/scripts/ember_gate_communication_mailbox_computer_use_selftest.py
python src/ember/governance/scripts/ember_gate_goal_mode_parity_adapter_selftest.py
python src/ember/governance/scripts/ember_gate_backend_coordinator_agents_selftest.py
```

### Candidate generator selftest

```bash
python src/ember/governance/scripts/ember_candidate_generator_selftest.py
```

### D3 loop selftests

```bash
python src/ember/governance/scripts/ember_d3_broader_multifamily_admission_selftest.py
python src/ember/governance/scripts/ember_d3_broader_multifamily_loop_selftest.py
python src/ember/governance/scripts/ember_d3_generalized_candidate_exec_selftest.py
```

## Checks that require out-of-tree data or hardware

These require additional resources not included in this repository:

| check | what you need |
|---|---|
| `src/ember/governance/scripts/corpus_acquire.py` | several hundred GB local disk; internet access |
| `src/ember/governance/scripts/corpus_mix.py` | hydrated corpus from `corpus_acquire.py` |
| `scripts/train_multimodal_v0.py` | 24 GB VRAM GPU; hydrated corpus |
| any eval script | model weights (produced by training) |
| ScienceAgentBench tasks | local artifact from canonical source (see receipt) |
| D3 benchmark tasks | local Docker environment; D3 task files |

Manifests for the v0 corpus are under `manifests/corpus/`. Download sources
and expected hashes are recorded there and in the relevant acquisition
receipts under `receipts/`.

## What the repository does not contain

- Model weights
- Token shards or hydrated corpus bytes
- Third-party benchmark data (licenses prohibit redistribution)
- Third-party `vendor/` clones (provenance must be pinned in receipts)

## Receipts as the authoritative record

Every executed job writes a JSON receipt to `receipts/`. The receipt is the
only admissible evidence for any claim. `src/ember/governance/scripts/receipt_check.py` is the
floor validator; its selftest is the minimum reproducibility bar this
repository commits to.

Receipt cursor and goal-clear status are maintained in `GOAL.md §Current
Blocker Packet`. `STATE.md` holds the current position ledger.

# sp-6b replay rig v0 — deterministic B3 episode replay + scoring (#282)

**Status:** Instrument only. No model judging, no McNemar. Measures the
measurement substrate for fp-33 B3. Frozen at this commit; deviations per
fp-30b protocol.

## Purpose

B3 (fp33-surpass-prereg-v1 §Leg B) requires replaying the frozen 20-episode
duty battery identically to both seats (ember core, Gemma E2B) inside the
NC-K harness and scoring per episode deterministically. The replay rig is the
instrument that does the replay and scoring. It does NOT:

- Run any model or judge any output with a model
- Compute McNemar's exact test or any paired statistic (that is the fp33
  prereg scorer's job, downstream of rig output)
- Touch the real filesystem outside per-episode tempdirs (unless `--write`
  is explicitly passed)

## Architecture

```
sp6-duty-battery.jsonl     ← frozen content half (episodes)
sp6-duty-battery-encodings.jsonl  ← frozen encoding half (event streams + fixtures)
         │
         ▼
  load_battery() + load_encodings() → join_battery_encodings()
         │
         ▼  (per episode, independent)
  materialize(episode, sandbox_dir)   ← fixtures written into fresh tempdir
  build_events(episode, sandbox_dir)  ← {root} substituted, Events constructed
  replay_episode(episode, core, ...)  ← events fed to core(), Actions collected
  score_episode(episode, actions, ...) ← deterministic pass/fail
         │
         ▼
  run_battery() → [{id, pass, reason, emitted, ...}, ...]
```

## Target normalization (pinned order)

| Priority | Condition | Normalized target |
|----------|-----------|-------------------|
| 1 | `action.args` has key `'target'` | `args['target']` verbatim |
| 2a | `action.args` has `'to'` AND `to == event.payload['from']` | `'sender'` |
| 2b | `action.args` has `'to'` AND `to == 'owner'` | `'owner'` |
| 2c | `action.args` has `'to'` (other value) | raw value of `args['to']` |
| 3 | `action.args` has `'path'` | path relative to sandbox root (forward slashes) |
| 4 | (none of the above) | `''` |

## Silence rule

An episode is a **silence episode** if `expected_verb ∈ {no-action,
heartbeat-only, dedup, clean}` AND `target_pattern == '^$'`.

A silence episode **PASSes** iff no action with an OUTWARD verb is emitted.

**OUTWARD verb set:**

```
reply, ack-begin, challenge, clarify, escalate, report, flag-missing,
repair-escalate, gate-pass, gate-fail, execute-due, gate-then-next,
clear-lock, monitor
```

Internal verbs (e.g. `write_gate_note`, `heartbeat_touch`) do NOT fail
silence — they are non-outward bookkeeping actions.

## Action episode rule

An episode is an **action episode** if it is not a silence episode.

An action episode **PASSes** iff at least one emitted action satisfies:
- `action.verb == expected_verb`, AND
- `re.search(target_pattern, normalized_target)` is truthy.

## Determinism guarantee

`verify_determinism()` runs the full battery twice in-process (each episode in
its own fresh tempdir) and asserts that the `(verb, normalized_target)` stream
and pass/fail verdict are byte-identical between runs. The `REPLAY_EPOCH`
constant (`2026-06-22T00:00:00Z`) ensures `mtime_offset_s` application is
independent of wall-clock time.

## Receipt shape

When invoked with `--run --write`, the rig writes:

```json
{
  "ticket": "SP6B-REPLAY-RIG",
  "ts": "20260622T......Z",
  "status": "complete",
  "metric": {
    "pass_count": <N>,
    "total": 20,
    "pass_pct": <float>
  },
  "episodes": [
    {
      "id": "M1",
      "expected_verb": "reply",
      "target_pattern": "^sender$",
      "pass": true,
      "reason": "PASS: matched ('reply', 'sender')",
      "emitted": [["reply", "sender"]]
    },
    ...
  ]
}
```

Bare invocation (no `--run`) exits 1 with a `STAGED:` line — evidence-
promotion gate: a receipt must be deliberately triggered, never accidentally
produced.

## Seat-swap usage

The rig is **core-agnostic**. The same instrument, same frozen battery, same
scoring logic — only the `core` callable changes:

| Seat | core argument |
|------|---------------|
| Baseline (structural validation) | `stub_core` (rule-based, no model) |
| Ember B3 run | ember core callable (model-backed) |
| E2B B3 run | E2B adapter callable |

Pass the core to `run_battery(core=my_core)` or `replay_episode(ep, my_core, ...)`.

## Files

| Path | Role |
|------|------|
| `scripts/nck/replay_rig.py` | Rig implementation |
| `scripts/nck/selftest_replay_rig.py` | Fail-closed selftest (rig mechanics only) |
| `docs/sp6-duty-battery.jsonl` | Frozen battery content half |
| `docs/sp6-duty-battery-encodings.jsonl` | Frozen battery encoding half |
| `docs/sp6-duty-battery-v0.md` | Battery contract |
| `docs/fp33-surpass-prereg-v1.md` | B3 scoring context (McNemar) |

## What the rig does NOT do

- **No model judging.** Verb classification and target matching are
  deterministic Python — no LLM in the scoring path.
- **No McNemar.** The rig outputs per-episode pass/fail vectors. The paired
  McNemar exact test (B3 bar: `p < 0.05`, ember strictly better) is computed
  downstream by the fp-33 prereg scorer over the paired ember/E2B result
  vectors.
- **No cross-episode state.** Each episode materializes an independent
  sandbox. R4's already-gated fixture is its own fixture, not R1's output.
- **No live tool execution.** The registry used during replay registers no-op
  recorders only — dispatch never touches the real filesystem outside the
  sandbox.

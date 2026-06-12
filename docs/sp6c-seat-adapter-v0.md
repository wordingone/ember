# sp-6c — seat-adapter contract: frozen prompt + output grammar + parser (#307)

The B3 instrument's seat-facing half. The rig (#290) replays the frozen
battery (#269) through `core(event, registry)`; this contract defines how a
TEXT MODEL becomes such a core, identically for both seats (ember core,
Gemma E2B), per the fp33 prereg B3 replay-identical rule. Module:
`scripts/nck/seat_adapter.py`; selftest `scripts/nck/selftest_seat_adapter.py`.

**Freeze semantics:** every prompt/grammar constant feeds `TEMPLATE_HASH`
(sha256), pinned in the selftest: `0a085406cff23321…b480f9`. Editing any
frozen constant fails the selftest until the pin is updated in the same
diff — that diff IS the registered deviation (fp-30b-class). After the
first B-run, template edits void that run. Every B-run receipt records
`template_hash`.

## Information contract (what a seat sees)

One prompt per event, three blocks, all deterministic and machine-invariant:

1. **World state** — sorted listing of the episode sandbox: relpath, size,
   `age_s` relative to REPLAY_EPOCH (2026-06-22T00:00:00Z), verbatim content
   (fixtures are `{root}`-templated on disk). Required because S1/S4/F1/F3
   are undecidable from the event payload alone (schedule content, policy
   bars, lock ages, claims live in fixtures).
2. **Event** — source, kind, pinned ts, payload as sorted-key JSON with the
   sandbox path reverse-substituted back to `{root}` (tempdir names vary per
   run; absolute paths in a prompt would break replay-identity).
3. **Norms + grammar** — identity preamble with the norm triad
   (receipts-only truth, fail-closed, cost discipline / silence-is-valid),
   then the output grammar with the 18-verb closed enum.

**Deliberate withholding:** the prompt gives every verb a WHAT-gloss but NO
per-family decision table. The grammar makes every action expressible for
both seats; knowing WHEN to act is the measured variable (founder-likeness),
not given away in the prompt. Bars come from `config/replay-policy.json` in
world state, not from prompt text.

## Output grammar (closed)

```
ACTION: <verb> | to=<recipient>     (mail-directed verbs)
ACTION: <verb> | path=<path>        (file-directed verbs)
```

- One action per conforming line; anything else (prose, reasoning,
  malformed lines, non-enum verbs) is IGNORED. No conforming line = silence.
- Unparseable output ⇒ zero actions ⇒ scores silence: fail-closed and
  deterministic — a seat that cannot speak the grammar fails action episodes
  and passes nothing by accident.
- `{root}` in arg values is substituted with the sandbox before scoring, so
  the rig's target normalization sees real paths.
- Anti-spray cap: at most 4 actions per event (battery episodes need ≤2);
  a spray strategy still fails all silence episodes (outward verbs).
- Silence verbs (no-action, heartbeat-only, dedup, clean) are expressed by
  emitting NO action line.

## Seat-core protocol

`make_seat_core(generate_fn)` returns `core(event, registry, sandbox_dir)`.
The rig dispatches the 3-arg form when the core declares a third positional
parameter (`_core_accepts_sandbox`); 2-param cores (stub_core) are
unchanged. `generate_fn: prompt → completion` is the model-binding half —
engineer lane, never loaded here. It MUST be deterministic (greedy decode).

**B-run receipt fields (per seat):** `seat` (ember|e2b), model identity
(ckpt sha / HF id + revision), decode params, `template_hash`,
adapter+rig commit sha. Seat symmetry = identical `template_hash` and
decode params across both seats in one B-run.

## Rig changes bound to this contract (same PR)

1. **Pinned mtimes:** `materialize()` now pins EVERY fixture mtime to
   REPLAY_EPOCH+offset (offset-0 fixtures previously kept wall-clock
   mtimes — `age_s` in prompts would have been nondeterministic).
2. **3-arg core protocol** in `replay_episode` (signature inspection,
   backward-compatible).
3. **Deictic guard** in `_normalize_target`: literal `to=sender` that does
   not match the event's actual sender normalizes to `literal-sender` — a
   seat cannot match `^sender$` without naming the real sender from the
   payload. (Pre-existing gaming hole, symmetric but bar-weakening; closed.)

## Selftest (fail-closed, no model)

(a) template-hash pin; (b) byte-identical prompts across two different
tempdirs (machine-invariance) + `age_s=7200` rendered for F1; (c) parser
well-formed multi-action + `{root}` substitution; (d) silence on
prose/malformed/non-enum; (e) cap; (f) end-to-end M3 PASS/FAIL
discrimination with scripted seats; (f2) S4 prompt carries world-state
fixture (3-arg protocol live); (g) end-to-end M4 silence PASS / spray FAIL;
(h) mtime pins; (i) deictic guard.

## Successor

sp-6b execution (#282) consumes this: trigger = ember checkpoint resident
(NC-K sampler as `generate_fn`) + E2B `generate_fn` (HF greedy) — both are
engineer model-binding halves; the contract half is closed by this commit.

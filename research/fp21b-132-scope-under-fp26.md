# fp-21b prong-A (#132) — trigger-scope under the frozen fp-26 (b) decision

Owner: Leo (#132 [math]). Status: **OPEN — trigger-gated**. Not closed, not
reduced. This note pins the exact world in which #132's re-execution fires,
and ties that scope to the frozen fp-26 decision sha so it cannot silently
drift from the freeze.

Artifact: `scripts/fp21b_scope_132.py` (`--selftest` / `--emit`).
Receipt: `receipts/fp21b-scope-132-20260611T124051Z.json`
(verdict `SCOPE-PINNED`, `fires_in_world: w1-mbpp`, `owned_core_b_refuses: true`).

## What #132 asks

fp-21b prong-A: *does the borrowed-world band predict downstream transfer?*
Its bars and band-legs are **Qwen / w1-mbpp** artifacts — the `fp21b_prereg`
`WORLD_PIN` (`model: Qwen/Qwen2.5-Coder-3B-Instruct`, `world: w1-mbpp`). The
question is intrinsically a **borrowed-world** question: it is about whether a
band measured on the borrowed core's sampling distribution carries to held-out
frontier tasks in that same world.

## Why the frozen fp-26 (b) decision retargets the firing world

fp-26 (`fp26-prereg-20260611T081213Z`, decision sha `5ef7cc20…`) froze round-3
shape **(b) = owned-core in-dist accumulation**: v0 pretrain (ember-v0) →
fp-22 verify-floor world → accumulation rounds where **eval distribution ==
train distribution by construction**. Two consequences, made precise by the
scope artifact's three demonstrated gate branches:

1. **Primary (b) round-3 sampling comes from ember-v0** — a different
   model+world than the band's `WORLD_PIN`. fp-21b's own world gate
   (`check_sampling_world`) returns **NOT-APPLICABLE-WORLD-CHANGED** on it
   (the selftest in `fp21b_prereg` already asserts `ember-v0-0.37b` →
   refusal). The transfer-**prediction** question does not apply at all: (b)'s
   world is in-dist by construction, so cross-task transfer is not the axis it
   turns on. The borrowed-world band bars **do not carry**.

2. **fp-21b prong-A fires ONLY on a fallback-(a) round-3 sampling receipt** —
   borrowed-core (Qwen / w1-mbpp), which exists only if the owned core kills
   the fp-22 verify floor and fp-26's kill rule demotes to fallback (a). On a
   genuine w1-mbpp sibling the gate returns **APPLICABLE** and the prong-A
   re-execution runs against round-3 bars.

A third branch — **no sibling receipt** — returns **PROTOCOL-FLAG** (refuse to
apply borrowed bars without the world stamp), which is the fail-closed default.

## Why this is scope-pinning, not scope reduction

The prong-A re-execution **still happens when its trigger lands**. Nothing is
deferred-to-later or carved out: the only thing pinned is *which world the
trigger is*. #132 stays OPEN precisely because it is genuinely
trigger-conditional — it is not resolved, so it does not close and mints no
successor (the re-execution itself is the deferred work, gated on fallback-(a)).

The pin is tamper-guarded: `fp21b_scope_132.py` fail-closes (`--emit` refuses,
`--selftest` asserts) if the fp-26 decision artifact sha drifts from `5ef7cc20…`.
The scope cannot drift from the freeze without breaking the gate.

## Cross-refs

- `research/fp26-round3-shape-decision.md` (sha `5ef7cc20…`) — the frozen
  decision this scope is tied to; `binds.fp21b_132` = "retargets to the owned
  core's FIRST sampling round".
- `scripts/fp21b_prereg.py` — `WORLD_PIN` + `check_sampling_world`; its selftest
  already proves the owned-core refusal.
- `scripts/fp26_prereg.py` — the freeze executor (`prereg_frozen:true`,
  G-prereg row of the v0 launch gate).

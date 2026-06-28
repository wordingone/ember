# fp-34 prereg v1 — owned-core band definition + transfer-prediction protocol (FROZEN 2026-06-12, Closes #264)

Status: FROZEN before any owned-core round-1 sampling receipt exists
(v0-r1s1 job 12c050e7 is mid-pretrain) — the definition cannot have been
fitted to the data it will judge. Post-freeze edits = registered deviation
(fp-30b protocol).

Lineage: fp-21b prong-A is DORMANT with its borrowed-world freeze untouched
(docs/fp21b-prong-a-disposition.md). This is the re-instantiated carrier of
the underlying question — does band membership predict downstream value —
on OWNED-core data, same bars, fresh seed.

## Band predicate (owned core, single-model form)

The borrowed-world band was relational (easy-for-1.5B / hard-for-3B). The
owned track has one core, so the predicate is the fp-7 pricing logic in
single-core form — verified-but-hard, the high-bits stratum:

    band_owned(t) := s_r1(t) > 0  AND  laplace_phat(s_r1(t), n_r1(t)) <= 0.5

where s_r1/n_r1 are task t's verified-success count and sample count from
the owned-core ROUND-1 sampling receipts. Derivation (declared, not fitted):
among solved tasks, per-episode information bits(phat) rises as phat falls;
s>0 keeps the verifier floor; 0.5 is the coin-rate boundary. The threshold
is part of the freeze.

**Band freeze rule (inherited verbatim from fp-15):** the band is computed
ONCE from round-1 receipts when they land (`fp34_band_owned.py freeze`,
emitting a band-manifest receipt with the input receipt shas) and never
recomputed from round-2 outcomes.

## Bars (inherited, frozen)

ratio bar 1.5 / permutation p < 0.05 / 10,000 shuffles / **seed 19** (fresh
by declaration — 16, 17, 18 are taken by fp-12, fp-15/21b, and the fp-33
seed set respectively).

## Protocol (mirrors fp-15 two-prong structure)

- **Prong A — yield prediction (fires: first owned-core ROUND-2 sampling
  receipt):** yield = NEW verified episodes per sampled k, split band vs
  nonband by the frozen round-1 band. PREDICTIVE iff
  yield_band/yield_nonband >= 1.5 with perm p < 0.05 (task-label shuffle,
  10k, seed 19); REFUTED-direction iff ratio <= 1/1.5; else INCONCLUSIVE.
  Machinery: `fp15_bandtransfer.split_yield` / `perm_pvalue` imported, seed
  overridden — the estimator is shared code, not a reimplementation.
- **Prong B — transfer (fires ONLY on prong-A PREDICTIVE):** matched-step
  band-only vs nonband-only training arm pair at matched episode count and
  compute; paired held-out transfer delta decides (yield alone cannot —
  sampling ease != transfer value). Three-test gate applies to any claimed
  gain.

## Executable

`scripts/fp34_band_owned.py` — `freeze` (round-1 receipts → band manifest),
`verdict` (round-2 receipt + manifest → prong-A receipt), `--selftest`
(pure-logic: predicate boundary cases, seed-19 determinism, shared-machinery
import). Receipts: `receipts/fp34-band-manifest-<ts>.json`,
`receipts/fp34-bandtransfer-<ts>.json`.

## Successor (minted with this freeze — fp class never empties)

fp-35: prediction → policy. If prong A lands PREDICTIVE, does band-weighted
k-allocation beat uniform allocation on F (verified episodes per GPU-hour)
at matched sampling budget — paired arms, same bars, fresh seed declared at
its freeze. Trigger: fp-34 prong-A PREDICTIVE receipt.

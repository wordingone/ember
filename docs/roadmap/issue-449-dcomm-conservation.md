# Issue #449 - d_comm and optimizer-transition conservation

Status: `SUPERSEDED_NOT_PLANNED`, conditional on accepted owner comments,
independent exact-head PASS, fresh green checks and merge. This document does
not claim a current experiment or result.

Source: https://github.com/wordingone/ember/issues/449

Canonical owner comments:

- EMBER-05/#1119: https://github.com/wordingone/ember/issues/1119#issuecomment-5225891465
- optimizer owner #707: https://github.com/wordingone/ember/issues/707#issuecomment-5225891509
- Ember Lab custody owner #898: https://github.com/wordingone/ember/issues/898#issuecomment-5225891571
- source bridge: https://github.com/wordingone/ember/issues/449#issuecomment-5225893060

## Historical evidence boundary

The production Muon convention was `scale=max(1,m/n)^0.5`; strict doubling
gave `r_gate=r_up=1`, `r_down=1/sqrt(2)`. The gate null was `sqrt(2)`, with
frozen c bands `[0.25,0.45]`, `abs(c)<0.05`, and attribution-only band (iii).
Every future run re-reads the exact source SHA.

The first rung-2 measurement reported RESET `d=0.156090`, `c=0.988060`, but
its string/name lookup missed numeric optimizer state, cached zero momentum and
made TRANSPLANT byte-identical. It is INVALID for the arm decision. The
corrected `grow-rung2-20260709-remeasure` chain proved:

- B1 full optimizer/RNG snapshot and double-SHA quiescence;
- B1m exact ordered eight-microstep hashes
  `f04b36707b9922828f28ed4bac6f24a222f93e39e91132b0d08bfc09f3a63aa7`,
  `7668263c3a2638da147a7aa1a878a04287b8c235eeef4eadc2d3392898ec72ee`,
  `14505ddc27b468a482fe44a750fb8fdf7178c6f6b79c7c9441a3d964644c2a44`,
  `de286529a302fbc6ec8fa1b33d55160c36f13ea6b684ab55080a267ab4d9de82`,
  `ae2a5395cc8710194cbd5cc0d58957458c060846d13e51947c5098fa5263089d`,
  `316c79c1d3a549cf6012134fd1e1b822896d230f3d1793b5d0344b3a41e21df1`,
  `6667c059ec7003f47b45be9bda90a318bc26ac93e6cfe6a9d29b140ca0b60b87`,
  and `77688fa1c454452d83a22098a5372bfad23adaca26680658b7949f40cc6bf651`,
  aggregate SHA
  `2e56e349ebbd680668902a2f6edeb32439528074fe656ec65543b2f3eb4f1f7e`,
  and true nonzero momentum;
- B2 eps 0.05/seed 0, operator SHA
  `5d9c16f49b2c4ad056cc174a692a92f18ab034d881699a8564f3da763f51a40f`
  and loaded-weight realization;
- B3 RESET `d=0.1560465`, `c=0.9880676` versus TRANSPLANT `d=0.9410028`,
  `c=0.6074390`, producing the historical RESET ruling. B3 ran on a fork before
  stabilization and production resumed only from the untouched B1 state.

Tracked evidence is exact: preflight blob
`9e2b28e93758ad75c081f3cef88db478495ca5a3` (3,560 bytes), B1
`984fa9dcf1735cd633bb847e49bd69cce6e77496` (3,228), B1m
`a2c88eefc13668a2ff34c78e383e766d7bd4c44a` (2,775), B2
`03f59006f1a6306ed13e8b052602f4736d3b070b` (1,930), B3
`ab0af41de0762a1251b292781330525cfd36bccc` (2,980), B3-gradpost
`b362ce0684975af321af44166d03896a62b3656c` (5,231), eps0 rider
`c391eef590a1a3763e23c20e1a5b8da43051994e` (5,195), and fp32 rider
`417c4bd98273212753d28508d22a4ac079df5b93` (5,228). Off-repo cache paths
are not tracked evidence and must be reopened by exact hashes before use.

## Surviving contract

Gate/up/down remain separate. Down uses the exact norm-coupled realized tangent
and q aggregate, the RMS `1/sqrt(2)` register with 5% kill, and spectral
plateau disclosure. Gate retains the failed strong eps0 row (`1.0028543`
against the 0.2% bar), passed monotonic 0/0.025/0.05 row, and the fp32 rider's
exact-anchor admissibility rule, residual `<=0.1%` plus improved-cosine PASS,
residual `>0.1%` KILL, and executed non-exact anchor (`0.0001153` delta),
`0.797%` residual/no-cosine-improvement public-KILL boundary.

Q2 remains an event-local `s*<G_post,U_T-U_R>` bridge with dimensional audit,
no pre-audit absolute band, fitted rather than assumed-20 NS5 coherence, a
`[0.7,1.3]` first-order NS5 band, N=200 rotation null, scale/orthogonal
decomposition and the exact three-way verdict grammar: `BRIDGE-ALIVE` iff the
orthogonal component clears the null threshold, `NULL-PRIMARY` iff it does not,
and `EFFECTIVE-LR-ARTIFACT` iff raw clears but orthogonal does not. It does not
predict eval W.

Rung-3 remains RESET/layer-0/step-0 on an exact pinned batch and
momentum-proven snapshot, scale convention, eps 0.05, strict 32768->65536 FF
doubling at d_model 1024. It requires per-arm steps through 40, momentum buffers
at 0/1/2/4/8/16/32/40, persistence at 200/1000, c3 `[0.976,0.994]` and all
kill/weak/dead/generic/eps0-fork branches plus kappa/collapsed-direction and
concentration fields. Its trend remains
`beta_miss=-log2((1-c3)/(1-c2))` with batch, eps-seed, eps-match and bf16/QAT
variance disclosed.

#1119 owns growth/decision/Q2/rung-3 science. #707 owns optimizer geometry,
tangents and RESET/TRANSPLANT equivalence. #898 owns sole current Ember Lab
dispatch/resource/receipt custody. Historical C-BASE runner/daemon/sub-3B paths
are retired as execution authority but remain searchable provenance.

## Falsifier / reopen

Reopen if any frozen constant, B-stage identity, invalid-first correction, arm,
per-class requirement, rider, custody gap, refusal, rollback or no-credit field
is removed; if historical evidence is promoted to current-3B evidence; or if a
parallel authority is introduced.

```text
completion_credit=false
scientific_execution_credit=false
acquisition_credit=false
result_credit=false
gpu_credit=false
training_credit=false
checkpoint_credit=false
capability_credit=false
milestone_credit=false
```

`NO_NEW_PARALLEL_AUTHORITY`.

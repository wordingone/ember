<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Issue 54 installed fireball capture

This directory is the content-addressed installed-binary evidence for issue #54.
`receipt.json` binds Ember source commit
`5782062d60602d040efe18edce07ffeadc726eb7`, the compiled binary SHA-256,
the capture producer SHA-256, the operator viewport, three captures at least two
seconds apart, and every frame/cell artifact hash. The receipt SHA-256 is
`08f04159ad515c1c70deb26e6e578927bccfc00104d43b2ce2fc611988dda2e3`.

The installed 190x85 ConPTY frames were captured at the operator's 1720x1440
left-snapped layout. All three have the same 5x5 bounds and the same 13 occupied
terminal cells. Their style projections are distinct, proving that the fixed
geometry remains live rather than being a frozen image.

## Historical-to-current architecture crosswalk

- Historical clause: diagnose and remove horizontal flame jitter, originally
  suspected to be per-frame string-width variance; preserve the separate
  operator art-quality obligation.
- Current owner: `tools/ember-cli/src/components/fireball.ts`, the production
  `ReplScreen`/`Homescreen` path, and the real compiled Ember CLI capture in this
  directory.
- Mechanism status: `SUPERSEDED`. Current source uses one fixed occupancy for
  every color-pulse frame. The historical per-frame translation and stale #44
  ownership pointer are not restored.
- Lossless mapping: the geometry/jitter clause is discharged here. The living
  tip/motion character and operator art-quality clause remains explicitly owned
  by current EMBER-03 parent #1117 and must not be inferred complete from this
  capture.
- Current primitives reused: the existing fireball raster, real Ink renderer,
  compiled entrypoint, Windows ConPTY, and xterm cell model. No alternate UI,
  renderer, launcher, daemon, receipt authority, or compatibility path was
  introduced.
- Conflict scan: this change does not touch `runtime/ember-lab`, serving,
  training, custody, checkpoint, corpus, scheduler, or model authority.

`NO_NEW_PARALLEL_AUTHORITY`

Claim boundary: installed Ember UI geometry and color-pulse evidence only. This
is not evidence of model availability, training, benchmark performance,
capability, or completion of EMBER-02/EMBER-03.

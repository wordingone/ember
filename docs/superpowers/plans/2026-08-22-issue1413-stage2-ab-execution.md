# Issue #1413 Stage-2 Matched A/B Execution Plan

**Goal:** Wire the merged census-bound FP8 and CUDA-graph primitives into the real governed vertical training loop, then produce a fail-closed matched BF16-versus-Stage-2 receipt.

**Immutable base:** `e2283dfd04aa7e61436764d6821d3afe6c64f13b` (public merge of PR #1878).

**Architecture:** The default governed route remains unchanged. An explicit Stage-2 flag opens only the checked-in census sidecar at raw SHA-256 `86e37ad5868da1ef77419d643c3ff31ee0a38b7e9f603b9c0807376958ef5d0c`, installs FP8 only at reviewed SwiGLU down sites, and routes forward/loss/backward through one graph executor. Decode, verifier, gradient clipping, optimizer update, FP8 refresh, cursor mutation, checkpoint publication, and telemetry stay outside capture. Each arm writes a no-overwrite run receipt; a separate comparator requires identical source/config/input/seed/order, zero fallbacks, finite matched losses, real FP8 dispatches, real graph replays, and accelerated throughput strictly above 1,000 tok/s.

---

### Task 1: RED tests for the production boundary

- Add tests proving the default path is unchanged.
- Add tests proving explicit activation uses the canonical census and refuses a foreign hash/path, resume ambiguity, and simultaneous census minting.
- Add a fake graph backend test proving capture/replay encloses only forward/loss/backward while clip, optimizer, refresh, cursor, checkpoint, and telemetry remain outside.
- Add receipt tests for no-overwrite output and matched-arm identity/loss/mechanism/throughput gates.

### Task 2: Real loop integration

- Add a census-bound Stage-2 step executor with static tensors per admitted signature.
- Warm up and capture each admitted signature without moving optimizer or cursor state; zero warmup/capture gradients before the counted replay.
- Replay the graph for the counted training step, then clip, update, and refresh outside capture.
- Aggregate exact FP8 kernel and CUDA-graph receipts with zero fallback.

### Task 3: Governed CLI and receipts

- Add explicit Stage-2 activation and no-overwrite run-receipt arguments to `governed-vertical` and its preflight.
- Bind every run receipt to runner/config/input identities, seed, record order, losses, token count, elapsed step time, checkpoint identity, and mechanism counters.
- Add a receipt-only comparison command that never launches a model or GPU.

### Task 4: Source gates and merge

- Run focused and affected tests through `scripts/owned_process.py` with finite timeouts and verified cleanup.
- Run authority conservation, repository guard, exact diff review, and independent exact-head review.
- Publish and merge only with green required checks; source review grants no performance or closure credit.

### Task 5: Matched execution and terminal review

- From the merged source, preflight and execute BF16 baseline first, then the census-bound arm, using identical seed/config/input/order and separate no-overwrite custody roots.
- Preserve both roots and all runner/run/comparison receipts.
- Require the comparison validator to PASS: real FP8 dispatches, real graph replays, zero fallbacks, matched finite loss, and Stage-2 throughput greater than 1,000 tok/s.
- Obtain independent terminal receipt review, publish exact evidence to #1413, and verify public issue closure before removing #1413 from the permanent backlog.

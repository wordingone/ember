# #1413 scratch-only readiness artifact

This is a CPU/file-only preparation artifact. It is not a launcher, trainer,
model authority, benchmark, or result receipt. The current Ember tree has no
pinned LLMQ dev source/build receipt or one-RTX-4090 3B benchmark receipt.

The checker therefore fails closed with `PRELAUNCH_REJECTED` until a safe
relative LLMQ source path is reopened and its raw bytes match `source_sha256`,
the build receipt repeats that source digest and binds a reopened binary path
to its raw `binary_sha256`, and both the adoption-design and
mechanism-attribution paths are reopened and rehashed against their digests;
it also rejects benchmark receipts whose status is not `PASS`, whose model is
not the exact `Qwen2.5-3B` reference run, whose hardware is not an exact
`RTX 4090`, or whose measured FP8/BF16 tok/s fields are missing, non-finite,
or non-positive. A missing receipt remains an explicit external remainder;
an incomplete or foreign receipt is a prelaunch refusal.

The governed source receipt is closed over a canonical `remote_ref` as well as
the commit, tree, source path, and source SHA. Admission reopens the configured
remote object/ref, proves that the declared commit is reachable from the
fetched governed ref, and hashes the raw `commit:path` blob; dirty working-tree
bytes, caller-authored local commits, and URL-rewrite redirects are refused
before readiness. A self-consistent local repository is not upstream custody.
With those static identities present but no benchmark receipt, it reports
`READY_FOR_EXTERNAL_EXECUTION` while the actual governed LLMQ build and 4090
benchmark remain an explicit external remainder. Any eventual execution must
route through Ember CLI -> Ember Lab.

Build and benchmark receipts are not authority merely because their caller
fields agree. The build receipt must reopen Ember Lab's existing
content-addressed `ember-lab-operational-receipt-v1` from an authenticated
Ember Lab named-pipe `export_assessment_evidence` response. The response is the
sole locator authority; `EMBER_STATE_ROOT` and packet-provided state roots are
ignored, and artifacts are reopened from the newly created export directory,
never from the mutable source checkout or caller's packet root. The opened
pipe's server PID must resolve to the independently selected repository build
at `runtime/ember-lab/target/release/ember-lab.exe` (or the debug build only
when release is absent), with exact normalized path and reopened-byte hash;
packet, response, and environment binary locators are ignored. Blocking pipe
I/O runs in a hidden owned worker with a ten-second end-to-end deadline. That
daemon export must bind the exact `domains/runtime/runtime/ember-lab/src/lib.rs` and daemon binary bytes, the
terminal job/identity/resource lease, exit zero, and daemon-sealed stdout and
stderr; the invented caller-side producer/status shape is refused. A benchmark
receipt must reuse that exact daemon export and job, equate its hardware UUID
to the daemon resource lease, and bind its raw FP8/BF16 samples to the sealed
stdout name and SHA before rederiving every rate. It must also reopen the
exported schedule identity, measured-at timestamp, total duration/tokens,
operational-receipt SHA, and prediction/measurement daemon identities. Missing, forged, foreign,
or self-authored producer, hardware, run, or sample evidence remains
`PRELAUNCH_REJECTED` and cannot create benchmark, adoption, capability, or
result credit. No new launcher or receipt authority is introduced here.

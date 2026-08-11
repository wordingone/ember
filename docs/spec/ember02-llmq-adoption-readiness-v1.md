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
fields agree. The build receipt must reopen a non-test-only
`ember-lab-operational-receipt-v1` for the same job and source-manifest/output
digests, bind the exact `runtime/ember-lab/src/lib.rs` producer bytes and the
producer binary bytes, and require daemon identity plus exit-zero terminal
state. A benchmark receipt must reuse that exact operational receipt and job,
bind the output binary, hardware UUID, command/config, and raw multi-step log
bytes, then rederive every FP8/BF16 rate from the raw rows. Missing, forged,
foreign, or self-authored producer receipts remain `PRELAUNCH_REJECTED` and
cannot create benchmark, adoption, capability, or result credit.

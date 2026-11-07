# Memory terminal budget R1

This is the R1-only repair of Kai's review e63a39969db7e243b776d0cd6a4d3812a4130abb8b8788ee7fa044dcac2b5a04, authorized by Leo75391. The predecessor memory implementation, original failures, 12 baseline artifact comparisons and controlled scale receipt2e702828 remain frozen. The source algorithm and the three artifact schemas/order/escaping/LF are unchanged; R1 changes terminal budget verification and the outer command only.

The command checks that preflight bytes plus an8192-byte terminal reservation fit inside the same134217728-byte whole-root ceiling before either write. It creates the pending/unaccepted JSON reservation at the final terminal path before launching a child. The existing source and refusal root scans count it. The source verifies its bound path,8192-byte length and hash before input work and before same-volume promotion. The parent replaces that document in place, padded to8192 bytes, only after checking actual encoded length. It verifies final hash/length readback and unchanged root occupancy before reporting persistence. An oversized terminal record becomes a bounded truthful failure125 retaining actual primary child/outer result, cleanup fields and reason prefix/full hash. Pending evidence remains unaccepted on a prelaunch or write failure. There is no cap raise, alternate destination, deletion or automatic retry.

## Pins and executed boundary

- source43f93066866ad44d9e2ec8fe06888d6d914321a3a18aa969affb5aaa5670a390
- unchanged runnera97416abebbaa13af387a18d418984182d829bd2efc8253be52ada705827bf52
- binding8cd5c9311d7518e74e3b534da4e7aa18e88a4cf62b958fa1e8d6be2906ebbda6
- command4a8629dc5928c110bffbdc2b4b0b02e897a5342832c29712a8eec078390dc702

One boundary invocation ran after the actual owner release: fixture child46784 at2026-10-09T18:21:06.8756116Z to18:21:08.7328094Z, exit0, cleanup verified, active job0, actual512MiB process/job limits. Outer47592 ended18:21:08.8994251Z with the same clean outcome. Receipt64932efc has22 passing assertions. The predecessor's actual terminal write overran a controlled full131072-byte root as expected. The new functions and changed source verifier/writer exercised exact-cap success/refusal,1-byte overcapacity rejection, checked preflight/reserve creation, pending/tampered/missing/truncated states, retained staging, oversized-record failure and sharing-write failure. Fixed physical terminal length and final hash/readback/root occupancy were verified.

This executed the actual pinned command functions extracted from its AST and compiled changed source methods. It did not execute the full production launcher or real catalog pipeline. Tiny terminal records label their statuses as fixture simulations. No production payload, A/B runtime reads, Python, GPU or scale/equality replay occurred. Private observations99,848,192 and118,452,224 bytes; held native phase peaks118,452,224, not separately queried post-exit peaks. Fixture writes/occupancy were below8MiB.

## Release and remaining evidence

The prepared fresh C root contains only four pinned files114574 bytes and has not run. Inputs,512MiB caps,900 seconds,two metadata passes,150GiB reserve,one compute thread,BelowNormal and marker-absence policy remain unchanged. The old controlled scale coverage limits remain; this boundary result establishes no production memory fit, accepted real count, admission, trained model, merge or parent issue completion.

Kai rechecks only R1 code/pins; an actual PASS under Leo75391 permits at most one production attempt with fresh owner/resource/marker/input/host gates. Git publication remains one additional carrier commit on draft PR2361; current metadata policy is checked by actual CI repo-policy-gate per Leo75383. Original packet statuses stating commit-unheld are retained as event-time evidence.

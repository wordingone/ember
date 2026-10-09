# Selected projection memory successor

This is the one bounded memory delta authorized by Leo75005/75037 on draft [PR #2361](https://github.com/wordingone/ember/pull/2361). The predecessor commit is 5509abfcbfde07a7800574c236118767ce42b19b. Its reviewed source90fea10d and actual production refusal8268ebb6 remain unchanged.

## Change

The existing hash traversal, all-row membership duplicate/totality checks, every leakage intersection, two metadata passes, pass digests and per-kind counts remain. Membership rows are serialized into an unaccepted staging directory before releasing the phase-one collection references and delegates. Frozen final validation counts remain separate from live index cardinalities.

The pass-two object and selected receipt-link dictionaries are pre-sized from the selected digest count. The dictionary for every valid receipt-row hash is pre-sized from the completed pass-one receipt kind counts with an integer/capacity guard.

Accepted artifacts are written with a 64 KiB serializer/FileStream buffer; each write rejects a buffer above 1 MiB and checks byte counts, wall, private-memory samples and the C reserve. Each file has a streaming hash and length recheck. The staging directory becomes run only through a same-volume Directory.Move after the unchanged final predicates, pass hashes and kind counts, output hashes/counters and final resource/marker checks. Refusal preserves staging; no cleanup or automatic retry is performed.

A fresh C production root holds four frozen source/runner/binding/command pins plus its production artifacts, with a 128 MiB root ceiling. The prepared production command has not run. The 512 MiB private/process/job caps, source byte limits, two metadata passes, 900-second wall, one compute thread, BelowNormal priority, hidden creation and original input pins remain.

Phase measurements retain the actual runtime version, effective GC configuration (including hard limit), last-GC available/heap/committed/fragmented figures, and native JobObject peaks. A GC observation describes the last collection; it is not an instantaneous live-heap measurement. No GC setting or forced collection was added.

## Executed evidence

- The first suite exited1 before any projection child was launched: the fixture helper used a doubled event-name separator. Receipt f9b1e844 is retained as suite-refusal-v1.json.
- Leo75231 explicitly released exactly one corrected replay. Only the separator and separately named fixture/output references changed; product source and runner were unchanged.
- Replay ran 2026-10-09T17:24:37.5211851Z through 17:25:42.7073825Z; exit0, cleanup verified, active job processes0. The whole suite took about65 seconds, within900.
- Twelve true-baseline comparisons matched all three artifact hashes, in both root orders with0/8192 extra nonselected memberships. Existing global duplicate, no-sample, private observer/query-failure, cap-trigger snapshot and prediction-schema negative fixtures passed.
- The scale case serialized130578 selected Members,293852 global membership IDs and130103 selected hashes, including475 repeated selected hashes. It used4096 distinct receipt rows and one receipt link per selected object digest. Final validation counts retain162665 heldout and608 adjudicated hash indexes; released phase-one live indexes were zero.
- Scale projection PID46164 ran 17:25:18.8723481Z through 17:25:42.4281071Z; exit0 and clean teardown. Sampled PrivateUsage peak424632320 bytes (about405 MiB). Maximum recorded phase JobObject peaks: process425369600 and job426741760 bytes, both below512 MiB. These are the held phase counter measurements, not a separately queried post-exit peak.
- Effective runtime was pwsh7.6.5.500, .NET10.0.11, X64; effective GCHeapHardLimit and TotalAvailableMemory were402653184 bytes (384 MiB). This is observed runtime evidence, not a new imposed limit.
- Scale export147051035 bytes. Total scale occupancy/cumulative writes including its validation receipt229192846 bytes (about219 MiB), below256 MiB. Staging promotion did not duplicate payload files. No A/B runtime reads, Python, production payload copy or production invocation occurred.

## Coverage limits

IDs are24 Unicode characters (24-25 UTF8 bytes), with quote, backslash, LF and e-acute at four positions. Dataset IDs are34 characters, hashes/tokenizer64 ASCII characters, windows0/10. The fixture does not cover longer IDs through the4096-byte metadata scalar limit, extensive escaping/Unicode, larger receipt cardinalities, duplicate receipt-row hashes, many receipts per object, or other field/receipt distributions. Production memory fit remains unproved. Small baseline fixtures independently cover all four nonzero leakage intersections.

The PowerShell refusal formatter retains its existing whole-document JSON formatting; the accepted source artifact writer is streamed. The held scale refusal/cap fixtures do not establish a maximum size for every possible failure diagnostic document.

## Reproduction and release

The validation scripts preserve their existing C fixture layout: baseline-source-leo74221.cs, baseline-runner-leo74221.ps1, prior-validate-privateusage.ps1, validate-cap-snapshot.ps1 and validate-refusal-peak.ps1 remain at the package's parent namespace. The v2 scripts use separately named C outputs and refuse prior state. Every actual projection child is gated, hidden and attached to its own512 MiB process/job memory JobObject; the scaffold has a kill-on-close job without imposing a combined parent-plus-child memory cap.

The controller and production binding/command are frozen snapshots of the authorized C paths. An executed command or saved profile supplies no permission for another run. Future execution requires the applicable owner allocation and fresh pins/resource checks.

All35 carried code/receipt inputs are byte-pinned in memory-delta-byte-manifest-v1.json, including expected raw Git blob OIDs. The actual Git index, one additional commit and remote head are still unheld while the GPU marker prohibits the Python process guard. The parent .gitattributes preserves raw bytes. Kai's one delta recheck and Leo's explicit at-most-one production release remain required. Synthetic completion proves no admission, trained model, parent issue completion, merge or linked-issue closure.

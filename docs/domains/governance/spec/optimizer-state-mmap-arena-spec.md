# Optimizer-state memory-mapped arena — design spec (#898)

Status: **design only, no implementation**. This is Cure A from the #898
2026-08-21 amendment, specified here so its real cost can be weighed against
the host setup contract (`docs/host-setup-contract.md`) before either is
built out further. Nothing in this document is wired into any code path.

## Problem restated

`FullStateAdamWCPUOffload` (`src/ember/infrastructure/tools/ember-restart-3b/a1_optimizer.py`)
allocates three fp32 CPU tensors per parameter — `master_copy`, `exp_avg`,
`exp_avg_sq` — as ordinary anonymous host memory (`torch.zeros_like(...,
device="cpu")` / `.clone()`). At 3.84B active parameters that is
3 × 4 bytes × 3.84e9 ≈ 42.9 GiB of anonymous, private, commit-charged memory.
Anonymous private memory is always commit-charged against the Windows
commit limit whether it is resident in RAM or paged out — that charge is
what the host-commit preflight (`checkpoint_artifacts.py`) refuses against,
and what forced the 32→64 GiB pagefile increase (#898 2026-08-21 amendment).

The proposed cure: back those three tensors with memory-mapped files on an
ember-custody disk (via `torch.UntypedStorage.from_file(..., shared=True)`,
with each state tensor a view over its own arena file) instead of anonymous
memory. A file-backed mapping's pages are NOT commit-charged the same way —
the backing store is the file itself, not the pagefile — so the host commit
demand for this mechanism would drop from ~57 GiB to working-set scale (the
largest single tensor touched at once, ≈0.26 GiB per Cure A's own note in
the amendment, plus whatever the OS chooses to keep cached).

## Proposed shape

- One arena file per state tensor kind, per owner shard, under an
  ember-custody root on the B: write-root (consistent with
  `drive-usage-boundaries.md`'s "ember run custody: B: ONLY" ruling) —
  e.g. `<run-root>/optimizer-arena/{shared,vision,...}/{master,exp_avg,exp_avg_sq}.arena`.
- Arena files are pre-sized and preflighted by ember machinery (a
  `host_setup_contract`-style declared-size check against the arena's target
  DISK, not host commit — see the disk-budget interplay below), and their
  identity (path, byte size, sha256 of the zero-initialized or resumed
  content) is receipted the same way checkpoint shards are today.
- `FullStateAdamWCPUOffload.initialize_state` would open
  `torch.UntypedStorage.from_file(path, shared=True, size=nbytes)` for each
  of the three tensors per parameter group (or a single arena file segmented
  by parameter offset, to avoid per-parameter file-handle sprawl — the exact
  layout, one-file-per-tensor-kind vs. one-file-per-parameter, is an open
  question this spec flags but does not resolve) and construct each state
  tensor as a view over that mapped storage instead of a freestanding
  `torch.zeros_like` allocation.
- `step()`'s arithmetic (`mul_`, `add_`, `addcmul_`, `addcdiv_`) is unchanged
  — it already operates in place on `master_copy`, `exp_avg`, and
  `exp_avg_sq`, which is exactly what a memory-mapped tensor view supports.
  The only change is where those tensors' storage physically lives.
- Step math is per-parameter already (the loop iterates
  `group["params"]`), so no single in-flight allocation grows — the mmap
  working set at any instant is bounded by whatever pages the OS chooses to
  keep resident, not by the full 42.9 GiB, matching the amendment's ≈0.26 GiB
  largest-tensor note.

## Honest I/O-cost analysis

This is the section the amendment explicitly requires before this cure is
adopted over the host setup contract. The arena does not eliminate work; it
relocates where the cost is paid — from a fixed, one-time pagefile grant to
a recurring, per-step disk-write obligation.

### What gets dirtied per step

Every registered parameter's full state is modified on every `step()` call,
not a subset:

| Tensor | Bytes (3.84B params, fp32) | Operation | In-place? |
|---|---|---|---|
| `master_copy` | 14.30 GiB | `mul_` (weight decay), `addcdiv_` (update) | yes — dirtied |
| `exp_avg` | 14.30 GiB | `mul_`, `add_` (momentum) | yes — dirtied |
| `exp_avg_sq` | 14.30 GiB | `mul_`, `addcmul_` (second moment) | yes — dirtied |
| `denominator` (transient) | 14.30 GiB | `exp_avg_sq.sqrt()` — new tensor, `div_`, `add_` | new alloc, not part of the arena |

**All three persistent state tensors are 100% dirtied on every step** — this
is not a sparse-update optimizer. There is no subset of "hot" pages that
stays resident while the rest stays clean; the entire 42.9 GiB changes every
time. This matters because it removes the usual mitigation for mmap
write-back cost (only flushing pages that actually changed) — here,
"changed" is the whole arena, always.

### Write-amplification bounds

A memory-mapped file's dirty pages must eventually be written back to the
backing file — by the OS's periodic modified-page writer, by memory pressure
forcing eviction, or by an explicit flush (`msync` / `FlushViewOfFile`).
Because 100% of the arena is dirtied every step, the only lever that reduces
total bytes written is **coalescing**: if multiple steps complete faster than
the OS's flush interval, only the final state at flush time needs to be
written, not every intermediate step's state.

- **Worst case (memory-pressured host, this exact scenario):** the
  reference host is memory-constrained by construction — that is the whole
  reason this cure exists. Under active memory pressure the OS evicts and
  flushes dirty pages aggressively, close to every step. At 42.9 GiB/step,
  a 100-step run writes **≈4.29 TiB** to the custody disk.
- **Best case (idle host, generous flush interval, steps faster than the
  flush interval):** if the working set fits comfortably in free RAM and
  several steps land inside one flush window, only the flush-window count
  (not the step count) determines writes. At, say, a 5-second flush interval
  and sub-second steps, this could plausibly reduce total writes by an order
  of magnitude — but this bound is **not something ember controls or can
  rely on**: it depends on Windows' lazy-writer scheduling, which is
  unversioned OS behavior, not a contract. Any capacity plan built on this
  spec MUST use the worst-case bound, not the best case, exactly as
  `real-path-closure.md` requires (fixture-only or best-case-only proof is
  not closure).
- **Conclusion: budget for the worst case.** Any production use of this
  arena must assume close to full per-step writeback (42.9 GiB × step count)
  until a real measured run on the reference host under real memory pressure
  says otherwise. That measurement is itself named debt this spec creates,
  not a result claimed here.

### SSD wear

4.29 TiB of writes for one 100-step run is a large fraction of many consumer
NVMe drives' total lifetime write endurance (TBW) rating — commodity 1-2 TB
consumer NVMe drives are commonly rated in the 300-1200 TBW range. A single
100-step run at the worst-case bound could consume roughly 0.4-1.4% of a
drive's entire rated lifetime endurance in one run. A longer training run
(thousands of steps) at this rate is not viable on consumer NVMe without
either (a) a drive with substantially higher endurance, (b) a redesign that
avoids full-state dirtying every step, or (c) confirmation that the
best-case coalescing bound holds in practice and is far below the worst
case. This is a real, named cost — not a rounding error.

### Throughput tradeoff

Dirty-page writeback competes with training for the same disk. If the
custody disk's sustained write bandwidth is, say, 3-7 GB/s (typical
consumer NVMe sequential write), a worst-case 42.9 GiB per-step flush would
take roughly 6-14 seconds of pure I/O time if it had to complete
synchronously — comparable to or larger than a training step's own compute
time at this parameter count. In practice writeback is asynchronous and
does not block the next step directly, but if writeback falls behind compute,
dirty pages accumulate, the OS's modified list grows, and eventually either
(a) new page-cache allocations stall waiting for eviction, or (b) the
`ProtectiveOwnedStop` machinery (per #898's governor law) could see this as
unattributed pressure and trip a survival-floor freeze. The threshold at
which this becomes a real stall is undetermined without a measured run —
also named debt.

### Checkpoint interplay

The optimizer state is already file-backed once a checkpoint is published
(`checkpoint_artifacts.py` writes `optimizer-state-{owner}.pt` shards). The
arena proposal makes the *live, in-training* state file-backed too, which
raises two interplay questions this spec flags rather than resolves:

1. **Are the arena files and the checkpoint shards the same bytes?** If the
   arena's on-disk layout matched the checkpoint schema exactly, a
   checkpoint publication could become a rename/hardlink of the live arena
   file instead of a full re-serialization pass — a real efficiency gain.
   But the current checkpoint format (`torch.save` payloads, owner-sharded
   `.pt` files with metadata dicts, not raw tensor arenas) does not match a
   raw mmap arena's layout, so this gain is NOT free — it requires either
   changing the checkpoint schema (a versioned, reviewed change of its own)
   or accepting that arena writeback and checkpoint publication remain two
   independent write paths to two independent sets of bytes, each dirtying
   the disk on its own schedule.
2. **Resume identity.** `load_checkpoint_artifacts` currently loads
   optimizer state into ordinary CPU tensors via `torch.load`. Resuming into
   an arena-backed tensor instead means the load path must re-open (or
   re-create and populate) the arena file rather than deserializing into
   fresh anonymous memory — an additional identity/lifecycle surface
   (stale arena file from a prior aborted run vs. a freshly sized one) that
   needs its own preflight, analogous to the checkpoint identity binding
   this module already enforces (`CheckpointIdentityMismatch`).

### Write-budget accounting interplay

`disk_budget_runner.py` enforces a declared per-drive write budget
(`write_budget_statistic: NAMED_FILE_ROOT_MAX_GROWTH_BYTES`) against
explicit, tracked file writes. OS-driven mmap dirty-page writeback is
**not** an explicit write call ember makes — it is the kernel's own
lazy-writer flushing pages behind the process's back. This is a real gap:
at the worst-case bound (≈42.9 GiB per step), an in-training arena could
grow the custody disk's write total by orders of magnitude beyond what any
declared-write-budget accounting currently sees, silently, because no
tracked write function is ever called. Any implementation of this arena
MUST either (a) size and declare a write budget for arena writeback
explicitly and conservatively (worst-case bound, not best-case), submitted
to the same budget-refusal machinery as checkpoint writes, or (b) instrument
the arena's flush behavior (e.g. periodic explicit `msync`/`FlushViewOfFile`
calls at a bounded cadence, so writes are attributable and tracked instead
of left to the OS) so the accounting gap does not exist. Shipping the arena
without closing this gap would defeat the entire write-budget contract for
however many bytes the arena's own writeback contributes.

## Conditions under which the arena would be better than a provisioned pagefile

**Operator ruling: the mmap arena and the pagefile are the same mechanic.**
Both are disk acting as ledger backing for state that already fits in RAM —
a fixed pagefile lets Windows page anonymous state out to disk under
commit pressure; this arena would have ember do the equivalent paging
itself, in userspace, via explicit file-backed tensors. Neither one shrinks
the true amount of state that must round-trip through disk when RAM alone
cannot hold it; the arena only relocates who is doing the paging and how
visible the mechanism is. That equivalence, combined with the honest cost
analysis above (100% of the state dirtied every step, worst-case ~4.29 TiB
per 100 steps, an unclosed write-budget-accounting gap, and an unresolved
checkpoint-format mismatch), means the arena is **not the endorsed
direction**. It would add a second, less-tested paging mechanism alongside
the OS's own, tested one, without changing the fundamental resource
trade-off.

Rejecting the arena and formalizing a pagefile floor as Ember's durable
answer are independent claims — declining one does not establish the other
(operator scoping ruling, 2026-08-21, `docs/host-setup-contract.md`). What
this comparison does establish: if disk-as-ledger backing is needed at all
for state that already fits in RAM, the OS's own paging mechanism is the
better place for it than a second, less-tested userspace one, since it
carries no per-step disk-write or SSD-wear cost of its own beyond what the
OS already does. Whether a pagefile floor should be relied on repeatedly, or
only ever as the kind of one-time, operator-reviewed exception that
recovered the E8 dense A1 launch, is the separate question the operator
ruling answers, not this comparison. The conditions below are recorded for
completeness — they
identify where the SAME underlying disk-as-ledger trade-off might need to
move from OS-managed paging to ember-managed paging — but none of them
currently overrides the ruling above:

1. **The required footprint no longer fits a reasonable fixed pagefile.**
   If a future scale-up's optimizer state exceeds what can be covered by a
   pagefile sized within the disk space also needed for corpus, checkpoints,
   and other custody bytes, growing the pagefile stops being viable — but
   this is evidence to redesign the workload's footprint (fewer bytes of
   state, e.g. reduced-precision moments) before reaching for a second
   paging mechanism that carries the same disk cost with less OS support.
2. **Commit headroom must be preserved for other concurrent host
   consumers.** A mechanism that avoids consuming shared commit capacity
   leaves more of it for other lanes — but the ledger-backing equivalence
   above means this would only be a real gain if the arena's own writeback
   is materially cheaper than OS paging, which section "Honest I/O-cost
   analysis" does not show.
3. **The checkpoint-interplay efficiency gain is realized.** If the
   checkpoint schema changed so the arena file IS the checkpoint, the
   arena's disk-write cost would stop being pure overhead — but this
   requires a separate, reviewed checkpoint-schema change this spec does
   not propose.
4. **A measured run refutes the worst-case bound.** Even if realized, this
   narrows the arena's cost gap without changing the underlying
   same-mechanic equivalence with the pagefile.

**Recommendation: keep the host setup contract as the sole cure for this
resource dimension.** This arena spec is retained as a documented,
non-endorsed design record — evidence that the alternative was considered
and why it was not adopted — not as a queued follow-up.

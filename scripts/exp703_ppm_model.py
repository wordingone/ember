#!/usr/bin/env python3
"""
#703 PPM apparatus, stage 1: exact byte-level PPM-D model.

Frozen conventions this module implements (issue #703 coordinator comment
4942030643, section 9 "PPM freezes" + section 5 event-space definitions):

  - Order cap 8 bytes (parametrized here as `order_cap`, default 8).
  - Escape method PPM-D (Howard 1993): for a context node with total count T
    and k distinct non-excluded symbol types observed, P(symbol with count c)
    = (2c - 1) / (2T); P(escape) = k / (2T). These sum to 1 by construction.
  - Full exclusions ON: once a symbol has been assigned probability mass at a
    higher (longer-context) order, it is removed from consideration -- both
    from the count total and the type count -- at every shorter order in the
    same escape chain.
  - Update exclusion ON: training a symbol increments its count at the
    longest available context and continues to successively shorter contexts
    ONLY until it reaches a context where the symbol already had a non-zero
    count before this update (that context's count is still incremented; no
    shorter context is touched after that). This is the standard PPM
    "exclusion updating" rule (Moffat 1990) applied uniformly across orders.
  - EXACT trie: contexts are stored by exact byte tuple in a dict-of-dicts
    trie (`self.nodes[order][context_tuple]`) -- no hashing/collision-prone
    structure is used as the source of truth.
  - Alphabet size 257 = 256 bytes + one reserved EOT symbol (byte value 256,
    represented here as `alphabet_size - 1` by default). EOT is never
    token-internal; it terminates the current document and resets context to
    the empty tuple (order -1 floor territory) for the next document.
  - Order -1 floor = uniform distribution over the full alphabet (257 for the
    real model; `alphabet_size` for toy instantiations used by the lattice
    correctness proofs in exp703_lattices.py / exp703_marginalization.py).
  - State budget cap: THREE-TIER refusal (raises PpmStateCapExceeded).
    `approx_state_bytes()` is a CHEAP, NON-AUTHORITATIVE heuristic (fixed
    per-node + per-count-entry overhead) checked on every new node/entry
    creation event for a fast, always-on first line of defense -- but a
    measured counterexample (order_cap=8, alphabet_size=257, 4000 bytes
    from `random.Random(42)`, state_cap_bytes=8,000,000) shows it can
    under-count true resident memory by ~3.16x (approx=4,496,152 vs
    measured=14,194,992), i.e. it can report "under cap" while the process
    is already well over it -- a fail-open on the decisive statistic.

    Two AUTHORITATIVE tiers cover the periodic check, invoked by
    `_check_cap_periodic()` at the TRAINING-CALL boundary (once per
    `train_symbol` call, unconditionally -- NOT once per new-node/entry
    creation event; a prior version tied the periodic counter to the
    latter, so a STABLE-CONTEXT stream that never creates a new node/entry
    after its first call never reincremented it and the documented "every
    LIVE_CHECK_INTERVAL training calls" fallback was unreachable --
    receipted: 500 training calls of a fixed repeated symbol, counter
    stuck at 2, LIVE_CHECK_INTERVAL=100 never reached; fixed here, see
    PPM703_STABLE_CONTEXT_PERIODIC_CHECK_PASS), throttled by
    `LIVE_CHECK_TRIGGER_FRACTION` of the cap (derived with a >2x safety
    margin below the measured 3.16x worst-case undercount ratio) or every
    `LIVE_CHECK_INTERVAL` training calls, whichever comes first:

      1. `isolated_ppm_state_bytes()` -- a tracemalloc snapshot filtered to
         allocations whose traceback originates in THIS FILE, diffed
         against a per-instance baseline captured at the start of
         `__init__`. This is the AUTHORITATIVE figure for `state_cap_bytes`
         PPM-state enforcement, and the one a publishable PPM-memory claim
         must cite.
      2. `process_live_bytes_governor()` -- `tracemalloc.get_traced_memory()`,
         the current traced allocation total for the ENTIRE PYTHON PROCESS.
         A deliberately coarser, conservative SECOND safety rail, never
         itself a PPM-state claim (issue #703 PR #759 external re-audit,
         PR comment 4943548456: the prior name `live_state_bytes()` claimed
         to measure "PPM LIVE memory" while actually returning this
         process-wide total -- receipted: an unrelated 2MB bytearray
         allocated before model construction inflated the OLD reading by
         >99% of its value and triggered a false-positive refusal at
         symbol 52 while true PPM state was 5,840 bytes; renamed and split
         here, see PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS).

    `state_cap_bytes` is enforced against BOTH tiers independently; the
    raised message names which tripped. The heuristic alone is never
    sufficient grounds to proceed near the cap, and the process-wide
    reading alone is never sufficient grounds to conclude PPM state itself
    is over cap.

This module is CPU-only, pure Python, no external dependencies.
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from dataclasses import dataclass, field


class PpmStateCapExceeded(RuntimeError):
    """Raised when the model's estimated resident state exceeds state_cap_bytes."""


@dataclass
class _Node:
    counts: dict = field(default_factory=dict)  # symbol -> count
    total: int = 0


class PpmModel:
    """Exact-trie byte-level PPM-D model with full exclusions + update exclusion.

    Parametrized over alphabet_size and order_cap so the SAME class backs both
    the real order-8/alphabet-257 production model and the tiny toy
    alphabets used by the P1/P2 correctness-proof lattices -- the
    marginalization engine that consumes `next_byte_probs` is therefore
    exercising the actual production code path, not a stand-in.
    """

    NODE_OVERHEAD_BYTES = 96     # disclosed heuristic: dict + node object overhead
    ENTRY_OVERHEAD_BYTES = 56    # disclosed heuristic: one (symbol -> count) dict entry

    # Measured worst-case undercount ratio of the heuristic vs tracemalloc-
    # live memory (order_cap=8, alphabet_size=257, 4000 bytes from
    # random.Random(42), state_cap_bytes=8,000,000): approx=4,496,152 vs
    # live=14,194,992 -> ratio 3.1571. LIVE_CHECK_TRIGGER_FRACTION is set to
    # roughly HALF of 1/ratio (1/3.1571 = 0.3167 -> ~0.15), i.e. a >2x safety
    # margin below the measured worst case, so the authoritative tracemalloc
    # check engages well before a heuristic-only pass near the cap could be
    # masking a real breach -- a measured margin, not a guessed constant.
    MEASURED_WORST_CASE_UNDERCOUNT_RATIO = 3.1571
    LIVE_CHECK_TRIGGER_FRACTION = 0.15
    LIVE_CHECK_INTERVAL = 100    # also force a live check every N training calls

    def __init__(self, alphabet_size: int = 257, order_cap: int = 8,
                 state_cap_bytes: int = 8 * 1024 ** 3, eot_symbol: int | None = None):
        if alphabet_size < 2:
            raise ValueError("alphabet_size must be >= 2 (at least one byte symbol + EOT)")
        if order_cap < 0:
            raise ValueError("order_cap must be >= 0")
        self.alphabet_size = alphabet_size
        self.order_cap = order_cap
        self.state_cap_bytes = state_cap_bytes
        self.eot_symbol = alphabet_size - 1 if eot_symbol is None else eot_symbol
        if not (0 <= self.eot_symbol < alphabet_size):
            raise ValueError("eot_symbol out of alphabet range")
        # Ensure tracemalloc is tracing so the AUTHORITATIVE tiers
        # (isolated_ppm_state_bytes / process_live_bytes_governor) have
        # real data; track whether THIS instance started it so a caller
        # who already had tracemalloc running for their own purposes is
        # never stopped out from under them. This MUST happen before the
        # baseline snapshot below, and the baseline MUST be captured
        # before any other allocation this constructor makes (self.nodes
        # included), so isolated_ppm_state_bytes() attributes this
        # instance's OWN top-level dicts to itself, not to "baseline".
        self._owns_tracemalloc = not tracemalloc.is_tracing()
        if self._owns_tracemalloc:
            tracemalloc.start()
        self._tracemalloc_baseline_module_bytes = self._measure_module_bytes_now()
        # nodes[order][context_tuple] -> _Node ; order 0 == empty-context (unigram) node.
        self.nodes: list[dict] = [dict() for _ in range(order_cap + 1)]
        self._approx_bytes = 0
        self.symbols_trained = 0
        self.documents_trained = 0
        self._live_check_counter = 0
        # Edge-trigger latch for the trigger-fraction early-warning in
        # _check_cap_periodic -- see that method's docstring for why this
        # must fire ONCE on crossing, not on every call while above
        # threshold (a level-triggered read here reintroduced, via a
        # different path, exactly the "authoritative check fires on every
        # call" cost this repair round's other half was fixing).
        self._live_check_trigger_fired = False

    # ---- state accounting -------------------------------------------------

    def approx_state_bytes(self) -> int:
        """CHEAP, NON-AUTHORITATIVE heuristic estimate (fixed per-node +
        per-count-entry overhead). Measured to under-count true resident
        memory by ~3.16x in the worst case tested (see
        MEASURED_WORST_CASE_UNDERCOUNT_RATIO) -- never sufficient alone to
        conclude the model is under `state_cap_bytes`; use
        `live_state_bytes()` for the authoritative figure."""
        return self._approx_bytes

    def _measure_module_bytes_now(self) -> int:
        """Internal: current tracemalloc total for allocations whose most
        recent traceback frame is THIS FILE, with NO baseline subtraction.
        Used both to seed `_tracemalloc_baseline_module_bytes` in
        `__init__` and by `isolated_ppm_state_bytes()` for the live
        reading. `tracemalloc.start()` is called with its default
        `nframe=1` (see `__init__`), so `all_frames` defaults to matching
        only the allocation site itself -- exactly what "this trie's own
        growth" means, since every `_Node()` / `dict()` / counts-entry
        write in this class happens directly inside this file's own
        functions, not a callee elsewhere."""
        snapshot = tracemalloc.take_snapshot()
        filtered = snapshot.filter_traces(
            (tracemalloc.Filter(inclusive=True, filename_pattern=__file__),))
        return sum(stat.size for stat in filtered.statistics("lineno"))

    def isolated_ppm_state_bytes(self) -> int:
        """AUTHORITATIVE, MODULE-ISOLATED live measurement (issue #703
        PR #759 external re-audit, PR comment 4943548456): current
        `_measure_module_bytes_now()` diffed against the baseline captured
        at the start of `__init__` (before this instance allocated
        anything), so any same-file allocation that predates this
        instance is excluded from ITS reported figure. This is what
        `state_cap_bytes` is enforced against for the PUBLISHABLE 'PPM
        state size' claim -- `process_live_bytes_governor()` below is a
        separate, deliberately coarser, conservative process-wide safety
        rail and is never itself the PPM-state figure.

        A foreign allocation made by CALLER code (a different file/line,
        e.g. an unrelated bytearray) does not appear here, because its
        traceback frame points to the caller's file, not this one -- see
        PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS for the executed
        counterexample.

        CONCURRENCY LIMITATION (disclosed, not hidden): isolation is by
        SOURCE FILE, not Python object identity. If multiple PpmModel
        instances are alive in the same process simultaneously, this
        method cannot distinguish which instance a given block of this
        file's allocations belongs to -- it reports the combined total for
        every live same-process instance (plus this module's own
        transient locals, negligible and momentary). This repo's
        correctness harness constructs one instance at a time; a caller
        needing exact per-instance isolation under true concurrency needs
        a different mechanism (out of scope here).

        PERFORMANCE NOTE (disclosed): `tracemalloc.take_snapshot()` walks
        every currently-traced block in the WHOLE process before this
        method's filter narrows it down -- fine at this apparatus's toy
        scale (throttled to at most once per LIVE_CHECK_INTERVAL training
        calls), but a future large-corpus port should re-benchmark this
        cost rather than assume it is still negligible."""
        return max(0, self._measure_module_bytes_now() - self._tracemalloc_baseline_module_bytes)

    def process_live_bytes_governor(self) -> int:
        """Conservative, PROCESS-WIDE safety rail (issue #703 PR #759
        external re-audit, PR comment 4943548456 -- honestly renamed from
        the prior `live_state_bytes`, which claimed to measure 'PPM LIVE
        memory' while actually returning
        `tracemalloc.get_traced_memory()[0]`, the current traced
        allocation total for the ENTIRE PYTHON PROCESS, not this instance
        or even this module). This number is NEVER a PPM-state claim: an
        unrelated caller allocation, another module's cache, or a second
        live model can inflate it with zero PPM growth -- receipted: an
        unrelated 2MB bytearray allocated before model construction
        inflated this reading by >99% of its value and triggered a
        false-positive refusal at symbol 52 while true PPM state was
        5,840 bytes (see PPM703_FOREIGN_ALLOCATION_ISOLATION_PASS). It
        remains a useful SECOND, coarser rail: refusing when the whole
        process is genuinely close to a memory ceiling is still a
        reasonable safety posture even when the attribution is fuzzy --
        but `_check_cap_periodic` reports explicitly which tier tripped,
        so a refusal here is never mis-read as evidence about PPM trie
        size specifically."""
        current, _peak = tracemalloc.get_traced_memory()
        return current

    def live_state_bytes(self) -> int:
        """DEPRECATED ALIAS. This name is the exact defect the external
        re-audit named (PR comment 4943548456): it returns the
        PROCESS-WIDE total, not PPM state, despite its name. Kept only so
        a caller mid-migration does not break outright -- new code must
        call `isolated_ppm_state_bytes()` for the authoritative
        PPM-specific figure or `process_live_bytes_governor()` for the
        explicit process-wide safety rail."""
        return self.process_live_bytes_governor()

    def _check_cap(self):
        """Tier 1 ONLY: cheap heuristic pre-check, fired on every new
        node/entry creation event (fast, always on). The periodic
        authoritative checks (isolated + process-wide) are NOT here -- see
        `_check_cap_periodic`, called once per `train_symbol` call
        regardless of whether that call created anything."""
        if self._approx_bytes > self.state_cap_bytes:
            raise PpmStateCapExceeded(
                f"PPM state estimate {self._approx_bytes} bytes exceeds cap "
                f"{self.state_cap_bytes} bytes (order_cap={self.order_cap}, "
                f"alphabet_size={self.alphabet_size}, "
                f"symbols_trained={self.symbols_trained})"
            )

    def _check_cap_periodic(self):
        """Tier 2/3: authoritative checks, called ONCE per `train_symbol`
        call -- UNCONDITIONALLY, i.e. the training-call boundary, matching
        the documented 'every LIVE_CHECK_INTERVAL training calls' contract
        exactly (issue #703 PR #759 external re-audit, PR comment
        4943548456: the OLD code incremented `_live_check_counter` only
        inside `_check_cap`, which a STABLE-CONTEXT stream -- same
        (context, symbol) repeated, no new node/entry after the first call
        -- reaches exactly once; the documented fallback was therefore
        unreachable for such a stream regardless of call count. Receipted
        old-code-fails: 500 training calls of a fixed repeated symbol,
        counter stuck at 2, LIVE_CHECK_INTERVAL=100 never reached. Fixed
        by moving the counter here, see
        PPM703_STABLE_CONTEXT_PERIODIC_CHECK_PASS), throttled by a
        measured trigger fraction of the cap OR the fixed call interval,
        whichever comes first.

        The trigger-fraction condition is EDGE-triggered (fires once, on
        the training call where `_approx_bytes` first crosses
        `state_cap_bytes * LIVE_CHECK_TRIGGER_FRACTION`, latched via
        `_live_check_trigger_fired`), NOT level-triggered: `_approx_bytes`
        only grows, so a level-triggered read (a bare `>=` re-evaluated
        fresh every call, no latch) makes `due` permanently True for
        EVERY remaining training call once the threshold is crossed --
        and since this method now runs unconditionally on every
        `train_symbol` call (not just new-node/entry events, the fix
        above), that means a full process-wide tracemalloc snapshot on
        every one of potentially thousands of subsequent calls (caught
        during this repair round's own selftest run: a 4000-symbol
        training fixture hung past a 90s budget under a level-triggered
        first draft of this method, entirely explained by this cost --
        the OLD code was accidentally shielded from it, since its
        growth-triggered `_check_cap()` naturally fires less often as the
        trie fills up). After the initial edge-fire, the regular
        `LIVE_CHECK_INTERVAL` cadence alone continues to throttle further
        checks. Checks `isolated_ppm_state_bytes()` (the authoritative
        PPM-specific figure) FIRST, then `process_live_bytes_governor()`
        (the conservative process-wide rail) -- either can independently
        refuse, and the raised message names which."""
        self._live_check_counter += 1
        due = self._live_check_counter >= self.LIVE_CHECK_INTERVAL
        if not due and not self._live_check_trigger_fired:
            if self._approx_bytes >= self.state_cap_bytes * self.LIVE_CHECK_TRIGGER_FRACTION:
                due = True
                self._live_check_trigger_fired = True
        if not due:
            return
        self._live_check_counter = 0
        isolated = self.isolated_ppm_state_bytes()
        if isolated > self.state_cap_bytes:
            raise PpmStateCapExceeded(
                f"PPM ISOLATED (module-filtered tracemalloc) state {isolated} "
                f"bytes exceeds cap {self.state_cap_bytes} bytes (heuristic "
                f"estimate was {self._approx_bytes} bytes -- non-authoritative, "
                f"see approx_state_bytes()/isolated_ppm_state_bytes() "
                f"docstrings). order_cap={self.order_cap}, "
                f"alphabet_size={self.alphabet_size}, "
                f"symbols_trained={self.symbols_trained}"
            )
        process_wide = self.process_live_bytes_governor()
        if process_wide > self.state_cap_bytes:
            raise PpmStateCapExceeded(
                f"Process-wide (tracemalloc, ALL process allocations, NOT "
                f"isolated to PPM state -- see process_live_bytes_governor() "
                f"docstring) live memory {process_wide} bytes exceeds cap "
                f"{self.state_cap_bytes} bytes. This is a conservative SAFETY "
                f"refusal, not evidence the PPM trie itself is over cap "
                f"(isolated_ppm_state_bytes()={isolated} bytes, "
                f"heuristic={self._approx_bytes} bytes). "
                f"order_cap={self.order_cap}, alphabet_size={self.alphabet_size}, "
                f"symbols_trained={self.symbols_trained}"
            )

    def _get_node(self, order: int, context: tuple, create: bool) -> _Node | None:
        d = self.nodes[order]
        node = d.get(context)
        if node is None and create:
            node = _Node()
            d[context] = node
            self._approx_bytes += self.NODE_OVERHEAD_BYTES
            self._check_cap()
        return node

    # ---- training -----------------------------------------------------

    def train_symbol(self, context: tuple, symbol: int):
        """Train one (context, symbol) event with update exclusion."""
        if not (0 <= symbol < self.alphabet_size):
            raise ValueError(f"symbol {symbol} out of alphabet range [0, {self.alphabet_size})")
        max_o = min(len(context), self.order_cap)
        for o in range(max_o, -1, -1):
            ctx_o = context[len(context) - o:] if o > 0 else ()
            node = self._get_node(o, ctx_o, create=True)
            prev = node.counts.get(symbol, 0)
            was_new = prev == 0
            if was_new:
                self._approx_bytes += self.ENTRY_OVERHEAD_BYTES
                self._check_cap()
            node.counts[symbol] = prev + 1
            node.total += 1
            if not was_new:
                # update exclusion: symbol already known at this order,
                # do not propagate the update to shorter orders.
                break
        self.symbols_trained += 1
        # Training-call-boundary periodic check -- unconditional, every
        # call, regardless of whether this call created any new node/entry
        # (see _check_cap_periodic docstring for why this must NOT be
        # folded into the growth-triggered _check_cap above).
        self._check_cap_periodic()

    def train_bytes(self, byte_iter, reset_context_on_eot: bool = True):
        """Train on a stream of symbols (ints in [0, alphabet_size)), applying
        the per-document context reset convention on EOT."""
        context: tuple = ()
        for b in byte_iter:
            self.train_symbol(context, b)
            if reset_context_on_eot and b == self.eot_symbol:
                context = ()
                self.documents_trained += 1
            else:
                context = (context + (b,))[-self.order_cap:] if self.order_cap > 0 else ()

    def train_from_file(self, path: str, reset_context_on_eot: bool = True,
                         max_bytes: int | None = None):
        """Train from a raw byte file. `path` is caller-supplied (CLI arg or
        repo-relative) -- this module never hardcodes a corpus path. Raw
        files contain byte values 0-255 only; EOT (256th symbol) is not a
        literal byte value and is never encountered by this reader -- for a
        file with no embedded document-boundary convention the entire file
        trains as one document (single context-reset at start only). Callers
        needing per-document resets on a real corpus must supply their own
        `byte_iter` (e.g. one that injects `self.eot_symbol` between shard
        records) to `train_bytes` directly instead of this convenience path.
        """
        n = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                for b in chunk:
                    self.train_symbol_stream_byte(b)
                    n += 1
                    if max_bytes is not None and n >= max_bytes:
                        return n
        return n

    def train_symbol_stream_byte(self, byte_value: int):
        """Streaming single-byte trainer used by train_from_file; keeps
        context state across calls (self._stream_context)."""
        if not hasattr(self, "_stream_context"):
            self._stream_context: tuple = ()
        self.train_symbol(self._stream_context, byte_value)
        self._stream_context = (self._stream_context + (byte_value,))[-self.order_cap:] \
            if self.order_cap > 0 else ()

    # ---- prediction (full exclusion PPM-D) -----------------------------

    def next_byte_probs(self, context: tuple) -> dict:
        """Full-exclusion PPM-D next-symbol distribution given `context`
        (bytes since the last EOT / document start). Returns a dict mapping
        every symbol with positive probability to its probability; the
        returned masses sum to 1.0 over the full alphabet (order -1 floor
        guarantees full alphabet coverage)."""
        excluded: set[int] = set()
        remaining_mass = 1.0
        result: dict = {}
        max_o = min(len(context), self.order_cap)
        for o in range(max_o, -1, -1):
            ctx_o = context[len(context) - o:] if o > 0 else ()
            node = self._get_node(o, ctx_o, create=False)
            if node is None or node.total == 0:
                continue
            present = [(s, c) for s, c in node.counts.items() if s not in excluded and c > 0]
            if not present:
                continue
            T = sum(c for _, c in present)
            k = len(present)
            denom = 2 * T
            esc = k / denom
            for s, c in present:
                p = (2 * c - 1) / denom
                if p < 0:
                    p = 0.0  # guard: PPM-D formula assumes c>=1, always non-negative in practice
                result[s] = result.get(s, 0.0) + remaining_mass * p
                excluded.add(s)
            remaining_mass *= esc
        rem_symbols = [s for s in range(self.alphabet_size) if s not in excluded]
        if rem_symbols and remaining_mass > 0:
            share = remaining_mass / len(rem_symbols)
            for s in rem_symbols:
                result[s] = result.get(s, 0.0) + share
        return result

    def prefix_probability(self, byte_seq, reset_on_eot: bool = True) -> float:
        """Exact chain-rule probability of observing `byte_seq` (a finite
        sequence of symbols) starting from an empty (order -1) context,
        applying the per-document reset convention if `byte_seq` itself
        contains an EOT before its end (defensive; lattice tests never do
        this mid-sequence)."""
        context: tuple = ()
        prob = 1.0
        for b in byte_seq:
            probs = self.next_byte_probs(context)
            p = probs.get(b, 0.0)
            prob *= p
            if prob == 0.0:
                return 0.0
            if reset_on_eot and b == self.eot_symbol:
                context = ()
            else:
                context = (context + (b,))[-self.order_cap:] if self.order_cap > 0 else ()
        return prob


def _cli():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train-path", type=str, default=None,
                     help="repo-relative or absolute path to a raw byte training "
                          "slice (no default/hardcoded path)")
    ap.add_argument("--order-cap", type=int, default=8)
    ap.add_argument("--alphabet-size", type=int, default=257)
    ap.add_argument("--state-cap-gib", type=float, default=8.0)
    ap.add_argument("--max-bytes", type=int, default=None,
                     help="optional cap on bytes consumed (e.g. for the 100MB "
                          "frozen training-slice convention: 100*1024*1024)")
    args = ap.parse_args()
    if args.train_path is None:
        print("no --train-path given; nothing to train (this stage does not "
              "ship a real corpus -- run exp703_selftest.py for apparatus "
              "correctness proofs)")
        return 0
    model = PpmModel(alphabet_size=args.alphabet_size, order_cap=args.order_cap,
                      state_cap_bytes=int(args.state_cap_gib * 1024 ** 3))
    t0 = time.time()
    n = model.train_from_file(args.train_path, max_bytes=args.max_bytes)
    dt = time.time() - t0
    mb = n / (1024 * 1024)
    print(f"PPM703_TRAIN: bytes={n} ({mb:.3f} MB) wall_s={dt:.3f} "
          f"s_per_MB={(dt / mb) if mb > 0 else float('nan'):.4f} "
          f"state_bytes_est={model.approx_state_bytes()}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())

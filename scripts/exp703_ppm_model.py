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
  - State budget cap: refusal (raises PpmStateCapExceeded) once the model's
    ESTIMATED resident state exceeds `state_cap_bytes` (default 8 GiB). The
    estimate is a disclosed heuristic (fixed per-node + per-count-entry
    overhead), not a live process-memory measurement -- adequate for a hard
    refusal gate at apparatus-build stage; tightening to a live measurement
    (tracemalloc/resource) is a candidate follow-up, not required by this
    apparatus PR (no training run against the real 100MB slice happens in
    this PR -- see train_from_file's parameterized, non-hardcoded path).

This module is CPU-only, pure Python, no external dependencies.
"""

from __future__ import annotations

import argparse
import sys
import time
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
        # nodes[order][context_tuple] -> _Node ; order 0 == empty-context (unigram) node.
        self.nodes: list[dict] = [dict() for _ in range(order_cap + 1)]
        self._approx_bytes = 0
        self.symbols_trained = 0
        self.documents_trained = 0

    # ---- state accounting -------------------------------------------------

    def approx_state_bytes(self) -> int:
        return self._approx_bytes

    def _check_cap(self):
        if self._approx_bytes > self.state_cap_bytes:
            raise PpmStateCapExceeded(
                f"PPM state estimate {self._approx_bytes} bytes exceeds cap "
                f"{self.state_cap_bytes} bytes (order_cap={self.order_cap}, "
                f"alphabet_size={self.alphabet_size}, "
                f"symbols_trained={self.symbols_trained})"
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

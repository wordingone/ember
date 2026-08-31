# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fineweb_exclusion.py — enforce the L3 fineweb_edu exclusion at LOAD time (#1436).

The v1-provenance-manifest RULED fineweb_edu DROP/EXCLUDED on 2026-07-06 (Llama-3-70B-
Instruct classifier taint, arXiv:2406.17557; receipts/v1-provenance-manifest-20260706.jsonl).
No shards-v1 binary was ever produced, so shards-v0 is the only stream that exists and it
still physically contains all 1,666,837,789 fineweb_edu tokens with zero source-awareness in
`PackedShardLoader` (scripts/timeshare_pretrain.py) — the ruling was prose, not bytes. The
2026-08-04 L3 provenance audit derived the exact fineweb_edu
token-offset range from the receipted per-source stream_tokens counts, in the writer's own
fp22_row concatenation order.

This module is CURE #2 from the issue ("teach the loader source-awareness"): derive the
excluded offset range PROGRAMMATICALLY from the TOKEN-SHARDS-V0 receipt (never hardcoded),
fail-closed if that receipt does not validate against the actual on-disk shard bytes, and
give `PackedShardLoader` a window filter so a window overlapping ANY excluded byte is never
yielded — bound to sha256s, not file names, per the issue's acceptance criterion.

Enforcement is OPT-OUT, not opt-in (#1436 rework): `resolve_excluded_ranges_for_stream`
is the single policy function that BOTH `PackedShardLoader` (its default when the caller
passes nothing) and the launch gate's G-shards row call, so the loader and the gate can
never disagree about whether a stream is enforced. A caller that does nothing gets the
fail-closed path; the legacy unfiltered path now requires an explicit `excluded_ranges=[]`.

Public API:
  ruled_excluded_sources(nc=NC)               -> fail-closed {source, ...} read from the RULING
  compute_source_offsets(receipt, assembly)   -> {source: (start, end)} in fp22_row order
  excluded_ranges_from_validated(receipt, assembly, excluded_sources) -> merged ranges
  enforcement_for_validated_receipt(receipt, nc=NC) -> (ranges, reason) with no re-sha
  resolve_excluded_ranges_for_stream(shard_dir, n_tokens, nc=NC) -> (ranges, reason)
  excluded_token_ranges(nc=NC, ...)           -> fail-closed sorted [(start, end), ...]
  usable_window_starts(n_tokens, seq, block_len, excluded_ranges) -> sorted [int, ...]
  assert_windows_exclude_ranges(window_starts, block_len, excluded_ranges) -> None or raises
  WindowPlan(n_tokens, seq, block_len, excluded_ranges) -> the loader's own window geometry

CLI:
  --selftest         hermetic; synthetic fixtures only, touches no production data
  --preflight         PRODUCTION read-only: validates the real receipt against the real
                      shard bytes, derives the range, and writes a
                      FINEWEB-EDU-EXCLUSION-PREFLIGHT receipt (no .bin bytes are written;
                      this is a pure read + assertion pass, no_gpu, no training).
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from token_shards_v0 import (                      # noqa: E402
    ASSEMBLY_RECEIPT, TICKET as SHARD_TICKET, validate_shards_receipt,
)
import receipt_check                               # noqa: E402

EXCLUSION_TICKET = "FINEWEB-EDU-EXCLUSION-PREFLIGHT"
# AUDITED BASELINE, not the enforced set. The enforced set is read from the
# RULING receipt by ruled_excluded_sources(); this constant is the floor that
# reading must never fall below (see that function).
EXCLUDED_SOURCES = {"fineweb_edu"}
DEFAULT_SHARD_RECEIPT = "token-shards-v0-20260611T170047Z.json"
RULING_RECEIPT = "v1-provenance-manifest-20260706.jsonl"
SHARD_RECEIPT_GLOB = "receipts/token-shards-v0-*.json"


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _row_excludes(row):
    """True iff a v1-provenance-manifest row rules its source out of training.
    Checked as an OR over the two fields the manifest actually uses -- `action`
    ("DROP") and `provenance_verdict` ("EXCLUDED (fail-closed per clause 3)") --
    so a future ruling written in either dialect is enforced rather than
    silently ignored for want of the other key."""
    if str(row.get("action", "")).strip().upper() == "DROP":
        return True
    verdict = str(row.get("provenance_verdict", "")).strip().upper()
    return verdict.startswith("EXCLUDED")


def ruled_excluded_sources(nc=NC, ruling_name=RULING_RECEIPT):
    """FAIL-CLOSED: the set of sources the PROVENANCE RULING excludes, read from
    the ruling receipt itself rather than from a constant in this file.

    This is the anti-rot mechanism the issue asks for. #1436 exists because the
    2026-07-06 ruling was prose that nothing executed; hardcoding its outcome as
    a Python set would reproduce the same failure one ruling later. Reading the
    ruling means a future DROP verdict is enforced by every caller the moment
    the receipt lands, with no code change to forget.

    The audited baseline EXCLUDED_SOURCES must remain a SUBSET of what the
    ruling yields. An edit that removed fineweb_edu from the ruling is exactly
    the silent-rot direction this function prevents, so it raises rather than
    quietly re-admitting tainted tokens."""
    path = f"{nc}/receipts/{ruling_name}"
    if not os.path.exists(path):
        raise ValueError(
            f"ruled_excluded_sources: provenance ruling not on disk: {path} — "
            "refusing to guess which sources are excluded")
    ruled = set()
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"ruled_excluded_sources: {ruling_name}:{lineno} is not "
                    f"valid JSON ({e}) — refusing to read a damaged ruling")
            if not isinstance(row, dict):
                continue
            src = row.get("source")
            if isinstance(src, str) and src and _row_excludes(row):
                ruled.add(src)
    missing = EXCLUDED_SOURCES - ruled
    if missing:
        raise ValueError(
            f"ruled_excluded_sources: {ruling_name} no longer excludes "
            f"{sorted(missing)}, which the 2026-08-04 L3 audit ruled out — "
            "refusing to re-admit audited-tainted sources on a ruling edit")
    return ruled


def compute_source_offsets(receipt, assembly):
    """{source: (start, end)} half-open token-offset ranges, in the writer's own
    fp22_row concatenation order (src/ember/governance/scripts/token_shards_v0.py `_resolve_sources`
    sorts by fp22_row and appends each source's stream in that order — strict
    concatenation, never shuffled/interleaved). Pure function of the two receipt
    dicts; raises ValueError if a source in the assembly is missing from
    per_source (the receipts have drifted apart and must not be trusted)."""
    per_source = receipt.get("per_source") or {}
    rows = sorted(assembly.get("sources", []),
                  key=lambda s: s.get("fp22_row", 1 << 30))
    offsets = {}
    cursor = 0
    for row in rows:
        src = row["source"]
        entry = per_source.get(src)
        if not isinstance(entry, dict) or not isinstance(
                entry.get("stream_tokens"), int):
            raise ValueError(
                f"compute_source_offsets: per_source[{src!r}] missing/invalid "
                "stream_tokens — receipts disagree, refusing to derive offsets")
        n = entry["stream_tokens"]
        offsets[src] = (cursor, cursor + n)
        cursor += n
    total = receipt.get("total_stream_tokens")
    if isinstance(total, int) and cursor != total:
        raise ValueError(
            f"compute_source_offsets: sum(per_source stream_tokens) {cursor} != "
            f"total_stream_tokens {total} — cannot trust the derived offsets")
    return offsets


def excluded_ranges_from_validated(receipt, assembly, excluded_sources):
    """Merged half-open (start, end) ranges for `excluded_sources`, derived from
    receipt dicts the CALLER has already byte-validated. Split out of
    excluded_token_ranges so a caller that just ran validate_shards_receipt
    (the launch gate's G-shards row) can derive the ranges without re-sha-ing
    every multi-GB shard a second time -- same derivation, same refusals, one
    validation pass."""
    offsets = compute_source_offsets(receipt, assembly)
    missing = set(excluded_sources) - set(offsets)
    if missing:
        raise ValueError(
            f"excluded_token_ranges: excluded source(s) {sorted(missing)} not "
            f"present in the derived offset map {sorted(offsets)} — refusing "
            "to silently exclude nothing")
    ranges = sorted(offsets[s] for s in excluded_sources)
    # merge adjacent/overlapping ranges so downstream overlap checks are simple
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def excluded_token_ranges(nc=NC, shard_dir=None, shard_receipt_name=DEFAULT_SHARD_RECEIPT,
                          assembly_name=ASSEMBLY_RECEIPT,
                          excluded_sources=None):
    """FAIL-CLOSED: load + validate the TOKEN-SHARDS-V0 receipt against the
    actual on-disk shard bytes (validate_shards_receipt — the same byte-true
    sha/count/parity check the launch gate uses), load + validate the assembly
    receipt it pins, then derive the excluded sources' offset ranges from the
    validated numbers. Any receipt miss, sha drift, or missing premise raises
    ValueError — this function NEVER returns a range for bytes it hasn't
    itself proven exist. `shard_dir` overrides the receipt's own NC-relative
    shard_dir (worktree-invariant, mirrors validate_shards_receipt's own
    shard_dir_override contract) — pass it when the shard bytes live in an
    out-of-tree data store rather than this checkout.

    Returns a sorted, merged list of (start, end) half-open token-offset
    tuples covering every requested excluded source."""
    if excluded_sources is None:
        excluded_sources = ruled_excluded_sources(nc)
    receipt_path = f"{nc}/receipts/{shard_receipt_name}"
    if not os.path.exists(receipt_path):
        raise ValueError(f"excluded_token_ranges: shard receipt not on disk: "
                         f"{receipt_path}")
    receipt = _load_json(receipt_path)
    violations = validate_shards_receipt(receipt, nc, shard_dir_override=shard_dir)
    if violations:
        raise ValueError(
            "excluded_token_ranges: TOKEN-SHARDS-V0 receipt FAILS validation "
            f"against on-disk shard bytes — refusing to trust any offset "
            f"derived from it: {violations}")

    assembly_path = f"{nc}/receipts/{assembly_name}"
    if not os.path.exists(assembly_path):
        raise ValueError(f"excluded_token_ranges: assembly receipt not on disk: "
                         f"{assembly_path}")
    assembly = _load_json(assembly_path)
    prem = (receipt.get("premises") or {}).get("assembly_receipt") or {}
    if prem.get("name") != assembly_name:
        raise ValueError(
            "excluded_token_ranges: shard receipt's pinned assembly premise "
            f"{prem.get('name')!r} != the assembly receipt being used "
            f"{assembly_name!r} — refusing a mismatched pin")

    return excluded_ranges_from_validated(receipt, assembly, excluded_sources)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap. An EMPTY interval on either side overlaps
    NOTHING: a zero-token excluded range covers no token, so no window can
    contain one of its tokens. Without this guard the naive comparison reports
    an overlap for every window straddling the degenerate point and drops clean
    windows -- found by the randomized WindowPlan-vs-brute-force sweep in
    _selftest(), which disagreed on range (134, 134)."""
    if a_start >= a_end or b_start >= b_end:
        return False
    return a_start < b_end and b_start < a_end


def usable_window_starts(n_tokens, seq, block_len, excluded_ranges):
    """Every window start `i*seq` for `i` in `[0, (n_tokens-block_len)//seq]`
    whose covered byte range `[start, start+block_len)` does NOT overlap any
    excluded range. Pure function, O(n_windows * n_ranges) — n_ranges is a
    handful of sources, never large. A window that straddles an excluded
    boundary is dropped whole (fail-closed on the boundary tokens too: a
    window is either entirely clean or entirely excluded, never partially
    consumed)."""
    if n_tokens < block_len:
        return []
    n_windows_full = (n_tokens - block_len) // seq + 1
    if not excluded_ranges:
        return [i * seq for i in range(n_windows_full)]
    out = []
    for i in range(n_windows_full):
        start = i * seq
        end = start + block_len
        if not any(_overlaps(start, end, es, ee) for es, ee in excluded_ranges):
            out.append(start)
    return out


def assert_windows_exclude_ranges(window_starts, block_len, excluded_ranges):
    """Byte-exact re-verification (never sampled) that NOT ONE window in
    `window_starts` overlaps ANY excluded range. Raises AssertionError on the
    first violation found. This is the launch preflight assertion the issue
    requires: "a training run cannot consume a fineweb_edu token" — proven
    over every yielded window, not a source-average estimate."""
    for start in window_starts:
        end = start + block_len
        for es, ee in excluded_ranges:
            if _overlaps(start, end, es, ee):
                raise AssertionError(
                    f"window [{start}, {end}) overlaps excluded range "
                    f"[{es}, {ee}) — fineweb_edu exclusion enforcement failed")


def _excluded_index_runs(n_windows_full, seq, block_len, excluded_ranges):
    """Merged, sorted inclusive index intervals [lo, hi] of the windows that
    overlap an excluded range. Closed-form, so the full production stream never
    materializes a 6.8M-element Python list just to describe a handful of
    contiguous spans.

    Window i covers [i*seq, i*seq+block_len). It overlaps [es, ee) iff
      i*seq < ee            -> i <= (ee - 1) // seq
      es < i*seq + block_len -> i >= (es - block_len) // seq + 1
    (Python floor division is correct for the negative numerator that a range
    starting inside the first window produces.)"""
    runs = []
    for es, ee in excluded_ranges:
        if ee <= es:
            continue
        lo = max(0, (es - block_len) // seq + 1)
        hi = min(n_windows_full - 1, (ee - 1) // seq)
        if lo <= hi:
            runs.append((lo, hi))
    runs.sort()
    merged = []
    for lo, hi in runs:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


class WindowPlan:
    """The loader's window geometry, as an IMPORTABLE object (#1436 rework).

    `PackedShardLoader` (scripts/timeshare_pretrain.py) delegates both its
    window count and its index -> start-offset remap here, so the selection
    behavior a training run actually executes can be constructed and asserted
    on without importing that module -- which is execution-denied under the
    2026-07-12 `historical_only` lock. A source-text grep passes while the
    remap is off by one; constructing this object and reading `start_for_index`
    cannot.

    `excluded_ranges` empty/None is the legacy identity geometry, arithmetically
    byte-identical to the pre-#1436 `start = (i % n_windows) * seq`."""

    def __init__(self, n_tokens, seq, block_len, excluded_ranges=None):
        if seq <= 0 or block_len <= 0:
            raise ValueError(f"WindowPlan: seq {seq} / block_len {block_len} "
                             "must both be positive")
        self.n_tokens = int(n_tokens)
        self.seq = int(seq)
        self.block_len = int(block_len)
        self.excluded_ranges = [tuple(r) for r in (excluded_ranges or [])]
        self.n_windows_full = (0 if self.n_tokens < self.block_len
                               else (self.n_tokens - self.block_len) // self.seq + 1)
        if not self.excluded_ranges:
            self._runs = None
            self.n_windows = self.n_windows_full
            return
        excluded_runs = _excluded_index_runs(
            self.n_windows_full, self.seq, self.block_len, self.excluded_ranges)
        # complement: the usable index runs, in ascending order
        usable = []
        cursor = 0
        for lo, hi in excluded_runs:
            if cursor < lo:
                usable.append((cursor, lo - 1))
            cursor = max(cursor, hi + 1)
        if cursor <= self.n_windows_full - 1:
            usable.append((cursor, self.n_windows_full - 1))
        self._runs = usable
        self.n_windows = sum(hi - lo + 1 for lo, hi in usable)

    def start_for_index(self, i):
        """Token offset of usable window `i` (taken mod n_windows, matching the
        loader's deterministic cycling contract)."""
        if self.n_windows <= 0:
            raise IndexError("WindowPlan: no usable windows")
        i %= self.n_windows
        if self._runs is None:
            return i * self.seq
        for lo, hi in self._runs:
            span = hi - lo + 1
            if i < span:
                return (lo + i) * self.seq
            i -= span
        raise IndexError("WindowPlan: index past the usable runs (unreachable)")

    def all_starts(self):
        """Every usable window start, ascending. O(n_windows) memory -- for
        tests and receipts, never on the training hot path."""
        if self._runs is None:
            return [i * self.seq for i in range(self.n_windows_full)]
        return [i * self.seq for lo, hi in self._runs for i in range(lo, hi + 1)]

    def index_runs(self):
        """The usable index runs as inclusive [lo, hi] pairs (identity geometry
        reports the single full run)."""
        if self._runs is None:
            return ([(0, self.n_windows_full - 1)]
                    if self.n_windows_full > 0 else [])
        return list(self._runs)


def assert_plan_excludes_ranges(plan, excluded_ranges=None):
    """Byte-exact re-verification that NOT ONE window `plan` can yield overlaps
    an excluded range -- proven over the plan's contiguous index RUNS instead of
    by enumerating every window.

    This is equivalence, not a sampling shortcut. Within a run, consecutive
    windows are stride `seq` and length `block_len`; when block_len >= seq they
    overlap each other, so the union of the run's windows is exactly the
    contiguous token span [lo*seq, hi*seq + block_len). A span that misses every
    excluded range therefore proves every window inside it does. _selftest()
    asserts this agrees with the per-window check across a randomized sweep.
    The loader always satisfies block_len = seq + 1 + n_mtp > seq; the
    block_len < seq case (windows with gaps between them, no loader produces
    it) falls back to per-window enumeration rather than over-claiming.

    Matters because the production stream has ~6.8M windows: enumerating them
    to prove the invariant would cost hundreds of MB at every loader
    construction, which is the kind of cost that gets a check disabled."""
    ranges = plan.excluded_ranges if excluded_ranges is None else excluded_ranges
    if not ranges:
        return
    if plan.block_len < plan.seq:
        assert_windows_exclude_ranges(plan.all_starts(), plan.block_len, ranges)
        return
    for lo, hi in plan.index_runs():
        span_start = lo * plan.seq
        span_end = hi * plan.seq + plan.block_len
        for es, ee in ranges:
            if _overlaps(span_start, span_end, es, ee):
                raise AssertionError(
                    f"usable window run [{lo}, {hi}] spans tokens "
                    f"[{span_start}, {span_end}) which overlaps excluded range "
                    f"[{es}, {ee}) — exclusion enforcement failed")


# ---------------------------------------------------------------------------
# Default-enforcement policy (opt-OUT), shared by the loader and the gate
# ---------------------------------------------------------------------------
def enforcement_for_validated_receipt(receipt, nc=NC, assembly_name=ASSEMBLY_RECEIPT,
                                      excluded_sources=None):
    """(ranges, reason) for a TOKEN-SHARDS-V0 receipt the caller has ALREADY
    byte-validated. Raises on any derivation failure -- an excluded source that
    is present in the stream but whose offsets cannot be derived is a hard
    refusal, never an empty range."""
    if excluded_sources is None:
        excluded_sources = ruled_excluded_sources(nc)
    assembly_path = f"{nc}/receipts/{assembly_name}"
    if not os.path.exists(assembly_path):
        raise ValueError(f"enforcement_for_validated_receipt: assembly receipt "
                         f"not on disk: {assembly_path}")
    assembly = _load_json(assembly_path)
    # Membership is decided by the ASSEMBLY -- the list of sources the stream
    # was built from -- NOT by the receipt's per_source map. Reading per_source
    # first would be fail-OPEN: deleting a source's per_source entry would look
    # exactly like "that source was never in this stream" and silently disable
    # its exclusion. An excluded source the assembly lists MUST be derivable
    # from the receipt, and compute_source_offsets refuses when it is not.
    in_assembly = sorted(s for s in excluded_sources
                         if s in {row.get("source")
                                  for row in (assembly.get("sources") or [])})
    if not in_assembly:
        return [], ("no ruled-excluded source appears in the assembly this "
                    "stream was built from — nothing to exclude")
    ranges = [(s, e) for s, e in
              excluded_ranges_from_validated(receipt, assembly, in_assembly)
              if e > s]
    if not ranges:
        return [], (f"ruled-excluded source(s) {', '.join(in_assembly)} carry "
                    "zero tokens in this stream — nothing to exclude")
    return ranges, (f"excluding {', '.join(in_assembly)} over "
                    f"{len(ranges)} range(s)")


LOADER_MODULE = "timeshare_pretrain.py"
LOADER_CLASS = "PackedShardLoader"
LOADER_PARAM = "excluded_ranges"


def loader_default_is_enforcing(source=None, scripts_dir=HERE):
    """(ok, detail): is `PackedShardLoader.__init__`'s `excluded_ranges` default
    still the ENFORCING one?

    Parsed with `ast` and judged on the default's VALUE NODE, not grepped for a
    substring. A permissive default is a literal -- `None` (ast.Constant) or
    `[]` (an empty ast.List) -- and makes exclusion opt-in again, which is the
    exact defect #1436 was reopened for. The enforcing default is a sentinel
    object referenced by name, so the check is: the default node exists and is
    not a permissive literal.

    The launch gate calls this because it CANNOT import the loader to test the
    behavior directly -- timeshare_pretrain.py raises SystemExit at import
    under the 2026-07-12 `historical_only` lock. `source` is injectable so the
    check itself is unit-tested against both a passing and a failing fixture
    rather than only ever run against the one file that happens to pass."""
    import ast
    if source is None:
        path = os.path.join(scripts_dir, LOADER_MODULE)
        if not os.path.exists(path):
            return False, f"{LOADER_MODULE} not found in {scripts_dir}"
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"{LOADER_MODULE} does not parse: {e}"
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == LOADER_CLASS), None)
    if cls is None:
        return False, f"class {LOADER_CLASS} not found"
    init = next((n for n in cls.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "__init__"), None)
    if init is None:
        return False, f"{LOADER_CLASS}.__init__ not found"
    args = init.args
    default = None
    found = False
    for arg, dflt in zip(args.kwonlyargs, args.kw_defaults):
        if arg.arg == LOADER_PARAM:
            found, default = True, dflt
            break
    if not found:
        names = [a.arg for a in args.args + args.kwonlyargs]
        for arg, dflt in zip(reversed(args.args), reversed(args.defaults or [])):
            if arg.arg == LOADER_PARAM:
                found, default = True, dflt
                break
        if not found:
            return False, (f"{LOADER_CLASS}.__init__ has no {LOADER_PARAM} "
                           f"parameter (params: {names}) — the loader cannot "
                           "exclude anything")
    if default is None:
        return False, (f"{LOADER_PARAM} is a REQUIRED parameter; every existing "
                       "caller would break rather than inherit enforcement")
    if isinstance(default, ast.Constant) and default.value is None:
        return False, (f"{LOADER_PARAM} defaults to None — exclusion is opt-IN "
                       "again, so a caller that does nothing trains on the "
                       "tainted range (#1436)")
    if isinstance(default, (ast.List, ast.Tuple, ast.Set)) and not default.elts:
        return False, (f"{LOADER_PARAM} defaults to an empty literal — "
                       "exclusion is opt-IN again (#1436)")
    return True, (f"{LOADER_CLASS}.__init__ {LOADER_PARAM} defaults to "
                  f"{ast.unparse(default)} (enforcing)")


def identify_stream_receipt(n_tokens, nc=NC):
    """Basename of the TOKEN-SHARDS-V0 receipt that
    `resolve_excluded_ranges_for_stream` would bind for a stream of `n_tokens`,
    or None. Same glob and same total_stream_tokens discriminator, with no
    validation pass -- so the launch gate can assert which receipt the loader
    default will bind without paying a second full sha sweep over every
    multi-GB shard. resolve_excluded_ranges_for_stream calls this, so the two
    cannot drift apart."""
    for path in reversed(sorted(glob.glob(f"{nc}/{SHARD_RECEIPT_GLOB}"))):
        try:
            receipt = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if receipt.get("total_stream_tokens") == n_tokens:
            return os.path.basename(path)
    return None


def resolve_excluded_ranges_for_stream(shard_dir, n_tokens, nc=NC,
                                       excluded_sources=None):
    """THE default-enforcement policy. ONE function, called both by
    `PackedShardLoader` when the caller passes no `excluded_ranges` and by the
    launch gate's G-shards row -- so the loader and the gate can never disagree
    about whether a given stream is enforced.

    Returns (ranges, reason).

    A stream is IDENTIFIED as the receipted v0 stream by its own token count
    matching a TOKEN-SHARDS-V0 receipt's `total_stream_tokens`. That check is
    free and runs first, so synthetic fixtures and dry-run shards -- whose
    lengths never match -- pay no validation cost and keep the legacy identity
    geometry. Excluded offsets are only meaningful against the exact stream
    they were derived from; applying them to a different corpus would silently
    drop arbitrary windows, which is why the match is required rather than
    assumed.

    Once a stream IS identified as the receipted v0 stream, the derivation is
    fail-closed: `excluded_token_ranges` re-validates the receipt against the
    on-disk shard bytes and raises on any drift. A caller on the tainted stream
    therefore either gets proven-clean windows or an exception -- never an
    unfiltered stream.

    The UNIDENTIFIED case returning ([], reason) is deliberate and is NOT the
    whole safety story: a production launch is protected by the launch gate's
    own cross-check (`v0_pretrain_launch_gate._shards_exclusion_check`), which
    independently re-derives this identification and BLOCKS --live when the
    declared stream would not bind to a receipt. A direct `PackedShardLoader`
    caller bypassing the gate must not assume the loader alone proves
    cleanliness for an arbitrary stream -- it proves it only for streams this
    function can identify."""
    name = identify_stream_receipt(n_tokens, nc)
    if name is None:
        return [], (f"no TOKEN-SHARDS-V0 receipt declares a {n_tokens}-token "
                    "stream — not the receipted v0 corpus, so no derived "
                    "exclusion applies")
    receipt = _load_json(f"{nc}/receipts/{name}")
    # the assembly comes from the receipt's OWN pinned premise, not from this
    # module's default constant -- the receipt already declares which assembly
    # it was built against, and excluded_token_ranges refuses a mismatched pin.
    prem = (receipt.get("premises") or {}).get("assembly_receipt") or {}
    assembly_name = prem.get("name") or ASSEMBLY_RECEIPT
    ranges = excluded_token_ranges(
        nc, shard_dir=shard_dir, shard_receipt_name=name,
        assembly_name=assembly_name, excluded_sources=excluded_sources)
    if not ranges:
        return [], (f"{name} matches this stream; no ruled-excluded source "
                    "carries tokens in it")
    return ranges, f"enforced from {name}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _utc_ts():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_preflight(nc=NC, shard_dir=None, shard_receipt_name=DEFAULT_SHARD_RECEIPT,
                  assembly_name=ASSEMBLY_RECEIPT, excluded_sources=None,
                  seq=1024, n_mtp=2):
    """Read-only production preflight: derive the excluded ranges (fail-closed
    against the real receipts/shard bytes), compute the usable-window count
    for the frozen v0 loader geometry, byte-exact verify zero overlap, and
    return a receipt dict. no_gpu; touches no training state."""
    if excluded_sources is None:
        excluded_sources = ruled_excluded_sources(nc)
    ranges = excluded_token_ranges(nc, shard_dir=shard_dir,
                                   shard_receipt_name=shard_receipt_name,
                                   assembly_name=assembly_name,
                                   excluded_sources=excluded_sources)
    receipt = _load_json(f"{nc}/receipts/{shard_receipt_name}")
    n_tokens = receipt["total_stream_tokens"]
    block_len = seq + 1 + n_mtp
    starts_full = usable_window_starts(n_tokens, seq, block_len, [])
    starts_clean = usable_window_starts(n_tokens, seq, block_len, ranges)
    assert_windows_exclude_ranges(starts_clean, block_len, ranges)
    excluded_content_tokens = sum(
        (receipt.get("per_source") or {}).get(s, {}).get("content_tokens", 0)
        for s in excluded_sources)
    clean_content_tokens = receipt["content_total_tokens"] - excluded_content_tokens
    return {
        "ticket": EXCLUSION_TICKET,
        "ts": _utc_ts(),
        "shard_receipt": shard_receipt_name,
        "assembly_receipt": assembly_name,
        "excluded_sources": sorted(excluded_sources),
        "excluded_token_ranges": [list(r) for r in ranges],
        "loader_geometry": {"seq": seq, "n_mtp": n_mtp, "block_len": block_len},
        "n_windows_unenforced": len(starts_full),
        "n_windows_enforced": len(starts_clean),
        "n_windows_dropped": len(starts_full) - len(starts_clean),
        "zero_overlap_verified": True,
        "clean_content_tokens": clean_content_tokens,
        "stream_content_tokens": receipt["content_total_tokens"],
        "no_gpu": True,
        # Every post-genesis receipt must carry the constitutional invariant
        # hash (guard changed-receipts leg -> receipt_check, which refuses
        # MISSING_INVARIANT_SHA256). Read from receipt_check -- the component
        # that ENFORCES the value -- never copied, so the two cannot drift.
        # And any receipt carrying a *sha256* field must declare its
        # sha_convention (receipt_check SHA-CONVENTION rule); the string
        # matches the fleet's standing convention for constitutional-hash-
        # only receipts (e.g. attribution-702 revalidation).
        "invariant_sha256": receipt_check.INVARIANT_SHA256,
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"),
        },
    }


def _selftest():
    """Hermetic — no repo receipts, no production data. Exercises the offset
    derivation and window filter against synthetic fixtures shaped exactly
    like the real receipt schema."""
    receipt = {
        "total_stream_tokens": 1000,
        "per_source": {
            "code_github_clean": {"stream_tokens": 400},
            "fineweb_edu": {"stream_tokens": 300},
            "wikipedia_en": {"stream_tokens": 300},
        },
    }
    assembly = {"sources": [
        {"source": "code_github_clean", "fp22_row": 1},
        {"source": "fineweb_edu", "fp22_row": 2},
        {"source": "wikipedia_en", "fp22_row": 3},
    ]}
    offsets = compute_source_offsets(receipt, assembly)
    assert offsets == {
        "code_github_clean": (0, 400),
        "fineweb_edu": (400, 700),
        "wikipedia_en": (700, 1000),
    }, offsets

    # order independence: assembly listed out of fp22_row order still resolves
    # to the same offsets (sort is by fp22_row, not list position)
    shuffled = {"sources": list(reversed(assembly["sources"]))}
    assert compute_source_offsets(receipt, shuffled) == offsets

    # a source missing from per_source is a hard refusal, never a silent skip
    bad_receipt = {"total_stream_tokens": 700,
                   "per_source": {"code_github_clean": {"stream_tokens": 400},
                                  "wikipedia_en": {"stream_tokens": 300}}}
    try:
        compute_source_offsets(bad_receipt, assembly)
        raise AssertionError("expected ValueError for a missing source")
    except ValueError:
        pass

    # a total-tokens mismatch is a hard refusal (receipts disagree)
    drift_receipt = dict(receipt)
    drift_receipt["total_stream_tokens"] = 999
    try:
        compute_source_offsets(drift_receipt, assembly)
        raise AssertionError("expected ValueError for a total mismatch")
    except ValueError:
        pass

    # --- window filtering -------------------------------------------------
    seq, n_mtp = 8, 2
    block_len = seq + 1 + n_mtp        # 11
    n_tokens = 100
    excl = [(40, 70)]                  # e.g. offsets [40,70) excluded
    all_starts = usable_window_starts(n_tokens, seq, block_len, [])
    clean_starts = usable_window_starts(n_tokens, seq, block_len, excl)
    assert len(clean_starts) < len(all_starts)
    assert set(clean_starts) <= set(all_starts)
    # zero clean window ever overlaps the excluded range — byte-exact check,
    # never sampled
    assert_windows_exclude_ranges(clean_starts, block_len, excl)
    for s in all_starts:
        if s not in clean_starts:
            e = s + block_len
            assert e > excl[0][0] and s < excl[0][1], (
                f"window {s} was dropped but does not overlap {excl}")

    # a violated invariant is caught, not silently passed
    try:
        assert_windows_exclude_ranges([45], block_len, excl)   # 45..56 overlaps 40..70
        raise AssertionError("expected AssertionError for an overlapping window")
    except AssertionError as e:
        assert "overlaps excluded range" in str(e)

    # empty excluded_ranges is the identity (no filtering) — the legacy path
    assert usable_window_starts(n_tokens, seq, block_len, []) == \
        usable_window_starts(n_tokens, seq, block_len, None if False else [])

    # multiple excluded ranges, including adjacent ones that should merge in
    # excluded_token_ranges (tested indirectly via the merge logic inline)
    r1 = usable_window_starts(200, seq, block_len, [(0, 20), (20, 40)])
    r2 = usable_window_starts(200, seq, block_len, [(0, 40)])
    assert r1 == r2, "adjacent excluded ranges must behave like one merged range"

    # n_tokens < block_len -> no windows, no crash
    assert usable_window_starts(5, seq, block_len, []) == []

    # --- WindowPlan: closed-form geometry == brute-force enumeration --------
    # The closed-form run math is what the loader executes; an off-by-one there
    # would silently feed excluded tokens. Prove equivalence against the
    # brute-force filter over a randomized sweep, not one hand-picked case.
    import random as _random
    rng = _random.Random(1436)
    for _ in range(400):
        s = rng.randint(1, 32)
        bl = s + 1 + rng.randint(0, 4)
        nt = rng.randint(0, 600)
        n_ranges = rng.randint(0, 3)
        ranges = []
        for _r in range(n_ranges):
            a = rng.randint(0, max(0, nt))
            b = a + rng.randint(0, 60)
            ranges.append((a, b))
        plan = WindowPlan(nt, s, bl, ranges)
        brute = usable_window_starts(nt, s, bl, ranges)
        assert plan.all_starts() == brute, (nt, s, bl, ranges,
                                            plan.all_starts()[:8], brute[:8])
        assert plan.n_windows == len(brute), (nt, s, bl, ranges)
        # start_for_index reproduces the same list in order, and cycles mod n
        if brute:
            assert [plan.start_for_index(i) for i in range(len(brute))] == brute
            assert plan.start_for_index(len(brute)) == brute[0]
        # and no yielded start ever overlaps -- byte-exact, never sampled
        assert_windows_exclude_ranges(plan.all_starts(), bl, ranges)
        # the O(runs) span proof the loader actually runs agrees with the
        # per-window enumeration on every one of these cases
        assert_plan_excludes_ranges(plan)

    # identity geometry is arithmetically the pre-#1436 formula
    plan_id = WindowPlan(100, 8, 11, [])
    assert plan_id.n_windows == (100 - 11) // 8 + 1
    assert [plan_id.start_for_index(i) for i in range(plan_id.n_windows)] == \
        [i * 8 for i in range(plan_id.n_windows)]

    # the span proof CATCHES a bad run set -- it is not vacuously true. Poison
    # a plan's runs with an index that does overlap and require the raise.
    plan_bad = WindowPlan(100, 8, 11, [(40, 70)])
    assert_plan_excludes_ranges(plan_bad)              # honest plan passes
    plan_bad._runs = [(0, 11)]                         # readmit the excluded run
    try:
        assert_plan_excludes_ranges(plan_bad)
        raise AssertionError("expected AssertionError for a poisoned run set")
    except AssertionError as e:
        assert "overlaps excluded range" in str(e)

    # --- the loader-default AST check catches a permissive default ---------
    # Exercised against synthetic sources so the check itself is tested, not
    # only ever run against the one real file that happens to pass.
    _ENFORCING = ("_SENTINEL = object()\n"
                  "class PackedShardLoader:\n"
                  "    def __init__(self, shard_dir, seq, n_mtp, *,\n"
                  "                 excluded_ranges=_SENTINEL): pass\n")
    ok, why = loader_default_is_enforcing(source=_ENFORCING)
    assert ok, why
    for bad_default, expect in (("None", "opt-IN"), ("[]", "empty literal"),
                                ("()", "empty literal")):
        bad = _ENFORCING.replace("excluded_ranges=_SENTINEL",
                                 f"excluded_ranges={bad_default}")
        ok, why = loader_default_is_enforcing(source=bad)
        assert not ok and expect in why, (bad_default, ok, why)
    # a positional (non-kwonly) enforcing default is still accepted
    ok, why = loader_default_is_enforcing(
        source="_S = object()\nclass PackedShardLoader:\n"
               "    def __init__(self, shard_dir, excluded_ranges=_S): pass\n")
    assert ok, why
    # the parameter vanishing entirely, or becoming required, both fail closed
    ok, why = loader_default_is_enforcing(
        source="class PackedShardLoader:\n    def __init__(self, shard_dir): pass\n")
    assert not ok and "no excluded_ranges parameter" in why, why
    ok, why = loader_default_is_enforcing(
        source="class PackedShardLoader:\n"
               "    def __init__(self, shard_dir, *, excluded_ranges): pass\n")
    assert not ok and "REQUIRED parameter" in why, why
    ok, why = loader_default_is_enforcing(source="class Other: pass\n")
    assert not ok and "not found" in why, why
    # and the REAL loader in this checkout defaults to enforcement
    ok, why = loader_default_is_enforcing()
    assert ok, why

    # a fully-excluded stream leaves zero usable windows and refuses to index
    plan_none = WindowPlan(100, 8, 11, [(0, 100)])
    assert plan_none.n_windows == 0
    try:
        plan_none.start_for_index(0)
        raise AssertionError("expected IndexError with zero usable windows")
    except IndexError:
        pass

    print("FINEWEB_EXCLUSION_SELFTEST_PASS")


def _selftest_fail_closed_against_real_schema():
    """Exercises excluded_token_ranges()'s fail-closed path against a synthetic
    on-disk fixture that mirrors the real TOKEN-SHARDS-V0 + assembly receipt
    shapes (via token_shards_v0's own selftest fixture builder), proving the
    end-to-end wiring (receipt validation -> offset derivation) without
    touching any production receipt or shard byte."""
    import copy
    import struct
    import tempfile
    import token_shards_v0 as tsv

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        os.makedirs(f"{td}/shards")
        os.makedirs(f"{td}/tokenizer")
        prem_names = {"assembly_receipt": "fixture-assembly.json",
                     "tokenizer_freeze_receipt": "fixture-tokfreeze.json"}
        for nm in prem_names.values():
            json.dump({"ticket": "FIXTURE", "ts": "20260101T000000Z"},
                      open(f"{td}/receipts/{nm}", "w"))
        json.dump({"vocab_size": 32000},
                  open(f"{td}/domains/model/tokenizer/tokenizer.json", "w"))
        # the RULING fixture: excluded_token_ranges now defaults its excluded
        # set to ruled_excluded_sources(nc), so the fixture tree must carry a
        # ruling of its own -- proving the default really does read the ruling
        # rather than a constant.
        with open(f"{td}/receipts/{RULING_RECEIPT}", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"source": "code_github_clean",
                                 "provenance_verdict": "CLEAN"}) + "\n")
            fh.write(json.dumps({"source": "fineweb_edu", "action": "DROP",
                                 "provenance_verdict":
                                     "EXCLUDED (fail-closed per clause 3)"}) + "\n")

        def _write_shard(name, n):
            ids = [8 + (i % 100) for i in range(n)]
            with open(f"{td}/shards/{name}", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in ids))
            return n

        n0 = _write_shard("v0-00000.bin", 3000)
        total = n0

        def _sha(p):
            return tsv._sha(p)

        per_source = {s: {"content_tokens": 0, "separator_tokens": 0,
                          "stream_tokens": 0} for s in tsv.EXPECTED_SOURCES}
        # split the single shard's tokens across two sources so an excluded
        # range sits strictly inside the stream (not the whole thing)
        per_source["code_github_clean"] = {"content_tokens": 1000,
                                           "separator_tokens": 0,
                                           "stream_tokens": 1000}
        per_source["fineweb_edu"] = {"content_tokens": total - 1000,
                                     "separator_tokens": 0,
                                     "stream_tokens": total - 1000}

        receipt = {
            "ticket": tsv.TICKET, "ts": "20260611T000000Z", "shard_dir": "shards",
            "shards": [{"name": "v0-00000.bin", "sha256": _sha(f"{td}/shards/v0-00000.bin"),
                       "n_tokens": n0}],
            "total_stream_tokens": total, "content_total_tokens": total,
            "per_source": per_source, "separator_id": tsv.SEPARATOR_ID,
            "reserved_band_guard": {"reserved_ids": tsv.RESERVED_IDS,
                                    "max_id_lt": tsv.VOCAB_SIZE,
                                    "reserved_ids_observed_in_stream": 0},
            "loader_windows": {"seq": tsv.SEQ, "n_mtp": tsv.N_MTP,
                               "block_len": tsv.BLOCK_LEN,
                               "n_windows": (total - tsv.BLOCK_LEN) // tsv.SEQ + 1},
            "premises": {
                "assembly_receipt": {"name": prem_names["assembly_receipt"],
                                     "sha256": _sha(f"{td}/receipts/{prem_names['assembly_receipt']}")},
                "tokenizer_freeze_receipt": {"name": prem_names["tokenizer_freeze_receipt"],
                                             "sha256": _sha(f"{td}/receipts/{prem_names['tokenizer_freeze_receipt']}")},
                "tokenizer_json": {"path": "domains/model/tokenizer/tokenizer.json",
                                   "sha256": _sha(f"{td}/domains/model/tokenizer/tokenizer.json")},
            },
            "sha_convention": tsv.SHA_CONVENTION, "no_gpu": True,
        }
        assembly = {"ticket": "FIXTURE", "ts": "20260101T000000Z", "sources": [
            {"source": "code_github_clean", "fp22_row": 1},
            {"source": "fineweb_edu", "fp22_row": 2},
            {"source": "wikipedia_en", "fp22_row": 3},
            {"source": "gutenberg_en", "fp22_row": 4},
            {"source": "ledger_mit", "fp22_row": 5},
        ]}
        json.dump(assembly, open(f"{td}/receipts/{prem_names['assembly_receipt']}", "w"))
        receipt["premises"]["assembly_receipt"]["sha256"] = _sha(
            f"{td}/receipts/{prem_names['assembly_receipt']}")
        json.dump(receipt, open(f"{td}/receipts/fixture-shard.json", "w"))
        assert tsv.validate_shards_receipt(receipt, td) == [], \
            tsv.validate_shards_receipt(receipt, td)

        ranges = excluded_token_ranges(
            td, shard_receipt_name="fixture-shard.json",
            assembly_name=prem_names["assembly_receipt"])
        assert ranges == [(1000, total)], ranges

        # tamper a shard byte -> validate_shards_receipt fails -> hard refusal,
        # never a silently-stale range
        with open(f"{td}/shards/v0-00000.bin", "r+b") as fh:
            fh.seek(0)
            fh.write(struct.pack("<H", 9999))
        try:
            excluded_token_ranges(td, shard_receipt_name="fixture-shard.json",
                                  assembly_name=prem_names["assembly_receipt"])
            raise AssertionError("expected ValueError after tampering shard bytes")
        except ValueError as e:
            assert "FAILS validation" in str(e)

        # mismatched assembly pin -> hard refusal
        _write_shard("v0-00000.bin", n0)   # restore
        other_assembly = copy.deepcopy(assembly)
        json.dump(other_assembly, open(f"{td}/receipts/other-assembly.json", "w"))
        try:
            excluded_token_ranges(td, shard_receipt_name="fixture-shard.json",
                                  assembly_name="other-assembly.json")
            raise AssertionError("expected ValueError for a mismatched assembly pin")
        except ValueError as e:
            assert "mismatched pin" in str(e)

        # --- the RULING reader is fail-closed both ways --------------------
        assert ruled_excluded_sources(td) == {"fineweb_edu"}
        # a ruling edit that re-admits an audited-tainted source is refused,
        # never silently honored (the silent-rot direction #1436 is about)
        with open(f"{td}/receipts/rot-ruling.jsonl", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"source": "fineweb_edu",
                                 "provenance_verdict": "CLEAN"}) + "\n")
        try:
            ruled_excluded_sources(td, ruling_name="rot-ruling.jsonl")
            raise AssertionError("expected ValueError for a re-admitting ruling")
        except ValueError as e:
            assert "refusing to re-admit" in str(e)
        # a missing ruling is a refusal, never an empty excluded set
        try:
            ruled_excluded_sources(td, ruling_name="no-such-ruling.jsonl")
            raise AssertionError("expected ValueError for a missing ruling")
        except ValueError as e:
            assert "not on disk" in str(e)
        # a DAMAGED ruling (malformed JSON line) is a refusal, never a
        # partial read -- this branch previously had zero coverage anywhere
        # (independent review of e55446a, finding 1), so a regression could
        # have silently turned "damaged" into "skip the bad line"
        with open(f"{td}/receipts/damaged-ruling.jsonl", "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"source": "fineweb_edu",
                                 "action": "DROP"}) + "\n")
            fh.write("{this line is not JSON\n")
        try:
            ruled_excluded_sources(td, ruling_name="damaged-ruling.jsonl")
            raise AssertionError("expected ValueError for a damaged ruling")
        except ValueError as e:
            assert "damaged ruling" in str(e)
        # a NEW source ruled DROP is picked up with no code change -- the
        # anti-rot property, proven rather than asserted in prose
        with open(f"{td}/receipts/future-ruling.jsonl", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"source": "fineweb_edu", "action": "DROP"}) + "\n")
            fh.write(json.dumps({"source": "wikipedia_en",
                                 "provenance_verdict": "EXCLUDED (future)"}) + "\n")
        assert ruled_excluded_sources(td, ruling_name="future-ruling.jsonl") == \
            {"fineweb_edu", "wikipedia_en"}

        # --- the shared default policy identifies the stream by its length --
        shards_dir = f"{td}/shards"
        glob_name = "token-shards-v0-20260101T000000Z.json"
        json.dump(receipt, open(f"{td}/receipts/{glob_name}", "w"))
        ranges, why = resolve_excluded_ranges_for_stream(shards_dir, total, nc=td)
        assert ranges == [(1000, total)], (ranges, why)
        assert glob_name in why, why
        # a stream whose length matches no receipt keeps the legacy identity
        # geometry (synthetic fixtures/dry-runs never pay for enforcement)
        ranges2, why2 = resolve_excluded_ranges_for_stream(shards_dir, total + 1, nc=td)
        assert ranges2 == [] and "not the receipted v0 corpus" in why2, why2
        # but a matching stream whose bytes have drifted is a HARD refusal --
        # the default can never fall back to unfiltered on the tainted stream
        with open(f"{td}/shards/v0-00000.bin", "r+b") as fh:
            fh.seek(0)
            fh.write(struct.pack("<H", 9999))
        try:
            resolve_excluded_ranges_for_stream(shards_dir, total, nc=td)
            raise AssertionError("expected ValueError once shard bytes drifted")
        except ValueError as e:
            assert "FAILS validation" in str(e)
        _write_shard("v0-00000.bin", n0)   # restore

        # --- gate-side entry point: same ranges, no second sha pass ---------
        g_ranges, g_why = enforcement_for_validated_receipt(
            receipt, nc=td, assembly_name=prem_names["assembly_receipt"])
        assert g_ranges == [(1000, total)], (g_ranges, g_why)
        assert "fineweb_edu" in g_why, g_why

        # an excluded source the ASSEMBLY never listed is genuinely absent
        g_ranges, g_why = enforcement_for_validated_receipt(
            receipt, nc=td, assembly_name=prem_names["assembly_receipt"],
            excluded_sources={"a_source_never_in_this_stream"})
        assert g_ranges == [] and "appears in the assembly" in g_why, g_why

        # DELETING a source's per_source entry must NOT read as "absent" --
        # membership comes from the assembly, so this is a derivation refusal.
        # (fail-OPEN in the first cut of this check: it returned "nothing to
        # exclude" and greened the row.)
        holed = copy.deepcopy(receipt)
        holed["per_source"].pop("fineweb_edu")
        try:
            enforcement_for_validated_receipt(
                holed, nc=td, assembly_name=prem_names["assembly_receipt"])
            raise AssertionError("expected ValueError for a holed per_source")
        except ValueError as e:
            assert "missing/invalid stream_tokens" in str(e)

        # an excluded source present but carrying ZERO tokens excludes nothing,
        # and says so rather than reporting a degenerate empty range
        zeroed = copy.deepcopy(receipt)
        zeroed["per_source"]["code_github_clean"]["stream_tokens"] = total
        zeroed["per_source"]["fineweb_edu"]["stream_tokens"] = 0
        g_ranges, g_why = enforcement_for_validated_receipt(
            zeroed, nc=td, assembly_name=prem_names["assembly_receipt"])
        assert g_ranges == [] and "zero tokens" in g_why, g_why

    print("FINEWEB_EXCLUSION_FAIL_CLOSED_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="PRODUCTION read-only: validate the real receipt "
                         "against the real shard bytes and emit a "
                         f"{EXCLUSION_TICKET} receipt")
    ap.add_argument("--shard-dir", default=None,
                    help="override the shard receipt's own shard_dir (e.g. "
                         "an out-of-tree ember-data path)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        _selftest_fail_closed_against_real_schema()
        return
    if a.preflight:
        from receipt_write import checked_write        # noqa: E402
        receipt = run_preflight(shard_dir=a.shard_dir)
        out = f"{NC}/receipts/fineweb-edu-exclusion-preflight-{receipt['ts']}.json"
        checked_write(out, receipt)
        print(f"FINEWEB_EDU_EXCLUSION_PREFLIGHT_DONE "
              f"{os.path.relpath(out, NC)} "
              f"({receipt['n_windows_enforced']:,}/"
              f"{receipt['n_windows_unenforced']:,} windows usable)")
        return
    print("FINEWEB_EXCLUSION_STAGED — pass --selftest or --preflight "
         "--shard-dir <real shards path>")


if __name__ == "__main__":
    main()

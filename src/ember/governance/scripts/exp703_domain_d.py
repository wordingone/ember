#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
#703 PPM apparatus, stage 1 -- domain-D restriction machinery.

Implements AMENDMENT-1 to the frozen prereg (issue #703 comment
4942559293, dated 2026-07-11, "adopts external falsifier
BLOCK_703_FULL_BYTE_EVENT_PARTITION"):

  Defect: the exact 2c557 tokenizer (normalizer=null, ByteLevel
  pre_tokenizer use_regex=true, byte_fallback=false, unk_token=null,
  decoder=null) consumes Unicode str/UTF-8 only through its encode()
  interface: raw bytes 128-255 are not standalone-encodable, and 0x00 is
  silently dropped. So "every byte string tokenizes" (frozen v3 P1(c)) is
  FALSE on the raw 256+EOT alphabet -- seg(.) is undefined/non-injective
  on positive PPM mass and token events do not partition the measure.

  Cure adopted -- route B (domain restriction + renormalization), NOT a
  raw-byte adapter:
    1. Event space redefined over D := valid-UTF-8 byte strings containing
       no NUL (0x00), with EOT adjoined as the end-of-document symbol.
    2. PPM measure renormalized to prefix(D): at every context, P_ppm
       conditionals renormalize over exactly the next-byte continuations
       that keep the prefix inside prefix(D) -- bytes that cannot extend a
       valid UTF-8 prefix are excluded from the support, 0x00 is excluded
       everywhere, EOT allowed only where D permits document end. The
       order -1 base distribution inherits the same restriction (it is
       already folded into next_byte_probs() before renormalization here,
       so no special-casing is needed).
    3. New mandatory P0 measurement (pre-P1): NUL and invalid-UTF-8
       incidence, with per-cause counts, exclusion never silent.
    5. P1/P2 toy-lattice machinery is UNAFFECTED (toy tokenizers are fully
       specified constructions over small synthetic alphabets, not real
       UTF-8 bytes) -- the marginalization theorem's precondition set
       gains "frontier restricted to prefix(D)-closure" instead. This
       module demonstrates that precondition is satisfied purely by
       COMPOSITION: `RestrictedPpmModel` implements the exact same
       next_byte_probs()/prefix_probability() interface as PpmModel /
       FixedFixtureModel, so exp703_marginalization.py's
       cylinder_mass_ground_truth / cylinder_mass_bounded_lookahead /
       p_ppm_tok need ZERO code changes to respect the D-restriction --
       they already only explore branches with positive next_byte_probs()
       mass, and a D-restricted model simply reports zero mass for
       NUL/invalid-UTF-8 continuations. See exp703_selftest.py's
       run_p0_domain_incidence for the integration proof.

AMENDMENT-1a + the branch-b disposition (issue #703, tightened same day):
  The P0 incidence census cannot run on token shards or detokenized IDs
  (the tokenizer is non-injective on the excluded causes: NUL is erased
  pre-shard, invalid UTF-8 can never enter the interface -- a
  post-tokenization scan reports zero BY CONSTRUCTION, not by measurement).
  Branch rule: P0(a) if exact raw pre-tokenizer document bytes with
  source/document-boundary + SHA custody exist -- census those bytes before
  any decode/encode; else P0(b) -- declare original incidence UNMEASURABLE
  and narrow D/Claim A to the token-reconstructed document process, no
  zero-incidence claim of any kind. Branch (b) is CANONICAL for this repo
  checkout (receipts/token-shards-v0-20260611T170047Z.json's own
  provenance_230 disclosure: "the real shard bytes ... are NOT re-derivable
  here (no raw corpus/shard data in this checkout)"; and
  receipts/eng36-assembly-20260611T052337Z.json preserves only source
  revision pins (url_pin.revision_sha) + manifest hashes (manifest_sha256),
  never raw bytes). `p0_branch_b_citation()` below reads BOTH receipts LIVE
  from disk and asserts they still say what this module claims, rather than
  hardcoding a quote that could go stale.
"""

from __future__ import annotations

import json
import os


# ---------------------------------------------------------------------------
# UTF-8 prefix validity -- leverages CPython's own RFC-3629-compliant UTF-8
# codec (via bytes.decode) rather than a hand-rolled byte-range table, so
# overlong encodings / surrogate-range rejection / the U+10FFFF ceiling are
# all inherited correctly instead of re-derived (and possibly re-broken).
# ---------------------------------------------------------------------------
def is_valid_utf8_prefix(b: bytes) -> bool:
    """True if `b` either decodes as complete valid UTF-8, or is a
    genuinely truncated (not malformed) prefix of a longer valid sequence
    -- i.e. could still become valid UTF-8 with more bytes appended."""
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        return e.end == len(b) and e.reason == "unexpected end of data"


def at_utf8_boundary(b: bytes) -> bool:
    """True if `b` decodes as COMPLETE valid UTF-8 (no pending multi-byte
    sequence) -- i.e. a document may legally end right here."""
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def allowed_next_bytes(recent_context: bytes, eot_symbol: int) -> set:
    """DEPRECATED (issue #703 PR #759 coordinator gate blocker 3, UTF-8
    repair defect, marker PPM703_UTF8_FOUR_BYTE_BOUNDARY_COUNTEREXAMPLE_PASS):
    kept only so any external caller still importing this name gets a loud
    failure pointer, not silent wrong answers. `recent_context` (a raw
    trailing-byte SUFFIX of the real history) cannot in general be decoded
    STANDALONE: after a completed 4-byte codepoint (e.g. f0 9f 98 80), the
    last 3 bytes are bare continuation bytes with no lead byte in view, so
    this function misreads a FRESH boundary as a dead mid-sequence state and
    reports an empty allowed set -- `restricted_next_byte_probs` below no
    longer calls this; it uses `utf8_dfa_state_from_history`, which walks
    the ENTIRE context from a known start state instead of guessing from a
    raw suffix. Retained as an explicit trap, not removed silently."""
    raise NotImplementedError(
        "allowed_next_bytes(recent_context, ...) is retired: a raw trailing-byte "
        "suffix cannot be decoded standalone (see PPM703_UTF8_FOUR_BYTE_BOUNDARY_"
        "COUNTEREXAMPLE_PASS). Use utf8_dfa_state_from_history(full_context, ...) "
        "+ allowed_next_bytes_from_state(state, ...) instead.")


# ---------------------------------------------------------------------------
# Explicit UTF-8 DFA (RFC 3629) -- carries state derived from the FULL byte
# history, never reconstructed by decoding an arbitrary trailing suffix.
#
# A state is (bytes_remaining, lo, hi):
#   bytes_remaining == 0  -> READY: a document may end here (EOT allowed),
#     and any valid LEAD byte (ASCII or a multi-byte lead) may start next.
#     lo/hi are unused (canonically 0, 0).
#   bytes_remaining >= 1  -> mid-sequence: the NEXT byte must lie in
#     [lo, hi] (a continuation byte, restricted range for exactly the FIRST
#     continuation after certain lead bytes -- this is what bans overlong
#     encodings, the UTF-16 surrogate range, and code points > U+10FFFF by
#     construction, matching CPython's own strict UTF-8 codec exactly).
#     EOT is never allowed mid-sequence.
# ---------------------------------------------------------------------------
UTF8_READY = (0, 0, 0)

# Lead-byte -> (bytes_remaining_after_lead, lo, hi) for the first continuation
# byte, or None if the lead byte itself is never valid (bare continuation
# byte 0x80-0xBF with no preceding lead, the two overlong 2-byte lead bytes
# 0xC0-0xC1, or 0xF5-0xFF which would exceed U+10FFFF or are reserved).
def _lead_transition(b: int):
    if 0x00 <= b <= 0x7F:
        return UTF8_READY  # 1-byte ASCII, immediately complete
    if 0xC2 <= b <= 0xDF:
        return (1, 0x80, 0xBF)
    if b == 0xE0:
        return (2, 0xA0, 0xBF)  # first continuation restricted: bans overlong 3-byte
    if 0xE1 <= b <= 0xEC:
        return (2, 0x80, 0xBF)
    if b == 0xED:
        return (2, 0x80, 0x9F)  # first continuation restricted: bans surrogate range
    if 0xEE <= b <= 0xEF:
        return (2, 0x80, 0xBF)
    if b == 0xF0:
        return (3, 0x90, 0xBF)  # first continuation restricted: bans overlong 4-byte
    if 0xF1 <= b <= 0xF3:
        return (3, 0x80, 0xBF)
    if b == 0xF4:
        return (3, 0x80, 0x8F)  # first continuation restricted: bans code points > U+10FFFF
    return None  # 0x80-0xBF (bare continuation), 0xC0-0xC1 (overlong), 0xF5-0xFF (invalid)


def utf8_dfa_step(state: tuple, b: int):
    """One incremental DFA transition: `state` + next byte `b` -> new state,
    or None if `b` is not a valid continuation of `state` (REJECT). Pure
    function of (state, byte) -- never looks at any other history, so a
    caller CAN thread it forward one byte at a time (the mechanism the
    coordinator's preferred cure names: 'carry an explicit UTF-8 DFA state
    alongside the PPM context')."""
    bytes_remaining, lo, hi = state
    if bytes_remaining == 0:
        return _lead_transition(b)
    if not (lo <= b <= hi):
        return None
    remaining = bytes_remaining - 1
    if remaining == 0:
        return UTF8_READY
    return (remaining, 0x80, 0xBF)  # only the FIRST continuation byte is range-restricted


def utf8_dfa_state_from_history(context: tuple, eot_symbol: int) -> tuple:
    """Derive the CURRENT DFA state by simulating the DFA over the ENTIRE
    `context` from a known start state (UTF8_READY), resetting to
    UTF8_READY on EOT (a document boundary) -- never by decoding a raw
    trailing suffix standalone (the retired `allowed_next_bytes` defect:
    the last 3 bytes of a JUST-COMPLETED 4-byte codepoint are bare
    continuation bytes with no lead byte in view, and cannot be correctly
    interpreted without the lead byte that came before them). This is a
    full re-simulation, not a guess -- every byte in `context` was itself
    only ever accepted because it was in the allowed set THIS module
    computed for the state before it (domain-D is closed under its own
    restriction), so the walk can never hit a REJECT transition for a
    genuine PPM-generated context; a REJECT here means a caller passed a
    context this module never sanctioned, which is a defect worth an
    assertion, not a silent wrong answer."""
    state = UTF8_READY
    for b in context:
        if b == eot_symbol:
            state = UTF8_READY
            continue
        new_state = utf8_dfa_step(state, b)
        assert new_state is not None, (
            f"utf8_dfa_state_from_history: byte {b:#04x} is not a valid UTF-8 "
            f"continuation of state {state} -- context {context!r} was never "
            f"domain-D-valid (defect in the caller, not this DFA)")
        state = new_state
    return state


def allowed_next_bytes_from_state(state: tuple, eot_symbol: int) -> set:
    """The prefix(D) support given an EXPLICIT DFA state: every byte value
    with a defined `utf8_dfa_step(state, b)` transition, restricted further
    to exclude NUL (0x00) always (domain D bans NUL structurally, on top of
    plain UTF-8 validity -- U+0000 is otherwise a legal 1-byte code point),
    plus EOT iff `state == UTF8_READY` (a document may legally end only at
    a completed code-point boundary)."""
    bytes_remaining, lo, hi = state
    if bytes_remaining == 0:
        allowed = {b for b in range(1, 256) if _lead_transition(b) is not None}
        allowed.add(eot_symbol)
        return allowed
    return {b for b in range(lo, hi + 1)}  # continuation range is always >= 0x80, NUL excluded


def restricted_next_byte_probs(model, context: tuple, eot_symbol: int) -> dict:
    """The AMENDMENT-1 section-2 renormalization: raw = model's own
    next_byte_probs(context) (which already folds in the order -1 uniform
    floor, so that floor inherits the restriction automatically); restrict
    to the prefix(D) support -- derived via an EXPLICIT UTF-8 DFA state
    walked from the full `context` (issue #703 PR #759 coordinator gate
    blocker 3 UTF-8 repair defect, PPM703_UTF8_FOUR_BYTE_BOUNDARY_
    COUNTEREXAMPLE_PASS: the retired raw-suffix heuristic misread a
    completed 4-byte codepoint's tail as a dead mid-sequence state) -- and
    renormalize to sum to 1. `context` here is the model's own full
    since-EOT/document-start history (see PpmModel.next_byte_probs'
    docstring); the DFA state derivation is therefore correct regardless of
    the underlying model's OWN order_cap truncation (the wrapper's history
    is independent of the base model's internal trie-lookup truncation --
    'DFA state survives PPM order-cap truncation')."""
    raw = model.next_byte_probs(context)
    state = utf8_dfa_state_from_history(context, eot_symbol)
    allowed = allowed_next_bytes_from_state(state, eot_symbol)
    allowed.discard(0)  # NUL always excluded, even from a READY state's ASCII-lead range
    restricted = {s: p for s, p in raw.items() if s in allowed and p > 0}
    total = sum(restricted.values())
    if total <= 0.0:
        raise ZeroDivisionError(
            f"restricted_next_byte_probs: prefix(D) support has zero PPM mass "
            f"at DFA state {state} (context={context!r}) -- model assigns zero "
            f"probability to every D-valid continuation")
    return {s: p / total for s, p in restricted.items()}


class RestrictedPpmModel:
    """Drop-in next_byte_probs()/prefix_probability() wrapper around any
    base model (PpmModel or FixedFixtureModel) that applies the prefix(D)
    restriction + renormalization at every step. Passing an instance of
    this class as the `model` argument to exp703_marginalization's
    cylinder_mass_ground_truth / cylinder_mass_bounded_lookahead / p_ppm_tok
    is the ENTIRE mechanism by which "frontier restricted to
    prefix(D)-closure" is satisfied -- those functions are unmodified."""

    def __init__(self, base_model, eot_symbol: int):
        self.base_model = base_model
        self.eot_symbol = eot_symbol
        self.alphabet_size = base_model.alphabet_size

    def next_byte_probs(self, context: tuple) -> dict:
        return restricted_next_byte_probs(self.base_model, context, self.eot_symbol)

    def prefix_probability(self, byte_seq, reset_on_eot: bool = True) -> float:
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
                context = context + (b,)
        return prob


# ---------------------------------------------------------------------------
# P0 census (branch b: token-reconstructed-domain incidence only; original
# pre-tokenization-byte incidence is UNMEASURABLE in this checkout).
# ---------------------------------------------------------------------------
def document_domain_census(documents: list) -> dict:
    """Per-document domain census over a list of byte-string documents:
    counts documents containing NUL, documents that are not valid complete
    UTF-8, and the union (excluded from D). This is the counting apparatus
    itself -- exercised on a synthetic positive-control corpus in
    exp703_selftest.py (planted NUL / planted invalid-UTF-8 / clean docs),
    since no real corpus is in scope for this apparatus-only PR (no eval
    pass) and, per the branch-b disposition, original pre-tokenization
    bytes are unavailable in this checkout regardless."""
    n_docs = len(documents)
    nul_count = 0
    invalid_utf8_count = 0
    excluded_count = 0
    for doc in documents:
        has_nul = 0 in doc
        is_valid = at_utf8_boundary(doc)
        if has_nul:
            nul_count += 1
        if not is_valid:
            invalid_utf8_count += 1
        if has_nul or not is_valid:
            excluded_count += 1
    return {
        "n_docs": n_docs,
        "nul_count": nul_count,
        "invalid_utf8_count": invalid_utf8_count,
        "excluded_count": excluded_count,
    }


def p0_branch_b_citation(repo_root: str) -> dict:
    """Reads the two disposition receipts LIVE from disk (never a
    hardcoded quote) and asserts they still support the branch-b
    disposition; raises if either file is missing or no longer says what
    this module claims -- a stale citation is a defect, not a detail."""
    shards_path = os.path.join(repo_root, "receipts", "token-shards-v0-20260611T170047Z.json")
    assembly_path = os.path.join(repo_root, "receipts", "eng36-assembly-20260611T052337Z.json")

    with open(shards_path, "r", encoding="utf-8") as f:
        shards_receipt = json.load(f)
    reason = shards_receipt["provenance_230"][0]["reason"]
    assert "NOT re-derivable" in reason or "no raw corpus/shard data in this checkout" in reason, \
        f"{shards_path}: provenance_230 reason no longer supports branch-b (stale citation): {reason!r}"

    with open(assembly_path, "r", encoding="utf-8") as f:
        assembly_receipt = json.load(f)
    sources = assembly_receipt["sources"]
    # Each source must carry a manifest_sha256 AND a url_pin whose own
    # identity is asserted by SOME sha-shaped pin field -- remote HF
    # datasets pin via url_pin.revision_sha; the local-ledger source
    # (ledger_mit) pins via url_pin.ledger_sha256 instead (no upstream git
    # revision exists for a local read-only ledger) -- both are
    # manifest-hash/revision-pin evidence, never raw bytes, so both satisfy
    # the branch-b disposition; only a field carrying an actual byte payload
    # would violate it (checked separately below).
    def _has_sha_pin(url_pin: dict) -> bool:
        return any(k.endswith("_sha") or k.endswith("sha256") for k in url_pin)

    assert sources and all("manifest_sha256" in s and "url_pin" in s and _has_sha_pin(s["url_pin"])
                            for s in sources), \
        f"{assembly_path}: sources[] no longer carries manifest_sha256 + a sha-pinned " \
        f"url_pin for every source (stale citation)"
    assert not any("raw" in k.lower() and "bytes" not in k.lower() for s in sources for k in s), \
        f"{assembly_path}: sources[] gained a field suggesting raw byte custody -- re-verify branch"

    return {
        "branch": "b",
        "citations": [
            {"path": "receipts/token-shards-v0-20260611T170047Z.json",
             "field": "provenance_230[0].reason",
             "quote": reason},
            {"path": "receipts/eng36-assembly-20260611T052337Z.json",
             "field": "sources[].manifest_sha256 + sources[].url_pin.{revision_sha|ledger_sha256}",
             "quote": f"{len(sources)} sources, each carries a manifest_sha256 and a "
                      f"sha-pinned url_pin (source revision/ledger pin + manifest hash) -- "
                      f"no raw byte payload field present"},
        ],
        "declaration": "original pre-tokenization-byte NUL/invalid-UTF-8 incidence is "
                        "UNMEASURABLE in this checkout; D and Claim A are narrowed to the "
                        "token-reconstructed document process; no zero-incidence claim made.",
    }

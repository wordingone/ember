#!/usr/bin/env python3
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
    """The prefix(D) support at this point: every raw byte value 1-255
    (0x00/NUL always excluded) that keeps `recent_context + [byte]` a
    valid UTF-8 prefix, plus EOT iff `recent_context` is already at a
    UTF-8 character boundary. `recent_context` only needs the trailing
    <=3 raw bytes (UTF-8 sequences are at most 4 bytes, RFC 3629), so
    callers may safely pass a short suffix rather than the full history."""
    allowed = {b for b in range(1, 256) if is_valid_utf8_prefix(recent_context + bytes([b]))}
    if at_utf8_boundary(recent_context):
        allowed.add(eot_symbol)
    return allowed


def restricted_next_byte_probs(model, context: tuple, eot_symbol: int) -> dict:
    """The AMENDMENT-1 section-2 renormalization: raw = model's own
    next_byte_probs(context) (which already folds in the order -1 uniform
    floor, so that floor inherits the restriction automatically); restrict
    to the prefix(D) support and renormalize to sum to 1."""
    raw = model.next_byte_probs(context)
    recent = bytes(b for b in context[-3:] if b != eot_symbol)
    allowed = allowed_next_bytes(recent, eot_symbol)
    restricted = {s: p for s, p in raw.items() if s in allowed and p > 0}
    total = sum(restricted.values())
    if total <= 0.0:
        raise ZeroDivisionError(
            f"restricted_next_byte_probs: prefix(D) support has zero PPM mass "
            f"at context tail {recent!r} -- model assigns zero probability to "
            f"every D-valid continuation")
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

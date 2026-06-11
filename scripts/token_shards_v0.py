"""token_shards_v0.py — TOKEN-SHARDS-V0 receipt contract + fail-closed validator.

The v0 owned-core pretrain trains on flat uint16 packed shards produced from
the frozen v0 corpus with the frozen tokenizer (timeshare_pretrain.py's
PackedShardLoader reads `*.bin` shards as one stream). The launch chain must
refuse `--live` unless those shards exist and a TOKEN-SHARDS-V0 receipt proves
they are the contracted bytes. Before this module the launch gate had NO row
checking shards — it printed "dispatch permitted" with zero `.bin` on disk
(fail-open w.r.t. the training input, same class as eng-46/eng-48).

This module owns the gate-side half (eng-49 / #183):

  * the TOKEN-SHARDS-V0 receipt schema (what a shard-production run must emit);
  * `validate_shards_receipt(d, nc)` — fail-closed: every pinned premise must
    exist + receipt_check PASS + sha-match; the frozen tokenizer.json must
    sha-match; every declared shard file must exist and its on-disk sha256 +
    byte-derived token count must match the receipt; per-source / total /
    separator / reserved-band / loader-window numbers must be internally
    consistent and re-derivable from the bytes. Any miss is a violation.

The PRODUCTION WRITER (corpus zstd -> frozen tokenizer -> uint16 `.bin`
shards + this receipt) is the eng-50 half below (`produce_shards_v0`); its
`--emit` run is governed by the Step-1 chain (HOLD lifted 2026-06-11, Leo
14620). `--census` is the read-only diagnostic that sizes the text-borne
special-literal deviation (Leo 14628).
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_check import validate_receipt          # noqa: E402

# ---- frozen v0 shard contract (mirrors configs/v0-pretrain-config.json + the
#      tokenizer-freeze receipt; changing any of these is a contract change) --
SEQ = 1024
N_MTP = 2
BLOCK_LEN = SEQ + 1 + N_MTP            # 1027 — PackedShardLoader window length
BYTES_PER_TOKEN = 2                    # uint16 ("<u2"); vocab 32000 < 65536
VOCAB_SIZE = 32000
SEPARATOR_ID = 0                       # <|endoftext|> — appended between docs
RESERVED_IDS = [1, 2, 3, 4, 5, 6, 7]   # multimodal band; never from source text
EXPECTED_SOURCES = {
    "code_github_clean", "fineweb_edu", "gutenberg_en",
    "ledger_mit", "wikipedia_en",
}
SHA_CONVENTION = ("sha256 over the exact on-disk file bytes, no normalization; "
                  "shard + receipt paths carry the git -text pin")

TICKET = "TOKEN-SHARDS-V0"

# ---- producer pins (eng-50 #185): the frozen inputs the writer reads ------
ASSEMBLY_RECEIPT = "eng36-assembly-20260611T052337Z.json"
TOKENIZER_FREEZE_RECEIPT = "tokenizer-freeze-20260611T154111Z.json"
SHARD_DIR = "shards"                       # nc-relative output dir for .bin
SHARD_TOKEN_CAP = 256 * 1024 * 1024        # 256Mi tokens/shard (~512 MiB uint16)
DOC_TEXT_FIELD = "text"                     # corpus JSONL doc content field


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _check_premise(nc, key, sub, out):
    """A pinned premise receipt: must exist, receipt_check PASS, sha-match."""
    if not isinstance(sub, dict):
        out.append(f"premise {key} not a dict")
        return
    name, sha = sub.get("name"), sub.get("sha256")
    if not name or not sha:
        out.append(f"premise {key} missing name/sha256")
        return
    p = f"{nc}/receipts/{name}"
    if not os.path.exists(p):
        out.append(f"premise {key}: {name} not on disk")
        return
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:              # noqa: BLE001
        out.append(f"premise {key}: unreadable {e}")
        return
    f = validate_receipt(d)
    if f:
        out.append(f"premise {key}: receipt_check FAIL {f}")
    if _sha(p) != sha:
        out.append(f"premise {key}: sha drift {_sha(p)[:12]} != {sha[:12]}")


def _scan_uint16_shard(path):
    """Re-derive reserved-band / range / parity facts from the ACTUAL shard
    bytes — never trust the receipt's declared reserved_ids_observed_in_stream
    (eng-53 #192: that field was a self-report; a shard could declare 0 while
    its bytes carried reserved ids).

    A shard is a flat little-endian uint16 stream. Returns
    (odd_bytes, reserved_count, oob_count):
      odd_bytes      - byte length is not a multiple of 2 (not a uint16 stream);
                       getsize//2 would silently floor the dangling byte.
      reserved_count - count of ids in the reserved multimodal band 1..7
                       (id 0 is the legitimate doc separator; allowed).
      oob_count      - count of ids >= VOCAB_SIZE (out of vocab).
    numpy-vectorized (zero-copy frombuffer); runs once at gate time over the
    packed shards, so a multi-GB scan stays sub-second per shard after I/O.
    """
    import numpy as np
    with open(path, "rb") as fh:
        raw = fh.read()
    odd = (len(raw) % BYTES_PER_TOKEN) != 0
    n = len(raw) // BYTES_PER_TOKEN
    arr = np.frombuffer(raw[:n * BYTES_PER_TOKEN], dtype="<u2")
    lo, hi = RESERVED_IDS[0], RESERVED_IDS[-1]      # 1..7
    reserved = int(np.count_nonzero((arr >= lo) & (arr <= hi)))
    oob = int(np.count_nonzero(arr >= VOCAB_SIZE))
    return odd, reserved, oob


def validate_shards_receipt(d, nc=NC):
    """Return a list of violations (empty = the shard contract holds).

    Fail-closed in the fp26_prereg.check_premises grammar: a receipt is valid
    only if the bytes it describes are present and match. Numbers are
    re-derived from the on-disk shard bytes, not trusted as declared.
    """
    v = []
    if d.get("ticket") != TICKET:
        v.append(f"ticket {d.get('ticket')!r} != {TICKET!r}")
    # schema floor (ticket/ts/sha_convention/int-count rules)
    for f in validate_receipt(d):
        v.append(f"receipt_check: {f}")

    # pinned premises: assembly + tokenizer-freeze receipts
    prem = d.get("premises") or {}
    _check_premise(nc, "assembly_receipt", prem.get("assembly_receipt"), v)
    _check_premise(nc, "tokenizer_freeze_receipt",
                   prem.get("tokenizer_freeze_receipt"), v)
    # frozen tokenizer.json sha pin
    tj = prem.get("tokenizer_json") or {}
    tpath, tsha = tj.get("path"), tj.get("sha256")
    if not tpath or not tsha:
        v.append("premise tokenizer_json missing path/sha256")
    else:
        fp = f"{nc}/{tpath}"
        if not os.path.exists(fp):
            v.append(f"tokenizer_json {tpath} not on disk")
        elif _sha(fp) != tsha:
            v.append(f"tokenizer_json sha drift {_sha(fp)[:12]} != {tsha[:12]}")

    # shards: each declared file present + sha-match + byte-derived count match
    shard_dir = d.get("shard_dir")
    shards = d.get("shards")
    derived_total = 0
    scanned_reserved = 0          # reserved ids 1..7 re-derived from shard bytes
    shards_ok = isinstance(shards, list) and shards and isinstance(shard_dir, str)
    if not shards_ok:
        v.append("shard_dir/shards missing or empty")
    else:
        for i, s in enumerate(shards):
            if not isinstance(s, dict):
                v.append(f"shard[{i}] not a dict")
                continue
            name, sha, nt = s.get("name"), s.get("sha256"), s.get("n_tokens")
            if not name or not sha:
                v.append(f"shard[{i}] missing name/sha256")
                continue
            if not isinstance(nt, int):
                v.append(f"shard[{i}] {name} n_tokens not int")
                continue
            if not str(name).endswith(".bin"):
                v.append(f"shard[{i}] {name} is not a .bin shard")
            fp = f"{nc}/{shard_dir}/{name}"
            if not os.path.exists(fp):
                v.append(f"shard[{i}] {name} not on disk")
                continue
            if _sha(fp) != sha:
                v.append(f"shard[{i}] {name} sha drift {_sha(fp)[:12]} != "
                         f"{sha[:12]}")
            disk_nt = os.path.getsize(fp) // BYTES_PER_TOKEN
            if disk_nt != nt:
                v.append(f"shard[{i}] {name} n_tokens {nt} != bytes/2 {disk_nt}")
            # byte-true scan: re-derive reserved/oob/parity from the bytes, do
            # NOT trust the declared reserved_ids_observed_in_stream (eng-53).
            odd, res_n, oob_n = _scan_uint16_shard(fp)
            if odd:
                v.append(f"shard[{i}] {name} odd byte length "
                         f"{os.path.getsize(fp)} (not a uint16 stream)")
            if res_n:
                v.append(f"shard[{i}] {name} {res_n} reserved-band id(s) "
                         "(1..7) present in stream bytes")
            if oob_n:
                v.append(f"shard[{i}] {name} {oob_n} id(s) >= {VOCAB_SIZE} "
                         "present in stream bytes")
            scanned_reserved += res_n
            derived_total += nt

    # total stream tokens == sum of shard token counts, and a loadable stream
    tst = d.get("total_stream_tokens")
    if not isinstance(tst, int):
        v.append("total_stream_tokens not int")
    elif shards_ok and tst != derived_total:
        v.append(f"total_stream_tokens {tst} != sum(shard n_tokens) "
                 f"{derived_total}")
    if shards_ok and derived_total < BLOCK_LEN:
        v.append(f"stream {derived_total} tokens < block_len {BLOCK_LEN} "
                 "(loader would raise; no full window)")

    # per-source content/separator/stream token counts, summing to the total
    ps = d.get("per_source") or {}
    if set(ps) != EXPECTED_SOURCES:
        v.append(f"per_source sources {sorted(ps)} != "
                 f"{sorted(EXPECTED_SOURCES)}")
    else:
        ssum = 0
        for src, c in ps.items():
            if not isinstance(c, dict):
                v.append(f"per_source[{src}] not a dict")
                continue
            for fld in ("content_tokens", "separator_tokens", "stream_tokens"):
                if not isinstance(c.get(fld), int):
                    v.append(f"per_source[{src}].{fld} not int")
            if isinstance(c.get("content_tokens"), int) and \
               isinstance(c.get("separator_tokens"), int) and \
               isinstance(c.get("stream_tokens"), int) and \
               c["content_tokens"] + c["separator_tokens"] != c["stream_tokens"]:
                v.append(f"per_source[{src}] content+separator != stream")
            if isinstance(c.get("stream_tokens"), int):
                ssum += c["stream_tokens"]
        if isinstance(tst, int) and ssum != tst:
            v.append(f"sum(per_source stream_tokens) {ssum} != "
                     f"total_stream_tokens {tst}")

    # separator id + reserved-band guard
    if d.get("separator_id") != SEPARATOR_ID:
        v.append(f"separator_id {d.get('separator_id')!r} != {SEPARATOR_ID}")
    g = d.get("reserved_band_guard") or {}
    if g.get("reserved_ids") != RESERVED_IDS:
        v.append(f"reserved_band_guard.reserved_ids != {RESERVED_IDS}")
    if g.get("max_id_lt") != VOCAB_SIZE:
        v.append(f"reserved_band_guard.max_id_lt != {VOCAB_SIZE}")
    if g.get("reserved_ids_observed_in_stream") != 0:
        v.append("reserved_band_guard.reserved_ids_observed_in_stream != 0 "
                 "(multimodal ids 1..7 must never appear from source text)")
    # cross-check the declared field against the byte-true scan: a receipt that
    # declares 0 while its shard bytes carry reserved ids must FAIL (eng-53).
    if shards_ok and isinstance(g.get("reserved_ids_observed_in_stream"), int) \
       and g["reserved_ids_observed_in_stream"] != scanned_reserved:
        v.append("reserved_band_guard.reserved_ids_observed_in_stream "
                 f"{g['reserved_ids_observed_in_stream']} != byte-scanned "
                 f"{scanned_reserved}")

    # loader window math, re-derived from the byte-true token total
    lw = d.get("loader_windows") or {}
    if lw.get("seq") != SEQ:
        v.append(f"loader_windows.seq != {SEQ}")
    if lw.get("n_mtp") != N_MTP:
        v.append(f"loader_windows.n_mtp != {N_MTP}")
    if lw.get("block_len") != BLOCK_LEN:
        v.append(f"loader_windows.block_len != {BLOCK_LEN}")
    nw = lw.get("n_windows")
    if not isinstance(nw, int) or nw <= 0:
        v.append("loader_windows.n_windows not a positive int")
    elif shards_ok and derived_total >= BLOCK_LEN:
        exp = (derived_total - BLOCK_LEN) // SEQ + 1
        if nw != exp:
            v.append(f"loader_windows.n_windows {nw} != re-derived {exp} "
                     f"((total-{BLOCK_LEN})//{SEQ}+1)")
    return v


# ---------------------------------------------------------------------------
# Production writer (eng-50 #185). build-now; the --emit run against the real
# corpus is HELD pending the shard-production call. emit=False is a dry count
# (no files written); emit=True writes the uint16 shards + a receipt that
# passes validate_shards_receipt above.
# ---------------------------------------------------------------------------
def _utc_ts():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def _load_pinned(nc, name):
    """Load + receipt_check a pinned input receipt; return (sha256, dict).
    Fail-closed: raises on miss or receipt_check failure."""
    p = f"{nc}/receipts/{name}"
    if not os.path.exists(p):
        raise FileNotFoundError(f"pinned receipt missing: {name}")
    d = json.load(open(p, encoding="utf-8"))
    f = validate_receipt(d)
    if f:
        raise ValueError(f"pinned receipt {name} fails receipt_check: {f}")
    return _sha(p), d


def _iter_docs(path):
    """Yield each document's text from a .jsonl.zst (or plain .jsonl) shard."""
    import io
    with open(path, "rb") as fh:
        if str(path).endswith(".zst"):
            import zstandard
            reader = zstandard.ZstdDecompressor().stream_reader(fh)
            stream = io.TextIOWrapper(reader, encoding="utf-8")
        else:
            stream = io.TextIOWrapper(fh, encoding="utf-8")
        for line in stream:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            t = doc.get(DOC_TEXT_FIELD)
            if t is None:
                raise ValueError(f"{path}: doc missing {DOC_TEXT_FIELD!r}")
            yield t


def _resolve_sources(nc, assembly):
    """From the assembly receipt -> ordered [(source, [shard paths])] in fp22
    stream order. Each per-source manifest is sha-pinned by the assembly; each
    corpus shard is sha-verified against its manifest before it is read
    (fail-closed input integrity). Only exercised on the --emit production run."""
    rows = sorted(assembly.get("sources", []),
                  key=lambda s: s.get("fp22_row", 1 << 30))
    out = []
    for s in rows:
        src = s["source"]
        man_path = f"{nc}/{s['manifest_mirror'].replace(chr(92), '/')}"
        if _sha(man_path) != s["manifest_sha256"]:
            raise ValueError(f"{src}: manifest sha drift {man_path}")
        man = json.load(open(man_path, encoding="utf-8"))
        base = (man.get("out_dir_windows") or "").replace(chr(92), "/")
        paths = []
        for sh in man.get("shards", []):
            fp = f"{base}/{sh['file']}"
            if not os.path.exists(fp):              # fall back to nc-sibling layout
                fp = f"{nc}/../corpus-v0/{src}/{sh['file']}"
            if _sha(fp) != sh["sha256"]:
                raise ValueError(f"{src}/{sh['file']}: corpus shard sha drift")
            paths.append(fp)
        out.append((src, paths))
    return out


ENCODE_BATCH_DOCS = 512                    # mirror tokenizer_freeze.count_tokens
ENCODE_BATCH_BYTES = 32_000_000            # bounded by docs AND chars

ENCODE_SEMANTICS = (
    "added-token-matching-disabled-v1: production encoding loads the frozen "
    "tokenizer.json (on-disk bytes sha-pinned, unchanged) with its "
    "added_tokens table stripped IN MEMORY, so special literals occurring in "
    "source text tokenize as ordinary byte-level pieces; ids 0..7 are "
    "unreachable from text by construction (band tokens are absent from the "
    "BPE merges) and every literal is probe-encoded at build to prove it. "
    "Doc-boundary separator id 0 is writer-inserted only. (Leo 14628: the "
    "band contract is supreme; the counting instrument aligns to it.)")


def _production_tokenizer(nc, tokfreeze, match_added_tokens):
    """Load the sha-pinned frozen tokenizer for corpus encoding.

    match_added_tokens=False is the PRODUCTION semantics (ENCODE_SEMANTICS):
    the added_tokens table is stripped in memory and each special literal is
    probe-encoded to prove no id < 8 can originate from text.
    match_added_tokens=True is the legacy/diagnostic semantics (census): the
    tokenizer as-frozen, where added-token literals in raw text match to
    their reserved ids — exactly the deviation being measured."""
    tok_json_rel = (tokfreeze.get("tokenizer_repo_path")
                    or "tokenizer/tokenizer.json").replace(chr(92), "/")
    tok_json_sha = tokfreeze.get("tokenizer_json_sha256")
    tok_json_path = f"{nc}/{tok_json_rel}"
    if not os.path.exists(tok_json_path) or _sha(tok_json_path) != tok_json_sha:
        raise ValueError("tokenizer.json missing or sha drift vs freeze "
                         "receipt — refusing to tokenize")
    from tokenizers import Tokenizer
    if match_added_tokens:
        return Tokenizer.from_file(tok_json_path)
    d = json.load(open(tok_json_path, encoding="utf-8"))
    literals = [a["content"] for a in d.get("added_tokens", [])]
    d["added_tokens"] = []
    tk = Tokenizer.from_str(json.dumps(d))
    for lit in literals:                  # fail-closed strip verification
        bad = [i for i in tk.encode(lit, add_special_tokens=False).ids
               if i < 8]
        if bad:
            raise ValueError(f"added-token strip failed: literal {lit!r} "
                             f"still encodes to reserved id(s) {bad}")
    return tk


def _encode_batch_factory(nc, tokfreeze, encode_fn, match_added_tokens=False):
    """Bounded-batch encoder: texts -> list[list[int]] in input order.
    Production path = frozen tokenizer via encode_batch (the call shape
    tokenizer_freeze.count_tokens uses — GIL-releasing, parallel across
    docs, id-identical per doc to encode()). An injected encode_fn
    (selftests) is wrapped per-doc."""
    if encode_fn is not None:
        return lambda texts: [encode_fn(t) for t in texts]
    tk = _production_tokenizer(nc, tokfreeze, match_added_tokens)
    return lambda texts: [e.ids for e in tk.encode_batch(texts)]


def produce_shards_v0(nc, encode_fn=None, sources=None, out_dir=SHARD_DIR,
                      token_cap=SHARD_TOKEN_CAP, emit=False,
                      assembly_name=ASSEMBLY_RECEIPT,
                      tokfreeze_name=TOKENIZER_FREEZE_RECEIPT):
    """Encode the frozen corpus into flat uint16 packed shards + return a
    TOKEN-SHARDS-V0 receipt.

    encode_fn: text -> list[int]. Default = the frozen tokenizer under
    ENCODE_SEMANTICS (added-token matching disabled), batched via
    encode_batch. Every produced id must land in [8, VOCAB_SIZE) — reserved
    ids 0..7 and out-of-vocab ids are REFUSED (raise), so the reserved
    multimodal band can never originate from source text. A separator id 0
    is appended after each document. emit=True writes the shards;
    emit=False is a dry count.

    The shard buffer is a list of uint16 numpy chunks, never a Python int
    list: the 2026-06-11 production run buffered ~256Mi Python ints
    (~10 GB working set), got working-set-trimmed, and crawled ~7 h on
    page-ins with zero progress output. ~2 bytes/token now, and every
    emitted shard logs."""
    import numpy as np
    asm_sha, assembly = _load_pinned(nc, assembly_name)
    tok_sha, tokfreeze = _load_pinned(nc, tokfreeze_name)
    tok_json_rel = (tokfreeze.get("tokenizer_repo_path")
                    or "tokenizer/tokenizer.json").replace(chr(92), "/")
    tok_json_sha = tokfreeze.get("tokenizer_json_sha256")
    encode_batch_fn = _encode_batch_factory(nc, tokfreeze, encode_fn,
                                            match_added_tokens=False)
    if sources is None:
        sources = _resolve_sources(nc, assembly)

    out_abs = f"{nc}/{out_dir}"
    if emit:
        os.makedirs(out_abs, exist_ok=True)
    per_source, shards = {}, []
    chunks, buf_len, shard_idx = [], 0, 0            # uint16 ndarray chunks
    sep_arr = np.asarray([SEPARATOR_ID], dtype="<u2")

    def _emit_shard(arr):
        nonlocal shard_idx
        name = f"v0-{shard_idx:05d}.bin"
        if emit:
            arr.tofile(f"{out_abs}/{name}")
            sha = _sha(f"{out_abs}/{name}")
        else:
            sha = hashlib.sha256(arr.tobytes()).hexdigest()
        shards.append({"name": name, "sha256": sha, "n_tokens": int(arr.size)})
        shard_idx += 1
        print(f"[emit] {name} ({arr.size:,} tokens)", flush=True)

    def _drain(final=False):
        nonlocal chunks, buf_len
        while buf_len >= token_cap:
            big = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
            _emit_shard(big[:token_cap])
            big = big[token_cap:]
            chunks, buf_len = ([big] if big.size else []), int(big.size)
        if final and buf_len:
            big = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
            _emit_shard(big)
            chunks, buf_len = [], 0

    def _ingest(src, texts, counters):
        """Encode one bounded batch; per-doc range check + doc separator."""
        nonlocal buf_len
        for ids in encode_batch_fn(texts):
            arr = np.asarray(ids, dtype=np.int64)
            if arr.size:
                bad = (arr < 8) | (arr >= VOCAB_SIZE)
                if bad.any():
                    tid = int(arr[int(np.argmax(bad))])
                    raise ValueError(
                        f"{src}: token id {tid} outside [8,{VOCAB_SIZE}) — "
                        "reserved band 0..7 / oov must never come from text")
                chunks.append(arr.astype("<u2"))
            chunks.append(sep_arr)                    # doc boundary
            buf_len += int(arr.size) + 1
            counters[0] += int(arr.size)
            counters[1] += 1
        _drain()

    for src, shard_paths in sources:
        counters = [0, 0]                             # [content, separators]
        batch, bbytes = [], 0
        for sp in shard_paths:
            for text in _iter_docs(sp):
                batch.append(text)
                bbytes += len(text)
                if (len(batch) >= ENCODE_BATCH_DOCS
                        or bbytes >= ENCODE_BATCH_BYTES):
                    _ingest(src, batch, counters)
                    batch, bbytes = [], 0
        if batch:
            _ingest(src, batch, counters)
        per_source[src] = {"content_tokens": counters[0],
                           "separator_tokens": counters[1],
                           "stream_tokens": counters[0] + counters[1]}
        print(f"[source] {src}: {counters[0]:,} content tokens / "
              f"{counters[1]:,} docs", flush=True)
    _drain(final=True)

    # fail-closed: content tokens must reproduce the FROZEN real_token_counts
    # (#195 AC: "grand total == 6,973,632,296" + "fail-closed if the total
    # drifts"). real_token_counts is CONTENT only — no doc separators — so the
    # packed stream total is larger by the doc count; compare content, not
    # stream. A per-source mismatch always refuses; the grand-total check fires
    # only once every frozen source is present (partial/slice runs skip it).
    freeze_counts = tokfreeze.get("real_token_counts") or {}
    content_total = sum(c["content_tokens"] for c in per_source.values())
    sep_total = sum(c["separator_tokens"] for c in per_source.values())
    freeze_total = freeze_counts.get("total")
    fz_sources = {k for k in freeze_counts if k != "total"}
    drift = []
    for src, c in per_source.items():
        exp = freeze_counts.get(src)
        if exp is not None and c["content_tokens"] != exp:
            drift.append(f"{src} content {c['content_tokens']} != freeze {exp}")
    covered = bool(fz_sources) and set(per_source) >= fz_sources
    if covered and freeze_total is not None and content_total != freeze_total:
        drift.append(f"content_total {content_total} != freeze total "
                     f"{freeze_total}")
    if drift:
        raise ValueError("TOKEN-SHARDS-V0 freeze reproduction FAILED: "
                         + "; ".join(drift))

    total = sum(s["n_tokens"] for s in shards)
    n_windows = (total - BLOCK_LEN) // SEQ + 1 if total >= BLOCK_LEN else 0
    return {
        "ticket": TICKET,
        "ts": _utc_ts(),
        "shard_dir": out_dir,
        "shards": shards,
        "total_stream_tokens": total,
        "content_total_tokens": content_total,
        "freeze_reproduction": {
            "freeze_total": freeze_total,
            "content_total_tokens": content_total,
            "separator_tokens": sep_total,
            "total_match": bool(covered and freeze_total is not None
                                and content_total == freeze_total),
        },
        "per_source": per_source,
        "separator_id": SEPARATOR_ID,
        "encode_semantics": (ENCODE_SEMANTICS if encode_fn is None
                             else "injected-encoder (selftest)"),
        "reserved_band_guard": {
            "reserved_ids": RESERVED_IDS, "max_id_lt": VOCAB_SIZE,
            # reaching here without raising == no reserved id ever appeared
            "reserved_ids_observed_in_stream": 0,
        },
        "loader_windows": {"seq": SEQ, "n_mtp": N_MTP,
                           "block_len": BLOCK_LEN, "n_windows": n_windows},
        "premises": {
            "assembly_receipt": {"name": assembly_name, "sha256": asm_sha},
            "tokenizer_freeze_receipt": {"name": tokfreeze_name,
                                         "sha256": tok_sha},
            "tokenizer_json": {"path": tok_json_rel, "sha256": tok_json_sha},
        },
        "sha_convention": SHA_CONVENTION,
        "emit": bool(emit),
        "no_gpu": True,
    }


def census_special_ids(nc, encode_fn=None, sources=None,
                       assembly_name=ASSEMBLY_RECEIPT,
                       tokfreeze_name=TOKENIZER_FREEZE_RECEIPT):
    """Read-only diagnostic (Leo 14628 — sizes the deviation, decides
    nothing): per source, count text-borne ids in the guarded bands under
    the LEGACY matching-ENABLED semantics — reserved/separator ids 0..7
    (added-token literals in raw corpus text match to their ids; the writer
    REFUSES them) and out-of-vocab ids. Content totals are recounted under
    the same semantics, so per-source agreement with the prior freeze
    receipt's real_token_counts cross-checks the instrument. Writes nothing,
    raises on nothing; returns {source: stats}."""
    import numpy as np
    _, assembly = _load_pinned(nc, assembly_name)
    _, tokfreeze = _load_pinned(nc, tokfreeze_name)
    enc = _encode_batch_factory(nc, tokfreeze, encode_fn,
                                match_added_tokens=True)
    if sources is None:
        sources = _resolve_sources(nc, assembly)
    freeze_counts = tokfreeze.get("real_token_counts") or {}
    out = {}
    for src, shard_paths in sources:
        st = {"docs": 0, "content_tokens": 0,
              "low_id_tokens": {str(i): 0 for i in range(8)},
              "docs_with_low_ids": 0,
              "oob_tokens": 0, "docs_with_oob": 0}

        def _take(texts, st=st):
            for ids in enc(texts):
                arr = np.asarray(ids, dtype=np.int64)
                st["docs"] += 1
                st["content_tokens"] += int(arr.size)
                if not arr.size:
                    continue
                low = arr[arr < 8]
                if low.size:
                    st["docs_with_low_ids"] += 1
                    for i, n in zip(*np.unique(low, return_counts=True)):
                        st["low_id_tokens"][str(int(i))] += int(n)
                n_oob = int(np.count_nonzero(arr >= VOCAB_SIZE))
                if n_oob:
                    st["oob_tokens"] += n_oob
                    st["docs_with_oob"] += 1

        batch, bbytes = [], 0
        for sp in shard_paths:
            for text in _iter_docs(sp):
                batch.append(text)
                bbytes += len(text)
                if (len(batch) >= ENCODE_BATCH_DOCS
                        or bbytes >= ENCODE_BATCH_BYTES):
                    _take(batch)
                    batch, bbytes = [], 0
        if batch:
            _take(batch)
        exp = freeze_counts.get(src)
        st["freeze_content_tokens"] = exp
        st["matches_freeze"] = (None if exp is None
                                else exp == st["content_tokens"])
        out[src] = st
        print(f"[census] {src}: docs={st['docs']:,} "
              f"content={st['content_tokens']:,} "
              f"low={ {k: v for k, v in st['low_id_tokens'].items() if v} } "
              f"oob={st['oob_tokens']} matches_freeze={st['matches_freeze']}",
              flush=True)
    return out


# ---------------------------------------------------------------------------
# Selftest — hermetic; builds a synthetic shard set in a temp dir. Reads/writes
# NO production corpus and emits no production data.
# ---------------------------------------------------------------------------
def _selftest():
    import copy
    import struct
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        os.makedirs(f"{td}/shards")
        os.makedirs(f"{td}/tokenizer")
        # minimal premise receipts (no sha fields -> receipt_check clean)
        prem_names = {
            "assembly_receipt": "fixture-assembly.json",
            "tokenizer_freeze_receipt": "fixture-tokfreeze.json",
        }
        for nm in prem_names.values():
            json.dump({"ticket": "FIXTURE", "ts": "20260101T000000Z"},
                      open(f"{td}/receipts/{nm}", "w"))
        json.dump({"vocab_size": 32000}, open(f"{td}/tokenizer/tokenizer.json",
                                               "w"))
        # two synthetic uint16 shards; ids stay in [8, 31999] (no reserved/sep)
        def _write_shard(name, n):
            ids = [8 + (i % 100) for i in range(n)]
            with open(f"{td}/shards/{name}", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in ids))
            return n
        n0, n1 = _write_shard("v0-00000.bin", 2048), _write_shard(
            "v0-00001.bin", 2048)
        total = n0 + n1                                   # 4096
        exp_windows = (total - BLOCK_LEN) // SEQ + 1      # (4096-1027)//1024+1=3

        def _premise(key):
            nm = prem_names[key]
            return {"name": nm, "sha256": _sha(f"{td}/receipts/{nm}")}

        # per-source split: put all content on one source, separators elsewhere,
        # arranged so each source's content+separator == stream and they sum to
        # `total`. (Synthetic; the production writer fills real counts.)
        per_source = {s: {"content_tokens": 0, "separator_tokens": 0,
                          "stream_tokens": 0} for s in EXPECTED_SOURCES}
        per_source["code_github_clean"] = {"content_tokens": total - 5,
                                           "separator_tokens": 5,
                                           "stream_tokens": total}

        good = {
            "ticket": TICKET,
            "ts": "20260611T000000Z",
            "shard_dir": "shards",
            "shards": [
                {"name": "v0-00000.bin", "sha256": _sha(f"{td}/shards/v0-00000.bin"),
                 "n_tokens": n0},
                {"name": "v0-00001.bin", "sha256": _sha(f"{td}/shards/v0-00001.bin"),
                 "n_tokens": n1},
            ],
            "total_stream_tokens": total,
            "per_source": per_source,
            "separator_id": SEPARATOR_ID,
            "reserved_band_guard": {
                "reserved_ids": RESERVED_IDS, "max_id_lt": VOCAB_SIZE,
                "reserved_ids_observed_in_stream": 0,
            },
            "loader_windows": {"seq": SEQ, "n_mtp": N_MTP,
                               "block_len": BLOCK_LEN, "n_windows": exp_windows},
            "premises": {
                "assembly_receipt": _premise("assembly_receipt"),
                "tokenizer_freeze_receipt": _premise("tokenizer_freeze_receipt"),
                "tokenizer_json": {"path": "tokenizer/tokenizer.json",
                                   "sha256": _sha(f"{td}/tokenizer/tokenizer.json")},
            },
            "sha_convention": SHA_CONVENTION,
            "no_gpu": True,
        }
        # well-formed receipt -> no violations
        assert validate_shards_receipt(good, td) == [], \
            validate_shards_receipt(good, td)
        # and it passes the schema floor on its own
        assert validate_receipt(good) == [], validate_receipt(good)

        # each mutation must fire at least one violation (fail-closed)
        def _bad(mut):
            d = copy.deepcopy(good)
            mut(d)
            out = validate_shards_receipt(d, td)
            assert out, f"expected violation, got none for {mut}"
            return out

        def _set_ticket(d): d["ticket"] = "WRONG"
        def _drop_shard_file(d): os.unlink(f"{td}/shards/v0-00001.bin")
        def _shard_sha(d): d["shards"][0]["sha256"] = "0" * 64
        def _shard_count(d): d["shards"][0]["n_tokens"] = 999999
        def _total_mismatch(d): d["total_stream_tokens"] = total + 1
        def _drop_source(d): d["per_source"].pop("wikipedia_en")
        def _bad_sep(d): d["separator_id"] = 1
        def _bad_reserved(d): d["reserved_band_guard"]["reserved_ids"] = [1, 2]
        def _reserved_seen(d):
            d["reserved_band_guard"]["reserved_ids_observed_in_stream"] = 3
        def _bad_windows(d): d["loader_windows"]["n_windows"] = exp_windows + 7
        def _prem_sha(d): d["premises"]["assembly_receipt"]["sha256"] = "0" * 64
        def _tok_sha(d): d["premises"]["tokenizer_json"]["sha256"] = "0" * 64
        def _no_sha_conv(d): d.pop("sha_convention")

        assert any("ticket" in x for x in _bad(_set_ticket))
        assert any("not on disk" in x for x in _bad(_drop_shard_file))
        # restore the file the previous mutation deleted (temp dir is shared)
        _write_shard("v0-00001.bin", n1)
        assert any("sha drift" in x for x in _bad(_shard_sha))
        assert any("bytes/2" in x for x in _bad(_shard_count))
        assert any("total_stream_tokens" in x for x in _bad(_total_mismatch))
        assert any("per_source sources" in x for x in _bad(_drop_source))
        assert any("separator_id" in x for x in _bad(_bad_sep))
        assert any("reserved_ids" in x for x in _bad(_bad_reserved))
        assert any("observed_in_stream" in x for x in _bad(_reserved_seen))
        assert any("n_windows" in x for x in _bad(_bad_windows))
        assert any("premise assembly_receipt" in x for x in _bad(_prem_sha))
        assert any("tokenizer_json" in x for x in _bad(_tok_sha))
        assert any("MISSING_SHA_CONVENTION" in x for x in _bad(_no_sha_conv))

        # --- eng-53: byte-true reserved/range/parity scan (NOT the declared
        # field). Each mutation rewrites shard 0's BYTES and updates its sha so
        # the sha-match passes and the BYTE SCAN is what fires; the receipt
        # still declares reserved_ids_observed_in_stream == 0 throughout.
        good0_ids = [8 + (i % 100) for i in range(n0)]   # == _write_shard bytes

        def _restore0():
            with open(f"{td}/shards/v0-00000.bin", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in good0_ids))

        def _reserved_in_bytes(d):
            ids = list(good0_ids)
            ids[5] = 1                               # reserved-band id in bytes
            with open(f"{td}/shards/v0-00000.bin", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in ids))
            d["shards"][0]["sha256"] = _sha(f"{td}/shards/v0-00000.bin")

        def _oob_in_bytes(d):
            ids = list(good0_ids)
            ids[7] = 35000                           # id >= VOCAB_SIZE in bytes
            with open(f"{td}/shards/v0-00000.bin", "wb") as fh:
                fh.write(b"".join(struct.pack("<H", x) for x in ids))
            d["shards"][0]["sha256"] = _sha(f"{td}/shards/v0-00000.bin")

        def _odd_bytes(d):
            with open(f"{td}/shards/v0-00000.bin", "ab") as fh:
                fh.write(b"\x00")                    # dangling byte -> odd length
            d["shards"][0]["sha256"] = _sha(f"{td}/shards/v0-00000.bin")

        assert any("reserved-band id" in x for x in _bad(_reserved_in_bytes))
        _restore0()
        assert any(f">= {VOCAB_SIZE}" in x for x in _bad(_oob_in_bytes))
        _restore0()
        assert any("odd byte length" in x for x in _bad(_odd_bytes))
        _restore0()

    print("TOKEN_SHARDS_V0_VALIDATOR_SELFTEST_PASS")


def _selftest_writer():
    """End-to-end writer selftest on a SYNTHETIC corpus (real zstd read + the
    real chunk/separator/uint16 path), with an injected encoder. Reads/writes
    no production data; the emitted fixture receipt must pass the eng-49
    validator."""
    import json as _json
    import tempfile
    import zstandard

    def _toy_encode(t):
        return [8 + (ord(c) % 100) for c in t]     # all ids in [8, 108)

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        os.makedirs(f"{td}/tokenizer")
        os.makedirs(f"{td}/corpus")
        with open(f"{td}/tokenizer/tokenizer.json", "w", encoding="utf-8") as fh:
            fh.write('{"model":"fixture"}')
        tj_sha = _sha(f"{td}/tokenizer/tokenizer.json")
        _json.dump({"ticket": "FIX-ASM", "ts": "20260101T000000Z"},
                   open(f"{td}/receipts/fixture-assembly.json", "w"))
        _json.dump({"ticket": "FIX-TOK", "ts": "20260101T000000Z",
                    "tokenizer_repo_path": "tokenizer/tokenizer.json",
                    "tokenizer_json_sha256": tj_sha, "sha_convention": "fixture"},
                   open(f"{td}/receipts/fixture-tokfreeze.json", "w"))

        def _write_corpus(src, docs):
            p = f"{td}/corpus/{src}.jsonl.zst"
            payload = "\n".join(_json.dumps({"text": t, "source": src})
                                for t in docs).encode("utf-8")
            with open(p, "wb") as fh:
                fh.write(zstandard.ZstdCompressor().compress(payload))
            return p
        # one 300-char doc per source -> 1505 stream tokens > block_len 1027
        sources = [(s, [_write_corpus(s, ["x" * 300])])
                   for s in sorted(EXPECTED_SOURCES)]

        receipt = produce_shards_v0(
            td, encode_fn=_toy_encode, sources=sources, out_dir="shards",
            token_cap=600, emit=True,
            assembly_name="fixture-assembly.json",
            tokfreeze_name="fixture-tokfreeze.json")

        # the writer's own receipt must pass the eng-49 validator end-to-end
        assert receipt["ticket"] == TICKET
        assert validate_shards_receipt(receipt, td) == [], \
            validate_shards_receipt(receipt, td)
        assert set(receipt["per_source"]) == EXPECTED_SOURCES
        assert receipt["total_stream_tokens"] >= BLOCK_LEN
        assert receipt["loader_windows"]["n_windows"] >= 1
        assert len(receipt["shards"]) >= 2, "token_cap should force >1 shard"
        for s in receipt["shards"]:                # flat uint16: bytes == n*2
            sz = os.path.getsize(f"{td}/shards/{s['name']}")
            assert sz == s["n_tokens"] * BYTES_PER_TOKEN, (s, sz)
        assert all(c["separator_tokens"] == 1            # one separator per doc
                   for c in receipt["per_source"].values())

        # reserved-band guard: an encoder emitting a reserved id must RAISE
        raised = False
        try:
            produce_shards_v0(td, encode_fn=lambda t: [5], sources=sources[:1],
                              out_dir="shards2", token_cap=600, emit=False,
                              assembly_name="fixture-assembly.json",
                              tokfreeze_name="fixture-tokfreeze.json")
        except ValueError as e:
            raised = "reserved band" in str(e) or "outside" in str(e)
        assert raised, "a reserved/oov id must be refused by the writer"

        # census (diagnostic): COUNTS guarded ids instead of raising
        cen = census_special_ids(td, encode_fn=_toy_encode, sources=sources,
                                 assembly_name="fixture-assembly.json",
                                 tokfreeze_name="fixture-tokfreeze.json")
        assert set(cen) == EXPECTED_SOURCES
        assert all(st["low_id_tokens"] == {str(i): 0 for i in range(8)}
                   and st["oob_tokens"] == 0 for st in cen.values()), cen
        cen2 = census_special_ids(td, encode_fn=lambda t: [5, 8, 0, 40000],
                                  sources=sources[:1],
                                  assembly_name="fixture-assembly.json",
                                  tokfreeze_name="fixture-tokfreeze.json")
        st = next(iter(cen2.values()))
        assert st["low_id_tokens"]["5"] == 1 and st["low_id_tokens"]["0"] == 1
        assert st["docs_with_low_ids"] == 1 and st["oob_tokens"] == 1
        assert st["content_tokens"] == 4 and st["docs"] == 1

    print("TOKEN_SHARDS_V0_WRITER_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser(
        description="TOKEN-SHARDS-V0 receipt contract + fail-closed validator "
                    "(gate-side half; production writer is eng-50, run HELD)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--validate", metavar="RECEIPT",
                    help="fail-closed validate a token-shards-v0 receipt against "
                         "the on-disk shards (exit non-zero on any violation)")
    ap.add_argument("--emit", action="store_true",
                    help="PRODUCTION: read the frozen corpus, write uint16 .bin "
                         "shards, and emit a checked TOKEN-SHARDS-V0 receipt. "
                         "Governed by the Step-1 chain (HOLD lifted "
                         "2026-06-11, Leo 14620).")
    ap.add_argument("--census", action="store_true",
                    help="read-only diagnostic: per-source counts of "
                         "text-borne guarded ids (0..7 / oov) under legacy "
                         "matching-ENABLED semantics + content totals vs the "
                         "frozen counts; writes receipts/special-id-census-"
                         "<ts>.json")
    ap.add_argument("--out", default=SHARD_DIR,
                    help="shard output dir, relative to the repo (default "
                         f"{SHARD_DIR!r}). Use an out-of-tree path like "
                         "'../shards-v0' so the ~14 GB packed shards stay out "
                         "of git; the receipt records this as shard_dir.")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        _selftest_writer()
        return
    if a.validate:
        d = json.load(open(a.validate, encoding="utf-8"))
        viol = validate_shards_receipt(d, NC)
        if viol:
            for x in viol:
                print(f"SHARD CONTRACT VIOLATION: {x}")
            raise SystemExit(1)
        print("TOKEN_SHARDS_V0_RECEIPT_VALID")
        return
    if a.census:
        from receipt_write import checked_write       # noqa: E402
        per_source = census_special_ids(NC)
        low_total = sum(sum(s["low_id_tokens"].values())
                        for s in per_source.values())
        payload = {
            "ticket": "SPECIAL-ID-CENSUS-V0",
            "ts": _utc_ts(),
            "semantics": ("added-token literal matching ENABLED (legacy "
                          "counting semantics) — measures how many ids 0..7 "
                          "raw corpus text yields; sizes the deviation for "
                          "the matching-disabled re-derivation (Leo 14628, "
                          "decision frozen pre-census)"),
            "per_source": per_source,
            "total_low_id_tokens": low_total,
            "premises": {
                "assembly_receipt": {
                    "name": ASSEMBLY_RECEIPT,
                    "sha256": _sha(f"{NC}/receipts/{ASSEMBLY_RECEIPT}")},
                "tokenizer_freeze_receipt": {
                    "name": TOKENIZER_FREEZE_RECEIPT,
                    "sha256": _sha(
                        f"{NC}/receipts/{TOKENIZER_FREEZE_RECEIPT}")},
            },
            "sha_convention": SHA_CONVENTION,
            "no_gpu": True,
        }
        out = f"{NC}/receipts/special-id-census-{payload['ts']}.json"
        checked_write(out, payload)
        print(f"SPECIAL_ID_CENSUS_DONE {os.path.relpath(out, NC)} "
              f"({low_total:,} text-borne low ids)")
        return
    if a.emit:
        from receipt_write import checked_write       # noqa: E402
        receipt = produce_shards_v0(NC, emit=True, out_dir=a.out)
        out = f"{NC}/receipts/token-shards-v0-{receipt['ts']}.json"
        checked_write(out, receipt)
        viol = validate_shards_receipt(
            json.load(open(out, encoding="utf-8")), NC)
        if viol:
            raise SystemExit(f"emitted shard receipt FAILS contract: {viol}")
        print(f"TOKEN_SHARDS_V0_EMITTED {os.path.relpath(out, NC)} "
              f"({receipt['total_stream_tokens']:,} stream tokens, "
              f"{len(receipt['shards'])} shards)")
        return
    print("TOKEN_SHARDS_V0_STAGED — pass --selftest, --validate <receipt>, or "
          "--emit (production; HELD pending the shard-production call). The "
          "writer reads the frozen corpus -> uint16 shards; emit is the only "
          "path that touches production data.")


if __name__ == "__main__":
    main()

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
shards + this receipt) is the deferred half (eng-50): build-now, and its
`--emit` run stays HELD pending the shard-production call. This module
deliberately ships NO corpus-reading / shard-writing path — it produces no
data; it only defines + enforces the contract the writer must satisfy.
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

    print("TOKEN_SHARDS_V0_VALIDATOR_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser(
        description="TOKEN-SHARDS-V0 receipt contract + fail-closed validator "
                    "(gate-side half; production writer is eng-50, run HELD)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--validate", metavar="RECEIPT",
                    help="fail-closed validate a token-shards-v0 receipt against "
                         "the on-disk shards (exit non-zero on any violation)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
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
    print("TOKEN_SHARDS_V0_STAGED — pass --selftest or --validate <receipt>. "
          "Production writer (corpus->uint16 shards) is eng-50; its run is "
          "HELD pending the shard-production call.")


if __name__ == "__main__":
    main()

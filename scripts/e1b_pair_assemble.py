#!/usr/bin/env python3
"""fp-32d (#253) — E1b pair-receipt assembler.

`fp32_e1b_gate.py` audits a FP32-E1B-LOSSMATCH pair receipt; nothing built
one from the trainer's leg runs — the missing link that made the B=24
deviation (3.35 d vs 4.31 d run) silently unreachable in the launch sequence
(mail 14675 re-sequenced it as a hard-capped window after fp-30d GREEN).

Contract:
- Leg receipts are consumed VERBATIM: each must carry the gate's
  LEG_REQUIRED fields ({batch, lr_muon, lr_adamw, steps, tokens, ce_final10,
  wall_s, governor, free_vram_gib_min}) — the assembler recomputes NOTHING
  and defaults NOTHING; a missing field is a refusal naming the leg + field.
  This doubles as the leg-receipt contract for the eng trainer's leg mode.
- Leg order is positional and explicit: base (B=4), candidate, optional
  scaled-lr retry. The gate re-checks the ordering rules independently.
- Pair pins added here: shard_receipt (newest production
  token-shards-v0-<ts>.json, or --shards explicit) + shard_set_sha256 over
  its exact on-disk bytes; init_seed (--seed, or read identically from every
  leg receipt — any mismatch refuses: paired legs with different seeds are
  not a pair); seq + token_budget from the gate's frozen constants;
  data_order_basis (--data-order-basis, or identical across legs).
- PRE-FLIGHT: fp32_e1b_gate.check_pair must return ZERO findings or the
  assembler refuses and writes NOTHING. The gate remains the separate
  authority — the assembler never emits a verdict receipt; it prints the
  would-be verdict for operator information only.

Bare invocation is staged exit 1 (14644 evidence-promotion class).
--selftest runs on temp fixtures only; live-tree contact is read-only with
a purity snapshot (fp-30e pattern).
"""
import argparse
import glob as globmod
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_write import checked_write                 # noqa: E402
import fp32_e1b_gate as e1b                             # noqa: E402

SHA_CONVENTION = e1b.SHA_CONVENTION
_SHARDS_NAME = re.compile(r"^token-shards-v0-\d{8}T\d{6}Z\.json$")


class Refusal(SystemExit):
    def __init__(self, msg):
        print(f"E1B_ASSEMBLE_REFUSAL: {msg}")
        super().__init__(1)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _resolve_shards(nc, explicit=None):
    if explicit:
        if not _SHARDS_NAME.match(os.path.basename(explicit)):
            raise Refusal(f"{explicit} is not a production "
                          "token-shards-v0-<ts>.json name")
        p = f"{nc}/receipts/{os.path.basename(explicit)}"
        if not os.path.exists(p):
            raise Refusal(f"shards receipt {explicit} not under receipts/")
        return p
    hits = sorted(p for p in
                  globmod.glob(f"{nc}/receipts/token-shards-v0-*.json")
                  if _SHARDS_NAME.match(os.path.basename(p)))
    if not hits:
        raise Refusal("no production token-shards-v0-<ts>.json receipt — "
                      "the E1b legs run ON the emitted shards; assemble "
                      "after the emission receipt is committed")
    return hits[-1]


def _consistent(legs, paths, field, explicit=None):
    """One value for a pair-level field: explicit wins; otherwise every leg
    receipt must carry it identically."""
    if explicit is not None:
        return explicit
    vals = [(p, d.get(field)) for p, d in zip(paths, legs)]
    missing = [p for p, x in vals if x is None]
    if missing:
        raise Refusal(f"{field} not given (--flag) and missing from leg "
                      f"receipt(s): {[os.path.basename(p) for p in missing]}")
    uniq = {json.dumps(x, sort_keys=True) for _, x in vals}
    if len(uniq) != 1:
        raise Refusal(f"{field} differs across leg receipts: "
                      f"{[(os.path.basename(p), x) for p, x in vals]} — "
                      "legs with different pins are not a pair")
    return vals[0][1]


def assemble(nc=NC, leg_paths=(), shards=None, seed=None,
             data_order_basis=None, write=True):
    """Build + pre-flight the pair receipt. Returns (pair, out_path|None)."""
    if not 2 <= len(leg_paths) <= 3:
        raise Refusal(f"need 2 leg receipts (base, candidate) or 3 (+ the "
                      f"single scaled-lr retry), got {len(leg_paths)}")
    legs_raw = []
    for p in leg_paths:
        if not os.path.exists(p):
            raise Refusal(f"leg receipt {p} not on disk")
        try:
            legs_raw.append(json.load(open(p, encoding="utf-8")))
        except Exception as e:                  # noqa: BLE001
            raise Refusal(f"leg receipt {p} unreadable: {e}")

    legs = []
    for p, d in zip(leg_paths, legs_raw):
        leg = {}
        for k in e1b.LEG_REQUIRED:
            if k not in d:
                raise Refusal(f"leg {os.path.basename(p)} missing required "
                              f"field {k!r} — the trainer's leg mode must "
                              "emit every LEG_REQUIRED field; the assembler "
                              "computes nothing")
            leg[k] = d[k]
        legs.append(leg)

    spath = _resolve_shards(nc, shards)
    pair = {
        "ticket": e1b.PAIR_TICKET,
        "ts": _utc_ts(),
        "issue": 225,
        "shard_receipt": os.path.basename(spath),
        "shard_set_sha256": _sha(spath),
        "init_seed": _consistent(legs_raw, leg_paths, "init_seed", seed),
        "seq": e1b.SEQ,
        "token_budget": e1b.TOKEN_BUDGET,
        "data_order_basis": _consistent(legs_raw, leg_paths,
                                        "data_order_basis",
                                        data_order_basis),
        "legs": legs,
        "leg_receipts": [{"path": os.path.relpath(p, nc).replace(os.sep, "/"),
                          "sha256": _sha(p)} for p in leg_paths],
        "assembled_by": "scripts/e1b_pair_assemble.py (fp-32d #253) — leg "
                        "fields verbatim, zero recomputation",
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }

    findings = e1b.check_pair(pair, nc)
    if findings:
        for x in findings:
            print(f"  PRE-FLIGHT FINDING: {x}")
        raise Refusal(f"{len(findings)} check_pair finding(s) — pair does "
                      "not bind; NOTHING written. Fix the legs, never the "
                      "pair.")
    out = None
    if write:
        out = f"{nc}/receipts/fp32-e1b-lossmatch-{pair['ts']}.json"
        checked_write(pair, out)
        v, _ = e1b.verdict(pair)
        print(f"E1B_PAIR_ASSEMBLED {os.path.relpath(out, nc)} "
              f"(informational verdict: {v} — the gate is the authority: "
              f"python scripts/fp32_e1b_gate.py against this receipt)")
    return pair, out


# ---------------------------------------------------------------------------
# selftest — temp fixtures only; live contact READ-ONLY + purity snapshot
# ---------------------------------------------------------------------------
def _live_snapshot():
    rdir = f"{NC}/receipts"
    return tuple(sorted(os.listdir(rdir))) if os.path.isdir(rdir) else None


def _fixture(td, *, seed_b=31):
    """Temp tree with a live-consistent shards receipt + two leg receipts
    (built on the gate's own _leg helper so the shapes can never drift)."""
    os.makedirs(f"{td}/receipts")
    json.dump({"ticket": "TOKENIZER-FREEZE-V0", "ts": "20260101T000000Z",
               "real_token_counts": {"total": 7_000_000_000}},
              open(f"{td}/receipts/tokenizer-freeze-20260101T000000Z.json",
                   "w"))
    json.dump({"ticket": e1b.SHARDS_TICKET, "ts": "20260101T000001Z",
               "total_stream_tokens": 7_000_000_000},
              open(f"{td}/receipts/token-shards-v0-20260101T000001Z.json",
                   "w"))
    pa, pb = f"{td}/leg-base.json", f"{td}/leg-cand.json"
    la = {**e1b._leg(4, 2.000), "init_seed": 31,
          "data_order_basis": "shard-order seed 31"}
    lb = {**e1b._leg(16, 2.020), "init_seed": seed_b,
          "data_order_basis": "shard-order seed 31"}
    json.dump(la, open(pa, "w"))
    json.dump(lb, open(pb, "w"))
    return pa, pb


def _selftest():
    import tempfile
    live_before = _live_snapshot()

    # happy path: assembles, binds, gate verdict computable on the artifact
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td)
        pair, out = assemble(nc=td, leg_paths=[pa, pb])
        assert out and os.path.exists(out)
        assert e1b.check_pair(pair, td) == []
        v, detail = e1b.verdict(json.load(open(out, encoding="utf-8")))
        assert v == "PASS", (v, detail)        # 2.020 <= 2.000*1.02

    # missing leg field -> refusal naming leg + field, nothing written
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td)
        d = json.load(open(pb))
        del d["ce_final10"]
        json.dump(d, open(pb, "w"))
        try:
            assemble(nc=td, leg_paths=[pa, pb])
            raise AssertionError("missing leg field must refuse")
        except Refusal:
            pass
        assert not globmod.glob(f"{td}/receipts/fp32-e1b-lossmatch-*.json")

    # init_seed conflict across legs -> refusal
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td, seed_b=32)
        try:
            assemble(nc=td, leg_paths=[pa, pb])
            raise AssertionError("seed conflict must refuse")
        except Refusal:
            pass

    # explicit --seed overrides leg fields (single source when given)
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td, seed_b=32)
        pair, _ = assemble(nc=td, leg_paths=[pa, pb], seed=31, write=False)
        assert pair["init_seed"] == 31

    # check_pair finding (candidate batch off-ladder) -> refusal, no write
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td)
        d = json.load(open(pb))
        d["batch"] = 8                        # not in CANDIDATES (16, 24)
        d["steps"] = (e1b.TOKEN_BUDGET + 8 * e1b.SEQ - 1) // (8 * e1b.SEQ)
        d["tokens"] = d["steps"] * 8 * e1b.SEQ
        json.dump(d, open(pb, "w"))
        try:
            assemble(nc=td, leg_paths=[pa, pb])
            raise AssertionError("off-ladder candidate must refuse")
        except Refusal:
            pass
        assert not globmod.glob(f"{td}/receipts/fp32-e1b-lossmatch-*.json")

    # no production shards receipt -> refusal (legs run ON the shards)
    with tempfile.TemporaryDirectory() as td:
        pa, pb = _fixture(td)
        os.remove(f"{td}/receipts/token-shards-v0-20260101T000001Z.json")
        try:
            assemble(nc=td, leg_paths=[pa, pb])
            raise AssertionError("missing shards receipt must refuse")
        except Refusal:
            pass

    assert _live_snapshot() == live_before, \
        "SELFTEST PURITY VIOLATION: live receipts changed during --selftest"
    print("E1B_PAIR_ASSEMBLE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--assemble", action="store_true",
                    help="build + pre-flight the pair receipt from leg "
                         "receipts; writes only if check_pair binds")
    ap.add_argument("--legs", nargs="+", default=[],
                    help="leg receipt paths IN ORDER: base(B=4) candidate "
                         "[scaled-lr retry]")
    ap.add_argument("--shards", help="explicit production shards receipt "
                                     "name (default: newest)")
    ap.add_argument("--seed", type=int, help="init_seed (else read "
                                             "identically from legs)")
    ap.add_argument("--data-order-basis", help="data order pin (else read "
                                               "identically from legs)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.assemble:
        print("E1B_PAIR_ASSEMBLE_STAGED (--assemble --legs base.json "
              "cand.json [retry.json] builds the FP32-E1B-LOSSMATCH pair "
              "receipt; fires inside the post-fp-30d E1b window, mail 14675)")
        raise SystemExit(1)
    assemble(leg_paths=a.legs, shards=a.shards, seed=a.seed,
             data_order_basis=a.data_order_basis)


if __name__ == "__main__":
    main()
